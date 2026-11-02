"""Check every claim against the sources it cites.

A claim is *supported* when it cites at least one source that was actually in
the prompt and every number in it appears in one of its cited sources. Numbers
are compared by value with scale awareness, because filings and answers state
the same figure differently: "$109.2 billion" (answer) vs "109,158" in a table
reported in millions, or "14%" vs "14 %". Years are ignored (they appear in
every source header). This catches the common grounding failures: invented
figures, figures from the wrong source, and citations to sources never shown.

Two relaxations keep the check from rejecting answers that are grounded but
badly cited (common with small local models, see reports/generation_v0_ollama.md):
- Arithmetic shown in the claim ("12% + 11% + 11% = 34%") supports its result
  when the sum is right; the inputs are still checked against the sources.
- Citation repair: a claim with no valid citation, or whose figures are not in
  the sources it cites, is re-attributed to the provided sources that contain
  those figures and share its wording. Such claims are marked `repaired` (the
  model's citation was wrong, the content was not). A figure that appears in no
  provided source still fails, so invented numbers are never rescued.

Figures alone can't catch a real number relabelled as another metric, so release sources get two more checks
(`_row_fits`): a figure stated as a count can't rest on a dollar amount ("69,138 million iPhone units" on
"| iPhone | $69,138 |"), one product can't claim a combined row ("Model Y" on "Model 3/Y deliveries"), and a figure
must sit in the column of the period the claim names ("440,808 in Q1 2024" on a row where Q1 2024 says 433,371).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.agent.entities import ALL_QUARTERS, find_quarters, find_years
from app.generation.columns import Period, known_periods, periods_of_figure
from app.generation.context import Source
from app.generation.schemas import Claim
from app.ingestion.models import Chunk

ClaimStatus = Literal["supported", "unsupported_number", "invalid_citation"]

# "B"/"M" only directly after the digits ("$37.7B"), so a stray letter after a space isn't a unit.
_NUM = re.compile(r"(?<![\w.])\$?\(?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\)?(\s*(?:%|percent|billion|million|thousand|bn|mn)|[BM]\b)?",
                  re.IGNORECASE)
_SCALE = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6, "m": 1e6, "thousand": 1e3}


@dataclass(frozen=True)
class Number:
    value: float  # unscaled value as written, e.g. 109.2 for "$109.2 billion"
    decimals: int
    scale: float  # 1e9 for "billion", 1 when unstated
    percent: bool
    raw: str


def extract_numbers(text: str) -> list[Number]:
    out = []
    for m in _NUM.finditer(text):
        whole, frac, unit = m.group(1), m.group(2) or "", (m.group(3) or "").strip().lower()
        value = float(whole.replace(",", "") + frac)
        if not frac and not unit and "," not in whole and 1990 <= value <= 2035:
            continue  # a year
        out.append(Number(value, len(frac) - 1 if frac else 0, _SCALE.get(unit, 1.0), unit in ("%", "percent"), m.group(0).strip()))
    return out


def _matches(claim: Number, source: Number) -> bool:
    """Does the claim's figure equal the source figure, allowing rounding and unit changes?"""
    if claim.percent != source.percent and (claim.percent or source.percent):
        # "14%" vs "14" in a table column labelled %: allow only exact value
        return claim.value == source.value
    claim_abs = claim.value * claim.scale
    # Source tables usually omit units ("in millions"); try the common reporting scales.
    for unit in ({source.scale} if source.scale != 1 else {1.0, 1e3, 1e6, 1e9}):
        source_abs = source.value * unit
        if source_abs == 0:
            if claim_abs == 0:
                return True
            continue
        # Round the source figure to the claim's precision in the claim's scale.
        if round(source_abs / claim.scale, claim.decimals) == round(claim.value, claim.decimals):
            return True
    return False


_EQUATION = re.compile(
    r"((?:\$?\d[\d,]*(?:\.\d+)?\s*(?:%|billion|million)?\s*[+\-−]\s*)+\$?\d[\d,]*(?:\.\d+)?\s*(?:%|billion|million)?)"
    r"\s*=\s*(\$?\d[\d,]*(?:\.\d+)?\s*(?:%|billion|million)?)", re.IGNORECASE)


def derived_figures(text: str) -> list[Number]:
    """Results of arithmetic written out in the text whose sums check out, e.g. 34% in "12% + 11% + 11% = 34%"."""
    out = []
    for m in _EQUATION.finditer(text):
        operands, result = extract_numbers(m.group(1)), extract_numbers(m.group(2))
        signs = [-1 if op in "-−" else 1 for op in re.findall(r"[+\-−]", m.group(1))]
        if len(result) != 1 or len(signs) != len(operands) - 1:
            continue
        total = operands[0].value * operands[0].scale + sum(s * n.value * n.scale for s, n in zip(signs, operands[1:]))
        r = result[0]
        if round(total / r.scale, r.decimals) == round(r.value, r.decimals):
            out.append(r)
    return out


_STOPWORDS = frozenset("""the and for with from that this was were are its their which while also into than over
under per has had have been being about after before between during fiscal year years total company compared
primarily due including other our approximately respectively increased decreased increase decrease reported
prior billion million thousand percent""".split())


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z&'-]{2,}", text.lower()) if w not in _STOPWORDS}


def overlap(claim_text: str, source: Source) -> float:
    """Share of the claim's content words that appear in the source (with its header: company, item)."""
    words = content_words(claim_text)
    return len(words & content_words(source.render())) / len(words) if words else 0.0


MIN_REPAIR_WORDS = 3  # too few words ("14%") to say which source a claim came from
MIN_REPAIR_OVERLAP = 0.6
MIN_SEGMENT_WORDS = 2  # a repaired figure's sentence or table row must share this many words with the claim
STEM_CHARS = 5  # crude stem for release rows: "delivered" / "deliveries"


def _segments(text: str) -> list[str]:
    """Sentences and table rows: the context a figure is stated in."""
    return [seg for seg in re.split(r"\n|(?<=[.;])\s+", text) if seg.strip()]


def _in_context(number: Number, words: set[str], source: Source, claim_text: str = "") -> bool:
    """Is the figure stated in a sentence/row about the same thing as the claim?

    Searching every provided source (not just the cited ones) makes coincidental matches
    likely, e.g. a "$115.80 billion" of operating cash flow for a capex claim, so a repair
    needs the figure next to the claim's own words.
    """
    if source.chunk.fiscal_quarter:
        return _in_release_context(number, words, source, claim_text)
    return any(len(words & content_words(seg)) >= MIN_SEGMENT_WORDS
               and any(_matches(number, n) for n in extract_numbers(seg)) for seg in _segments(source.chunk.text))


# A figure followed within a few words by something counted ("443,956 vehicles", "69,138 million iPhone units"), or after "sold".
_COUNTED = r"(?:\s+[\w/&'-]+){0,3}?\s+(?:units?|vehicles?|cars?|devices?|phones?|shipments?|subscribers?|customers?|employees?|people|users?)\b"
_SOLD = r"\b(?:sold|shipped)\s+(?:about\s+|approximately\s+)?"
_COUNT_ROW = re.compile(r"\b(?:units?|vehicles?|cars?|deliver|produc|shipments?|subscribers?|customers?|accounts?|employees?|headcount|"
                        r"people|users?|stations?|connectors?|locations?)", re.IGNORECASE)
_MONEY_TABLE = re.compile(r"\$|\bUSD\b")
_COMBINED = re.compile(r"\b([A-Z][a-z]+) (\w+)/(\w+)\b")  # "Model 3/Y": two products in one figure
# The claim talks about another period on purpose ("up from 18,120 a year ago"): columns can't judge it.
_COMPARES = re.compile(r"\b(?:ago|prior|previous|compared|versus|vs\.?|last year|earlier|from \$?\d)", re.IGNORECASE)


def _names_one_of_a_combined_figure(claim_text: str, row: str) -> bool:
    text = claim_text.lower()
    for name, a, b in _COMBINED.findall(row):
        if f"{name} {a}/{b}".lower() not in text and (f"{name} {a}".lower() in text) != (f"{name} {b}".lower() in text):
            return True
    return False


def _claimed_periods(claim_text: str, chunk: Chunk) -> set[Period] | None:
    """The periods a claim is about: those it names, or else the release's own quarter. None when it can't be said."""
    if _COMPARES.search(claim_text):
        return None
    quarters = find_quarters(claim_text)
    quarters = () if quarters == ALL_QUARTERS else quarters
    years = [*find_years(claim_text)[0], *find_years(claim_text)[1]]
    if quarters:
        return {(q, y) for q in quarters for y in (years or [chunk.fiscal_year])}
    return None if years else {(chunk.fiscal_quarter, chunk.fiscal_year)}  # type: ignore[arg-type]


def _is_bare_label_number(number: Number) -> bool:
    """The "3" of "Model 3" or a footnote mark: a plain small integer isn't a reported figure a column could judge."""
    return number.scale == 1 and number.decimals == 0 and number.value < 1000 and "$" not in number.raw


def _column_verdict(number: Number, claim_text: str, row: str, chunk: Chunk) -> bool | None:
    """True or False when the table's labels show the figure is or isn't in the claimed period's column; else None."""
    if number.percent or _is_bare_label_number(number):
        return None
    if not (claimed := _claimed_periods(claim_text, chunk)) or not claimed & known_periods(chunk):
        return None
    found = periods_of_figure(row, chunk, lambda cell: any(_matches(number, n) for n in extract_numbers(cell)))
    return None if found is None else bool(found & claimed)


def _on_chart_axis(number: Number, row: str) -> bool:
    """A slide's chart text ("0 1 2 3 4 (200) (150)"): evenly spaced tick labels aren't reported figures."""
    values = [n.value for n in extract_numbers(row)]
    for i, value in enumerate(values):
        if value == number.value * number.scale or value == number.value:
            for start in range(max(0, i - 3), i + 1):
                run = values[start : start + 4]
                if len(run) == 4 and len({round(b - a, 6) for a, b in zip(run, run[1:])}) == 1 and run[1] != run[0]:
                    return True
    return False


def _is_count_on_money(number: Number, claim_text: str, row: str, chunk: Chunk) -> bool:
    """A figure stated as a count, resting on dollars: on its own row, or in a money table's row naming nothing counted."""
    if "$" in number.raw:
        return False
    raw = re.escape(number.raw)
    if not (re.search(raw + _COUNTED, claim_text, re.IGNORECASE) or re.search(_SOLD + raw, claim_text, re.IGNORECASE)):
        return False
    if all("$" in n.raw for n in extract_numbers(row) if _matches(number, n)):
        return True
    return bool(_MONEY_TABLE.search(chunk.text)) and not _COUNT_ROW.search(row)


def _row_names_it(number: Number, claim_text: str, row: str, chunk: Chunk) -> bool:
    """Is this release row's figure the metric the claim says it is? See the module docstring."""
    return (not _names_one_of_a_combined_figure(claim_text, row) and not _is_count_on_money(number, claim_text, row, chunk)
            and not _on_chart_axis(number, row))


def _relabelled(numbers: Sequence[Number], claim_text: str, sources: Sequence[Source]) -> list[Number]:
    """Figures in the cited release sources only as another metric or another period's column.

    A column that shows the wrong period outweighs a table that can't be read: an unreadable table is no evidence.
    """
    if not sources or not all(s.chunk.fiscal_quarter for s in sources):
        return []
    rows = [(seg, s.chunk) for s in sources for seg in _segments(s.chunk.text)]
    rejected = []
    for n in numbers:
        fitting = [(r, c) for r, c in rows if any(_matches(n, x) for x in extract_numbers(r)) and _row_names_it(n, claim_text, r, c)]
        verdicts = {_column_verdict(n, claim_text, r, c) for r, c in fitting}
        if not fitting or (False in verdicts and True not in verdicts):
            rejected.append(n)
    return rejected


def _stems(words: set[str]) -> set[str]:
    return {w[:STEM_CHARS] for w in words if w.isalpha()}


def _in_release_context(number: Number, words: set[str], source: Source, claim_text: str = "") -> bool:
    """A release's rows don't repeat the company and period ("Net income | $19,309" sits under "Q3 FY25"),
    and its tables use nouns where answers use verbs ("deliveries", "delivered"). So the test is the exact
    figure in a row that names the claim's metric: words beyond the company, compared by stem.
    """
    metric = _stems(words - content_words(source.chunk.context))
    return any(metric & _stems(content_words(seg)) and _row_names_it(number, claim_text, seg, source.chunk)
               and any(_matches(number, n) for n in extract_numbers(seg)) for seg in _segments(source.chunk.text))


@dataclass
class VerifiedClaim:
    text: str
    source_ids: list[str]
    status: ClaimStatus
    unsupported_numbers: list[str] = field(default_factory=list)
    repaired: bool = False  # citations were added or replaced by the verifier, not given by the model

    @property
    def supported(self) -> bool:
        return self.status == "supported"


def normalize_source_id(raw: str) -> str:
    """"[S3]", "s3", "Source 3" and "3" all mean S3."""
    m = re.search(r"(\d+)", raw)
    return f"S{m.group(1)}" if m else raw.strip()


def _missing(numbers: Sequence[Number], derived: Sequence[Number], source_numbers: Sequence[Number]) -> list[Number]:
    return [n for n in numbers
            if not any(_matches(n, s) for s in source_numbers)
            and not any(n.percent == d.percent and n.value * n.scale == d.value * d.scale for d in derived)]


def verify_claim(claim: Claim, sources: Mapping[str, Source], repair: bool = True) -> VerifiedClaim:
    valid_ids = [sid for sid in dict.fromkeys(normalize_source_id(i) for i in claim.source_ids) if sid in sources]
    numbers, derived = extract_numbers(claim.text), derived_figures(claim.text)
    missing = _missing(numbers, derived, [n for sid in valid_ids for n in extract_numbers(sources[sid].chunk.text)])
    found = [n for n in numbers if n not in missing]
    missing += [n for n in _relabelled(found, claim.text, [sources[sid] for sid in valid_ids]) if n not in derived]
    if valid_ids and not missing:
        return VerifiedClaim(claim.text, valid_ids, "supported")
    if repair and (fixed := _repair(claim.text, valid_ids, missing, sources)):
        # The new sources together must not show the figure in another period's column.
        if not _relabelled(found + [n for n in numbers if n not in found], claim.text, [sources[sid] for sid in fixed]):
            return VerifiedClaim(claim.text, fixed, "supported", repaired=True)
    if not valid_ids:
        return VerifiedClaim(claim.text, list(claim.source_ids), "invalid_citation")
    return VerifiedClaim(claim.text, valid_ids, "unsupported_number", [n.raw for n in missing])


def _repair(text: str, cited: list[str], missing: list[Number], sources: Mapping[str, Source]) -> list[str] | None:
    """Re-attribute a claim to the provided sources that contain its unsupported figures.

    Greedy set cover over sources sharing most of the claim's wording; returns the new
    source ids, or None when the claim can't be pinned on any source.
    """
    enough_words = len(content_words(text)) >= MIN_REPAIR_WORDS
    # A release's figure is judged by its row alone (`_in_release_context`): short claims are normal there.
    scored = {sid: overlap(text, s) for sid, s in sources.items() if sid not in cited}
    candidates = sorted((sid for sid, o in scored.items()
                         if (enough_words and o >= MIN_REPAIR_OVERLAP) or (missing and sources[sid].chunk.fiscal_quarter)),
                        key=lambda sid: -scored[sid])
    if not missing:  # uncited claim without figures: the source that shares the most wording
        return [candidates[0]] if candidates and not cited else None
    words = content_words(text)
    added: list[str] = []
    while missing:
        best, covered = None, []
        for sid in candidates:
            hits = [n for n in missing if _in_context(n, words, sources[sid], text)]
            if len(hits) > len(covered):
                best, covered = sid, hits
        if best is None:
            return None
        added.append(best)
        candidates.remove(best)
        missing = [n for n in missing if n not in covered]
    return cited + added


def verify_claims(claims: Sequence[Claim], sources: Sequence[Source], repair: bool = True) -> list[VerifiedClaim]:
    by_id = {s.id: s for s in sources}
    return [verify_claim(c, by_id, repair) for c in claims]

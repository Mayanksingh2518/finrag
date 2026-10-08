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
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.generation.context import Source
from app.generation.schemas import Claim

ClaimStatus = Literal["supported", "unsupported_number", "invalid_citation"]

_NUM = re.compile(r"(?<![\w.])\$?\(?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\)?\s*(%|percent|billion|million|thousand|bn|mn)?",
                  re.IGNORECASE)
_SCALE = {"billion": 1e9, "bn": 1e9, "million": 1e6, "mn": 1e6, "thousand": 1e3}


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
        whole, frac, unit = m.group(1), m.group(2) or "", (m.group(3) or "").lower()
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


def _segments(text: str) -> list[str]:
    """Sentences and table rows: the context a figure is stated in."""
    return [seg for seg in re.split(r"\n|(?<=[.;])\s+", text) if seg.strip()]


def _in_context(number: Number, words: set[str], source: Source) -> bool:
    """Is the figure stated in a sentence/row about the same thing as the claim?

    Searching every provided source (not just the cited ones) makes coincidental matches
    likely, e.g. a "$115.80 billion" of operating cash flow for a capex claim, so a repair
    needs the figure next to the claim's own words.
    """
    return any(len(words & content_words(seg)) >= MIN_SEGMENT_WORDS
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
    if valid_ids and not missing:
        return VerifiedClaim(claim.text, valid_ids, "supported")
    if repair and (fixed := _repair(claim.text, valid_ids, missing, sources)):
        return VerifiedClaim(claim.text, fixed, "supported", repaired=True)
    if not valid_ids:
        return VerifiedClaim(claim.text, list(claim.source_ids), "invalid_citation")
    return VerifiedClaim(claim.text, valid_ids, "unsupported_number", [n.raw for n in missing])


def _repair(text: str, cited: list[str], missing: list[Number], sources: Mapping[str, Source]) -> list[str] | None:
    """Re-attribute a claim to the provided sources that contain its unsupported figures.

    Greedy set cover over sources sharing most of the claim's wording; returns the new
    source ids, or None when the claim can't be pinned on any source.
    """
    if len(content_words(text)) < MIN_REPAIR_WORDS:
        return None
    scored = {sid: overlap(text, s) for sid, s in sources.items() if sid not in cited}
    candidates = sorted((sid for sid, o in scored.items() if o >= MIN_REPAIR_OVERLAP), key=lambda sid: -scored[sid])
    if not missing:  # uncited claim without figures: the source that shares the most wording
        return [candidates[0]] if candidates and not cited else None
    words = content_words(text)
    added: list[str] = []
    while missing:
        best, covered = None, []
        for sid in candidates:
            hits = [n for n in missing if _in_context(n, words, sources[sid])]
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

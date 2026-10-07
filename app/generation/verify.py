"""Check every claim against the sources it cites.

A claim is *supported* when it cites at least one source that was actually in
the prompt and every number in it appears in one of its cited sources. Numbers
are compared by value with scale awareness, because filings and answers state
the same figure differently: "$109.2 billion" (answer) vs "109,158" in a table
reported in millions, or "14%" vs "14 %". Years are ignored (they appear in
every source header). This catches the common grounding failures: invented
figures, figures from the wrong source, and citations to sources never shown.
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


@dataclass
class VerifiedClaim:
    text: str
    source_ids: list[str]
    status: ClaimStatus
    unsupported_numbers: list[str] = field(default_factory=list)

    @property
    def supported(self) -> bool:
        return self.status == "supported"


def verify_claim(claim: Claim, sources: Mapping[str, Source]) -> VerifiedClaim:
    valid_ids = [sid for sid in dict.fromkeys(claim.source_ids) if sid in sources]
    if not valid_ids:
        return VerifiedClaim(claim.text, list(claim.source_ids), "invalid_citation")
    source_numbers = [n for sid in valid_ids for n in extract_numbers(sources[sid].chunk.text)]
    missing = [n.raw for n in extract_numbers(claim.text) if not any(_matches(n, s) for s in source_numbers)]
    return VerifiedClaim(claim.text, valid_ids, "unsupported_number" if missing else "supported", missing)


def verify_claims(claims: Sequence[Claim], sources: Sequence[Source]) -> list[VerifiedClaim]:
    by_id = {s.id: s for s in sources}
    return [verify_claim(c, by_id) for c in claims]

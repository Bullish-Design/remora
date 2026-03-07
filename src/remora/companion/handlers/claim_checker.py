from __future__ import annotations

import re
from remora.core.events.events import _FrozenEvent
from remora.companion.events import CompanionContextExtracted, CompanionClaimsChecked, CompanionClaim
from remora.companion.handlers.base import CompanionHandlerBase
from remora.companion.state import CompanionState

_PERCENTAGE_RE = re.compile(r"\d+\s*%")
_MULTIPLIER_RE = re.compile(r"\d+x\b", re.IGNORECASE)
_SUPERLATIVES = ["fastest", "slowest", "best", "worst", "most", "least", "always", "never", "every", "all"]
_AUTHORITY_PHRASES = ["studies show", "studies prove", "research shows", "research proves", "experts agree", "it is well known", "it is proven", "everyone knows", "science shows", "data shows", "benchmarks show"]

def _find_claims(text: str) -> list[CompanionClaim]:
    claims = []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    
    for sentence in sentences:
        lower = sentence.lower()
        reason = None
        if _PERCENTAGE_RE.search(sentence):
            reason = "percentage"
        elif _MULTIPLIER_RE.search(sentence):
            reason = "multiplier"
        else:
            for phrase in _AUTHORITY_PHRASES:
                if phrase in lower:
                    reason = "authority"
                    break
            if not reason:
                for word in _SUPERLATIVES:
                    if re.search(rf"\b{word}\b", lower):
                        reason = "superlative"
                        break
        
        if reason:
            claims.append(CompanionClaim(
                claim_text=sentence,
                status="unverified",
                evidence=f"Needs citation for {reason} claim"
            ))
    return claims

class ClaimCheckerHandler(CompanionHandlerBase):
    """Identifies unsupported claims in prose/markdown content."""
    
    async def handle(self, event: _FrozenEvent, state: CompanionState) -> list[_FrozenEvent]:
        if not isinstance(event, CompanionContextExtracted) or event.content_type != "markdown":
            return []
            
        claims = _find_claims(event.surrounding_code)
        if claims:
            return [CompanionClaimsChecked(claims=tuple(claims))]
            
        return [CompanionClaimsChecked(claims=())]

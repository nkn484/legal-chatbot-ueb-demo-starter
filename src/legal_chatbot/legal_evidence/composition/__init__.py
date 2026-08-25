"""P10 structured legal answer composition."""

from .deterministic import DeterministicEvidenceBoundComposer
from .models import (
    AnswerClaim,
    ClaimKind,
    CompositionEvidence,
    CompositionResult,
    CompositionSettings,
)
from .service import CompositionEvidenceReaderPort, StructuredAnswerComposer

__all__ = [
    "AnswerClaim",
    "ClaimKind",
    "CompositionEvidence",
    "CompositionEvidenceReaderPort",
    "CompositionResult",
    "CompositionSettings",
    "DeterministicEvidenceBoundComposer",
    "StructuredAnswerComposer",
]

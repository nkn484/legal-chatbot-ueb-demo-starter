"""Bounded discovery service driven exclusively by a validated read manifest."""

from dataclasses import dataclass

from legal_chatbot.sources.errors import SourceError
from legal_chatbot.sources.models import DiscoveryCandidate, SourceErrorCode
from legal_chatbot.sources.port import LegalSourceDiscoveryPort
from legal_chatbot.sources.registry import VBQPPLReadManifest


@dataclass(frozen=True)
class DiscoveryOutcome:
    """One content-safe review outcome for a manifest-approved document number."""

    document_number: str
    candidate: DiscoveryCandidate | None = None
    error_code: SourceErrorCode | None = None

    def __post_init__(self) -> None:
        if (self.candidate is None) == (self.error_code is None):
            raise ValueError("discovery outcome requires exactly one candidate or error code")
        if self.candidate is not None and self.candidate.document_number != self.document_number:
            raise ValueError("discovery candidate number must match its outcome")

    @property
    def success(self) -> bool:
        return self.candidate is not None

    def payload(self) -> dict[str, object]:
        """Serialize only reviewed identity fields and normalized failure codes."""
        if self.candidate is not None:
            return {
                "document_number": self.document_number,
                "outcome": "success",
                "candidate": self.candidate.model_dump(mode="json"),
            }
        return {
            "document_number": self.document_number,
            "outcome": "failure",
            "error": self.error_code.value if self.error_code is not None else "unavailable",
        }


async def discover_manifest(
    source: LegalSourceDiscoveryPort, manifest: VBQPPLReadManifest
) -> tuple[DiscoveryOutcome, ...]:
    """Discover every approved number sequentially, retaining normalized per-item failures."""
    outcomes: list[DiscoveryOutcome] = []
    for request in manifest.discovery_requests():
        try:
            candidate = await source.discover_document(request)
        except SourceError as error:
            outcomes.append(DiscoveryOutcome(request.document_number, error_code=error.code))
        except Exception:
            outcomes.append(
                DiscoveryOutcome(request.document_number, error_code=SourceErrorCode.UNAVAILABLE)
            )
        else:
            outcomes.append(DiscoveryOutcome(request.document_number, candidate=candidate))
    return tuple(outcomes)

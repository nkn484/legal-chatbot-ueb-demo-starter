"""P3 broad discovery contracts and orchestration."""

from .models import (
    BroadDiscoveryWorkspace,
    DiscoveryDocument,
    DiscoveryLane,
    DiscoveryLaneObservation,
    DiscoveryOutcome,
    DiscoveryReadRequest,
    DiscoverySettings,
    RawDiscoveryCandidate,
)
from .service import (
    BroadDiscoveryReaderPort,
    BroadDiscoveryResult,
    BroadDiscoveryService,
    collapse_candidates,
)

__all__ = [
    "BroadDiscoveryReaderPort",
    "BroadDiscoveryResult",
    "BroadDiscoveryService",
    "BroadDiscoveryWorkspace",
    "DiscoveryDocument",
    "DiscoveryLane",
    "DiscoveryLaneObservation",
    "DiscoveryOutcome",
    "DiscoveryReadRequest",
    "DiscoverySettings",
    "RawDiscoveryCandidate",
    "collapse_candidates",
]

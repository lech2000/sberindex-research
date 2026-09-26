"""Data boundaries for future implementation. No trained model or measured result."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, Sequence

@dataclass(frozen=True)
class Observation:
    municipality_id: str
    period: datetime
    value: float | None
    category: str
    unit: str
    available_at: datetime
    source_id: str
    vintage: str
    geography_version: str
    is_suppressed: bool = False

@dataclass(frozen=True)
class RunManifest:
    experiment_id: str
    git_commit: str
    data_sha256: str
    config_sha256: str
    seed: int
    cutoff: datetime
    model_revision: str

class ResearchPipeline(Protocol):
    def validate_data(self, observations: Sequence[Observation]) -> dict[str, Any]: ...
    def fit(self, observations: Sequence[Observation], manifest: RunManifest) -> None: ...
    def evaluate(self, observations: Sequence[Observation], manifest: RunManifest) -> dict[str, Any]: ...

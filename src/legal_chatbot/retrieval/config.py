"""Source-neutral bounded retrieval runtime settings."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from legal_chatbot.retrieval.quality_repair.strategy import (
    QUALITY_REPAIR_PROFILES,
    QualityRepairStrategy,
)


class RetrievalSettings(BaseSettings):
    """Server-owned retrieval switches; hidden user input cannot change them."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False,
        extra="ignore", hide_input_in_errors=True, populate_by_name=True,
    )

    lexical_repair_enabled: bool = Field(
        default=False, validation_alias="RETRIEVAL_LEXICAL_REPAIR_ENABLED"
    )
    semantic_hybrid_enabled: bool = Field(
        default=False, validation_alias="RETRIEVAL_SEMANTIC_HYBRID_ENABLED"
    )
    rerank_enabled: bool = Field(default=False, validation_alias="RETRIEVAL_RERANK_ENABLED")
    metadata_repair_enabled: bool = Field(
        default=False, validation_alias="RETRIEVAL_METADATA_REPAIR_ENABLED"
    )
    quality_repair_enabled: bool = Field(
        default=False, validation_alias="RETRIEVAL_QUALITY_REPAIR_ENABLED"
    )
    quality_title_search_enabled: bool = Field(
        default=False, validation_alias="RETRIEVAL_QUALITY_TITLE_SEARCH_ENABLED"
    )
    quality_hybrid_fusion_enabled: bool = Field(
        default=False, validation_alias="RETRIEVAL_QUALITY_HYBRID_FUSION_ENABLED"
    )
    quality_query_planner_enabled: bool = Field(
        default=False, validation_alias="RETRIEVAL_QUALITY_QUERY_PLANNER_ENABLED"
    )
    quality_dynamic_evidence_enabled: bool = Field(
        default=False, validation_alias="RETRIEVAL_QUALITY_DYNAMIC_EVIDENCE_ENABLED"
    )
    quality_repair_retrieval_enabled: bool = Field(
        default=False, validation_alias="RETRIEVAL_QUALITY_REPAIR_RETRIEVAL_ENABLED"
    )
    quality_strategy: str = Field(default="disabled", validation_alias="RETRIEVAL_QUALITY_STRATEGY")
    quality_selected_pool: int | None = Field(
        default=None, validation_alias="RETRIEVAL_QUALITY_SELECTED_POOL"
    )

    @model_validator(mode="after")
    def validate_quality_repair_flags(self) -> "RetrievalSettings":
        """Keep Phase-A contracts inert unless one complete named profile is selected."""

        flags = {
            "quality_title_search_enabled": self.quality_title_search_enabled,
            "quality_hybrid_fusion_enabled": self.quality_hybrid_fusion_enabled,
            "quality_query_planner_enabled": self.quality_query_planner_enabled,
            "quality_dynamic_evidence_enabled": self.quality_dynamic_evidence_enabled,
            "quality_repair_retrieval_enabled": self.quality_repair_retrieval_enabled,
        }
        if not self.quality_repair_enabled:
            if any(flags.values()):
                raise ValueError("quality subflags require RETRIEVAL_QUALITY_REPAIR_ENABLED")
            if self.quality_strategy != "disabled":
                raise ValueError("quality strategy requires RETRIEVAL_QUALITY_REPAIR_ENABLED")
            if self.quality_selected_pool is not None:
                raise ValueError("quality selected pool requires RETRIEVAL_QUALITY_REPAIR_ENABLED")
            return self
        if (
            self.quality_strategy == "disabled"
            or self.quality_strategy not in QUALITY_REPAIR_PROFILES
        ):
            raise ValueError("enabled quality repair requires a known non-disabled strategy")
        profile = QUALITY_REPAIR_PROFILES[self.quality_strategy]
        if not isinstance(profile, QualityRepairStrategy):
            raise ValueError("quality ablation controls cannot be enabled as runtime strategies")
        expected = profile.required_quality_flags
        enabled = frozenset(name for name, value in flags.items() if value)
        if enabled != expected:
            raise ValueError("quality subflags must exactly match the selected strategy profile")
        if self.quality_selected_pool not in profile.candidate_pool_sizes:
            raise ValueError("quality selected pool must be declared by the selected strategy")
        return self

"""Bounded, deterministic Vietnamese legal-question analysis contracts."""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Final

from pydantic import AliasChoices, Field, field_validator, model_validator

from .models import SourceBinding, SourceId, SourceScopeObservation, _FrozenContract

SourceScope = SourceScopeObservation

_MAX_INPUT_CHARS: Final = 2_000
_MAX_UNITS: Final = 4
_MAX_VALUE_CHARS: Final = 128
_WORD_RE: Final = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ỹĐđ]+", re.UNICODE)
_DOCUMENT_NUMBER_RE: Final = re.compile(
    r"\b\d{1,5}/(?:\d{2,4}/)?[0-9A-Za-zÀ-ÖØ-öø-ỹĐđ]+(?:[-.][0-9A-Za-zÀ-ÖØ-öø-ỹĐđ]+){0,3}\b",
    re.UNICODE,
)
_DATE_RE: Final = re.compile(
    r"\b(?:ngày\s*)?\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(?:năm\s*)?\d{4}\b",
    re.IGNORECASE | re.UNICODE,
)
_TIME_PHRASE_RE: Final = re.compile(
    r"\b(?:trước|sau|từ|đến|trong|kể từ|hiện nay|hiện tại|sắp tới)\s+[^,;?.!]{1,48}",
    re.IGNORECASE | re.UNICODE,
)
_ORGANIZATION_START_RE: Final = re.compile(
    r"\b(?:trường\s+đại\s+học|đại\s+học|công\s+ty|doanh\s+nghiệp|"
    r"ủy\s+ban(?:\s+nhân\s+dân)?|sở|cơ\s+quan)\b",
    re.IGNORECASE | re.UNICODE,
)
_STAGE_SPLIT_RE: Final = re.compile(
    r"\b(?:sau\s+đó|tiếp\s+theo|đồng\s+thời|rồi)\b", re.IGNORECASE | re.UNICODE
)
_COORDINATED_ACTION_SPLIT_RE: Final = re.compile(
    r"\b(?:và|hoặc|cũng\s+như)\b", re.IGNORECASE | re.UNICODE
)
_ORGANIZATION_STOP_WORDS: Final = frozenset(
    {
        "là",
        "có",
        "cần",
        "được",
        "áp",
        "thủ",
        "quy",
        "thế",
        "ở",
        "khi",
        "năm",
        "theo",
    }
)


class GenericIntent(StrEnum):
    GENERAL = "GENERAL"
    INFORMATION = "INFORMATION"
    PROCEDURE = "PROCEDURE"
    ELIGIBILITY = "ELIGIBILITY"
    DOCUMENT_LOOKUP = "DOCUMENT_LOOKUP"
    RIGHTS = "RIGHTS"
    OBLIGATION = "OBLIGATION"
    SANCTION = "SANCTION"
    AUTHORITY = "AUTHORITY"
    PROHIBITION = "PROHIBITION"
    LEGAL_CONSEQUENCE = "LEGAL_CONSEQUENCE"
    EVALUATION_CRITERIA = "EVALUATION_CRITERIA"
    DOCUMENT_MANAGEMENT = "DOCUMENT_MANAGEMENT"
    VALIDITY_APPLICABILITY = "VALIDITY_APPLICABILITY"
    MULTI_STAGE_PROCESS = "MULTI_STAGE_PROCESS"


class QueryComplexity(StrEnum):
    SIMPLE = "SIMPLE"
    MULTI_INTENT = "MULTI_INTENT"
    MULTI_SOURCE = "MULTI_SOURCE"
    AMBIGUOUS = "AMBIGUOUS"


class AmbiguityCode(StrEnum):
    NONE = "NONE"
    SOURCE_AMBIGUOUS = "SOURCE_AMBIGUOUS"
    SUBJECT_UNCLEAR = "SUBJECT_UNCLEAR"


class SourceAccessStatus(StrEnum):
    """Content-free status for a future reader boundary."""

    ACTIVE = "ACTIVE"
    SOURCE_ACCESS_UNAVAILABLE = "SOURCE_ACCESS_UNAVAILABLE"


class CorpusEligibilityStatus(StrEnum):
    """Persisted-corpus availability only; this says nothing about evidence or authority."""

    CORPUS_ELIGIBLE = "CORPUS_ELIGIBLE"
    MANUAL_SNAPSHOT_LIMITED = "MANUAL_SNAPSHOT_LIMITED"
    CORPUS_UNAVAILABLE = "CORPUS_UNAVAILABLE"
    MIXED_CORPUS_SCOPE = "MIXED_CORPUS_SCOPE"


class CorpusEligibility(_FrozenContract):
    """Content-free corpus limitation disclosure for one observed binding."""

    status: CorpusEligibilityStatus
    manual_snapshot_limitations_declared: bool = False

    @model_validator(mode="after")
    def validate_manual_limitation(self) -> CorpusEligibility:
        if (
            self.status is CorpusEligibilityStatus.MANUAL_SNAPSHOT_LIMITED
            and not self.manual_snapshot_limitations_declared
        ):
            raise ValueError("manual snapshot eligibility requires declared limitations")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "manual_snapshot_limitations_declared": self.manual_snapshot_limitations_declared,
        }


def _validate_private_text(value: str, *, maximum: int = _MAX_VALUE_CHARS) -> str:
    if not value or not value.strip() or len(value) > maximum:
        raise ValueError("private text must be nonblank and bounded")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("private text must not contain control characters")
    return value


class ConceptQuery(_FrozenContract):
    """Private memory-only terms for a future reader; it is not a query string."""

    core_concepts: tuple[str, ...] = Field(default=(), max_length=8, exclude=True, repr=False)
    important_noun_phrases: tuple[str, ...] = Field(
        default=(), max_length=8, exclude=True, repr=False
    )
    document_number_tokens: tuple[str, ...] = Field(
        default=(), max_length=4, exclude=True, repr=False
    )
    organization_aliases: tuple[str, ...] = Field(
        default=(), max_length=4, exclude=True, repr=False
    )
    safe_aliases: tuple[str, ...] = Field(default=(), max_length=6, exclude=True, repr=False)
    truncated: bool = False

    @field_validator(
        "core_concepts",
        "important_noun_phrases",
        "document_number_tokens",
        "organization_aliases",
        "safe_aliases",
    )
    @classmethod
    def validate_private_terms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("private terms must be unique")
        return tuple(_validate_private_text(item) for item in value)


class AnalyzerUnit(_FrozenContract):
    """One bounded unit with private derived observations and no executable query."""

    unit_id: str = Field(min_length=1, max_length=32, exclude=True, repr=False)
    intent: GenericIntent = Field(default=GenericIntent.GENERAL, exclude=True, repr=False)
    legal_actor: str | None = Field(
        default=None, max_length=_MAX_VALUE_CHARS, exclude=True, repr=False
    )
    action_event: str | None = Field(
        default=None, max_length=_MAX_VALUE_CHARS, exclude=True, repr=False
    )
    organization_scope: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    explicit_time: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    legal_topics: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    source_scope: SourceScope
    source_ids: tuple[SourceId, ...] = Field(default=(), max_length=1, exclude=True, repr=False)
    source_binding: SourceBinding = Field(default=SourceBinding.UNKNOWN, exclude=True, repr=False)
    concept_query: ConceptQuery = Field(default_factory=ConceptQuery, exclude=True, repr=False)
    # Compatibility-only private input for existing contracts. The analyzer never creates it.
    query_text: str | None = Field(
        default=None, max_length=_MAX_INPUT_CHARS, exclude=True, repr=False
    )

    @field_validator("unit_id")
    @classmethod
    def validate_unit_id(cls, value: str) -> str:
        return _validate_private_text(value, maximum=32)

    @field_validator("legal_actor", "action_event", "query_text")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _validate_private_text(value, maximum=_MAX_INPUT_CHARS)

    @field_validator("organization_scope", "explicit_time", "legal_topics")
    @classmethod
    def validate_private_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("private values must be unique")
        return tuple(_validate_private_text(item) for item in value)

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, value: tuple[SourceId, ...]) -> tuple[SourceId, ...]:
        if len(set(value)) != len(value):
            raise ValueError("source_ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_source_scope(self) -> AnalyzerUnit:
        if self.source_scope is SourceScope.EXPLICIT_SOURCE:
            if len(self.source_ids) != 1:
                raise ValueError("EXPLICIT_SOURCE requires exactly one source_id")
            expected = SourceBinding(self.source_ids[0].value)
            if self.source_binding not in (SourceBinding.UNKNOWN, expected):
                raise ValueError("source_binding must match the explicit source")
        elif self.source_ids:
            raise ValueError("NONE and AMBIGUOUS_SOURCE cannot resolve source_ids")
        elif self.source_scope is SourceScope.AMBIGUOUS_SOURCE:
            if self.source_binding not in (SourceBinding.UNKNOWN, SourceBinding.AMBIGUOUS):
                raise ValueError("ambiguous source scope requires ambiguous source_binding")
        elif self.source_binding not in (SourceBinding.UNKNOWN,):
            raise ValueError("unresolved source scope requires UNKNOWN source_binding")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent.value,
            "source_binding": self.source_binding.value,
            "query_terms_truncated": self.concept_query.truncated,
        }


def derived_source_scope(units: tuple[AnalyzerUnit, ...]) -> SourceScope:
    """Derive an observation summary without resolving or prioritizing a source."""

    scopes = {unit.source_scope for unit in units}
    if SourceScope.AMBIGUOUS_SOURCE in scopes:
        return SourceScope.AMBIGUOUS_SOURCE
    if SourceScope.EXPLICIT_SOURCE in scopes:
        return SourceScope.EXPLICIT_SOURCE
    return SourceScope.NONE


class AnalyzerObservation(_FrozenContract):
    """Private analysis with count/code-only diagnostics."""

    intent: GenericIntent = Field(exclude=True, repr=False)
    intent_label: str | None = Field(default=None, max_length=64, exclude=True, repr=False)
    legal_actor: str | None = Field(
        default=None, max_length=_MAX_VALUE_CHARS, exclude=True, repr=False
    )
    action_event: str | None = Field(
        default=None, max_length=_MAX_VALUE_CHARS, exclude=True, repr=False
    )
    organization_scope: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    explicit_time: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    legal_topics: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    # Legacy private names remain accepted while readers migrate to the explicit fields above.
    entities: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    organizations: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    topics: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    sub_intents: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    complexity: QueryComplexity
    ambiguity: AmbiguityCode = AmbiguityCode.NONE
    source_scope: SourceScope
    units: tuple[AnalyzerUnit, ...] = Field(
        default=(), max_length=_MAX_UNITS, exclude=True, repr=False
    )
    decomposition_text: str | None = Field(default=None, max_length=1_024, exclude=True, repr=False)
    unit_truncated: bool = False

    @field_validator("intent_label", "legal_actor", "action_event", "decomposition_text")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _validate_private_text(value, maximum=_MAX_INPUT_CHARS)

    @field_validator(
        "organization_scope",
        "explicit_time",
        "legal_topics",
        "entities",
        "organizations",
        "topics",
        "sub_intents",
    )
    @classmethod
    def validate_opaque_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("opaque values must be unique")
        return tuple(_validate_private_text(item) for item in value)

    @model_validator(mode="after")
    def validate_source_summary(self) -> AnalyzerObservation:
        if not self.units:
            raise ValueError("an analyzer observation requires at least one unit")
        if self.source_scope is not derived_source_scope(self.units):
            raise ValueError("source_scope must equal the derived per-unit source summary")
        return self

    def to_public_dict(self) -> dict[str, object]:
        bindings = {binding.value: 0 for binding in SourceBinding}
        for unit in self.units:
            bindings[unit.source_binding.value] += 1
        return {
            "unit_count": len(self.units),
            "intent_codes": [unit.intent.value for unit in self.units],
            "complexity": self.complexity.value,
            "ambiguity": self.ambiguity.value,
            "binding_distribution": bindings,
            "query_unit_count": len(self.units),
            "query_truncated_unit_count": sum(
                unit.concept_query.truncated for unit in self.units
            ),
            "unit_truncated": self.unit_truncated,
        }


class AnalyzerPolicy(_FrozenContract):
    """Independent server-owned live and persisted-corpus source scopes."""

    live_access_source_ids: tuple[SourceId, ...] = Field(
        default=(),
        max_length=3,
        exclude=True,
        repr=False,
        validation_alias=AliasChoices("live_access_source_ids", "active_source_ids"),
    )
    corpus_eligible_source_ids: tuple[SourceId, ...] = Field(
        default=(), max_length=3, exclude=True, repr=False
    )
    manual_snapshot_limited_source_ids: tuple[SourceId, ...] = Field(
        default=(), max_length=3, exclude=True, repr=False
    )
    manual_snapshot_limitations_declared: bool = False

    @field_validator(
        "live_access_source_ids",
        "corpus_eligible_source_ids",
        "manual_snapshot_limited_source_ids",
    )
    @classmethod
    def validate_source_ids(cls, value: tuple[SourceId, ...]) -> tuple[SourceId, ...]:
        if len(set(value)) != len(value):
            raise ValueError("source identifiers must be unique")
        return value

    @model_validator(mode="after")
    def validate_independent_scopes(self) -> AnalyzerPolicy:
        manual = set(self.manual_snapshot_limited_source_ids)
        if not manual <= set(self.corpus_eligible_source_ids):
            raise ValueError("manual snapshot sources must be corpus eligible")
        if manual and not self.manual_snapshot_limitations_declared:
            raise ValueError("manual snapshot sources require declared limitations")
        return self

    @property
    def active_source_ids(self) -> tuple[SourceId, ...]:
        """Compatibility name for the live-access scope only."""

        return self.live_access_source_ids

    def validate_observation(self, observation: AnalyzerObservation) -> AnalyzerObservation:
        """Compatibility validation for an active-only future reader boundary."""

        self.validate_known_observation(observation)
        observed_ids = {
            source_id
            for unit in observation.units
            if unit.source_scope is SourceScope.EXPLICIT_SOURCE
            for source_id in unit.source_ids
        }
        if not observed_ids <= set(self.active_source_ids):
            raise ValueError("observation source_ids must be allowed by the analyzer policy")
        return observation

    def validate_known_observation(self, observation: AnalyzerObservation) -> AnalyzerObservation:
        """Accept any enum-backed observed cue without treating it as live access."""

        for unit in observation.units:
            if unit.source_binding in (SourceBinding.UNKNOWN, SourceBinding.AMBIGUOUS):
                continue
            if unit.source_binding.value not in SourceId._value2member_map_:
                raise ValueError("observation contains an unknown source binding")
        return observation

    def access_status(self, binding: SourceBinding) -> SourceAccessStatus:
        """Report configured availability only; this method performs no source operation."""

        if (
            binding.value in SourceId._value2member_map_
            and SourceId(binding.value) in self.live_access_source_ids
        ):
            return SourceAccessStatus.ACTIVE
        return SourceAccessStatus.SOURCE_ACCESS_UNAVAILABLE

    def corpus_eligibility(self, binding: SourceBinding) -> CorpusEligibility:
        """Return configured persisted-corpus eligibility without checking evidence."""

        if binding.value not in SourceId._value2member_map_:
            return CorpusEligibility(status=CorpusEligibilityStatus.CORPUS_UNAVAILABLE)
        source_id = SourceId(binding.value)
        if source_id not in self.corpus_eligible_source_ids:
            return CorpusEligibility(status=CorpusEligibilityStatus.CORPUS_UNAVAILABLE)
        if source_id in self.manual_snapshot_limited_source_ids:
            return CorpusEligibility(
                status=CorpusEligibilityStatus.MANUAL_SNAPSHOT_LIMITED,
                manual_snapshot_limitations_declared=self.manual_snapshot_limitations_declared,
            )
        return CorpusEligibility(status=CorpusEligibilityStatus.CORPUS_ELIGIBLE)


_INTENT_RULES: Final = (
    (GenericIntent.PROHIBITION, ("nghiêm cấm", "cấm", "không được")),
    (GenericIntent.AUTHORITY, ("thẩm quyền", "cơ quan nào", "ai có quyền")),
    (GenericIntent.VALIDITY_APPLICABILITY, ("hiệu lực", "áp dụng", "phạm vi")),
    (GenericIntent.EVALUATION_CRITERIA, ("tiêu chí", "đánh giá", "xếp loại", "chấm điểm")),
    (GenericIntent.DOCUMENT_MANAGEMENT, ("ban hành", "lưu trữ", "sửa đổi", "bãi bỏ", "thay thế")),
    (GenericIntent.LEGAL_CONSEQUENCE, ("hậu quả", "hệ quả", "bồi thường", "phát sinh")),
    (GenericIntent.ELIGIBILITY, ("điều kiện", "có được", "đủ", "tiêu chuẩn")),
    (
        GenericIntent.DOCUMENT_LOOKUP,
        ("văn bản", "nghị định", "thông tư", "quyết định", "điều "),
    ),
    (GenericIntent.PROCEDURE, ("thủ tục", "hồ sơ", "đăng ký", "nộp", "cấp ", "gia hạn")),
    (GenericIntent.SANCTION, ("xử phạt", "phạt", "vi phạm", "kỷ luật")),
    (GenericIntent.OBLIGATION, ("nghĩa vụ", "phải", "trách nhiệm")),
    (GenericIntent.RIGHTS, ("quyền", "được hưởng", "khiếu nại")),
    (GenericIntent.INFORMATION, ("là gì", "quy định", "hướng dẫn", "bao nhiêu")),
)
_ACTOR_RULES: Final = (
    ("NGUOI_LAO_DONG", "người lao động"),
    ("NGUOI_SU_DUNG_LAO_DONG", "người sử dụng lao động"),
    ("SINH_VIEN", "sinh viên"),
    ("DOANH_NGHIEP", "doanh nghiệp"),
    ("CA_NHAN", "cá nhân"),
    ("CO_QUAN", "cơ quan"),
)
_ACTION_RULES: Final = (
    ("DANG_KY", "đăng ký"),
    ("NOP_HO_SO", "nộp hồ sơ"),
    ("TIEP_NHAN", "tiếp nhận"),
    ("THAM_DINH", "thẩm định"),
    ("PHE_DUYET", "phê duyệt"),
    ("CAP", "cấp "),
    ("GIA_HAN", "gia hạn"),
    ("DIEU_CHINH", "điều chỉnh"),
    ("THU_HOI", "thu hồi"),
    ("KHIEU_NAI", "khiếu nại"),
    ("TO_CAO", "tố cáo"),
    ("XU_PHAT", "xử phạt"),
    ("CHAM_DUT", "chấm dứt"),
    ("THANH_TOAN", "thanh toán"),
    ("BAO_CAO", "báo cáo"),
    ("KIEM_TRA", "kiểm tra"),
    ("LUU_TRU", "lưu trữ"),
    ("BAN_HANH", "ban hành"),
)
_TOPIC_RULES: Final = (
    ("LAO_DONG", ("lao động", "tiền lương", "hợp đồng lao động")),
    ("GIAO_DUC", ("sinh viên", "đào tạo", "học phí")),
    ("DOANH_NGHIEP", ("doanh nghiệp", "công ty", "kinh doanh")),
    ("HANH_CHINH", ("thủ tục", "cơ quan", "hành chính")),
    ("THUE", ("thuế", "khai thuế")),
    ("DAT_DAI", ("đất", "đất đai", "quyền sử dụng đất")),
    ("BAO_HIEM", ("bảo hiểm",)),
)
_SAFE_ALIAS_RULES: Final = (
    ("công ty", "doanh nghiệp"),
    ("người lao động", "lao động"),
    ("sinh viên", "người học"),
)
_STOP_WORDS: Final = frozenset(
    {"là", "gì", "cho", "với", "của", "và", "theo", "khi", "được", "trong", "những"}
)


def _unique_bounded(values: list[str], limit: int) -> tuple[tuple[str, ...], bool]:
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value[:_MAX_VALUE_CHARS])
    return tuple(unique[:limit]), len(unique) > limit


def _binding_for(text: str) -> tuple[SourceBinding, SourceScope, tuple[SourceId, ...]]:
    normalized = text.casefold()
    matches: list[SourceId] = []
    cues = (
        (SourceId.VBQPPL, ("vbqppl", "văn bản quy phạm pháp luật")),
        (SourceId.VNU, ("vnu", "đhqghn", "đại học quốc gia hà nội")),
        (
            SourceId.UEB,
            ("ueb", "trường đại học kinh tế - đại học quốc gia hà nội"),
        ),
    )
    for source_id, phrases in cues:
        if any(phrase in normalized for phrase in phrases):
            matches.append(source_id)
    if len(matches) == 1:
        source_id = matches[0]
        return SourceBinding(source_id.value), SourceScope.EXPLICIT_SOURCE, (source_id,)
    if len(matches) > 1:
        return SourceBinding.AMBIGUOUS, SourceScope.AMBIGUOUS_SOURCE, ()
    return SourceBinding.UNKNOWN, SourceScope.NONE, ()


def _intent_for(text: str) -> GenericIntent:
    normalized = text.casefold()
    for intent, markers in _INTENT_RULES:
        if any(marker in normalized for marker in markers):
            return intent
    return GenericIntent.GENERAL


def _first_code(text: str, rules: tuple[tuple[str, str], ...]) -> str | None:
    normalized = text.casefold()
    return next((code for code, marker in rules if marker in normalized), None)


def _topics_for(text: str) -> tuple[str, ...]:
    normalized = text.casefold()
    return tuple(
        code for code, markers in _TOPIC_RULES if any(marker in normalized for marker in markers)
    )[:4]


def _organization_values(text: str) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    candidates: list[str] = []
    for match in _ORGANIZATION_START_RE.finditer(text):
        tail = re.split(r"[,;?.!]", text[match.start() :], maxsplit=1)[0]
        words = tail.split()
        kept: list[str] = []
        for word in words[:7]:
            if word.casefold().strip(".,;:?!") in _ORGANIZATION_STOP_WORDS:
                break
            kept.append(word)
        if len(kept) > 1:
            candidates.append(" ".join(kept))
    organizations, truncated = _unique_bounded(candidates, 4)
    aliases, aliases_truncated = _unique_bounded(
        [" ".join(value.casefold().split()) for value in organizations], 4
    )
    return organizations, aliases, truncated or aliases_truncated


def _concept_query(
    text: str, actor: str | None, action: str | None, topics: tuple[str, ...]
) -> ConceptQuery:
    documents, document_truncated = _unique_bounded(
        [match.group(0).upper() for match in _DOCUMENT_NUMBER_RE.finditer(text)], 4
    )
    organizations, organization_aliases, organization_truncated = _organization_values(text)
    words = [word.casefold() for word in _WORD_RE.findall(text)]
    concepts, concept_truncated = _unique_bounded(
        [word for word in words if len(word) > 2 and word not in _STOP_WORDS], 8
    )
    noun_phrases, phrase_truncated = _unique_bounded(
        list(organizations)
        + ([actor] if actor else [])
        + ([action] if action else [])
        + list(topics),
        8,
    )
    aliases, alias_truncated = _unique_bounded(
        [alias for marker, alias in _SAFE_ALIAS_RULES if marker in text.casefold()], 6
    )
    return ConceptQuery(
        core_concepts=concepts,
        important_noun_phrases=noun_phrases,
        document_number_tokens=documents,
        organization_aliases=organization_aliases,
        safe_aliases=aliases,
        truncated=(
            document_truncated
            or organization_truncated
            or concept_truncated
            or phrase_truncated
            or alias_truncated
        ),
    )


def _is_material(text: str) -> bool:
    normalized = text.casefold()
    markers = tuple(marker for _, rules in _INTENT_RULES for marker in rules) + tuple(
        marker for _, marker in _ACTION_RULES
    )
    return len(_WORD_RE.findall(text)) >= 2 and any(marker in normalized for marker in markers)


def _has_material_action(text: str) -> bool:
    normalized = text.casefold()
    return len(_WORD_RE.findall(text)) >= 2 and any(
        marker in normalized for _, marker in _ACTION_RULES
    )


def _segments(text: str) -> tuple[list[str], bool]:
    sentences = [part.strip() for part in re.split(r"[;?.!]+", text) if part.strip()]
    parts: list[str] = []
    for sentence in sentences or [text]:
        split = [part.strip(" ,") for part in _STAGE_SPLIT_RE.split(sentence) if part.strip(" ,")]
        if len(split) > 1 and all(_is_material(part) for part in split):
            for stage in split:
                coordinated = [
                    part.strip(" ,")
                    for part in _COORDINATED_ACTION_SPLIT_RE.split(stage)
                    if part.strip(" ,")
                ]
                if len(coordinated) > 1 and all(_has_material_action(part) for part in coordinated):
                    parts.extend(coordinated)
                else:
                    parts.append(stage)
        else:
            coordinated = [
                part.strip(" ,")
                for part in _COORDINATED_ACTION_SPLIT_RE.split(sentence)
                if part.strip(" ,")
            ]
            if len(coordinated) > 1 and all(_has_material_action(part) for part in coordinated):
                parts.extend(coordinated)
            else:
                parts.append(sentence)
    material = [part for part in parts if _is_material(part)]
    selected = material if len(material) > 1 else [text]
    return selected[:_MAX_UNITS], len(selected) > _MAX_UNITS


def _validate_input(question: str) -> str:
    if not isinstance(question, str):
        raise ValueError("question must be text")
    normalized = unicodedata.normalize("NFC", question)
    if not normalized.strip() or len(normalized) > _MAX_INPUT_CHARS:
        raise ValueError("question must be nonblank and bounded")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError("question contains unsupported control characters")
    return " ".join(normalized.split())


class LegalQuestionAnalyzer:
    """Pure deterministic analyzer. It accepts no external dependencies."""

    def analyze(self, question: str) -> AnalyzerObservation:
        normalized = _validate_input(question)
        segments, unit_truncated = _segments(normalized)
        source_contexts = [_binding_for(segment) for segment in segments]
        explicit_contexts = {
            binding
            for binding, _, _ in source_contexts
            if binding not in (SourceBinding.UNKNOWN, SourceBinding.AMBIGUOUS)
        }
        may_inherit_context = (
            len(explicit_contexts) == 1
            and not any(binding is SourceBinding.AMBIGUOUS for binding, _, _ in source_contexts)
        )
        inherited_binding = next(iter(explicit_contexts), None) if may_inherit_context else None
        units: list[AnalyzerUnit] = []
        for index, (segment, context) in enumerate(
            zip(segments, source_contexts, strict=True), start=1
        ):
            actor = _first_code(segment, _ACTOR_RULES)
            action = _first_code(segment, _ACTION_RULES)
            topics = _topics_for(segment)
            binding, scope, source_ids = context
            if binding is SourceBinding.UNKNOWN and inherited_binding is not None:
                binding = inherited_binding
                source_id = SourceId(binding.value)
                scope = SourceScope.EXPLICIT_SOURCE
                source_ids = (source_id,)
            organizations, _, _ = _organization_values(segment)
            times, _ = _unique_bounded(
                [match.group(0) for match in _DATE_RE.finditer(segment)]
                + [match.group(0) for match in _TIME_PHRASE_RE.finditer(segment)],
                4,
            )
            units.append(
                AnalyzerUnit(
                    unit_id=f"u{index:02d}",
                    intent=_intent_for(segment),
                    legal_actor=actor,
                    action_event=action,
                    organization_scope=organizations,
                    explicit_time=times,
                    legal_topics=topics,
                    source_scope=scope,
                    source_ids=source_ids,
                    source_binding=binding,
                    concept_query=_concept_query(segment, actor, action, topics),
                )
            )
        ambiguity = (
            AmbiguityCode.SOURCE_AMBIGUOUS
            if any(unit.source_binding is SourceBinding.AMBIGUOUS for unit in units)
            else AmbiguityCode.NONE
        )
        explicit_bindings = {unit.source_binding for unit in units} - {
            SourceBinding.UNKNOWN,
            SourceBinding.AMBIGUOUS,
        }
        complexity = (
            QueryComplexity.AMBIGUOUS
            if ambiguity is not AmbiguityCode.NONE
            else QueryComplexity.MULTI_SOURCE
            if len(explicit_bindings) > 1
            else QueryComplexity.MULTI_INTENT
            if len(units) > 1
            else QueryComplexity.SIMPLE
        )
        first = units[0]
        return AnalyzerObservation(
            intent=GenericIntent.MULTI_STAGE_PROCESS if len(units) > 1 else first.intent,
            legal_actor=first.legal_actor,
            action_event=first.action_event,
            organization_scope=first.organization_scope,
            explicit_time=first.explicit_time,
            legal_topics=first.legal_topics,
            entities=tuple(value for value in (first.legal_actor, first.action_event) if value),
            organizations=first.organization_scope,
            topics=first.legal_topics,
            sub_intents=tuple(dict.fromkeys(unit.intent.value for unit in units)),
            complexity=complexity,
            ambiguity=ambiguity,
            source_scope=derived_source_scope(tuple(units)),
            units=tuple(units),
            unit_truncated=unit_truncated,
        )

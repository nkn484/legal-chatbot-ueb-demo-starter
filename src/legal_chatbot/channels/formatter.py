"""Deterministic server-side formatting for Official Zalo Bot replies."""

from typing import Final

from pydantic import ValidationError

from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.channels.errors import ChannelError, ChannelErrorCode
from legal_chatbot.channels.models import ChannelFormattedReply, _normalize_formatted_reply_text
from legal_chatbot.chat.models import ChatOutcome, GroundedChatResult
from legal_chatbot.retrieval.models import EvidenceTrustLabel, ResolvedCitation

OVERFLOW_REPLY_TEXT: Final = (
    "Dạ, em không thể gửi toàn bộ câu trả lời qua kênh này vì quá dài. Thầy/cô vui lòng thử lại "
    "với câu hỏi cụ thể hơn."
)


class ChannelFormatter:
    """Render validated chat results without exposing internal evidence identities."""

    def __init__(self, settings: ChannelSettings) -> None:
        if settings.max_outbound_chars < len(OVERFLOW_REPLY_TEXT):
            raise ChannelError(ChannelErrorCode.CONFIG_INVALID)
        self._max_outbound_chars = settings.max_outbound_chars

    def format(self, result: GroundedChatResult) -> ChannelFormattedReply:
        """Format one grounded result, returning a fixed safe message on overflow."""

        try:
            if not isinstance(result, GroundedChatResult):
                raise TypeError("result must be a grounded chat result")
            validated_result = GroundedChatResult.model_validate(result.model_dump())
            if validated_result.outcome is ChatOutcome.ANSWER:
                text = self._format_answer(validated_result)
                citation_count = len(validated_result.citations)
            else:
                text = validated_result.answer
                citation_count = 0
            normalized_text = _normalize_formatted_reply_text(text)
        except (TypeError, ValidationError, ValueError) as error:
            raise ChannelError(ChannelErrorCode.CHANNEL_MALFORMED) from error

        if not isinstance(normalized_text, str):
            raise ChannelError(ChannelErrorCode.CHANNEL_MALFORMED)
        if len(normalized_text) > self._max_outbound_chars:
            return ChannelFormattedReply(
                text=OVERFLOW_REPLY_TEXT,
                citation_count=0,
                overflowed=True,
            )
        return ChannelFormattedReply(
            text=normalized_text,
            citation_count=citation_count,
            overflowed=False,
        )

    @staticmethod
    def _format_answer(result: GroundedChatResult) -> str:
        source_lines = tuple(
            ChannelFormatter._format_citation(citation) for citation in result.citations
        )
        return "\n\n".join((result.answer, "\n".join(source_lines)))

    @staticmethod
    def _format_citation(citation: ResolvedCitation) -> str:
        parts = [f"Nguồn: {citation.source_id}"]
        if citation.document_number is not None:
            parts.append(f"Số văn bản: {citation.document_number}")
        if citation.title is not None:
            parts.append(f"Tiêu đề: {citation.title}")
        if citation.canonical_url is not None:
            parts.append(f"URL: {citation.canonical_url}")
        if citation.evidence_trust_label is EvidenceTrustLabel.OFFICIAL_LEGAL_PINNED_EXCEPTION:
            parts.append(
                "Lưu ý: Nội dung nguồn chính thức được truy xuất theo ngoại lệ TOFU/SPKI "
                "do người dùng phê duyệt; chuỗi CA đã được xác minh nhưng tên máy chủ chưa "
                "được xác minh"
            )
        elif citation.evidence_trust_label is EvidenceTrustLabel.MANUAL_SNAPSHOT:
            parts.append(
                "Lưu ý: Đây là bản chụp dữ liệu được nhập thủ công cho demo, không phải "
                "kết nối trực tiếp với cơ sở dữ liệu pháp luật chính thức"
            )
        return "; ".join(parts)

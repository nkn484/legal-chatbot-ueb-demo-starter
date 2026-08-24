"""Safe count-only report for one demo corpus dataset."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import func, select

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.demo_corpus.config import DemoCorpusSettings
from legal_chatbot.documents.orm import (
    CorpusCatalogEntry,
    DocumentVersion,
    SourceProvenanceRecord,
)
from legal_chatbot.sources.models import ProvenanceType


async def run() -> int:
    app_settings = Settings()  # type: ignore[call-arg]
    corpus_settings = DemoCorpusSettings()
    engine = create_engine(app_settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            status_rows = (
                await session.execute(
                    select(
                        CorpusCatalogEntry.source_id,
                        CorpusCatalogEntry.processing_status,
                        func.count(),
                    )
                    .where(CorpusCatalogEntry.dataset_id == corpus_settings.dataset_id)
                    .group_by(
                        CorpusCatalogEntry.source_id,
                        CorpusCatalogEntry.processing_status,
                    )
                    .order_by(
                        CorpusCatalogEntry.source_id,
                        CorpusCatalogEntry.processing_status,
                    )
                )
            ).all()
            manual_provenance_count = await session.scalar(
                select(func.count())
                .select_from(SourceProvenanceRecord)
                .join(
                    DocumentVersion,
                    SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                )
                .join(
                    CorpusCatalogEntry,
                    CorpusCatalogEntry.document_version_id == DocumentVersion.id,
                )
                .where(
                    CorpusCatalogEntry.dataset_id == corpus_settings.dataset_id,
                    SourceProvenanceRecord.provenance_type
                    == ProvenanceType.MANUAL_SNAPSHOT.value,
                )
            )
            mismatched_provenance_count = await session.scalar(
                select(func.count())
                .select_from(SourceProvenanceRecord)
                .join(
                    DocumentVersion,
                    SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                )
                .join(
                    CorpusCatalogEntry,
                    CorpusCatalogEntry.document_version_id == DocumentVersion.id,
                )
                .where(
                    CorpusCatalogEntry.dataset_id == corpus_settings.dataset_id,
                    SourceProvenanceRecord.provenance_type
                    != ProvenanceType.MANUAL_SNAPSHOT.value,
                )
            )
        by_source: dict[str, dict[str, int]] = {}
        for source_id, status, count in status_rows:
            by_source.setdefault(source_id, {})[status] = int(count)
        total = sum(count for statuses in by_source.values() for count in statuses.values())
        print(
            json.dumps(
                {
                    "dataset_id": corpus_settings.dataset_id,
                    "total": total,
                    "by_source": by_source,
                    "manual_snapshot_provenance": int(manual_provenance_count or 0),
                    "mismatched_provenance": int(mismatched_provenance_count or 0),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1 if total != 1_104 or mismatched_provenance_count else 0
    finally:
        await engine.dispose()


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()

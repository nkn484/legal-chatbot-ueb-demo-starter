"""Static benchmark-leakage guard for production source paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LeakageFinding:
    path: Path
    line: int
    marker: str


def scan_production_for_benchmark_leakage(
    production_root: Path,
    forbidden_markers: tuple[str, ...],
    *,
    excluded_relative_directories: tuple[str, ...] = (),
) -> tuple[LeakageFinding, ...]:
    """Find supplied oracle markers in runtime code; callers own the oracle inventory."""

    if not production_root.is_dir():
        raise ValueError("production root must be a directory")
    normalized_markers = tuple(
        marker for marker in forbidden_markers if isinstance(marker, str) and marker.strip()
    )
    if len(normalized_markers) != len(set(normalized_markers)):
        raise ValueError("forbidden markers must be unique nonblank strings")
    if any(
        not isinstance(directory, str)
        or not directory
        or Path(directory).name != directory
        for directory in excluded_relative_directories
    ):
        raise ValueError("excluded directories must be simple nonblank relative names")
    findings: list[LeakageFinding] = []
    for path in sorted(production_root.rglob("*.py")):
        relative_parts = path.relative_to(production_root).parts
        if any(directory in relative_parts for directory in excluded_relative_directories):
            continue
        content = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(content.splitlines(), start=1):
            for marker in normalized_markers:
                if marker in line:
                    findings.append(LeakageFinding(path=path, line=line_number, marker=marker))
    return tuple(findings)

"""Read a CSV metadata file into a list of Records.

Default crosswalk is Dublin Core. Column headers may use any of:

    - ``dc.title`` / ``dcterms.title`` / ``title``
    - ``dc.creator``, ``dc.subject``, ``dc.description``, ``dc.date``,
      ``dc.type``, ``dc.identifier``, ``dc.rights``, ``dc.publisher``,
      ``dc.contributor``, ``dc.format``, ``dc.language``, ``dc.relation``,
      ``dc.source``, ``dc.coverage``

Embargo end date (optional, used by DSpace/EPrints/Dataverse if their
embargo plugins are enabled):

    - ``dcterms.available`` / ``dc.available``
    - ``dc.date.available`` (DSpace qualified-DC convention)
    - ``embargo_until`` (friendly alias)

Multi-value fields are split on ``||`` (double pipe).

Files are linked via either:

    - ``filename`` column (single file per row), or
    - ``files`` column (``||``-separated list).

Both may be present; their values are merged.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

# Dublin Core elements supported by the default crosswalks in DSpace and
# EPrints. Both prefixed (``dc.title``) and unprefixed (``title``) headers
# are accepted; ``dcterms.X`` is treated as an alias for ``dc.X`` for the
# 15 core elements.
#
# ``available`` is a dcterms refinement (not one of the original 15 DC
# elements) but it is the canonical field for embargo end dates across
# DSpace, EPrints, and Dataverse. We accept it under any of:
#   - dcterms.available
#   - dc.available             (treated as an alias)
#   - dc.date.available         (DSpace's qualified-DC convention)
#   - embargo_until             (friendly alias)
DC_ELEMENTS = (
    "title",
    "creator",
    "subject",
    "description",
    "publisher",
    "contributor",
    "date",
    "type",
    "format",
    "identifier",
    "source",
    "language",
    "relation",
    "coverage",
    "rights",
    "available",
)

EMBARGO_ALIASES = (
    "embargo_until",
    "dc.date.available",
    "dcterms.date.available",
)

MULTIVALUE_SEPARATOR = "||"


# Accept ISO 8601 dates: YYYY, YYYY-MM, YYYY-MM-DD, optionally with time.
# Anything fuzzier and repositories will silently reject or mishandle it.
_ISO_DATE_RE = re.compile(
    r"^\d{4}(-\d{2}(-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?)?)?$"
)


def is_valid_embargo_date(value: str) -> bool:
    """True if ``value`` looks like an ISO 8601 date / datetime."""
    return bool(_ISO_DATE_RE.match(value.strip()))


@dataclass
class Record:
    """One CSV row, normalised."""

    row_number: int
    metadata: dict[str, list[str]] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        values = self.metadata.get("title", [])
        return values[0] if values else f"(untitled row {self.row_number})"

    def get(self, element: str) -> list[str]:
        """Return all values for a DC element (empty list if absent)."""
        return self.metadata.get(element, [])

    @property
    def embargo_until(self) -> str | None:
        """Return the (single) embargo end date for this record, if any."""
        values = self.metadata.get("available", [])
        return values[0] if values else None


def _normalise_header(header: str) -> str | None:
    """Map a raw CSV header to a DC element name, or None if non-DC."""
    h = header.strip().lower()
    if h in {"filename", "files"}:
        return h
    # Embargo aliases all map to the canonical 'available' element.
    if h in EMBARGO_ALIASES:
        return "available"
    for prefix in ("dc.", "dcterms."):
        if h.startswith(prefix):
            element = h[len(prefix):]
            if element in DC_ELEMENTS:
                return element
            return None
    if h in DC_ELEMENTS:
        return h
    return None


def _split_values(raw: str) -> list[str]:
    if raw is None:
        return []
    parts = [p.strip() for p in raw.split(MULTIVALUE_SEPARATOR)]
    return [p for p in parts if p]


def read_csv(path: Path) -> list[Record]:
    """Parse the CSV at ``path`` into a list of Records.

    Raises ValueError if no recognised metadata columns are present.
    """
    records: list[Record] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"CSV {path} has no header row")

        header_map: dict[str, str] = {}
        for raw in reader.fieldnames:
            mapped = _normalise_header(raw)
            if mapped is not None:
                header_map[raw] = mapped

        if not any(v in DC_ELEMENTS for v in header_map.values()):
            raise ValueError(
                f"CSV {path} has no recognised Dublin Core columns "
                f"(expected dc.title, dc.creator, etc.)"
            )

        for i, row in enumerate(reader, start=2):  # row 1 is the header
            metadata: dict[str, list[str]] = {}
            files: list[str] = []
            for raw_header, mapped in header_map.items():
                cell = row.get(raw_header) or ""
                values = _split_values(cell)
                if not values:
                    continue
                if mapped == "filename":
                    files.extend(values)
                elif mapped == "files":
                    files.extend(values)
                else:
                    metadata.setdefault(mapped, []).extend(values)

            # Validate embargo date format. Repositories silently reject
            # malformed dates, so catching them up front saves debugging.
            for embargo in metadata.get("available", []):
                if not is_valid_embargo_date(embargo):
                    raise ValueError(
                        f"Row {i}: embargo date {embargo!r} is not valid ISO 8601 "
                        f"(expected YYYY, YYYY-MM, YYYY-MM-DD, or full datetime)."
                    )

            records.append(Record(row_number=i, metadata=metadata, files=files))

    return records


def resolve_files(record: Record, files_dir: Path) -> list[Path]:
    """Resolve a record's filenames against ``files_dir``.

    Raises FileNotFoundError if any referenced file is missing.
    """
    resolved: list[Path] = []
    for name in record.files:
        candidate = files_dir / name
        if not candidate.exists():
            raise FileNotFoundError(
                f"Row {record.row_number}: file {name!r} not found in {files_dir}"
            )
        resolved.append(candidate)
    return resolved

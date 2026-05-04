"""Build an EPrints SWORD zip package.

Layout of the resulting zip::

    eprints.xml          # EPrints 3 XML import format
    <payload files>      # the files referenced from <documents>

The XML targets the importer registered for ``http://eprints.org/ep2/data/2.0``
in EPrints 3.2/3.3, which is the default crosswalk for SWORD deposits into
an EPrints repository.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree

from sword_packager.csv_reader import Record

EPRINTS_NS = "http://eprints.org/ep2/data/2.0"
NSMAP = {None: EPRINTS_NS}


# DC element -> EPrints field name. Mappings reflect the default
# EPrints DC importer crosswalk.
EPRINTS_FIELD_MAP = {
    "title": "title",
    "description": "abstract",
    "date": "date",
    "publisher": "publisher",
    "rights": "rights",
    "subject": "keywords",  # free-text keywords; controlled subjects need IDs
    "language": "language",
    "identifier": "id_number",
    "source": "publication",
    "relation": "related_url",
    "coverage": "geographic_cover",
    "format": "format",
}


def _add_creators(eprint: etree._Element, names: list[str]) -> None:
    if not names:
        return
    creators = etree.SubElement(eprint, "creators")
    for raw in names:
        item = etree.SubElement(creators, "item")
        name = etree.SubElement(item, "name")
        # Best-effort split on comma: "Family, Given"
        if "," in raw:
            family, given = (p.strip() for p in raw.split(",", 1))
        else:
            family, given = raw.strip(), ""
        etree.SubElement(name, "family").text = family
        etree.SubElement(name, "given").text = given


def _add_simple_field(eprint: etree._Element, tag: str, value: str) -> None:
    etree.SubElement(eprint, tag).text = value


def _add_keywords(eprint: etree._Element, keywords: list[str]) -> None:
    if keywords:
        etree.SubElement(eprint, "keywords").text = ", ".join(keywords)


def _eprint_type(record: Record) -> str:
    """Map dc.type to an EPrints type identifier (best-effort)."""
    types = record.get("type")
    if not types:
        return "article"
    raw = types[0].lower()
    mapping = {
        "article": "article",
        "journal article": "article",
        "book": "book",
        "book chapter": "book_section",
        "thesis": "thesis",
        "report": "monograph",
        "dataset": "dataset",
        "image": "image",
        "video": "video",
        "audio": "audio",
        "conference paper": "conference_item",
    }
    for key, value in mapping.items():
        if key in raw:
            return value
    return "other"


def _build_eprints_xml(record: Record, files: list[Path]) -> bytes:
    root = etree.Element(f"{{{EPRINTS_NS}}}eprints", nsmap=NSMAP)
    eprint = etree.SubElement(root, "eprint")

    etree.SubElement(eprint, "eprint_status").text = "inbox"
    etree.SubElement(eprint, "type").text = _eprint_type(record)

    if titles := record.get("title"):
        _add_simple_field(eprint, "title", titles[0])

    _add_creators(eprint, record.get("creator"))

    if descriptions := record.get("description"):
        _add_simple_field(eprint, "abstract", "\n\n".join(descriptions))

    for element, eprints_field in EPRINTS_FIELD_MAP.items():
        if element in {"title", "description", "subject"}:
            continue
        values = record.get(element)
        if not values:
            continue
        _add_simple_field(eprint, eprints_field, values[0])

    _add_keywords(eprint, record.get("subject"))

    if files:
        embargo = record.embargo_until
        documents = etree.SubElement(eprint, "documents")
        for fpath in files:
            doc = etree.SubElement(documents, "document")
            etree.SubElement(doc, "format").text = _format_for(fpath)
            etree.SubElement(doc, "main").text = fpath.name
            # EPrints applies embargoes at the document level. The
            # <embargo_date> field is the canonical one in EPrints 3.x
            # and is honoured by the default workflow when present.
            # We also set <security> to "staffonly" during the embargo
            # window so that misconfigured installs default to closed
            # rather than open.
            if embargo:
                etree.SubElement(doc, "embargo_date").text = embargo
                etree.SubElement(doc, "security").text = "staffonly"
            files_el = etree.SubElement(doc, "files")
            file_el = etree.SubElement(files_el, "file")
            etree.SubElement(file_el, "filename").text = fpath.name
            etree.SubElement(file_el, "filesize").text = str(fpath.stat().st_size)

    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


def _format_for(path: Path) -> str:
    """Map an extension to an EPrints document format label."""
    ext = path.suffix.lower().lstrip(".")
    mapping = {
        "pdf": "application/pdf",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain",
        "html": "text/html",
        "csv": "text/csv",
        "xml": "text/xml",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }
    return mapping.get(ext, "application/octet-stream")


def build_eprints_package(record: Record, files: list[Path], output: Path) -> Path:
    """Write an EPrints SWORD zip for ``record`` to ``output``."""
    xml_bytes = _build_eprints_xml(record, files)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("eprints.xml", xml_bytes)
        for fpath in files:
            zf.write(fpath, arcname=fpath.name)
    return output

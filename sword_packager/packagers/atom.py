"""Build a SWORDv2 Atom entry + SimpleZip package.

This is the format used by SWORDv2 multipart deposits and the Dataverse
SWORD API. It produces two artifacts that the deposit client sends:

    atom.xml             # an Atom entry with dcterms metadata
    <name>.zip           # SimpleZip of the payload files

The entry uses the Dublin Core terms namespace, which is what
``SimpleDCEntryIngester`` (DSpace) and the Dataverse SWORD endpoint
parse by default.

For convenience this builder produces a single zip containing both the
Atom entry and the payload files; the deposit client extracts the entry
when posting a multipart request and uses the zip as the binary part.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree

from sword_packager.csv_reader import Record

ATOM_NS = "http://www.w3.org/2005/Atom"
DCTERMS_NS = "http://purl.org/dc/terms/"

NSMAP = {
    None: ATOM_NS,
    "dcterms": DCTERMS_NS,
}


def _build_atom_entry(record: Record) -> bytes:
    entry = etree.Element(f"{{{ATOM_NS}}}entry", nsmap=NSMAP)

    titles = record.get("title")
    title_text = titles[0] if titles else f"Untitled (row {record.row_number})"
    etree.SubElement(entry, f"{{{ATOM_NS}}}title").text = title_text

    # Atom requires an id; use the first identifier or synthesise one.
    identifiers = record.get("identifier")
    entry_id = identifiers[0] if identifiers else f"urn:row:{record.row_number}"
    etree.SubElement(entry, f"{{{ATOM_NS}}}id").text = entry_id

    # author element is required by Atom.
    creators = record.get("creator") or ["Unknown"]
    for creator in creators:
        author = etree.SubElement(entry, f"{{{ATOM_NS}}}author")
        etree.SubElement(author, f"{{{ATOM_NS}}}name").text = creator

    # dcterms metadata mirrors DC field-by-field. ``available`` carries
    # the embargo end date and is consulted by Dataverse and DSpace
    # SWORDv2 if their respective embargo plugins are enabled.
    for element in (
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
    ):
        for value in record.get(element):
            el = etree.SubElement(entry, f"{{{DCTERMS_NS}}}{element}")
            el.text = value

    return etree.tostring(
        entry, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


def build_atom_package(record: Record, files: list[Path], output: Path) -> Path:
    """Write an Atom entry + SimpleZip bundle for ``record`` to ``output``.

    The zip contains ``atom.xml`` plus the payload files. Deposit clients
    that need a multipart POST extract ``atom.xml`` and send the rest as
    the binary part; clients that POST a SimpleZip directly can use the
    zip as-is (the ``atom.xml`` is then redundant but harmless).
    """
    entry_bytes = _build_atom_entry(record)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("atom.xml", entry_bytes)
        for fpath in files:
            zf.write(fpath, arcname=fpath.name)
    return output


def extract_atom_entry(package_zip: Path) -> bytes:
    """Read ``atom.xml`` out of a package zip (used by the deposit client)."""
    with zipfile.ZipFile(package_zip) as zf:
        return zf.read("atom.xml")

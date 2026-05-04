"""Build a DSpace METS SIP zip package.

Layout of the resulting zip::

    mets.xml             # METS manifest with a MODS dmdSec
    <payload files>      # the bitstreams referenced from fileSec

The MODS crosswalk is DSpace's default ingester for SWORD METS deposits
(SwordMETSIngester / DSpaceMETSIngester). Field mapping follows the
DC -> MODS crosswalk shipped with DSpace.
"""

from __future__ import annotations

import hashlib
import uuid
import zipfile
from pathlib import Path

from lxml import etree

from sword_packager.csv_reader import Record

METS_NS = "http://www.loc.gov/METS/"
MODS_NS = "http://www.loc.gov/mods/v3"
XLINK_NS = "http://www.w3.org/1999/xlink"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

NSMAP = {
    "mets": METS_NS,
    "mods": MODS_NS,
    "xlink": XLINK_NS,
    "xsi": XSI_NS,
}

MODS_SCHEMA_LOCATION = (
    "http://www.loc.gov/mods/v3 http://www.loc.gov/standards/mods/v3/mods-3-7.xsd"
)


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _add_mods_metadata(mods: etree._Element, record: Record) -> None:
    """Map DC values to a MODS element, following DSpace's crosswalk."""

    for title in record.get("title"):
        ti = etree.SubElement(mods, f"{{{MODS_NS}}}titleInfo")
        etree.SubElement(ti, f"{{{MODS_NS}}}title").text = title

    for creator in record.get("creator"):
        name = etree.SubElement(mods, f"{{{MODS_NS}}}name")
        np = etree.SubElement(name, f"{{{MODS_NS}}}namePart")
        np.text = creator
        role = etree.SubElement(name, f"{{{MODS_NS}}}role")
        rt = etree.SubElement(role, f"{{{MODS_NS}}}roleTerm")
        rt.set("type", "text")
        rt.text = "creator"

    for contributor in record.get("contributor"):
        name = etree.SubElement(mods, f"{{{MODS_NS}}}name")
        etree.SubElement(name, f"{{{MODS_NS}}}namePart").text = contributor
        role = etree.SubElement(name, f"{{{MODS_NS}}}role")
        rt = etree.SubElement(role, f"{{{MODS_NS}}}roleTerm")
        rt.set("type", "text")
        rt.text = "contributor"

    for subject in record.get("subject"):
        subj = etree.SubElement(mods, f"{{{MODS_NS}}}subject")
        etree.SubElement(subj, f"{{{MODS_NS}}}topic").text = subject

    for description in record.get("description"):
        abstract = etree.SubElement(mods, f"{{{MODS_NS}}}abstract")
        abstract.text = description

    for publisher in record.get("publisher"):
        oi = etree.SubElement(mods, f"{{{MODS_NS}}}originInfo")
        etree.SubElement(oi, f"{{{MODS_NS}}}publisher").text = publisher

    for date in record.get("date"):
        oi = etree.SubElement(mods, f"{{{MODS_NS}}}originInfo")
        di = etree.SubElement(oi, f"{{{MODS_NS}}}dateIssued")
        di.set("encoding", "iso8601")
        di.text = date

    for dc_type in record.get("type"):
        etree.SubElement(mods, f"{{{MODS_NS}}}genre").text = dc_type

    for fmt in record.get("format"):
        pd = etree.SubElement(mods, f"{{{MODS_NS}}}physicalDescription")
        etree.SubElement(pd, f"{{{MODS_NS}}}form").text = fmt

    for identifier in record.get("identifier"):
        ident = etree.SubElement(mods, f"{{{MODS_NS}}}identifier")
        ident.set("type", "uri")
        ident.text = identifier

    for source in record.get("source"):
        ri = etree.SubElement(mods, f"{{{MODS_NS}}}relatedItem")
        ri.set("type", "original")
        ti = etree.SubElement(ri, f"{{{MODS_NS}}}titleInfo")
        etree.SubElement(ti, f"{{{MODS_NS}}}title").text = source

    for language in record.get("language"):
        lang = etree.SubElement(mods, f"{{{MODS_NS}}}language")
        lt = etree.SubElement(lang, f"{{{MODS_NS}}}languageTerm")
        lt.set("type", "code")
        lt.set("authority", "rfc3066")
        lt.text = language

    for relation in record.get("relation"):
        ri = etree.SubElement(mods, f"{{{MODS_NS}}}relatedItem")
        ti = etree.SubElement(ri, f"{{{MODS_NS}}}titleInfo")
        etree.SubElement(ti, f"{{{MODS_NS}}}title").text = relation

    for coverage in record.get("coverage"):
        subj = etree.SubElement(mods, f"{{{MODS_NS}}}subject")
        etree.SubElement(subj, f"{{{MODS_NS}}}geographic").text = coverage

    for rights in record.get("rights"):
        ar = etree.SubElement(mods, f"{{{MODS_NS}}}accessCondition")
        ar.set("type", "use and reproduction")
        ar.text = rights

    # Embargo end date. DSpace's default MODS-to-DC crosswalk maps
    # <mods:dateOther type="available"> within originInfo to
    # dc.date.available, which the EmbargoSetter / EmbargoLifter plugins
    # consult IF they are enabled in dspace.cfg. We also add an
    # <accessCondition type="restrictionOnAccess"> as a human-readable
    # note that survives even if embargo enforcement is disabled.
    for embargo in record.get("available"):
        oi = etree.SubElement(mods, f"{{{MODS_NS}}}originInfo")
        do = etree.SubElement(oi, f"{{{MODS_NS}}}dateOther")
        do.set("type", "available")
        do.set("encoding", "iso8601")
        do.text = embargo
        ar = etree.SubElement(mods, f"{{{MODS_NS}}}accessCondition")
        ar.set("type", "restrictionOnAccess")
        ar.text = f"Embargoed until {embargo}"


def _build_mets_xml(record: Record, files: list[Path]) -> bytes:
    mets = etree.Element(
        f"{{{METS_NS}}}mets",
        nsmap=NSMAP,
        attrib={
            "ID": "sword-mets_mets",
            "OBJID": f"sword-mets_{uuid.uuid4()}",
            "LABEL": "DSpace SWORD Item",
            "PROFILE": "DSpace METS SIP Profile 1.0",
        },
    )

    # metsHdr
    hdr = etree.SubElement(
        mets,
        f"{{{METS_NS}}}metsHdr",
        attrib={"CREATEDATE": "2024-01-01T00:00:00"},
    )
    agent = etree.SubElement(
        hdr, f"{{{METS_NS}}}agent", attrib={"ROLE": "CUSTODIAN", "TYPE": "ORGANIZATION"}
    )
    etree.SubElement(agent, f"{{{METS_NS}}}name").text = "sword-packager"

    # dmdSec with MODS
    dmd_id = "sword-mets-dmd-1"
    dmd = etree.SubElement(mets, f"{{{METS_NS}}}dmdSec", attrib={"ID": dmd_id})
    md_wrap = etree.SubElement(
        dmd,
        f"{{{METS_NS}}}mdWrap",
        attrib={"LABEL": "SWAP Metadata", "MDTYPE": "MODS"},
    )
    xml_data = etree.SubElement(md_wrap, f"{{{METS_NS}}}xmlData")
    mods = etree.SubElement(
        xml_data,
        f"{{{MODS_NS}}}mods",
        attrib={f"{{{XSI_NS}}}schemaLocation": MODS_SCHEMA_LOCATION},
    )
    _add_mods_metadata(mods, record)

    # fileSec
    file_sec = etree.SubElement(mets, f"{{{METS_NS}}}fileSec")
    file_grp = etree.SubElement(
        file_sec, f"{{{METS_NS}}}fileGrp", attrib={"USE": "CONTENT"}
    )
    file_ids: list[str] = []
    for idx, fpath in enumerate(files, start=1):
        file_id = f"sword-mets-file-{idx}"
        file_ids.append(file_id)
        f_el = etree.SubElement(
            file_grp,
            f"{{{METS_NS}}}file",
            attrib={
                "ID": file_id,
                "GROUPID": f"sword-mets-fgid-{idx}",
                "MIMETYPE": _guess_mime(fpath),
                "CHECKSUM": _md5(fpath),
                "CHECKSUMTYPE": "MD5",
                "SIZE": str(fpath.stat().st_size),
            },
        )
        etree.SubElement(
            f_el,
            f"{{{METS_NS}}}FLocat",
            attrib={
                "LOCTYPE": "URL",
                f"{{{XLINK_NS}}}href": fpath.name,
            },
        )

    # structMap
    struct_map = etree.SubElement(
        mets,
        f"{{{METS_NS}}}structMap",
        attrib={"LABEL": "DSpace Object", "TYPE": "LOGICAL"},
    )
    div_item = etree.SubElement(
        struct_map,
        f"{{{METS_NS}}}div",
        attrib={"DMDID": dmd_id, "TYPE": "DSpace Item"},
    )
    for file_id in file_ids:
        bs_div = etree.SubElement(
            div_item,
            f"{{{METS_NS}}}div",
            attrib={"TYPE": "DSpace Bitstream"},
        )
        etree.SubElement(
            bs_div, f"{{{METS_NS}}}fptr", attrib={"FILEID": file_id}
        )

    return etree.tostring(
        mets, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


def _guess_mime(path: Path) -> str:
    import mimetypes

    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def build_mets_package(record: Record, files: list[Path], output: Path) -> Path:
    """Write a METS SIP zip for ``record`` to ``output``. Returns the path."""
    mets_xml = _build_mets_xml(record, files)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mets.xml", mets_xml)
        for fpath in files:
            zf.write(fpath, arcname=fpath.name)
    return output

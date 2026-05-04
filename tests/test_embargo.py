"""Tests for embargo date support."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from lxml import etree

from sword_packager.csv_reader import is_valid_embargo_date, read_csv, resolve_files
from sword_packager.packagers.atom import build_atom_package
from sword_packager.packagers.eprints import build_eprints_package
from sword_packager.packagers.mets import build_mets_package


@pytest.fixture
def embargoed_inputs(tmp_path: Path):
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "report.pdf").write_bytes(b"%PDF fake")

    csv_path = tmp_path / "metadata.csv"
    csv_path.write_text(
        "dc.title,dc.creator,embargo_until,files\n"
        '"Embargoed Report","Smith, A","2025-12-31","report.pdf"\n',
        encoding="utf-8",
    )
    return csv_path, files_dir, tmp_path


def test_is_valid_embargo_date_accepts_iso_forms():
    assert is_valid_embargo_date("2025")
    assert is_valid_embargo_date("2025-06")
    assert is_valid_embargo_date("2025-06-15")
    assert is_valid_embargo_date("2025-06-15T10:30:00")
    assert is_valid_embargo_date("2025-06-15T10:30:00Z")
    assert is_valid_embargo_date("2025-06-15T10:30:00+02:00")


def test_is_valid_embargo_date_rejects_garbage():
    assert not is_valid_embargo_date("next Tuesday")
    assert not is_valid_embargo_date("31/12/2025")  # not ISO
    assert not is_valid_embargo_date("12-31-2025")  # not ISO
    assert not is_valid_embargo_date("Dec 31, 2025")
    assert not is_valid_embargo_date("")


def test_csv_accepts_embargo_until_alias(embargoed_inputs):
    csv_path, _, _ = embargoed_inputs
    record = read_csv(csv_path)[0]
    assert record.embargo_until == "2025-12-31"
    # Should also be accessible via the canonical 'available' element.
    assert record.get("available") == ["2025-12-31"]


def test_csv_accepts_dcterms_available(tmp_path: Path):
    csv_path = tmp_path / "m.csv"
    csv_path.write_text(
        "dc.title,dcterms.available\nFoo,2026-01-01\n", encoding="utf-8"
    )
    record = read_csv(csv_path)[0]
    assert record.embargo_until == "2026-01-01"


def test_csv_accepts_dc_date_available(tmp_path: Path):
    """DSpace's qualified-DC convention."""
    csv_path = tmp_path / "m.csv"
    csv_path.write_text(
        "dc.title,dc.date.available\nFoo,2026-06-30\n", encoding="utf-8"
    )
    record = read_csv(csv_path)[0]
    assert record.embargo_until == "2026-06-30"


def test_csv_rejects_invalid_embargo_date(tmp_path: Path):
    csv_path = tmp_path / "m.csv"
    csv_path.write_text(
        "dc.title,embargo_until\nFoo,next Tuesday\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="not valid ISO 8601"):
        read_csv(csv_path)


def test_no_embargo_when_column_absent(tmp_path: Path):
    csv_path = tmp_path / "m.csv"
    csv_path.write_text("dc.title\nFoo\n", encoding="utf-8")
    record = read_csv(csv_path)[0]
    assert record.embargo_until is None


def test_mets_package_includes_embargo_in_mods(embargoed_inputs):
    csv_path, files_dir, tmp_path = embargoed_inputs
    record = read_csv(csv_path)[0]
    files = resolve_files(record, files_dir)
    out = tmp_path / "out" / "pkg.zip"

    build_mets_package(record, files, out)

    with zipfile.ZipFile(out) as zf:
        mets_bytes = zf.read("mets.xml")

    root = etree.fromstring(mets_bytes)
    ns = {"mods": "http://www.loc.gov/mods/v3"}

    # dateOther type="available" — DSpace's embargo crosswalk source
    date_others = root.findall(".//mods:dateOther[@type='available']", ns)
    assert len(date_others) == 1
    assert date_others[0].text == "2025-12-31"

    # accessCondition restrictionOnAccess as a human-readable note
    restrictions = root.findall(
        ".//mods:accessCondition[@type='restrictionOnAccess']", ns
    )
    assert len(restrictions) == 1
    assert "2025-12-31" in restrictions[0].text


def test_eprints_package_includes_embargo_per_document(embargoed_inputs):
    csv_path, files_dir, tmp_path = embargoed_inputs
    record = read_csv(csv_path)[0]
    files = resolve_files(record, files_dir)
    out = tmp_path / "out" / "ep.zip"

    build_eprints_package(record, files, out)

    with zipfile.ZipFile(out) as zf:
        xml_bytes = zf.read("eprints.xml")

    root = etree.fromstring(xml_bytes)
    ns = {"ep": "http://eprints.org/ep2/data/2.0"}

    embargo_dates = root.findall(".//ep:document/ep:embargo_date", ns)
    assert len(embargo_dates) == 1
    assert embargo_dates[0].text == "2025-12-31"

    # Security should be staffonly during the embargo
    security = root.findall(".//ep:document/ep:security", ns)
    assert len(security) == 1
    assert security[0].text == "staffonly"


def test_atom_package_includes_dcterms_available(embargoed_inputs):
    csv_path, files_dir, tmp_path = embargoed_inputs
    record = read_csv(csv_path)[0]
    files = resolve_files(record, files_dir)
    out = tmp_path / "out" / "atom.zip"

    build_atom_package(record, files, out)

    with zipfile.ZipFile(out) as zf:
        xml_bytes = zf.read("atom.xml")

    root = etree.fromstring(xml_bytes)
    ns = {"dcterms": "http://purl.org/dc/terms/"}

    available = root.findall("dcterms:available", ns)
    assert len(available) == 1
    assert available[0].text == "2025-12-31"


def test_eprints_package_omits_embargo_when_not_set(tmp_path: Path):
    """A record without an embargo_until should not get embargo_date / staffonly."""
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "open.pdf").write_bytes(b"%PDF fake")
    csv_path = tmp_path / "m.csv"
    csv_path.write_text(
        "dc.title,files\nOpen Paper,open.pdf\n", encoding="utf-8"
    )
    record = read_csv(csv_path)[0]
    files = resolve_files(record, files_dir)
    out = tmp_path / "ep.zip"
    build_eprints_package(record, files, out)

    with zipfile.ZipFile(out) as zf:
        xml_bytes = zf.read("eprints.xml")
    root = etree.fromstring(xml_bytes)
    ns = {"ep": "http://eprints.org/ep2/data/2.0"}

    assert root.findall(".//ep:document/ep:embargo_date", ns) == []
    assert root.findall(".//ep:document/ep:security", ns) == []

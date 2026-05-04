"""Tests for sword-packager."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from lxml import etree

from sword_packager.csv_reader import read_csv, resolve_files
from sword_packager.packagers.atom import build_atom_package
from sword_packager.packagers.eprints import build_eprints_package
from sword_packager.packagers.mets import build_mets_package


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "report.pdf").write_bytes(b"%PDF-1.4 fake pdf 1")
    (files_dir / "appendix.pdf").write_bytes(b"%PDF-1.4 fake pdf 2")
    (files_dir / "data.csv").write_bytes(b"a,b\n1,2\n")

    csv_path = tmp_path / "metadata.csv"
    csv_path.write_text(
        "dc.title,dc.creator,dc.subject,dc.description,dc.date,dc.type,dc.identifier,dc.rights,files\n"
        '"Climate Report","Smith, Jane||Doe, John","climate||policy",'
        '"Annual analysis","2024-03-15","Report","doi:10.1234/abc","CC-BY",'
        '"report.pdf||appendix.pdf"\n'
        '"Survey Data","Lee, Kim","data","Raw responses","2024","Dataset","","CC0","data.csv"\n',
        encoding="utf-8",
    )
    return tmp_path


def test_read_csv_parses_records(sample_dir: Path):
    records = read_csv(sample_dir / "metadata.csv")
    assert len(records) == 2

    r1 = records[0]
    assert r1.title == "Climate Report"
    assert r1.get("creator") == ["Smith, Jane", "Doe, John"]
    assert r1.get("subject") == ["climate", "policy"]
    assert r1.files == ["report.pdf", "appendix.pdf"]

    r2 = records[1]
    assert r2.get("identifier") == []  # empty cell -> no value
    assert r2.files == ["data.csv"]


def test_read_csv_accepts_filename_column(tmp_path: Path):
    csv_path = tmp_path / "m.csv"
    csv_path.write_text(
        "dc.title,filename\n" '"X","a.pdf"\n', encoding="utf-8"
    )
    records = read_csv(csv_path)
    assert records[0].files == ["a.pdf"]


def test_read_csv_accepts_unprefixed_headers(tmp_path: Path):
    csv_path = tmp_path / "m.csv"
    csv_path.write_text("title,creator,files\nT,A,f.pdf\n", encoding="utf-8")
    records = read_csv(csv_path)
    assert records[0].title == "T"
    assert records[0].get("creator") == ["A"]


def test_read_csv_rejects_csv_with_no_dc_columns(tmp_path: Path):
    csv_path = tmp_path / "m.csv"
    csv_path.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_csv(csv_path)


def test_resolve_files_raises_on_missing(sample_dir: Path):
    csv_path = sample_dir / "bad.csv"
    csv_path.write_text(
        "dc.title,files\nX,nope.pdf\n", encoding="utf-8"
    )
    record = read_csv(csv_path)[0]
    with pytest.raises(FileNotFoundError):
        resolve_files(record, sample_dir / "files")


def test_build_mets_package(sample_dir: Path):
    record = read_csv(sample_dir / "metadata.csv")[0]
    files = resolve_files(record, sample_dir / "files")
    out = sample_dir / "out" / "pkg.zip"

    build_mets_package(record, files, out)

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "mets.xml" in names
        assert "report.pdf" in names
        assert "appendix.pdf" in names

        mets_bytes = zf.read("mets.xml")

    root = etree.fromstring(mets_bytes)
    ns = {"mets": "http://www.loc.gov/METS/", "mods": "http://www.loc.gov/mods/v3"}
    titles = root.findall(".//mods:title", ns)
    assert any(t.text == "Climate Report" for t in titles)
    file_els = root.findall(".//mets:file", ns)
    assert len(file_els) == 2
    for fe in file_els:
        assert fe.get("CHECKSUM")
        assert fe.get("CHECKSUMTYPE") == "MD5"


def test_build_eprints_package(sample_dir: Path):
    record = read_csv(sample_dir / "metadata.csv")[0]
    files = resolve_files(record, sample_dir / "files")
    out = sample_dir / "out" / "ep.zip"

    build_eprints_package(record, files, out)

    with zipfile.ZipFile(out) as zf:
        assert "eprints.xml" in zf.namelist()
        xml_bytes = zf.read("eprints.xml")

    root = etree.fromstring(xml_bytes)
    ns = {"ep": "http://eprints.org/ep2/data/2.0"}
    title = root.find(".//ep:eprint/ep:title", ns)
    assert title is not None and title.text == "Climate Report"
    creators = root.findall(
        ".//ep:eprint/ep:creators/ep:item/ep:name/ep:family", ns
    )
    assert [c.text for c in creators] == ["Smith", "Doe"]


def test_build_atom_package(sample_dir: Path):
    record = read_csv(sample_dir / "metadata.csv")[0]
    files = resolve_files(record, sample_dir / "files")
    out = sample_dir / "out" / "atom.zip"

    build_atom_package(record, files, out)

    with zipfile.ZipFile(out) as zf:
        assert "atom.xml" in zf.namelist()
        xml_bytes = zf.read("atom.xml")

    root = etree.fromstring(xml_bytes)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "dcterms": "http://purl.org/dc/terms/",
    }
    assert root.find("atom:title", ns).text == "Climate Report"
    subjects = [s.text for s in root.findall("dcterms:subject", ns)]
    assert subjects == ["climate", "policy"]

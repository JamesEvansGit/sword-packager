"""Tests for Phase 1 CRUD additions: receipt parsing and state store."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sword_packager.csv_reader import read_csv, resolve_files
from sword_packager.deposit import deposit
from sword_packager.receipt import parse_receipt
from sword_packager.state import StateStore


SAMPLE_RECEIPT = b"""<?xml version="1.0" encoding="UTF-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:sword="http://purl.org/net/sword/terms/">
  <title>Climate Report</title>
  <id>http://example.org/items/42</id>
  <link rel="edit"        href="http://example.org/swordv2/edit/42"/>
  <link rel="edit-media"  href="http://example.org/swordv2/edit-media/42"
        type="application/atom+xml;type=feed"/>
  <link rel="edit-media"  href="http://example.org/swordv2/edit-media/42.atom"/>
  <link rel="http://purl.org/net/sword/terms/statement"
        href="http://example.org/swordv2/statement/42.atom"
        type="application/atom+xml;type=feed"/>
  <sword:treatment>Item entered the workflow review queue.</sword:treatment>
</entry>
"""


def test_parse_receipt_extracts_iris():
    receipt = parse_receipt(SAMPLE_RECEIPT)
    assert receipt.se_iri == "http://example.org/swordv2/edit/42"
    # Non-feed edit-media link should win over the feed-typed one
    assert receipt.em_iri == "http://example.org/swordv2/edit-media/42.atom"
    assert receipt.stmt_iri == "http://example.org/swordv2/statement/42.atom"
    assert receipt.atom_id == "http://example.org/items/42"
    assert receipt.title == "Climate Report"
    assert "review queue" in (receipt.treatment or "")


def test_parse_receipt_handles_missing_links():
    minimal = b"""<?xml version="1.0"?>
<entry xmlns="http://www.w3.org/2005/Atom">
  <title>Bare</title>
  <id>urn:bare</id>
</entry>
"""
    receipt = parse_receipt(minimal)
    assert receipt.se_iri is None
    assert receipt.em_iri is None
    assert receipt.stmt_iri is None
    assert receipt.atom_id == "urn:bare"


def test_state_store_upsert_and_get(tmp_path: Path):
    db = tmp_path / "state.db"
    store = StateStore(db)
    csv_path = tmp_path / "records.csv"
    csv_path.write_text("dc.title\nFoo\n", encoding="utf-8")

    receipt = parse_receipt(SAMPLE_RECEIPT)
    store.upsert(
        csv_path=csv_path,
        row_number=2,
        collection_url="https://example.org/coll/1",
        package_format="mets",
        receipt=receipt,
        status_code=201,
    )

    record = store.get(csv_path, 2)
    assert record is not None
    assert record.se_iri == receipt.se_iri
    assert record.em_iri == receipt.em_iri
    assert record.stmt_iri == receipt.stmt_iri
    assert record.last_status == 201
    assert record.package_format == "mets"


def test_state_store_upsert_preserves_iris_on_later_failure(tmp_path: Path):
    db = tmp_path / "state.db"
    store = StateStore(db)
    csv_path = tmp_path / "records.csv"
    csv_path.write_text("dc.title\nFoo\n", encoding="utf-8")

    receipt = parse_receipt(SAMPLE_RECEIPT)
    store.upsert(
        csv_path=csv_path, row_number=2,
        collection_url="https://example.org/coll/1", package_format="mets",
        receipt=receipt, status_code=201,
    )
    # A later failed attempt with no receipt must not blank out the IRIs
    store.upsert(
        csv_path=csv_path, row_number=2,
        collection_url="https://example.org/coll/1", package_format="mets",
        receipt=None, status_code=500,
    )
    record = store.get(csv_path, 2)
    assert record.se_iri == receipt.se_iri  # preserved
    assert record.last_status == 500       # but status reflects the latest


def test_state_store_list_for_csv(tmp_path: Path):
    db = tmp_path / "state.db"
    store = StateStore(db)
    csv_path = tmp_path / "records.csv"
    csv_path.write_text("dc.title\nFoo\n", encoding="utf-8")

    for n in (5, 2, 9):
        store.upsert(
            csv_path=csv_path, row_number=n,
            collection_url="c", package_format="mets",
            receipt=None, status_code=201,
        )
    rows = store.list_for_csv(csv_path)
    assert [r.row_number for r in rows] == [2, 5, 9]


def test_deposit_attaches_receipt_on_success(tmp_path: Path):
    """Mocked end-to-end: build a tiny package, deposit, parse the receipt."""
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "report.pdf").write_bytes(b"%PDF fake")

    csv_path = tmp_path / "m.csv"
    csv_path.write_text("dc.title,files\nFoo,report.pdf\n", encoding="utf-8")

    record = read_csv(csv_path)[0]
    files = resolve_files(record, files_dir)

    from sword_packager.packagers.mets import build_mets_package
    pkg = tmp_path / "pkg.zip"
    build_mets_package(record, files, pkg)

    class FakeResponse:
        status_code = 201
        headers = {"Content-Type": "application/atom+xml;type=entry", "Location": "http://example.org/edit/42"}
        text = SAMPLE_RECEIPT.decode("utf-8")
        content = SAMPLE_RECEIPT

    with patch("sword_packager.deposit.requests.post", return_value=FakeResponse()):
        result = deposit(
            package_path=pkg,
            collection_url="https://example.org/coll/1",
            username="u", password="p", package_format="mets",
        )

    assert result.ok
    assert result.receipt is not None
    assert result.receipt.se_iri == "http://example.org/swordv2/edit/42"
    assert result.receipt.stmt_iri.endswith("statement/42.atom")


def test_deposit_no_receipt_on_non_xml_response(tmp_path: Path):
    """A 201 with an HTML body should not crash; receipt comes back None."""
    pkg = tmp_path / "pkg.zip"
    pkg.write_bytes(b"PK\x03\x04 fake zip")

    class FakeResponse:
        status_code = 201
        headers = {"Content-Type": "text/html"}
        text = "<html>OK</html>"
        content = b"<html>OK</html>"

    with patch("sword_packager.deposit.requests.post", return_value=FakeResponse()):
        result = deposit(
            package_path=pkg, collection_url="x",
            username="u", password="p", package_format="mets",
        )
    assert result.ok
    assert result.receipt is None

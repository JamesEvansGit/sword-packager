"""Tests for the SWORD version selection mechanism."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sword_packager.deposit import deposit
from sword_packager.packagers import (
    formats_for_version,
    validate_version_format,
)


def test_formats_for_v1_excludes_atom():
    formats = formats_for_version("v1")
    assert "mets" in formats
    assert "eprints" in formats
    assert "atom" not in formats


def test_formats_for_v2_includes_all():
    formats = formats_for_version("v2")
    assert set(formats) == {"mets", "eprints", "atom"}


def test_validate_rejects_atom_on_v1():
    with pytest.raises(ValueError, match="not supported on SWORD v1"):
        validate_version_format("v1", "atom")


def test_validate_rejects_unknown_version():
    with pytest.raises(ValueError, match="Unknown SWORD version"):
        validate_version_format("v3", "mets")


def test_validate_rejects_unknown_format():
    with pytest.raises(ValueError, match="Unknown package format"):
        validate_version_format("v2", "bogus")


def test_validate_accepts_mets_on_both_versions():
    validate_version_format("v1", "mets")
    validate_version_format("v2", "mets")


class _FakeResponse:
    status_code = 201
    headers = {"Content-Type": "text/html"}
    text = "OK"
    content = b"OK"


def test_deposit_v2_sends_in_progress_false(tmp_path: Path):
    """v2 always sends In-Progress, set to false when --complete is the default."""
    pkg = tmp_path / "p.zip"
    pkg.write_bytes(b"PK\x03\x04 fake")

    with patch("sword_packager.deposit.requests.post", return_value=_FakeResponse()) as mock_post:
        deposit(
            package_path=pkg, collection_url="x",
            username="u", password="p", package_format="mets",
            sword_version="v2",
        )
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["In-Progress"] == "false"


def test_deposit_v1_omits_in_progress_when_complete(tmp_path: Path):
    """v1 omits In-Progress entirely when the deposit is complete."""
    pkg = tmp_path / "p.zip"
    pkg.write_bytes(b"PK\x03\x04 fake")

    with patch("sword_packager.deposit.requests.post", return_value=_FakeResponse()) as mock_post:
        deposit(
            package_path=pkg, collection_url="x",
            username="u", password="p", package_format="mets",
            sword_version="v1", in_progress=False,
        )
    headers = mock_post.call_args.kwargs["headers"]
    assert "In-Progress" not in headers


def test_deposit_v1_sends_in_progress_when_workflow_inbox(tmp_path: Path):
    """v1 with in_progress=True sends the header explicitly."""
    pkg = tmp_path / "p.zip"
    pkg.write_bytes(b"PK\x03\x04 fake")

    with patch("sword_packager.deposit.requests.post", return_value=_FakeResponse()) as mock_post:
        deposit(
            package_path=pkg, collection_url="x",
            username="u", password="p", package_format="mets",
            sword_version="v1", in_progress=True,
        )
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["In-Progress"] == "true"


def test_deposit_rejects_atom_on_v1(tmp_path: Path):
    pkg = tmp_path / "p.zip"
    pkg.write_bytes(b"PK\x03\x04 fake")

    with pytest.raises(ValueError, match="not supported on SWORD v1"):
        deposit(
            package_path=pkg, collection_url="x",
            username="u", password="p", package_format="atom",
            sword_version="v1",
        )

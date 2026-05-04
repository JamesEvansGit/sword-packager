"""Tests for cron-friendly behaviour: dedupe filter and rate-limit delay."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

from typer.testing import CliRunner

from sword_packager.cli import app
from sword_packager.state import StateStore


runner = CliRunner()


def _make_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build a CSV with 3 rows plus matching files. Returns (csv, files_dir, out_dir)."""
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    for i in range(1, 4):
        (files_dir / f"r{i}.pdf").write_bytes(b"%PDF fake")

    csv_path = tmp_path / "metadata.csv"
    csv_path.write_text(
        "dc.title,files\n"
        "First,r1.pdf\n"
        "Second,r2.pdf\n"
        "Third,r3.pdf\n",
        encoding="utf-8",
    )
    return csv_path, files_dir, tmp_path / "out"


class _FakeResponse:
    status_code = 201
    headers = {"Content-Type": "text/html"}
    text = "OK"
    content = b"OK"


def test_delay_is_called_between_submissions(tmp_path: Path):
    """Three rows -> two inter-submission sleeps of 0.5s."""
    csv_path, files_dir, out_dir = _make_inputs(tmp_path)
    state_file = tmp_path / "state.db"

    with patch("sword_packager.deposit.requests.post", return_value=_FakeResponse()), \
         patch("sword_packager.cli.time.sleep") as mock_sleep:
        result = runner.invoke(
            app,
            [
                "deposit", str(csv_path), str(files_dir), str(out_dir),
                "--collection-url", "https://example.org/c",
                "--username", "u", "--password", "p",
                "--sword-version", "v2", "--format", "mets",
                "--state-file", str(state_file),
                "--delay", "0.5",
            ],
        )

    assert result.exit_code == 0, result.output
    # Two sleeps for three records (between 1->2 and 2->3)
    assert mock_sleep.call_count == 2
    for call in mock_sleep.call_args_list:
        assert call.args == (0.5,)


def test_delay_zero_disables_sleep(tmp_path: Path):
    csv_path, files_dir, out_dir = _make_inputs(tmp_path)
    state_file = tmp_path / "state.db"

    with patch("sword_packager.deposit.requests.post", return_value=_FakeResponse()), \
         patch("sword_packager.cli.time.sleep") as mock_sleep:
        result = runner.invoke(
            app,
            [
                "deposit", str(csv_path), str(files_dir), str(out_dir),
                "--collection-url", "https://example.org/c",
                "--username", "u", "--password", "p",
                "--sword-version", "v2", "--format", "mets",
                "--state-file", str(state_file),
                "--delay", "0",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_sleep.assert_not_called()


def test_skip_already_deposited_filters_done_rows(tmp_path: Path):
    """Pre-populate the state DB so row 1 looks already-deposited; only rows 2&3 should POST."""
    csv_path, files_dir, out_dir = _make_inputs(tmp_path)
    state_file = tmp_path / "state.db"

    # Mark row 2 (first record - row_number=2 since header is row 1) as already done.
    store = StateStore(state_file)
    store.upsert(
        csv_path=csv_path,
        row_number=2,
        collection_url="https://example.org/c",
        package_format="mets",
        receipt=None,
        status_code=201,
    )

    fake_response = _FakeResponse()
    with patch("sword_packager.deposit.requests.post", return_value=fake_response) as mock_post, \
         patch("sword_packager.cli.time.sleep"):
        result = runner.invoke(
            app,
            [
                "deposit", str(csv_path), str(files_dir), str(out_dir),
                "--collection-url", "https://example.org/c",
                "--username", "u", "--password", "p",
                "--sword-version", "v2", "--format", "mets",
                "--state-file", str(state_file),
                "--skip-already-deposited",
                "--delay", "0",
            ],
        )

    assert result.exit_code == 0, result.output
    # Only two POSTs (rows 3 and 4); row 2 was skipped.
    assert mock_post.call_count == 2
    assert "Skipping 1 row" in result.output


def test_skip_already_deposited_with_no_new_rows(tmp_path: Path):
    """If everything's already deposited, exit cleanly without posting anything."""
    csv_path, files_dir, out_dir = _make_inputs(tmp_path)
    state_file = tmp_path / "state.db"

    store = StateStore(state_file)
    for row in (2, 3, 4):
        store.upsert(
            csv_path=csv_path, row_number=row,
            collection_url="https://example.org/c", package_format="mets",
            receipt=None, status_code=201,
        )

    with patch("sword_packager.deposit.requests.post") as mock_post, \
         patch("sword_packager.cli.time.sleep"):
        result = runner.invoke(
            app,
            [
                "deposit", str(csv_path), str(files_dir), str(out_dir),
                "--collection-url", "https://example.org/c",
                "--username", "u", "--password", "p",
                "--sword-version", "v2", "--format", "mets",
                "--state-file", str(state_file),
                "--skip-already-deposited",
                "--delay", "0",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_post.assert_not_called()
    assert "Nothing new to deposit" in result.output


def test_skip_already_deposited_does_not_skip_failed_rows(tmp_path: Path):
    """A row with last_status 500 should still be retried."""
    csv_path, files_dir, out_dir = _make_inputs(tmp_path)
    state_file = tmp_path / "state.db"

    store = StateStore(state_file)
    store.upsert(
        csv_path=csv_path, row_number=2,
        collection_url="https://example.org/c", package_format="mets",
        receipt=None, status_code=500,  # failed last time
    )

    with patch("sword_packager.deposit.requests.post", return_value=_FakeResponse()) as mock_post, \
         patch("sword_packager.cli.time.sleep"):
        result = runner.invoke(
            app,
            [
                "deposit", str(csv_path), str(files_dir), str(out_dir),
                "--collection-url", "https://example.org/c",
                "--username", "u", "--password", "p",
                "--sword-version", "v2", "--format", "mets",
                "--state-file", str(state_file),
                "--skip-already-deposited",
                "--delay", "0",
            ],
        )

    assert result.exit_code == 0, result.output
    # All three rows are attempted again, including the previously-failed one.
    assert mock_post.call_count == 3

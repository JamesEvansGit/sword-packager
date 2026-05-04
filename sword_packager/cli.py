"""Command-line interface for sword-packager.

Examples::

    # Build METS SIP packages from metadata.csv into ./out/
    sword-packager build metadata.csv ./files ./out --format mets

    # Build and deposit in one go (records IRIs in the state DB)
    sword-packager deposit metadata.csv ./files ./out \\
        --format mets \\
        --collection-url https://demo.dspace.org/swordv2/collection/123/456 \\
        --username alice --password secret

    # See what was deposited and fetch live state from the server
    sword-packager status metadata.csv

    # Move row 5 out of the workflow inbox (In-Progress: false)
    sword-packager complete metadata.csv 5 --username alice
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from sword_packager.csv_reader import read_csv, resolve_files
from sword_packager.deposit import (
    complete_deposit as do_complete,
    deposit as do_deposit,
    fetch_statement,
)
from sword_packager.packagers import (
    PACKAGE_FORMATS,
    SWORD_VERSIONS,
    formats_for_version,
    validate_version_format,
)
from sword_packager.state import DEFAULT_STATE_PATH, StateStore

app = typer.Typer(
    add_completion=True,
    help="Build and deposit SWORD packages from a CSV metadata file.",
)
console = Console()

FORMAT_CHOICES = list(PACKAGE_FORMATS)


def _resolve_sword_version(supplied: str | None) -> str:
    """Return a normalised SWORD version, prompting interactively if needed.

    If ``supplied`` is given, validate and normalise it. Otherwise prompt
    the user when stdin is a TTY. In non-interactive environments
    (CI, pipes), require ``--sword-version``.
    """
    if supplied is not None:
        v = supplied.lower().lstrip("v")
        v = f"v{v}" if v in {"1", "2"} else supplied.lower()
        if v not in SWORD_VERSIONS:
            raise typer.BadParameter(
                f"Unknown SWORD version {supplied!r}; choose v1 or v2."
            )
        return v

    if not sys.stdin.isatty():
        raise typer.BadParameter(
            "SWORD version not specified and stdin isn't a TTY. "
            "Pass --sword-version v1 or --sword-version v2."
        )

    console.print(
        "\n[bold]Which SWORD protocol version does the target server speak?[/bold]"
    )
    console.print(
        "  [cyan]v1[/cyan]  SWORD v1.3 — older endpoints, deposit-only "
        "(EPrints 3.2, DSpace 5/6 sword/)"
    )
    console.print(
        "  [cyan]v2[/cyan]  SWORD v2  — newer endpoints with deposit receipts "
        "and CRUD ops (EPrints 3.3+, DSpace swordv2/, Dataverse)"
    )
    while True:
        choice = typer.prompt("Version", default="v2").strip().lower().lstrip("v")
        choice = f"v{choice}" if choice in {"1", "2"} else choice
        if choice in SWORD_VERSIONS:
            return choice
        console.print(f"[red]Please enter v1 or v2.[/red]")


def _resolve_path(label: str, value: Path | None, *, must_exist: bool = False,
                  is_dir: bool = False, hint: str = "") -> Path:
    if value is None and hint:
        console.print(f"\n[dim]{hint}[/dim]")
    while value is None:
        raw = typer.prompt(label).strip()
        if not raw:
            console.print("[red]This field is required.[/red]")
            continue
        p = Path(raw).expanduser().resolve()
        if must_exist and not p.exists():
            console.print(f"[red]Path not found: {p}[/red]")
            continue
        if is_dir and p.exists() and not p.is_dir():
            console.print(f"[red]Not a directory: {p}[/red]")
            continue
        value = p
    return value


def _resolve_str(label: str, value: str | None, *, hint: str = "") -> str:
    if not value and hint:
        console.print(f"\n[dim]{hint}[/dim]")
    while not value:
        raw = typer.prompt(label).strip()
        if raw:
            value = raw
        else:
            console.print("[red]This field is required.[/red]")
    return value


def _resolve_format(version: str, supplied: str | None) -> str:
    """Pick a package format compatible with the chosen version."""
    compatible = formats_for_version(version)
    if supplied is not None:
        fmt = supplied.lower()
        try:
            validate_version_format(version, fmt)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        return fmt

    if not sys.stdin.isatty():
        # Sensible default: 'mets' if available, else first compatible.
        return "mets" if "mets" in compatible else compatible[0]

    if len(compatible) == 1:
        only = compatible[0]
        console.print(f"[dim]Using the only format available on {version}: {only}[/dim]")
        return only

    console.print(f"\n[bold]Package format for SWORD {version}?[/bold]")
    for f in compatible:
        console.print(f"  [cyan]{f}[/cyan]")
    while True:
        choice = typer.prompt("Format", default="mets" if "mets" in compatible else compatible[0])
        choice = choice.strip().lower()
        if choice in compatible:
            return choice
        console.print(f"[red]Choose one of: {', '.join(compatible)}[/red]")



def _slugify(value: str, max_length: int = 60) -> str:
    """Filesystem-safe slug from a record title."""
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE).strip().lower()
    value = re.sub(r"[\s_-]+", "-", value)
    return value[:max_length] or "record"


def _build_one(record, files, output_dir: Path, package_format: str) -> Path:
    builder = PACKAGE_FORMATS[package_format]["build"]
    ext = PACKAGE_FORMATS[package_format]["ext"]
    name = f"row{record.row_number:03d}-{_slugify(record.title)}{ext}"
    out_path = output_dir / name
    builder(record, files, out_path)
    return out_path


def _warn_about_embargoes(records, package_format: str) -> None:
    """Print a one-time warning if any record has an embargo date.

    The embargo XML is always written, but its enforcement is the
    target repository's responsibility — and on a fresh install of
    DSpace or EPrints the embargo plugins/workflow are often disabled.
    Surfacing this clearly avoids the surprise of "I set an embargo
    and the file is still public."
    """
    embargoed = [r for r in records if r.embargo_until]
    if not embargoed:
        return

    target_hint = {
        "mets":    "DSpace EmbargoSetter / EmbargoLifter plugins (configure in dspace.cfg)",
        "eprints": "EPrints document workflow with security=staffonly during the embargo window",
        "atom":    "Dataverse embargo settings, or DSpace SWORDv2 embargo handling",
    }.get(package_format, "the target repository's embargo configuration")

    console.print(
        f"\n[yellow][bold]Embargo notice:[/bold] {len(embargoed)} record(s) have an "
        f"embargo end date.[/yellow]"
    )
    console.print(
        f"[yellow]The date is written into the package XML, but enforcement "
        f"depends on the receiving repository being configured to honour it.[/yellow]"
    )
    console.print(f"[yellow]For [bold]{package_format}[/bold] packages this means: {target_hint}.[/yellow]")
    console.print(
        "[yellow]Verify with your repository administrator that embargoes "
        "are actually enforced before relying on them.[/yellow]\n"
    )


@app.command()
def build(
    csv_path: Optional[Path] = typer.Argument(None, help="CSV metadata file."),
    files_dir: Optional[Path] = typer.Argument(None, help="Directory holding the payload files."),
    output_dir: Optional[Path] = typer.Argument(None, help="Where to write the package zips."),
    sword_version: Optional[str] = typer.Option(
        None,
        "--sword-version",
        "-V",
        help="SWORD protocol version: v1 or v2. Prompted interactively if omitted.",
        case_sensitive=False,
    ),
    package_format: Optional[str] = typer.Option(
        None,
        "--format",
        "-f",
        help=f"Package format. One of: {', '.join(FORMAT_CHOICES)}. Constrained by the chosen version.",
        case_sensitive=False,
    ),
) -> None:
    """Build SWORD packages without depositing them."""
    csv_path = _resolve_path(
        "Path to metadata CSV file", csv_path, must_exist=True,
        hint="Your metadata spreadsheet saved as CSV. See examples/metadata.csv for the expected column layout.",
    )
    files_dir = _resolve_path(
        "Directory containing payload files", files_dir, must_exist=True, is_dir=True,
        hint="The folder holding the files (PDFs, datasets, etc.) listed in the 'files' column of your CSV.",
    )
    output_dir = _resolve_path(
        "Output directory for built packages", output_dir,
        hint="Where the ZIP packages will be written. The directory will be created if it does not already exist.",
    )
    version = _resolve_sword_version(sword_version)
    package_format = _resolve_format(version, package_format)

    records = read_csv(csv_path)
    if not records:
        console.print("[yellow]No records found in CSV.[/yellow]")
        raise typer.Exit(code=1)

    _warn_about_embargoes(records, package_format)

    output_dir.mkdir(parents=True, exist_ok=True)

    table = Table(title=f"Built {package_format} packages (SWORD {version})")
    table.add_column("Row", justify="right")
    table.add_column("Title")
    table.add_column("Files", justify="right")
    table.add_column("Package")

    failures = 0
    for record in records:
        try:
            files = resolve_files(record, files_dir)
        except FileNotFoundError as exc:
            console.print(f"[red]Row {record.row_number}: {exc}[/red]")
            failures += 1
            continue
        package_path = _build_one(record, files, output_dir, package_format)
        table.add_row(
            str(record.row_number),
            record.title,
            str(len(files)),
            package_path.name,
        )

    console.print(table)
    if failures:
        console.print(f"[yellow]{failures} record(s) skipped due to missing files.[/yellow]")
        raise typer.Exit(code=2)


@app.command()
def deposit(
    csv_path: Optional[Path] = typer.Argument(None, help="CSV metadata file."),
    files_dir: Optional[Path] = typer.Argument(None, help="Directory holding the payload files."),
    output_dir: Optional[Path] = typer.Argument(None, help="Where to write the package zips before deposit."),
    collection_url: Optional[str] = typer.Option(None, "--collection-url", "-c", help="SWORD collection deposit URL."),
    username: Optional[str] = typer.Option(None, "--username", "-u", help="Basic-auth username."),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Basic-auth password.", hide_input=True),
    sword_version: Optional[str] = typer.Option(
        None, "--sword-version", "-V",
        help="SWORD protocol version: v1 or v2. Prompted interactively if omitted.",
        case_sensitive=False,
    ),
    package_format: Optional[str] = typer.Option(
        None, "--format", "-f",
        help=f"Package format. Constrained by the chosen version.",
        case_sensitive=False,
    ),
    on_behalf_of: Optional[str] = typer.Option(None, "--on-behalf-of", help="Mediated deposit user."),
    in_progress: bool = typer.Option(False, "--in-progress", help="Mark deposits as still in progress (workflow inbox)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Build packages but do not POST them."),
    state_file: Path = typer.Option(DEFAULT_STATE_PATH, "--state-file", help="SQLite file storing deposit IRIs for later CRUD."),
    delay: float = typer.Option(
        10.0,
        "--delay",
        help="Seconds to wait between submissions, to avoid hammering the server. Set to 0 to disable.",
        min=0.0,
    ),
    skip_already_deposited: bool = typer.Option(
        False,
        "--skip-already-deposited",
        help="Skip rows already recorded in the state DB with a 2xx status. Use this for cron-driven runs to avoid duplicate deposits.",
    ),
) -> None:
    """Build packages and POST them to a SWORD endpoint."""
    csv_path = _resolve_path(
        "Path to metadata CSV file", csv_path, must_exist=True,
        hint="Your metadata spreadsheet saved as CSV. See examples/metadata.csv for the expected column layout.",
    )
    files_dir = _resolve_path(
        "Directory containing payload files", files_dir, must_exist=True, is_dir=True,
        hint="The folder holding the files (PDFs, datasets, etc.) listed in the 'files' column of your CSV.",
    )
    output_dir = _resolve_path(
        "Output directory for built packages", output_dir,
        hint="Where the ZIP packages will be written. The directory will be created if it does not already exist.",
    )
    collection_url = _resolve_str(
        "SWORD collection URL", collection_url,
        hint=(
            "The deposit URL for the target collection — found in the SWORD service document.\n"
            "  DSpace 7 or later  (path includes /server/):\n"
            "    SWORD v2 : https://<domain>/server/swordv2/collection/<handle>\n"
            "    SWORD v1 : https://<domain>/server/dspace-sword/sword/deposit/<handle>\n"
            "  DSpace 6 and earlier:\n"
            "    SWORD v2 : https://<domain>/swordv2/collection/<handle>\n"
            "    SWORD v1 : https://<domain>/dspace-sword/sword/deposit/<handle>\n"
            "  <handle> is the collection handle, e.g. 123456789/5\n"
            "  To look it up, fetch the service document and copy the href value:\n"
            "    DSpace 7+ : curl -u <user>:<pass> https://<domain>/server/swordv2/servicedocument\n"
            "    DSpace 6  : curl -u <user>:<pass> https://<domain>/swordv2/servicedocument"
        ),
    )
    username = _resolve_str(
        "Username", username,
        hint=(
            "Your repository account username.\n"
            "  The account must have (1) submit rights and (2) collection administrator role\n"
            "  on the target collection. Both are set in the DSpace admin UI under\n"
            "  Edit Collection → Roles. Without both roles deposits may fail or land\n"
            "  in a review queue rather than going live."
        ),
    )
    if not password:
        console.print("\n[dim]Your repository account password (input will be hidden).[/dim]")
        password = typer.prompt("Password", hide_input=True)
    version = _resolve_sword_version(sword_version)
    package_format = _resolve_format(version, package_format)

    if version == "v1":
        console.print(
            "[yellow]SWORD v1: deposit-only. Status/complete commands rely on "
            "v2 deposit receipts and won't be useful against v1 servers.[/yellow]"
        )

    records = read_csv(csv_path)
    if not records:
        console.print("[yellow]No records found in CSV.[/yellow]")
        raise typer.Exit(code=1)

    _warn_about_embargoes(records, package_format)

    output_dir.mkdir(parents=True, exist_ok=True)
    store = StateStore(state_file) if not dry_run else None

    # Filter out rows already deposited successfully, if asked.
    if skip_already_deposited and store is not None:
        existing = {
            r.row_number for r in store.list_for_csv(csv_path)
            if r.last_status is not None and 200 <= r.last_status < 300
        }
        if existing:
            before = len(records)
            records = [r for r in records if r.row_number not in existing]
            console.print(
                f"[dim]Skipping {before - len(records)} row(s) already deposited "
                f"(per {state_file}).[/dim]"
            )
        if not records:
            console.print("[green]Nothing new to deposit.[/green]")
            return

    table = Table(title=f"Deposit results — SWORD {version}, {package_format}")
    table.add_column("Row", justify="right")
    table.add_column("Title")
    table.add_column("Status", justify="right")
    table.add_column("SE-IRI" if version == "v2" else "Location")

    failures = 0
    submissions_made = 0
    for record in records:
        try:
            files = resolve_files(record, files_dir)
        except FileNotFoundError as exc:
            console.print(f"[red]Row {record.row_number}: {exc}[/red]")
            failures += 1
            continue

        package_path = _build_one(record, files, output_dir, package_format)

        if dry_run:
            table.add_row(str(record.row_number), record.title, "—", "(dry run)")
            continue

        # Throttle between submissions. Sleep BEFORE each POST after the
        # first one so a single-record run isn't artificially delayed.
        if submissions_made > 0 and delay > 0:
            console.print(
                f"[dim]Waiting {delay:g}s before next submission...[/dim]"
            )
            time.sleep(delay)
        submissions_made += 1

        result = do_deposit(
            package_path=package_path,
            collection_url=collection_url,
            username=username,
            password=password,
            package_format=package_format,
            sword_version=version,
            on_behalf_of=on_behalf_of,
            in_progress=in_progress,
        )

        # Persist whatever we got, even on failure, so the state DB shows
        # the last attempt; on v2 this is where the IRIs land.
        if store is not None:
            store.upsert(
                csv_path=csv_path,
                row_number=record.row_number,
                collection_url=collection_url,
                package_format=package_format,
                receipt=result.receipt,
                status_code=result.status_code,
            )

        status_style = "green" if result.ok else "red"
        se_iri = result.receipt.se_iri if result.receipt else None
        table.add_row(
            str(record.row_number),
            record.title,
            f"[{status_style}]{result.status_code}[/{status_style}]",
            se_iri or result.location or "(none)",
        )
        if not result.ok:
            failures += 1
            console.print(
                f"[red]Row {record.row_number} failed:\n{result.body[:500]}[/red]"
            )
        elif result.receipt is None and version == "v2":
            console.print(
                f"[yellow]Row {record.row_number}: deposit succeeded but no "
                "receipt was parseable; CRUD ops on this row won't be possible.[/yellow]"
            )

    console.print(table)
    if not dry_run:
        console.print(f"[dim]State recorded in {state_file}[/dim]")
    if failures:
        raise typer.Exit(code=2)


@app.command()
def status(
    csv_path: Path = typer.Argument(..., exists=True, readable=True, help="CSV metadata file (used as the state DB key)."),
    row: Optional[int] = typer.Option(None, "--row", "-r", help="Show only a single row, and fetch its Statement live from the server."),
    username: Optional[str] = typer.Option(None, "--username", "-u", help="Basic-auth username (only needed with --row to fetch the Statement)."),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Basic-auth password.", hide_input=True),
    state_file: Path = typer.Option(DEFAULT_STATE_PATH, "--state-file"),
) -> None:
    """Show recorded deposit state for a CSV.

    Without ``--row`` this prints a table of every deposit recorded for
    ``csv_path``. With ``--row N`` it additionally GETs the Statement
    IRI for that row and shows the server's view of the item, which is
    the only way to tell whether a deposit ultimately went live.
    """
    if not state_file.exists():
        console.print(f"[yellow]No state DB at {state_file}. Run `deposit` first.[/yellow]")
        raise typer.Exit(code=1)

    store = StateStore(state_file)

    if row is None:
        records = store.list_for_csv(csv_path)
        if not records:
            console.print(
                f"[yellow]No deposits recorded for {csv_path} in {state_file}.[/yellow]"
            )
            raise typer.Exit(code=1)

        table = Table(title=f"Deposits recorded for {csv_path.name}")
        table.add_column("Row", justify="right")
        table.add_column("Title")
        table.add_column("Status", justify="right")
        table.add_column("SE-IRI")
        table.add_column("Updated")
        for r in records:
            ok = r.last_status is not None and 200 <= r.last_status < 300
            style = "green" if ok else "red"
            table.add_row(
                str(r.row_number),
                r.title or "(no title)",
                f"[{style}]{r.last_status}[/{style}]",
                r.se_iri or "(none)",
                r.last_updated[:19],
            )
        console.print(table)
        return

    # Single-row mode: show what's stored, then fetch the Statement.
    record = store.get(csv_path, row)
    if record is None:
        console.print(f"[red]No deposit recorded for row {row} of {csv_path}.[/red]")
        raise typer.Exit(code=1)

    console.print(f"[bold]Row {row}[/bold]: {record.title or '(no title)'}")
    console.print(f"  SE-IRI:   {record.se_iri or '(none)'}")
    console.print(f"  EM-IRI:   {record.em_iri or '(none)'}")
    console.print(f"  Stmt-IRI: {record.stmt_iri or '(none)'}")
    console.print(f"  Atom id:  {record.atom_id or '(none)'}")
    console.print(f"  Treatment: {record.treatment or '(none)'}")
    console.print(f"  Last status: {record.last_status} at {record.last_updated}")

    if not record.stmt_iri:
        console.print("[yellow]No Statement IRI on file; can't fetch live state.[/yellow]")
        return

    if not username:
        console.print("[yellow]Pass --username (and --password) to fetch the live Statement.[/yellow]")
        return
    if password is None:
        password = typer.prompt("Password", hide_input=True)

    code, body, content_type = fetch_statement(record.stmt_iri, username, password)
    style = "green" if 200 <= code < 300 else "red"
    console.print(f"\n[bold]Statement[/bold] [{style}]({code} {content_type or ''})[/{style}]:")
    # Show a truncated dump; users can curl the IRI directly for the full doc.
    snippet = body[:2000]
    console.print(snippet)
    if len(body) > len(snippet):
        console.print(f"[dim]... {len(body) - len(snippet)} more bytes truncated[/dim]")


@app.command()
def complete(
    csv_path: Path = typer.Argument(..., exists=True, readable=True, help="CSV metadata file (used as the state DB key)."),
    row: int = typer.Argument(..., help="CSV row number to mark complete."),
    username: str = typer.Option(..., "--username", "-u"),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True),
    state_file: Path = typer.Option(DEFAULT_STATE_PATH, "--state-file"),
) -> None:
    """POST In-Progress: false to a row's SE-IRI to leave the workflow inbox."""
    if not state_file.exists():
        console.print(f"[red]No state DB at {state_file}.[/red]")
        raise typer.Exit(code=1)

    store = StateStore(state_file)
    record = store.get(csv_path, row)
    if record is None:
        console.print(f"[red]No deposit recorded for row {row} of {csv_path}.[/red]")
        raise typer.Exit(code=1)
    if not record.se_iri:
        console.print(f"[red]Row {row} has no SE-IRI on file; can't complete it.[/red]")
        raise typer.Exit(code=1)

    result = do_complete(record.se_iri, username, password)
    if result.ok:
        console.print(f"[green]Row {row} marked complete (HTTP {result.status_code}).[/green]")
        # Refresh persisted IRIs in case the server returned a new receipt
        # (some servers issue a fresh deposit receipt on the In-Progress flip).
        store.upsert(
            csv_path=csv_path,
            row_number=row,
            collection_url=record.collection_url,
            package_format=record.package_format,
            receipt=result.receipt,
            status_code=result.status_code,
        )
    else:
        console.print(f"[red]HTTP {result.status_code}: {result.body[:500]}[/red]")
        raise typer.Exit(code=2)


@app.command(name="list-formats")
def list_formats() -> None:
    """Print the supported package formats."""
    table = Table(title="Supported SWORD package formats")
    table.add_column("Name")
    table.add_column("Content-Type")
    table.add_column("X-Packaging")
    for name, fmt in PACKAGE_FORMATS.items():
        table.add_row(name, fmt["content_type"], fmt["packaging"])
    console.print(table)


if __name__ == "__main__":
    app()

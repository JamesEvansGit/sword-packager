"""Minimal SWORD v1.3 / v2 deposit client.

Posts a built package to a SWORD collection (deposit) URL with HTTP
basic auth and the appropriate headers:

    Content-Type:        package mime type (e.g. application/zip)
    Content-Disposition: filename=<basename>
    X-Packaging:         packaging URI for the format
    X-No-Op:             "false"
    X-On-Behalf-Of:      optional mediated-deposit user

For Atom multipart deposits we POST the Atom entry first, then the
binary; SWORDv2 also supports posting a SimpleZip directly with the
packaging URI set to ``http://purl.org/net/sword/package/SimpleZip``,
which is what we do here for simplicity.

Phase-1 CRUD additions:

    - DepositResult now carries a parsed DepositReceipt when the server
      returns one, so callers can persist the SE-IRI / EM-IRI / Stmt-IRI.
    - ``fetch_statement`` retrieves the Statement (Stmt-IRI) so the
      ``status`` CLI command can show the item's current state.
    - ``complete_deposit`` re-POSTs to the SE-IRI with In-Progress: false
      to move an item out of the workflow inbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests
from lxml import etree

from sword_packager.packagers import PACKAGE_FORMATS
from sword_packager.receipt import DepositReceipt, parse_receipt


@dataclass
class DepositResult:
    """Outcome of a single deposit attempt."""

    package: Path
    status_code: int
    location: str | None
    body: str
    receipt: DepositReceipt | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


def _try_parse_receipt(response: requests.Response) -> DepositReceipt | None:
    """Best-effort receipt parse. Returns None for non-XML or empty bodies."""
    if not response.content:
        return None
    content_type = response.headers.get("Content-Type", "")
    if "xml" not in content_type and "atom" not in content_type:
        return None
    try:
        return parse_receipt(response.content)
    except etree.XMLSyntaxError:
        return None


def deposit(
    package_path: Path,
    collection_url: str,
    username: str,
    password: str,
    package_format: str,
    sword_version: str = "v2",
    on_behalf_of: str | None = None,
    in_progress: bool = False,
    timeout: int = 60,
) -> DepositResult:
    """POST ``package_path`` to ``collection_url`` and return the result.

    ``sword_version`` is ``"v1"`` or ``"v2"``. Header handling differs:

    - v2 always sends ``In-Progress`` (true or false).
    - v1 only sends ``In-Progress: true`` to route to a workflow inbox;
      otherwise the header is omitted, since v1 servers (notably older
      EPrints) treat any presence of the header as "still in progress".

    Raises ``ValueError`` if the version/format combination is invalid.
    """
    from sword_packager.packagers import validate_version_format
    validate_version_format(sword_version, package_format)

    fmt = PACKAGE_FORMATS[package_format]
    headers = {
        "Content-Type": fmt["content_type"],
        "Content-Disposition": f"filename={package_path.name}",
        "X-Packaging": fmt["packaging"],
        "X-No-Op": "false",
        "X-Verbose": "true",
    }
    if sword_version == "v2":
        headers["In-Progress"] = "true" if in_progress else "false"
    elif in_progress:
        # v1: only send the header when the caller actually wants the
        # workflow inbox; absence means "complete" on v1 servers.
        headers["In-Progress"] = "true"
    if on_behalf_of:
        headers["X-On-Behalf-Of"] = on_behalf_of

    with package_path.open("rb") as fh:
        response = requests.post(
            collection_url,
            data=fh,
            headers=headers,
            auth=(username, password),
            timeout=timeout,
        )

    receipt = _try_parse_receipt(response) if 200 <= response.status_code < 300 else None

    return DepositResult(
        package=package_path,
        status_code=response.status_code,
        location=response.headers.get("Location"),
        body=response.text,
        receipt=receipt,
    )


def fetch_statement(
    stmt_iri: str,
    username: str,
    password: str,
    timeout: int = 30,
) -> tuple[int, str, str | None]:
    """GET the Statement at ``stmt_iri``.

    Returns ``(status_code, body, content_type)``. The body is left as
    text because Statements may come back as Atom or RDF/XML and the
    caller decides how to render them.
    """
    response = requests.get(
        stmt_iri,
        auth=(username, password),
        timeout=timeout,
        headers={"Accept": "application/atom+xml;type=feed, application/rdf+xml"},
    )
    return response.status_code, response.text, response.headers.get("Content-Type")


def complete_deposit(
    se_iri: str,
    username: str,
    password: str,
    timeout: int = 30,
) -> DepositResult:
    """POST In-Progress: false to ``se_iri`` to leave the workflow inbox.

    Per SWORDv2 section 9.3, an empty POST with In-Progress: false flips
    an item from "still being deposited" to "complete". Servers vary on
    response codes; we accept any 2xx as success.
    """
    response = requests.post(
        se_iri,
        data=b"",
        headers={"In-Progress": "false", "Content-Length": "0"},
        auth=(username, password),
        timeout=timeout,
    )
    receipt = _try_parse_receipt(response) if 200 <= response.status_code < 300 else None
    return DepositResult(
        package=Path(""),
        status_code=response.status_code,
        location=response.headers.get("Location"),
        body=response.text,
        receipt=receipt,
    )


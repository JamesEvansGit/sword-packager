"""Parse SWORDv2 deposit receipts.

A SWORDv2 deposit returns an Atom entry containing the IRIs needed for
subsequent CRUD operations. The link relations we care about are:

    rel="edit"                                                  -> SE-IRI
    rel="edit-media"                                            -> EM-IRI (Atom feed)
    rel="edit-media" type="application/atom+xml;type=feed"      -> EM-IRI feed
    rel="http://purl.org/net/sword/terms/statement"             -> Stmt-IRI

References:
    SWORDv2 profile, section 10.2 "The Deposit Receipt"
    http://swordapp.github.io/SWORDv2-Profile/SWORDv2Profile.html
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

ATOM_NS = "http://www.w3.org/2005/Atom"
SWORD_TERMS = "http://purl.org/net/sword/terms/"
SWORD_STATEMENT_REL = f"{SWORD_TERMS}statement"


@dataclass
class DepositReceipt:
    """Parsed SWORDv2 deposit receipt."""

    se_iri: str | None              # rel="edit"
    em_iri: str | None              # rel="edit-media"
    stmt_iri: str | None            # rel="http://purl.org/net/sword/terms/statement"
    atom_id: str | None             # <atom:id>
    title: str | None               # <atom:title>
    treatment: str | None           # <sword:treatment> (server's processing summary)
    raw_xml: bytes                  # original payload, for debugging


def parse_receipt(xml: bytes) -> DepositReceipt:
    """Parse a deposit-receipt Atom entry into a DepositReceipt.

    Missing elements come back as None rather than raising, since some
    servers (notably older EPrints) omit optional bits like the
    Statement IRI.

    Raises ``etree.XMLSyntaxError`` if ``xml`` isn't well-formed XML.
    """
    root = etree.fromstring(xml)

    se_iri: str | None = None
    em_iri: str | None = None
    em_iri_is_feed: bool = False
    stmt_iri: str | None = None

    for link in root.findall(f"{{{ATOM_NS}}}link"):
        rel = link.get("rel")
        href = link.get("href")
        if not rel or not href:
            continue
        if rel == "edit" and se_iri is None:
            se_iri = href
        elif rel == "edit-media":
            # Prefer the non-feed edit-media link (the IRI for POSTing
            # additional bitstreams) over the feed-typed one. Take the
            # feed only if no non-feed alternative is present.
            link_type = link.get("type") or ""
            is_feed = "type=feed" in link_type
            if em_iri is None or (em_iri_is_feed and not is_feed):
                em_iri = href
                em_iri_is_feed = is_feed
        elif rel == SWORD_STATEMENT_REL and stmt_iri is None:
            stmt_iri = href

    atom_id_el = root.find(f"{{{ATOM_NS}}}id")
    title_el = root.find(f"{{{ATOM_NS}}}title")

    # sword:treatment uses the SWORD terms namespace, but servers vary
    # on which prefix they declare. Match by local-name to be safe.
    treatment: str | None = None
    for el in root.iter():
        tag = etree.QName(el).localname
        if tag == "treatment" and el.text:
            treatment = el.text.strip()
            break

    return DepositReceipt(
        se_iri=se_iri,
        em_iri=em_iri,
        stmt_iri=stmt_iri,
        atom_id=atom_id_el.text.strip() if atom_id_el is not None and atom_id_el.text else None,
        title=title_el.text.strip() if title_el is not None and title_el.text else None,
        treatment=treatment,
        raw_xml=xml,
    )

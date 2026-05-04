"""SWORD package builders for METS SIP, EPrints XML, and Atom entry formats."""

from sword_packager.packagers.atom import build_atom_package
from sword_packager.packagers.eprints import build_eprints_package
from sword_packager.packagers.mets import build_mets_package

__all__ = ["build_atom_package", "build_eprints_package", "build_mets_package"]


SWORD_VERSIONS = ("v1", "v2")


PACKAGE_FORMATS = {
    "mets": {
        "build": build_mets_package,
        "content_type": "application/zip",
        "packaging": "http://purl.org/net/sword-types/METSDSpaceSIP",
        "ext": ".zip",
        "versions": ("v1", "v2"),
    },
    "eprints": {
        "build": build_eprints_package,
        "content_type": "application/zip",
        "packaging": "http://eprints.org/ep2/data/2.0",
        "ext": ".zip",
        "versions": ("v1", "v2"),
    },
    "atom": {
        "build": build_atom_package,
        "content_type": "application/atom+xml;type=entry",
        "packaging": "http://purl.org/net/sword/package/SimpleZip",
        "ext": ".zip",
        "versions": ("v2",),
    },
}


def formats_for_version(version: str) -> list[str]:
    """Return the format names compatible with a given SWORD version."""
    return [name for name, fmt in PACKAGE_FORMATS.items() if version in fmt["versions"]]


def validate_version_format(version: str, package_format: str) -> None:
    """Raise ``ValueError`` if ``package_format`` isn't usable on ``version``."""
    if version not in SWORD_VERSIONS:
        raise ValueError(
            f"Unknown SWORD version {version!r}; expected one of {SWORD_VERSIONS}."
        )
    if package_format not in PACKAGE_FORMATS:
        raise ValueError(
            f"Unknown package format {package_format!r}; "
            f"expected one of {sorted(PACKAGE_FORMATS)}."
        )
    if version not in PACKAGE_FORMATS[package_format]["versions"]:
        raise ValueError(
            f"Format {package_format!r} is not supported on SWORD {version}. "
            f"Compatible formats for {version}: {formats_for_version(version)}."
        )


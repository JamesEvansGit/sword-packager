# SWORD Packager and Submission Tools for DSpace (and Eprints)

## May 2026 - Work in Prgress

** IMPORTANT NOTE: as of April 2026, this project is 'work in progress' v0.1.0 can submit a mets sword v1 package, but other aspects, particularly related to Sword v2 require bug fixes and improvements.**


## Purpose

- A Python tool that turns a CSV metadata file plus a directory of payload files (PDFs, datasets, etc.) into **SWORD v1.3 / v2** deposit packages, and optionally POSTs them to a SWORD endpoint.
- The Python project is managed using Poetry, with the aim of making it simpler to managea Pyython versioning and dependencies. 
- The created SWORD packages can be deposited to a repository system such as DSapce (and eventuially, EPrints).
- The deposit part of the script can be scheduled to specific date/time internals and/or other variable conditions.


## Who is this for?

- Anyone doing **batch deposits into institutional or research repositories** where filling in a web form record-by-record would be painfully slow. The sweet spot is tens to thousands of records whose metadata fits comfortably in a spreadsheet, headed to a SWORDv1.3 or v2 endpoint.
- Anyone wishing to use some form of automation in their submission system, but with less complexity than a full REST API approach. 
- Users who don't have full repository level Administrator rights to the repository, but need to make regular timed or conditional deposits to one or more repository collections. 

Typical users:

- **Repository managers and digital librarians** doing bulk ingest of legacy collections, retrospective digitisation projects, or migrating content between repositories.
- **Research data managers** helping researchers deposit datasets at the end of a grant — a folder of files plus a spreadsheet of descriptions is the natural input shape.
- **Open-access / scholarly communications teams** processing publisher batches into the institutional repository to satisfy funder mandates (REF, NIH, Plan S).
- **CRIS / RIMS administrators** bridging research information systems (Pure, Symplectic Elements, Converis) into a DSpace or EPrints repository.
- **Digital humanities and special collections curators** with a metadata spreadsheet and a folder of scanned PDFs or images.
- **Journal editors and publishers** routing article supplements into a Dataverse or DSpace collection on acceptance.
- **Researchers self-archiving large outputs** — say, hundreds of conference papers or field reports — into an institutional EPrints.
- **Developers** who want a working reference implementation to study when adding SWORD support to their own application.

## Who is this NOT for?

It is **not** the right tool for single-record deposits (the web UI is faster), for SWORDv3-only targets like Invenio/Zenodo, or for workflows that need controlled-vocabulary metadata (LCSH, MeSH, ORCID-linked authors) — the default Dublin Core crosswalk is intentionally simple.

## What this does

For each row in the CSV it builds one SWORD package containing:

- a metadata manifest (METS, EPrints XML, or Atom entry)
- the payload files referenced by that row

Each row becomes a separate zip, so you can deposit many records from a single batch.

## Supported package formats

| `--format` | SWORD version | Manifest         | `X-Packaging`                                      | Targets                                       |
| ---------- | ------------- | ---------------- | -------------------------------------------------- | --------------------------------------------- |
| `mets`     | v1.3 and v2   | METS XML + MODS  | `http://purl.org/net/sword-types/METSDSpaceSIP`    | DSpace (default crosswalk)                    |
| `eprints`  | v1.3 and v2   | EPrints 3 XML    | `http://eprints.org/ep2/data/2.0`                  | EPrints 3.x (default crosswalk)               |
| `atom`     | **v2 only**   | Atom + dcterms   | `http://purl.org/net/sword/package/SimpleZip`      | DSpace SWORDv2, Dataverse SWORD API           |

All three use the default Dublin Core crosswalk on the receiving side, so the same CSV works across targets.

## SWORD version compatibility

This tool implements **SWORD v1.3 and SWORD v2** deposit. Pick the format that matches your target server:

| Target                                       | Recommended `--format`                  |
| -------------------------------------------- | --------------------------------------- |
| EPrints 3.2 (SWORDv1.3 server)               | `eprints` or `mets`                     |
| EPrints 3.3+ (SWORDv2 server, default)       | any of the three                        |
| DSpace 5 / 6 / 7 (ships both v1 and v2)      | any; `mets` is the most reliably ingested |
| Dataverse (SWORD API)                        | `atom`                                  |
| Invenio / Zenodo (SWORDv3 only)              | **not supported** — see below           |

### What is NOT supported

- **SWORDv3.** The v3 spec dropped XML/AtomPub in favor of a JSON-based protocol (reference implementation in Invenio/Zenodo). None of the packagers here will work against a SWORDv3 endpoint.
- **SWORDv2 strict multipart deposit.** The `atom` builder produces a SimpleZip-style single POST. Most v2 servers accept this, but a server that strictly requires `multipart/related` (Atom entry + media as separate parts) won't. Extending `deposit.py` to add multipart support is straightforward.
- **CRUD operations.** No `PUT` (replace), `DELETE`, or container-level updates that SWORDv2 added on top of v1.3. This is deposit-only — one POST per record.

## Install

```bash
poetry install
```

## CSV format

Headers are case-insensitive and may use any of these prefixes for Dublin Core fields:

- `dc.title`, `dc.creator`, `dc.subject`, `dc.description`, `dc.date`, `dc.type`, `dc.identifier`, `dc.publisher`, `dc.contributor`, `dc.rights`, `dc.language`, `dc.relation`, `dc.source`, `dc.format`, `dc.coverage`
- `dcterms.X` (alias for `dc.X`)
- bare `title`, `creator`, etc.

Multi-value fields use **`||`** (double pipe) as separator. For example:

```
dc.creator
"Smith, Jane||Doe, John"
```

becomes two creators. Double-pipe was chosen so commas inside names (e.g. `"Family, Given"`) and semicolons inside abstracts don't collide with the separator.

Files are linked to a row via either column (or both):

- `filename` — single filename
- `files` — `||`-separated list

Example (`examples/metadata.csv`):

```csv
dc.title,dc.creator,dc.subject,dc.date,dc.type,files
"Climate Trends","Smith, Jane||Doe, John","climate||policy","2024-03-15","Report","report.pdf||appendix.pdf"
"Survey Data","Lee, Kim","transport","2023","Dataset","survey.csv"
```

Empty cells are simply skipped.

## Embargoes

You can mark records as embargoed — i.e. only released after a future date — by adding an embargo column to the CSV. Any of these column headers work (they all mean the same thing internally):

- `embargo_until` (recommended, friendliest)
- `dcterms.available`
- `dc.available`
- `dc.date.available` (DSpace's qualified-DC convention)

The value must be ISO 8601: `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or a full datetime like `2026-12-31T23:59:59Z`. Anything else is rejected up front rather than being silently mishandled by the repository.

```csv
dc.title,dc.creator,embargo_until,files
"Forthcoming Article","Smith, A","2026-12-31","paper.pdf"
"Already Public","Lee, B","","data.csv"
```

### What gets written

Each packager translates the embargo into the field its target repository reads:

| Format    | Where the embargo lands in the package XML                                                          |
| --------- | --------------------------------------------------------------------------------------------------- |
| `mets`    | `<mods:dateOther type="available">` (crosswalks to `dc.date.available`) plus `<mods:accessCondition type="restrictionOnAccess">` |
| `eprints` | `<embargo_date>` on each `<document>`, with `<security>staffonly</security>` during the window      |
| `atom`    | `<dcterms:available>` in the Atom entry                                                              |

When at least one record has an embargo date, the CLI prints a yellow warning explaining what was written and who's responsible for enforcement.

### ⚠️ Enforcement is the repository's responsibility

**Writing an embargo date into a package does not, on its own, prevent access to the file.** The receiving repository has to be configured to honour it:

- **DSpace**: the EmbargoSetter and EmbargoLifter plugins must be enabled in `dspace.cfg`, and the embargo lifter has to run on a schedule (usually a cron job invoking `dspace embargo-lifter`). On a fresh install these are sometimes off by default.
- **EPrints**: the default workflow honours `<embargo_date>` on documents when present; some custom workflows ignore it. We additionally set `<security>staffonly</security>` so that misconfigured installs default to closed rather than open during the embargo window.
- **Dataverse**: dataset embargoes need to be enabled at the collection level by an administrator; the SWORD endpoint passes `dcterms:available` through but doesn't enforce it on its own.

**Verify with your repository administrator that embargoes are actually enforced before relying on them.** A good test is to deposit a record with a near-future embargo date, log out, and check that the file is genuinely inaccessible to anonymous users until the date passes.

## Repository account permissions

A valid username and password are not, on their own, enough to deposit. The submitting account must also have the right **role** in the target repository, granted to it by a repository administrator. Authentication failures from missing roles look identical to wrong-password errors at the SWORD level (typically `401 Unauthorized` or `403 Forbidden`), so it's worth confirming the account is set up correctly *before* blaming the credentials.

The exact requirements differ by repository:

### DSpace 7 / 8

For SWORDv2 deposit into a specific collection, the account typically needs **all** of:

- A user account in DSpace (created via the admin UI or LDAP/Shibboleth).
- **Submit** permission on the target collection — added via *Edit collection → Authorizations → ADD policy → Action: ADD*. Without this, deposits fail with `403`.
- For deposits that should **bypass the collection's review workflow** (so items go straight to archived rather than landing in a reviewer's inbox), the account also needs to be a **collection administrator** for that collection — added via *Edit collection → Assign roles → Administrators*. Without this role, items still deposit successfully but end up in the workflow queue regardless of the `In-Progress: false` header you send.
- For mediated deposit (`--on-behalf-of`), the account needs to be in the configured **mediated deposit group** (`mediated.deposit.group` in `sword2-server.cfg`) and the on-behalf-of user must exist in DSpace.

The `swordv2-server.cfg` file controls which packagers are accepted; if a package format you're sending isn't listed there, deposits fail even with full permissions.

### DSpace 5 / 6 (legacy SWORDv2)

Same shape as DSpace 7 — submit permission on the collection plus collection-admin to bypass the workflow — but the configuration files are `dspace.cfg` and `sword2.cfg` respectively.

### EPrints 3.x

- The account must be a registered EPrints user with a role that allows deposit. Out of the box the **user** role can deposit (items land in the user's inbox); the **editor** role is needed for items to enter live workflow stages.
- For mediated deposit (`X-On-Behalf-Of`), the submitting account must have the `editor` or `admin` role; an ordinary `user` cannot deposit on behalf of someone else.
- If your repository uses **subjects** as a controlled vocabulary, the account needs view permission on the subject tree being referenced.
- SWORD itself is enabled by default in EPrints 3.2+, but a site administrator may have restricted it to specific user roles via `cfg.d/plugins.pl` or `archives/<archive>/cfg/cfg.d/sword.pl`.

### Dataverse

- The account uses an **API token** (which Dataverse maps to a SWORDv1-style HTTP Basic auth with the token as the username and an empty password — pass the token as `--username` here).
- The account must have the **Curator** or **Contributor** role on the target dataverse (collection) to create datasets.
- To **publish** a deposited dataset rather than leaving it in draft state, the account additionally needs the **Curator** or **Admin** role; Contributors can deposit but not publish.
- File embargoes specifically require the dataverse to have file embargoes enabled at the collection level by an administrator.

### Quick verification checklist

Before scheduling a production run, have your repository administrator confirm:

1. The submitting account exists and can log in to the repository's web UI.
2. The account has at least submit/contributor permission on the target collection.
3. The account has the elevated role (collection admin / curator / editor) required for items to bypass the workflow if that's what you want.
4. The account can see and POST to the SWORD service document URL with its credentials (a quick `curl -u user:pass <servicedocument-url>` is the fastest test).
5. The collection accepts the package format(s) you intend to send.

A deposit that returns `201 Created` but never appears in the public listing is almost always a **workflow-permission** issue — the item deposited fine but is sitting in someone's review queue. Use `sword-packager status metadata.csv --row N --username ...` to fetch the Statement IRI and see exactly where it landed.

## Usage

### Tab completion

Enable shell tab completion once after installing:

```bash
poetry run sword-packager --install-completion
```

Restart your shell (or `source ~/.bashrc`) afterwards. Subcommands, flags, and option values will then complete on Tab.

### List supported formats

```bash
poetry run sword-packager list-formats
```

### Choose your SWORD version

The first thing the `build` and `deposit` commands need is the SWORD protocol version your target server speaks:

- **v1** — older endpoints, deposit-only (EPrints 3.2, DSpace `sword/`).
- **v2** — newer endpoints with deposit receipts and CRUD operations (EPrints 3.3+, DSpace `swordv2/`, Dataverse).

Pass it with `--sword-version v1` (or `v2`). If you omit the flag and you're at an interactive terminal, the tool prompts you. In a pipe or CI environment, it errors out rather than guessing — better than silently picking the wrong protocol.

The chosen version constrains the package format: `atom` is v2-only, while `mets` and `eprints` work on both. If you pick an incompatible combination on the command line, the tool fails fast and tells you which formats are compatible with the version you chose.

### Build packages locally (no deposit)

You can supply everything on one line or run the command with no arguments and be stepped through each input interactively — whichever suits you.

**Interactive (guided) mode — recommended for new users:**

```bash
poetry run sword-packager build
```

The tool will prompt for the CSV path, files directory, output directory, SWORD version, and package format in sequence.

**Non-interactive (scripted) mode:**

```bash
poetry run sword-packager build \
    metadata.csv ./files ./out \
    --sword-version v2 \
    --format mets
```

Both modes produce the same result: one zip per CSV row written into the output directory, named like `row002-climate-trends.zip`.

### Build and deposit

Again, interactive or fully specified — your choice.

**Interactive (guided) mode — recommended for new users:**

```bash
poetry run sword-packager deposit
```

You will be prompted in order for: CSV path, files directory, output directory, collection URL, username, password, SWORD version, and package format.

**Non-interactive (scripted) mode:**

```bash
poetry run sword-packager deposit \
    metadata.csv ./files ./out \
    --sword-version v2 \
    --format mets \
    --collection-url https://demo.dspace.org/server/swordv2/collection/123456789/5 \
    --username alice
```

You'll be prompted for the password if `--password` is not supplied. Useful flags:

- `--sword-version v1|v2` — required (or prompted at a TTY); see above
- `--in-progress` — mark the deposit as still in progress (lands in EPrints inbox / DSpace workflow rather than going live)
- `--on-behalf-of <email>` — mediated deposit
- `--dry-run` — build packages but skip the HTTP POST
- `--state-file <path>` — where to record the deposit IRIs (default `~/.sword-packager/state.db`)

After a successful **v2** deposit, the parsed deposit receipt — including the SE-IRI, EM-IRI, and Statement IRI — is saved to a small SQLite database. The `status` and `complete` commands use that to talk to the server about specific items later. **v1** servers don't return deposit receipts in the same way, so `status` and `complete` aren't useful against them.

> **Getting `401 Unauthorized` or `403 Forbidden`?** The credentials may be valid but the account may lack the right *role* on the target collection. See [Repository account permissions](#repository-account-permissions) above for the per-system requirements.

### Inspect deposit state (SWORDv2)

```bash
# Table of every recorded deposit for this CSV
poetry run sword-packager status metadata.csv

# Drill into row 5 and fetch the live Statement from the server
poetry run sword-packager status metadata.csv --row 5 \
    --username alice --password secret
```

The first form reads only the local state DB and shows what each row's last HTTP status was, when it happened, and the SE-IRI on file. The second form additionally GETs the Statement IRI, which is the only authoritative way to confirm an item went live (vs. sitting in a workflow inbox or being silently rejected).

### Mark a deposit complete

If you deposited with `--in-progress`, the item is in the workflow inbox. Move it out by POSTing `In-Progress: false` to its SE-IRI:

```bash
poetry run sword-packager complete metadata.csv 5 --username alice
```

This is the only Phase-1 CRUD command that mutates server state. Replace, add-file, delete, and full sync are deliberately not implemented yet — see the SWORDv2 CRUD roadmap notes below.

### Run on a schedule (cron / systemd timers)

For unattended runs, two flags make the deposit command cron-safe:

- `--skip-already-deposited` — skip rows whose last attempt got a 2xx response (rows that previously failed are still retried)
- `--delay N` — wait `N` seconds between submissions to avoid hammering the repository (default `10`, set `0` to disable)

Quick example:

```bash
sword-packager deposit metadata.csv ./files ./out \
    --sword-version v2 --format mets \
    --collection-url https://repo.example.org/server/swordv2/collection/123456789/5 \
    --username "$SWORD_USER" --password "$SWORD_PASS" \
    --skip-already-deposited \
    --delay 10
```

For full setup (cron entries, systemd `.service` + `.timer` units, credential handling, log rotation, operational tips), see [`docs/cron.md`](docs/cron.md).

### Find the collection URL

GET the SWORD service document with your credentials and look for `<atom:collection href="...">` entries. The path differs by DSpace version:

| DSpace version | Service document URL |
|---|---|
| DSpace 7 or later | `https://<domain>/server/swordv2/servicedocument` |
| DSpace 6 and earlier | `https://<domain>/swordv2/servicedocument` |

> **DSpace 7+ note:** all REST and SWORD endpoints moved under `/server/` in DSpace 7. Omitting it returns a 404.

```bash
# DSpace 7 or later — SWORD v2
curl -u alice:secret https://demo.dspace.org/server/swordv2/servicedocument

# DSpace 6 and earlier — SWORD v2
curl -u alice:secret https://demo.dspace.org/swordv2/servicedocument

# DSpace 7 or later — SWORD v1
curl -u alice:secret https://demo.dspace.org/server/dspace-sword/sword/servicedocument

# EPrints
curl -u alice:secret https://example.edu/sword-app/servicedocument
```

The `href` on each `<collection>` element is the value to pass to `--collection-url`. Collection URLs follow the same version-specific pattern:

| DSpace version | SWORD v2 collection URL |
|---|---|
| DSpace 7 or later | `https://<domain>/server/swordv2/collection/<handle>` |
| DSpace 6 and earlier | `https://<domain>/swordv2/collection/<handle>` |

## Layout of a built package

### METS SIP (`--format mets`)

```
mets.xml             # METS with a MODS dmdSec, fileSec, structMap
report.pdf
appendix.pdf
```

`mets.xml` includes MD5 checksums and sizes for each bitstream. DSpace's `SwordMETSIngester` picks this up and feeds the MODS through the standard MODS-to-DC crosswalk.

### EPrints (`--format eprints`)

```
eprints.xml          # <eprints xmlns="http://eprints.org/ep2/data/2.0">
report.pdf
appendix.pdf
```

The XML uses the EPrints 3 import format, with `<documents>/<document>/<files>` referencing each payload.

### Atom + SimpleZip (`--format atom`)

```
atom.xml             # Atom entry with dcterms:* metadata
report.pdf
appendix.pdf
```

The deposit client posts the whole zip with `Content-Type: application/zip` and `X-Packaging: http://purl.org/net/sword/package/SimpleZip`. SWORDv2 servers (DSpace, Dataverse) extract the entry from `atom.xml` if needed.

## Run the tests

```bash
poetry run pytest
```

## Project layout

```
sword-packager/
├── pyproject.toml
├── README.md
├── docs/
│   └── cron.md             # Running on a schedule (cron / systemd timers)
├── examples/
│   └── metadata.csv
├── sword_packager/
│   ├── __init__.py
│   ├── cli.py              # Typer CLI: build / deposit / status / complete / list-formats
│   ├── csv_reader.py       # CSV → Record objects
│   ├── deposit.py          # SWORD HTTP client (deposit + Statement fetch + complete)
│   ├── receipt.py          # Parse SWORDv2 deposit receipts (SE-IRI, EM-IRI, Stmt-IRI)
│   ├── state.py            # SQLite-backed store of deposit IRIs for CRUD ops
│   └── packagers/
│       ├── __init__.py     # Format registry + version compatibility
│       ├── atom.py         # SWORDv2 Atom + SimpleZip
│       ├── eprints.py      # EPrints 3 XML
│       └── mets.py         # DSpace METS SIP
└── tests/
    ├── test_packager.py    # CSV parsing and package builders
    ├── test_phase1.py      # Receipt parser, state store, deposit-with-state
    ├── test_versions.py    # SWORD v1/v2 version selection and validation
    ├── test_cron.py        # --delay and --skip-already-deposited
    └── test_embargo.py     # Embargo dates across CSV and all three packagers
```

## Notes and limitations

- Authentication is HTTP Basic. SWORD servers commonly require it over HTTPS — make sure your collection URL is `https://`.
- The METS builder uses a fixed `CREATEDATE`; replace it with `datetime.now(timezone.utc).isoformat()` if your repository validates timestamps.
- Multi-value DC subjects map to free-text keywords on the EPrints side. Controlled-vocabulary IDs (e.g. LCSH) need a custom crosswalk.

For SWORD version coverage and unsupported features (SWORDv3, multipart deposit, CRUD), see [SWORD version compatibility](#sword-version-compatibility) above.

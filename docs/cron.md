# Running sword-packager on a schedule

This guide shows how to run `sword-packager deposit` unattended from system cron or systemd timers, so that new rows added to a CSV get deposited automatically.

## The two flags that make scheduled runs safe

```bash
sword-packager deposit metadata.csv ./files ./out \
    --sword-version v2 --format mets \
    --collection-url https://repo.example.org/swordv2/collection/abc \
    --username "$SWORD_USER" --password "$SWORD_PASS" \
    --skip-already-deposited \
    --delay 10
```

- **`--skip-already-deposited`** — reads the state DB and skips any row whose last attempt got a 2xx response. Without this, a nightly cron job would re-deposit every row and create duplicates on the server. Rows that previously failed (4xx, 5xx, network errors) are still retried.
- **`--delay 10`** — wait 10 seconds between submissions. The delay only happens *between* records, not before the first or after the last, so a single-record run still completes immediately. Default is 10s; pass `--delay 0` to disable. Tune this to your repository's rate limits.

These two together give you "deposit anything new, gently" — exactly what an unattended pipeline needs.

## Example: cron

Put credentials in a file readable only by the service user (don't bake them into the crontab):

```bash
# /etc/sword-packager/env
SWORD_USER=deposit-bot
SWORD_PASS=correct-horse-battery-staple
SWORD_URL=https://repo.example.org/swordv2/collection/abc-123
```

```bash
sudo chown swordsvc:swordsvc /etc/sword-packager/env
sudo chmod 600 /etc/sword-packager/env
```

A wrapper script that loads the env and runs the deposit:

```bash
#!/usr/bin/env bash
# /usr/local/bin/sword-deposit-nightly
set -euo pipefail

set -a
. /etc/sword-packager/env
set +a

cd /var/lib/sword-packager
exec /usr/local/bin/poetry run sword-packager deposit \
    /var/lib/sword-packager/metadata.csv \
    /var/lib/sword-packager/files \
    /var/lib/sword-packager/out \
    --sword-version v2 --format mets \
    --collection-url "$SWORD_URL" \
    --username "$SWORD_USER" --password "$SWORD_PASS" \
    --state-file /var/lib/sword-packager/state.db \
    --skip-already-deposited \
    --delay 10
```

```bash
sudo chmod +x /usr/local/bin/sword-deposit-nightly
```

A crontab entry to run it nightly at 02:00, logging to a dated file:

```cron
# /etc/cron.d/sword-packager
SHELL=/bin/bash
0 2 * * *  swordsvc  /usr/local/bin/sword-deposit-nightly >> /var/log/sword-packager/$(date +\%Y-\%m-\%d).log 2>&1
```

Make sure the log directory exists and is writable:

```bash
sudo install -d -o swordsvc -g swordsvc /var/log/sword-packager
```

## Example: systemd timer

For distros using systemd, a service + timer is cleaner than cron and gives you `journalctl` for free.

`/etc/systemd/system/sword-packager.service`:

```ini
[Unit]
Description=Deposit new rows to the SWORD repository
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=swordsvc
Group=swordsvc
EnvironmentFile=/etc/sword-packager/env
WorkingDirectory=/var/lib/sword-packager
ExecStart=/usr/local/bin/poetry run sword-packager deposit \
    /var/lib/sword-packager/metadata.csv \
    /var/lib/sword-packager/files \
    /var/lib/sword-packager/out \
    --sword-version v2 --format mets \
    --collection-url ${SWORD_URL} \
    --username ${SWORD_USER} --password ${SWORD_PASS} \
    --state-file /var/lib/sword-packager/state.db \
    --skip-already-deposited \
    --delay 10

# Hardening
ProtectSystem=strict
ReadWritePaths=/var/lib/sword-packager
PrivateTmp=true
NoNewPrivileges=true
```

`/etc/systemd/system/sword-packager.timer`:

```ini
[Unit]
Description=Nightly SWORD deposit run

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true
RandomizedDelaySec=15m

[Install]
WantedBy=timers.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sword-packager.timer
sudo systemctl list-timers sword-packager.timer
```

Run it once on demand to verify it works:

```bash
sudo systemctl start sword-packager.service
sudo journalctl -u sword-packager.service -e
```

`Persistent=true` means a missed run (machine off, etc.) will fire as soon as the system is back online. `RandomizedDelaySec=15m` smears load if you have many machines hitting the same repository on the same schedule.

## Operational tips

- **Test first with `--dry-run`** to confirm packages build without actually depositing.
- **Log rotation**: cron logs grow; use `logrotate` or the dated-filename pattern above.
- **State DB backups**: `~/.sword-packager/state.db` (or wherever you point `--state-file`) is the only record linking your CSV rows to repository IRIs. Back it up with the rest of your config.
- **CSV updates**: when you edit the CSV to add new rows, `--skip-already-deposited` ignores existing rows by row number, so adding rows at the bottom is safe. Reordering rows or inserting in the middle would re-deposit everything below the change — append-only is the safest editing pattern for scheduled runs.
- **Failures**: cron will email the user named in the crontab on stderr output; systemd surfaces failures in `systemctl status`. Either way, monitor the exit code (non-zero means at least one row failed).
- **First-run safety**: the very first scheduled run will deposit *every* row in the CSV. If you don't want that, run it once manually with `--dry-run`, review the count, then run for real.

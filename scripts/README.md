# Rainfall sync (Pi → VPS)

The Pi has no persistent internet. A VPS elsewhere fetches BMKG rainfall and
exposes it over HTTP. This script tries to pull that cache when connectivity
happens to exist. Failed attempts are normal — do not treat them as incidents.

Set on the Pi (systemd Environment or `.env` loaded by your process manager):

- `VPS_RAINFALL_URL` — required for a real fetch
- `VPS_RAINFALL_API_KEY` — optional Bearer token
- `RAINFALL_SYNC_TIMEOUT_SECONDS` — default 8
- `RAINFALL_SYNC_INTERVAL_SECONDS` — default 300 (cron period only; this script does not loop)

One-shot (manual / cron):

```bash
cd /path/to/kja-system
venv/bin/python scripts/sync_rainfall.py
```

Cron every 5 minutes (matches the 300s default). Missing internet just logs a
one-liner and exits 0:

```cron
*/5 * * * * cd /path/to/kja-system && venv/bin/python scripts/sync_rainfall.py >> logs/rainfall_sync.log 2>&1
```

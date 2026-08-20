# monitor_lfpb

Automated weather monitor for **LFPB (Paris/Le Bourget)**, lat `48.9694` lon `2.4414`.

Runs on a GitHub Actions schedule (02:03 / 08:03 / 14:03 / 20:03 UTC — ~3 min
after each 00/06/12/18Z model cycle) and on manual dispatch. Each run:

- Fetches Open-Meteo daily `temperature_2m_max` from 6 models: `ecmwf_ifs025`,
  `gfs_seamless`, `icon_seamless`, `meteofrance_seamless`, `ukmo_seamless`,
  `gem_seamless`.
- Fetches the latest TAF and METAR for LFPB from aviationweather.gov.
- Fetches the latest real-time observation for the Le Bourget station
  (`95088001`, WMO 07150) from Meteo-France's public Observation API.
- Diffs everything against the previous run (`data/state.json`) and writes:
  - `data/latest_report.md` — human-readable report
  - `data/history.jsonl` — one JSON line per run (append-only log)
  - the GitHub Actions job summary

## Setup

The Meteo-France Observation API requires an API key. Add it as a repository
secret **before** the first scheduled run:

1. Repo → **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `METEOFRANCE_API_TOKEN`
3. Value: your Meteo-France "Donnees Publiques" API key (Observation API v2)

Without the secret, the script still runs — it just skips the Meteo-France
section and notes the token is missing.

## Manual run

Actions tab → **LFPB weather monitor** → **Run workflow**.

Or locally:

```bash
export METEOFRANCE_API_TOKEN=your_token_here   # optional
python monitor_lfpb.py
```

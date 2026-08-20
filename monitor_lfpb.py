#!/usr/bin/env python3
"""LFPB (Paris/Le Bourget) weather monitor.

Pulls Open-Meteo multi-model forecasts, aviationweather.gov TAF/METAR, and
Meteo-France real-time station observations; diffs against the previous run
stored in data/state.json; writes a report to data/latest_report.md,
data/history.jsonl, and (when running in GitHub Actions) the job summary.
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

LAT, LON = 48.9694, 2.4414
ICAO = "LFPB"
METEOFRANCE_STATION_ID = "95088001"  # Le Bourget (WMO 07150)
MODELS = [
    "ecmwf_ifs025",
    "gfs_seamless",
    "icon_seamless",
    "meteofrance_seamless",
    "ukmo_seamless",
    "gem_seamless",
]

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.jsonl")
REPORT_PATH = os.path.join(DATA_DIR, "latest_report.md")


def http_get_json(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_open_meteo():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}&daily=temperature_2m_max"
        f"&timezone=UTC&forecast_days=2&models={','.join(MODELS)}"
    )
    data = http_get_json(url)
    daily = data["daily"]
    today = daily["time"][0]
    return {
        model: daily[f"temperature_2m_max_{model}"][0]
        for model in MODELS
    }, today


def fetch_taf():
    url = f"https://aviationweather.gov/api/data/taf?ids={ICAO}&format=json"
    data = http_get_json(url)
    if not data:
        return None
    return data[0]


def fetch_metar():
    url = f"https://aviationweather.gov/api/data/metar?ids={ICAO}&format=json&hours=1"
    data = http_get_json(url)
    if not data:
        return None
    return data[0]


def fetch_meteofrance_obs(token):
    if not token:
        return None
    url = (
        "https://public-api.meteofrance.fr/public/DPObs/v2/station/infrahoraire-6m"
        f"?id_station={METEOFRANCE_STATION_ID}&format=json"
    )
    try:
        data = http_get_json(url, headers={"apikey": token})
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    if not data:
        return None
    obs = data[0]
    if obs.get("t") is not None:
        obs["t_celsius"] = round(obs["t"] - 273.15, 1)
    return obs


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def append_history(entry):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def build_report(prev, models, forecast_day, taf, metar, mf_obs, run_time):
    lines = []
    lines.append(f"# LFPB weather report — {run_time.isoformat()}")
    lines.append("")
    lines.append(f"## Open-Meteo daily max ({forecast_day})")
    lines.append("")
    lines.append("| Model | Prev (°C) | Now (°C) | Delta |")
    lines.append("|---|---|---|---|")
    prev_models = (prev or {}).get("models", {})
    for model in MODELS:
        now_v = models[model]
        prev_v = prev_models.get(model)
        if prev_v is None:
            delta_str = "n/a"
        else:
            delta = round(now_v - prev_v, 1)
            sign = "+" if delta > 0 else ""
            delta_str = f"{sign}{delta}"
        prev_str = f"{prev_v}" if prev_v is not None else "n/a"
        lines.append(f"| {model} | {prev_str} | {now_v} | {delta_str} |")

    values = list(models.values())
    lines.append("")
    lines.append(
        f"Consensus range: **{min(values):.1f}–{max(values):.1f}°C** "
        f"(mean {sum(values)/len(values):.1f}°C)"
    )

    lines.append("")
    lines.append("## TAF")
    prev_taf_raw = (prev or {}).get("taf_raw")
    if taf:
        raw = taf.get("rawTAF", "")
        lines.append(f"Issued: {taf.get('issueTime')}")
        lines.append("```")
        lines.append(raw)
        lines.append("```")
        if prev_taf_raw and prev_taf_raw != raw:
            lines.append("")
            lines.append("**TAF changed since last run.**")
            lines.append("Previous:")
            lines.append("```")
            lines.append(prev_taf_raw)
            lines.append("```")
        elif prev_taf_raw:
            lines.append("")
            lines.append("No change since last run.")
    else:
        lines.append("No TAF returned.")

    lines.append("")
    lines.append("## METAR (latest)")
    if metar:
        lines.append(f"`{metar.get('rawOb', '')}`")
    else:
        lines.append("No METAR returned.")

    lines.append("")
    lines.append("## Meteo-France station observation (Le Bourget, 95088001)")
    if mf_obs and "error" not in mf_obs:
        t_c = mf_obs.get("t_celsius")
        lines.append(f"Validity: {mf_obs.get('validity_time')}")
        lines.append(f"Temp: {t_c}°C, Humidity: {mf_obs.get('u')}%, "
                      f"Wind: {mf_obs.get('dd')}°/{mf_obs.get('ff')} m/s")
    elif mf_obs and "error" in mf_obs:
        lines.append(f"Error fetching observation: {mf_obs['error']}")
    else:
        lines.append("METEOFRANCE_API_TOKEN not set — skipped.")

    return "\n".join(lines) + "\n"


def main():
    run_time = datetime.now(timezone.utc)
    token = os.environ.get("METEOFRANCE_API_TOKEN")

    models, forecast_day = fetch_open_meteo()
    taf = fetch_taf()
    metar = fetch_metar()
    mf_obs = fetch_meteofrance_obs(token)

    prev = load_state()
    report = build_report(prev, models, forecast_day, taf, metar, mf_obs, run_time)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)

    new_state = {
        "run_time": run_time.isoformat(),
        "forecast_day": forecast_day,
        "models": models,
        "taf_raw": taf.get("rawTAF") if taf else None,
        "metar_raw": metar.get("rawOb") if metar else None,
    }
    save_state(new_state)
    append_history(new_state)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(report)

    print(report)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

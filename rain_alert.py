#!/usr/bin/env python3
"""Check Open-Meteo for near-term rain and push a ntfy.sh alert. Stdlib only."""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def log(data):
    print(json.dumps(data), flush=True)


def get_forecast(lat, lon):
    """Return ([(datetime_utc, precipitation_mm), ...], utc_offset_seconds, tz_abbreviation)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "minutely_15": "precipitation",
        "timezone": "auto",
        "forecast_days": 1,
    }
    url = f"{OPEN_METEO_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.load(resp)
    utc_offset = data.get("utc_offset_seconds", 0)
    tz_abbr = data.get("timezone_abbreviation", "UTC")
    times = data["minutely_15"]["time"]
    precip = data["minutely_15"]["precipitation"]
    slots = [
        (datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc) - timedelta(seconds=utc_offset), p)
        for t, p in zip(times, precip)
    ]
    return slots, utc_offset, tz_abbr


def find_rain(slots, lookahead_min, min_precip_mm, now):
    cutoff = now + timedelta(minutes=lookahead_min)
    for dt, precip in slots:
        if now <= dt <= cutoff and precip >= min_precip_mm:
            return dt, precip
    return None


def read_last_alert(state_file):
    try:
        return float(Path(state_file).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def write_last_alert(state_file, when):
    Path(state_file).write_text(str(when.timestamp()))


def send_ntfy(topic, message, title):
    headers = {"Title": title, "Tags": "cloud_with_rain"}
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status < 300


def main():
    lat = os.environ.get("LAT")
    lon = os.environ.get("LON")
    topic = os.environ.get("NTFY_TOPIC")
    if not lat or not lon or not topic:
        log({"error": "LAT, LON, and NTFY_TOPIC are required"})
        sys.exit(1)

    location_name = os.environ.get("LOCATION_NAME") or f"{lat}, {lon}"
    lookahead_min = float(os.environ.get("LOOKAHEAD_MIN", 45))
    min_precip_mm = float(os.environ.get("MIN_PRECIP_MM", 0.1))
    cooldown_hours = float(os.environ.get("COOLDOWN_HOURS", 3))
    state_file = os.path.expanduser(os.environ.get("STATE_FILE", "~/.rain-alert-last"))

    now = datetime.now(timezone.utc)

    try:
        slots, utc_offset, tz_abbr = get_forecast(lat, lon)
    except Exception as e:
        log({"error": f"forecast fetch failed: {e}"})
        return

    rain = find_rain(slots, lookahead_min, min_precip_mm, now)
    if not rain:
        log({"rain": False})
        return

    rain_time, precip = rain

    last_alert = read_last_alert(state_file)
    if last_alert and now.timestamp() - last_alert < cooldown_hours * 3600:
        log({"rain": True, "sent": False, "reason": "cooldown", "rain_time": rain_time.isoformat()})
        return

    minutes_away = round((rain_time - now).total_seconds() / 60)
    local_time = rain_time + timedelta(seconds=utc_offset)
    message = (
        f"Rain expected in {location_name} around {local_time.strftime('%H:%M')} {tz_abbr} "
        f"(in ~{minutes_away} min, {precip}mm). Cover your plants!"
    )

    try:
        send_ntfy(topic, message, title="Rain incoming")
    except Exception as e:
        log({"rain": True, "sent": False, "error": f"ntfy send failed: {e}"})
        return

    write_last_alert(state_file, now)
    log({"rain": True, "sent": True, "rain_time": rain_time.isoformat(), "precip_mm": precip})


if __name__ == "__main__":
    main()

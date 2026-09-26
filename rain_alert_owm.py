#!/usr/bin/env python3
"""Check OpenWeatherMap minute-by-minute forecast for near-term rain and push a ntfy.sh alert. Stdlib only."""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OWM_URL = "https://api.openweathermap.org/data/3.0/onecall"


def log(data):
    print(json.dumps(data), flush=True)


def get_forecast(lat, lon, api_key):
    """Return a list of (datetime_utc, precipitation_mm_per_h) minute slots."""
    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric",
        "exclude": "current,hourly,daily,alerts",
    }
    url = f"{OWM_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.load(resp)
    return [
        (datetime.fromtimestamp(m["dt"], tz=timezone.utc), m.get("precipitation", 0.0))
        for m in data.get("minutely", [])
    ]


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
    api_key = os.environ.get("OWM_API_KEY")
    if not lat or not lon or not topic or not api_key:
        log({"error": "LAT, LON, NTFY_TOPIC, and OWM_API_KEY are required"})
        sys.exit(1)

    lookahead_min = min(float(os.environ.get("LOOKAHEAD_MIN", 45)), 60)
    min_precip_mm = float(os.environ.get("MIN_PRECIP_MM", 0.3))
    cooldown_hours = float(os.environ.get("COOLDOWN_HOURS", 3))
    state_file = os.path.expanduser(os.environ.get("STATE_FILE", "~/.rain-alert-owm-last"))

    now = datetime.now(timezone.utc)

    try:
        slots = get_forecast(lat, lon, api_key)
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
    message = f"Rain expected around {rain_time.strftime('%H:%M UTC')} (in ~{minutes_away} min, {precip}mm/h). Cover your plants!"

    try:
        send_ntfy(topic, message, title="Rain incoming")
    except Exception as e:
        log({"rain": True, "sent": False, "error": f"ntfy send failed: {e}"})
        return

    write_last_alert(state_file, now)
    log({"rain": True, "sent": True, "rain_time": rain_time.isoformat(), "precip_mm_h": precip})


if __name__ == "__main__":
    main()

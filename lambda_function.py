"""AWS Lambda version of the rain alert check: Open-Meteo forecast, ntfy.sh alert, state in SSM Parameter Store."""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

ssm = boto3.client("ssm")


def get_forecast(lat, lon):
    """Return a list of (datetime_utc, precipitation_mm) 15-minute slots."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "minutely_15": "precipitation",
        "timezone": "UTC",
        "forecast_days": 1,
    }
    url = f"{OPEN_METEO_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.load(resp)
    times = data["minutely_15"]["time"]
    precip = data["minutely_15"]["precipitation"]
    return [
        (datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc), p)
        for t, p in zip(times, precip)
    ]


def find_rain(slots, lookahead_min, min_precip_mm, now):
    cutoff = now + timedelta(minutes=lookahead_min)
    for dt, precip in slots:
        if now <= dt <= cutoff and precip >= min_precip_mm:
            return dt, precip
    return None


def read_last_alert(param_name):
    try:
        resp = ssm.get_parameter(Name=param_name)
        return float(resp["Parameter"]["Value"])
    except ssm.exceptions.ParameterNotFound:
        return None


def write_last_alert(param_name, when):
    ssm.put_parameter(Name=param_name, Value=str(when.timestamp()), Type="String", Overwrite=True)


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


def lambda_handler(event, context):
    lat = os.environ["LAT"]
    lon = os.environ["LON"]
    topic = os.environ["NTFY_TOPIC"]
    lookahead_min = float(os.environ.get("LOOKAHEAD_MIN", 45))
    min_precip_mm = float(os.environ.get("MIN_PRECIP_MM", 0.1))
    cooldown_hours = float(os.environ.get("COOLDOWN_HOURS", 3))
    param_name = os.environ.get("SSM_PARAM_NAME", "/rain-alert/last")

    now = datetime.now(timezone.utc)

    try:
        slots = get_forecast(lat, lon)
    except Exception as e:
        result = {"error": f"forecast fetch failed: {e}"}
        print(json.dumps(result))
        return result

    rain = find_rain(slots, lookahead_min, min_precip_mm, now)
    if not rain:
        result = {"rain": False}
        print(json.dumps(result))
        return result

    rain_time, precip = rain

    last_alert = read_last_alert(param_name)
    if last_alert and now.timestamp() - last_alert < cooldown_hours * 3600:
        result = {"rain": True, "sent": False, "reason": "cooldown", "rain_time": rain_time.isoformat()}
        print(json.dumps(result))
        return result

    minutes_away = round((rain_time - now).total_seconds() / 60)
    message = f"Rain expected around {rain_time.strftime('%H:%M UTC')} (in ~{minutes_away} min, {precip}mm). Cover your plants!"

    try:
        send_ntfy(topic, message, title="Rain incoming")
    except Exception as e:
        result = {"rain": True, "sent": False, "error": f"ntfy send failed: {e}"}
        print(json.dumps(result))
        return result

    write_last_alert(param_name, now)
    result = {"rain": True, "sent": True, "rain_time": rain_time.isoformat(), "precip_mm": precip}
    print(json.dumps(result))
    return result

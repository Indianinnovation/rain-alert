# Rain Alert: Get Notified Before Rain Hits Your Plants

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/Indianinnovation/rain-alert)](https://github.com/Indianinnovation/rain-alert/commits/main)
[![Open Issues](https://img.shields.io/github/issues/Indianinnovation/rain-alert)](https://github.com/Indianinnovation/rain-alert/issues)
[![Open PRs](https://img.shields.io/github/issues-pr/Indianinnovation/rain-alert)](https://github.com/Indianinnovation/rain-alert/pulls)

A small Python service that checks a short-range rain forecast every 5 minutes and sends a push notification to your phone roughly 30–60 minutes before rain is expected, so you have time to cover or move your plants.

It has no external Python dependencies and costs nothing for personal use.

---

## How It Works

```
 every 5 min           forecast API                     ntfy.sh
 ┌──────────┐   GET   ┌──────────────────┐   rain?   ┌────────────┐   push   ┌─────────┐
 │ cron /   │ ──────► │ Open-Meteo  or   │ ────────► │ alert if   │ ───────► │  phone  │
 │ Lambda   │         │ OpenWeatherMap   │           │ not in     │          │         │
 └──────────┘         └──────────────────┘           │ cooldown   │          └─────────┘
                                                      └────────────┘
```

1. The script fetches the precipitation forecast for your location.
2. It looks for the first time slot within the lookahead window where rain meets the threshold.
3. If rain is found and no alert has been sent in the last few hours, it posts a message to your ntfy topic.
4. It records the alert time so a long storm doesn't send repeated notifications.

---

## Files

| File | Purpose |
|---|---|
| `rain_alert.py` | Local server version using **Open-Meteo** (15-minute data). Best for North America and Central Europe. |
| `rain_alert_owm.py` | Local server version using **OpenWeatherMap** (minute-by-minute data for the next hour). Better for other regions, such as Brazil. |
| `rain-alert.env` | Settings for `rain_alert.py`. |
| `rain-alert-owm.env` | Settings for `rain_alert_owm.py`, tuned for tropical regions. |
| `lambda_function.py` | AWS Lambda version (Open-Meteo), storing state in SSM Parameter Store. |
| `template.yaml` | AWS SAM template: function, 5-minute schedule, and IAM permissions. |

---

## Which Data Source Should I Use?

| Region | Recommended script | Why |
|---|---|---|
| USA, Canada | `rain_alert.py` | Open-Meteo uses NOAA's HRRR model, which provides true 15-minute forecasts. |
| Central Europe | `rain_alert.py` | Open-Meteo uses Germany's ICON-D2 high-resolution model. |
| Brazil, India, Africa, rest of the world | `rain_alert_owm.py` | Open-Meteo's 15-minute values are interpolated from hourly global models there; OpenWeatherMap offers a minute-by-minute forecast. |

**Accuracy caveat:** No forecast is perfect at a 30-minute range. Large rain bands are predicted well. Sudden afternoon thunderstorms, common in summer and in the tropics, can form in 15–30 minutes and are sometimes missed. For plants, a false alarm is cheap and a miss is costly, so the defaults lean slightly toward alerting.

---

## Step 1: Set Up Phone Notifications (ntfy)

1. Install the free **ntfy** app from the Play Store or App Store. No account is needed.
2. Tap **+** and subscribe to a topic name that is hard to guess, for example `garden-rain-8x3k2q`.
   Anyone who knows the topic name can read or send messages to it, so keep it obscure.
3. Test it from any computer:

   ```bash
   curl -d "Test from my garden server" ntfy.sh/garden-rain-8x3k2q
   ```

   If a notification appears on your phone, notifications are working.

**Android tip:** Disable battery optimization for the ntfy app, or notifications may arrive late.

---

## Step 2: Choose Where to Run It

### Option A: Local Server (Linux, Mac, Raspberry Pi)

Requires Python 3 and a machine that stays on 24/7.

1. Copy the script and its env file into a folder, for example `~/rain-alert/`.
2. Edit the env file with your settings (see [Configuration](#configuration)).
3. Test it once:

   ```bash
   cd ~/rain-alert
   set -a && . ./rain-alert.env && set +a
   python3 rain_alert.py
   ```

   You should see output such as `{"rain": false}`.

4. Schedule it every 5 minutes with `crontab -e`:

   ```bash
   */5 * * * * cd $HOME/rain-alert && set -a && . ./rain-alert.env && set +a && /usr/bin/python3 rain_alert.py >> log.txt 2>&1
   ```

   For the OpenWeatherMap version, replace `rain-alert.env` with `rain-alert-owm.env` and `rain_alert.py` with `rain_alert_owm.py`.

**Windows:** Use Task Scheduler with a task that repeats every 5 minutes, setting the environment variables in a small `.bat` wrapper.

### Option B: AWS Lambda

Requires the AWS SAM CLI and an AWS account.

1. Put `lambda_function.py` and `template.yaml` in one folder.
2. Build and deploy:

   ```bash
   sam build && sam deploy --guided
   ```

3. Enter `Lat`, `Lon`, and `NtfyTopic` when prompted.
4. To test notifications, run the function once with `LOOKAHEAD_MIN=1440` and `MIN_PRECIP_MM=0`, confirm the alert arrives, then remove those overrides and delete the `/rain-alert/last` SSM parameter so the cooldown doesn't block the next real alert.

The Lambda version currently uses Open-Meteo. To use OpenWeatherMap on Lambda, copy `get_forecast()` from `rain_alert_owm.py` into `lambda_function.py` and add `OWM_API_KEY` to the template's environment variables.

---

## Step 3 (OpenWeatherMap Only): Get an API Key

1. Create an account at openweathermap.org.
2. Subscribe to **"One Call by Call"** (One Call API 3.0). It includes 1,000 free calls per day. A credit card is required during activation, but you are only charged if you exceed the free tier.
3. **Cap your usage at 1,000 calls per day** in the **Billing plans** tab. The default limit is 2,000, so lowering it guarantees you never pay.
4. A new key can take up to 2 hours to activate. Authentication errors in the first hour are normal.

Checking every 5 minutes uses about 288 calls per day, well within the free limit.

---

## Configuration

All settings are environment variables in the `.env` file.

| Variable | Required | Default | Description |
|---|---|---|---|
| `LAT`, `LON` | Yes | — | Your garden's coordinates. Long-press the spot in Google Maps to get them. |
| `NTFY_TOPIC` | Yes | — | Your ntfy topic name. |
| `OWM_API_KEY` | OWM only | — | OpenWeatherMap API key. |
| `LOOKAHEAD_MIN` | No | `45` | How many minutes ahead to look for rain. Maximum 60 for OpenWeatherMap. |
| `MIN_PRECIP_MM` | No | `0.1` (Open-Meteo), `0.3` (OWM) | Rain threshold. Open-Meteo: mm per 15-minute slot. OpenWeatherMap: intensity in mm/h. |
| `COOLDOWN_HOURS` | No | `3` | Minimum time between alerts. |
| `STATE_FILE` | No | `~/.rain-alert-last` | Where the last alert time is stored (local versions). |

### Tuning Tips

- **Missing some showers?** Lower `MIN_PRECIP_MM` (for example 0.05 for Open-Meteo, or 0.1 mm/h for OpenWeatherMap) or increase `LOOKAHEAD_MIN`.
- **Too many false alarms?** Raise `MIN_PRECIP_MM`.
- **Tropical climate?** Use `LOOKAHEAD_MIN=60` to catch fast-forming afternoon storms.
- Review `log.txt` (or CloudWatch logs on Lambda) after a couple of weeks and compare alerts with actual rain.

---

## Cost

### Personal Use

| Item | Local server | AWS Lambda |
|---|---|---|
| Weather data | Free | Free |
| Notifications (ntfy.sh) | Free | Free |
| Compute | Electricity only (about $5/year for a Raspberry Pi) | $0 within the AWS free tier |
| Hardware | $0 if you have a server; about $50–80 once for a Raspberry Pi | None |

### Commercial Use

If you offer this as a product or service:

- **Open-Meteo** is free only for non-commercial use. Its commercial Standard plan is about $29/month for 1 million calls, which covers roughly 115 locations at 5-minute polling (or 230–350 locations at 10–15-minute polling).
- **OpenWeatherMap** charges per call beyond 1,000 calls/day.
- **ntfy.sh** offers paid plans for higher volume, or you can self-host ntfy for free.
- The current scripts handle **one location per copy**. Serving many users requires a backend that stores each user's location and notification topic.

Check each provider's pricing page before launching, as prices can change.

---

## Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| No notification when testing | Check the topic name matches exactly in the app and env file. Test with `curl` first. |
| Notifications arrive late (Android) | Disable battery optimization for the ntfy app. |
| `401 Unauthorized` from OpenWeatherMap | The key is still activating (wait up to 2 hours), or the One Call subscription isn't enabled. |
| `429 Too Many Requests` | You hit the daily call limit. Check your polling interval and billing cap. |
| Script runs but never alerts | Check `log.txt`. If it shows `"reason": "cooldown"`, an alert was already sent recently. Delete the state file to reset. |
| Cron job doesn't run | Use absolute paths, and check `log.txt` for errors such as missing environment variables. |

---

## Optional Improvements

- **Rain sensor:** Wire a cheap rain sensor to a Raspberry Pi to alert the moment rain actually starts, as a backup when the forecast misses a sudden storm.
- **Automatic cover:** Use the same trigger to drive a motor or relay that closes a cover or awning over the plants.
- **Self-hosted ntfy:** Run your own ntfy server for private topics with access control.
- **Multi-user service:** Store multiple locations and topics, and loop over them in one scheduled run.

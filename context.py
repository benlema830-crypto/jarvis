"""Live information Jarvis can look up: calendar, weather, system status."""

import datetime
import functools
import os

import icalendar
import psutil
import recurring_ical_events
import requests


def _fmt_time(dt: datetime.datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _day_label(d: datetime.date) -> str:
    today = datetime.date.today()
    if d == today:
        return "Today"
    if d == today + datetime.timedelta(days=1):
        return "Tomorrow"
    return d.strftime("%A %b %d")


def calendar_urls() -> list[str]:
    """ICS links from Outlook, Google, iCloud, etc. (GOOGLE_CALENDAR_ICS_URL is the old name)."""
    raw = ",".join(os.getenv(k, "") for k in ("CALENDAR_ICS_URLS", "GOOGLE_CALENDAR_ICS_URL"))
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    return ["https://" + u[len("webcal://"):] if u.lower().startswith("webcal://") else u for u in urls]


def upcoming_events(days: int = 1) -> str:
    """Events from now until the end of the day `days` days from today."""
    urls = calendar_urls()
    if not urls:
        return "Calendar not connected."

    now = datetime.datetime.now().astimezone()
    end = datetime.datetime.combine(
        now.date() + datetime.timedelta(days=days), datetime.time.max
    ).astimezone()

    events = []
    for url in urls:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        cal = icalendar.Calendar.from_ical(resp.content)
        for ev in recurring_ical_events.of(cal).between(now, end):
            start = ev.get("DTSTART").dt
            title = str(ev.get("SUMMARY", "Untitled event"))
            location = str(ev.get("LOCATION", "")).strip()
            if isinstance(start, datetime.datetime):
                start = start.astimezone()  # naive times are treated as local
                sort_key, when = start, f"{_day_label(start.date())} {_fmt_time(start)}"
            else:  # all-day event
                sort_key = datetime.datetime.combine(start, datetime.time.min).astimezone()
                when = f"{_day_label(start)} (all day)"
            events.append((sort_key, f"  - {when}: {title}" + (f" @ {location}" if location else "")))

    if not events:
        return "Nothing scheduled."
    events.sort(key=lambda e: e[0])
    return "\n".join(line for _, line in events[:15])


@functools.lru_cache(maxsize=1)
def _location() -> dict:
    return requests.get("https://ipinfo.io/json", timeout=5).json()


def _describe(code: int) -> str:
    for codes, text in [
        ((0,), "clear skies"), ((1,), "mostly clear"), ((2,), "partly cloudy"), ((3,), "overcast"),
        ((45, 48), "foggy"), (range(51, 58), "drizzle"), (range(61, 68), "rain"),
        (range(71, 78), "snow"), (range(80, 83), "rain showers"), ((85, 86), "snow showers"),
        (range(95, 100), "thunderstorms"),
    ]:
        if code in codes:
            return text
    return "unsettled weather"


def weather() -> str:
    loc = _location()
    lat, lon = loc["loc"].split(",")
    fahrenheit = loc.get("country") in ("US", "LR", "MM")
    unit = "F" if fahrenheit else "C"
    data = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2,
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "temperature_unit": "fahrenheit" if fahrenheit else "celsius",
            "wind_speed_unit": "mph" if fahrenheit else "kmh",
        },
        timeout=6,
    ).json()
    cur, day = data["current"], data["daily"]
    return (
        f"{loc.get('city', 'Your area')}: now {cur['temperature_2m']:.0f}°{unit}, {_describe(cur['weather_code'])}. "
        f"Today high {day['temperature_2m_max'][0]:.0f}°{unit} / low {day['temperature_2m_min'][0]:.0f}°{unit}, "
        f"{day['precipitation_probability_max'][0]}% chance of rain. "
        f"Tomorrow {_describe(day['weather_code'][1])}, high {day['temperature_2m_max'][1]:.0f}°{unit}, "
        f"{day['precipitation_probability_max'][1]}% chance of rain."
    )


def system_status() -> str:
    cpu = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage("C:\\").percent
    uptime = datetime.datetime.now() - datetime.datetime.fromtimestamp(psutil.boot_time())
    battery = psutil.sensors_battery()
    batt = f", battery {battery.percent:.0f}%{' charging' if battery.power_plugged else ''}" if battery else ""
    return (
        f"CPU {cpu}%, memory {mem}%, C: drive {disk}% full{batt}, "
        f"up for {uptime.seconds // 3600 + uptime.days * 24}h {uptime.seconds % 3600 // 60}m"
    )

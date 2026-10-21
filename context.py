"""Live information Jarvis can look up: calendar, weather, system status."""

import datetime
import functools
import os
from urllib.parse import urlsplit

import icalendar
import psutil
import recurring_ical_events
import requests

import worksafe
import preferences


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
    saved = preferences.read()
    if "calendar_urls" in saved:
        return saved["calendar_urls"]
    raw = ",".join(os.getenv(k, "") for k in ("CALENDAR_ICS_URLS", "GOOGLE_CALENDAR_ICS_URL"))
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    return ["https://" + u[len("webcal://"):] if u.lower().startswith("webcal://") else u for u in urls]


def fetch_calendar(url):
    """Read a bounded calendar feed. Never include its private URL in errors."""
    try:
        with requests.get(url, timeout=(5, 10), stream=True) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > 5 * 1024 * 1024:
                    raise ValueError("Calendar is larger than the 5 MB limit.")
        if not bytes(content).lstrip().startswith(b"BEGIN:VCALENDAR"):
            raise ValueError("That is not an ICS calendar feed. Copy the ICS link, not the HTML link.")
        return icalendar.Calendar.from_ical(bytes(content))
    except requests.RequestException:
        raise ValueError("Could not reach the calendar feed. Check the ICS link and internet connection.") from None


def connect_calendar(url):
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Paste a complete HTTPS calendar subscription link.")
    fetch_calendar(url)  # Keep the previous working connection if validation fails.
    preferences.update(calendar_urls=[url])


def upcoming_events(days: int = 1, open_outlook: bool = False) -> str:
    """Events from now until the end of the day `days` days from today.

    Background reads never automate Outlook. An explicit open_outlook=True retains
    the existing window-based reader for callers that deliberately request it."""
    urls = calendar_urls()
    if not urls and open_outlook and worksafe.outlook_allowed():
        import outlook_calendar  # only loaded when used: it sets up UI Automation
        return outlook_calendar.upcoming(days, launch=open_outlook)
    if not urls:
        return "Calendar not connected. Use Connect calendar in the Schedule panel to add your Outlook ICS link."

    now = datetime.datetime.now().astimezone()
    end = datetime.datetime.combine(
        now.date() + datetime.timedelta(days=days), datetime.time.max
    ).astimezone()

    events = []
    for url in urls:
        cal = fetch_calendar(url)
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


def starting_soon(minutes: int = 15) -> list[tuple[datetime.datetime, str]]:
    """Timed events (not all-day) starting within the next `minutes`, as (start, title)."""
    now = datetime.datetime.now().astimezone()
    soon = []
    for url in calendar_urls():
        for ev in recurring_ical_events.of(fetch_calendar(url)).between(now, now + datetime.timedelta(minutes=minutes)):
            start = ev.get("DTSTART").dt
            if isinstance(start, datetime.datetime) and start.astimezone() >= now:
                soon.append((start.astimezone(), str(ev.get("SUMMARY", "Untitled event"))))
    return sorted(soon)


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

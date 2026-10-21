"""The user's calendar in the New Outlook app (olk.exe), read and written through Windows UI Automation.

New Outlook has no scripting API, so this works its window the way a screen reader would: it
reads the event labels and fills in the new-event form directly. No screenshots and no mouse.
The new-event form does pop up briefly while an event is added.

Only used when JARVIS_ALLOW_OUTLOOK=1 (see worksafe.py). Outlook is opened if it isn't running.
"""

import ctypes
import datetime
import os
import re
import subprocess
import time

import uiautomation as auto

HERE = os.path.dirname(os.path.abspath(__file__))
APP_ID = r"shell:AppsFolder\Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows"
VIEWS = ("Day", "Work week", "Week", "Month")
SHOW_AS = ("Free", "Working elsewhere", "Tentative", "Busy", "Out of office")
SHOW_AS_LABEL = {"Out of office": "OOF"}  # how event labels spell it, where that differs
WEEKDAY_DATE = re.compile(r"\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day, (\w+ \d{1,2}, \d{4})")
SHORT_DATE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")

os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
auto.Logger.SetLogFile(os.path.join(HERE, "data", "uia.log"))
auto.SetGlobalSearchTimeout(5)


class OutlookError(Exception):
    pass


def _press(ctrl):
    for pattern, act in ((auto.PatternId.InvokePattern, lambda p: p.Invoke()),
                         (auto.PatternId.TogglePattern, lambda p: p.Toggle()),
                         (auto.PatternId.SelectionItemPattern, lambda p: p.Select())):
        p = ctrl.GetPattern(pattern)
        if p:
            act(p)
            return
    raise OutlookError(f"Can't press '{ctrl.Name}'.")


def _toggled(ctrl) -> bool:
    p = ctrl.GetPattern(auto.PatternId.TogglePattern)
    return bool(p and p.ToggleState == auto.ToggleState.On)


def _wait(check, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.2)
    return False


def _running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq olk.exe", "/NH"], capture_output=True, text=True,
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return "olk.exe" in out.lower()


def _main_window(launch: bool = True):
    win = auto.WindowControl(searchDepth=1, ClassName="Outlook Host", RegexName=r".* - Outlook$")
    if not win.Exists(1):
        if not launch:
            return None
        if not _running():  # launching it again would open a second window
            subprocess.Popen(["explorer.exe", APP_ID])
        if not win.Exists(45):
            raise OutlookError("Outlook didn't open.")
    # Outlook builds its accessibility tree only once something asks for it
    if not _wait(lambda: win.ButtonControl(Name="Calendar", searchDepth=20).Exists(0.3), 20):
        raise OutlookError("Outlook isn't responding (is it signed in?).")
    return win


def _open_calendar(win):
    button = win.ButtonControl(Name="Calendar", searchDepth=20)
    if not _toggled(button):
        _press(button)
    if not _wait(lambda: win.ButtonControl(Name="New event", searchDepth=40).Exists(0.3), 15):
        raise OutlookError("Couldn't open Outlook's calendar.")


def _current_view(win) -> str | None:
    for view in VIEWS:
        button = win.ButtonControl(Name=view, searchDepth=40)
        if button.Exists(0) and _toggled(button):
            return view
    return None


def _set_view(win, view: str):
    button = win.ButtonControl(Name=view, searchDepth=40)
    if button.Exists(2) and not _toggled(button):
        _press(button)
        time.sleep(0.8)


def _status(win) -> str:
    text = win.TextControl(RegexName=r"^Loaded \d+ events", searchDepth=40)
    return text.Name if text.Exists(0) else ""


def _go_to(win, day: datetime.date):
    """Show the week containing `day`, using the little month calendar."""
    header = win.ButtonControl(RegexName=r".*, select to change the month$", searchDepth=40)
    for _ in range(36):
        shown = datetime.datetime.strptime(header.Name.split(",")[0], "%B %Y")
        months = (day.year - shown.year) * 12 + day.month - shown.month
        if months == 0:
            break
        _press(win.ButtonControl(RegexName=r"^Go to next month" if months > 0 else r"^Go to previous month",
                                 searchDepth=40))
        time.sleep(0.3)
    before = _status(win)
    _press(win.ButtonControl(Name=f"{day.day}, {day:%B}, {day.year}", searchDepth=40))
    _wait(lambda: _status(win) != before, 4)
    time.sleep(0.4)


def _event_labels(win) -> list[str]:
    labels = []
    for ctrl, _ in auto.WalkControl(win, maxDepth=60):
        name = (ctrl.Name or "").replace("\n", " ").strip()
        if ctrl.ControlTypeName == "ButtonControl" and WEEKDAY_DATE.search(name) \
                and not name.startswith("Go to") and not WEEKDAY_DATE.match(name):
            labels.append(re.sub(r"^[\w ]+ icon, ", "", name))
    return labels


def _week_start(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=(day.weekday() + 1) % 7)  # Outlook's weeks start on Sunday


def _dates(label: str) -> list[datetime.date]:
    return [datetime.datetime.strptime(d, "%B %d, %Y").date() for d in WEEKDAY_DATE.findall(label)]


def upcoming(days: int = 1, launch: bool = True) -> str:
    """Events from today through `days` days from today, as lines for Jarvis to read."""
    with auto.UIAutomationInitializerInThread():
        win = _main_window(launch)
        if win is None:
            return "Outlook isn't open."
        _open_calendar(win)
        original = _current_view(win)
        today = datetime.date.today()
        last = today + datetime.timedelta(days=days)
        try:
            _set_view(win, "Week")
            seen, week = {}, _week_start(today)
            while week <= _week_start(last):
                _go_to(win, week)
                for label in _event_labels(win):
                    dates = _dates(label)
                    if dates and dates[0] <= last and dates[-1] >= today:
                        seen.setdefault(label, dates[0])
                week += datetime.timedelta(days=7)
        finally:
            if original:
                _set_view(win, original)
            _go_to(win, today)
    if not seen:
        return "Nothing scheduled."
    return "\n".join(f"  - {label}" for label, _ in sorted(seen.items(), key=lambda kv: kv[1])[:15])


def _fmt_time(t: datetime.datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def _discard(form):
    form.ButtonControl(Name="Close", searchDepth=3).GetInvokePattern().Invoke()
    ok = form.ButtonControl(Name="OK", searchDepth=40)
    if ok.Exists(3):
        _press(ok)


def add_event(title: str, start: datetime.date | datetime.datetime, end: datetime.date | datetime.datetime,
              location: str = "", notes: str = "", show_as: str = "") -> str:
    """Add an event. Dates (not datetimes) make an all-day event, end date inclusive.
    Timed events must start and end on the same day."""
    all_day = not isinstance(start, datetime.datetime)
    if all_day and end < start:
        raise OutlookError("The end date is before the start date.")
    if not all_day and (end.date() != start.date() or end <= start):
        raise OutlookError("A timed event has to start and end on the same day, end after start.")
    if show_as and show_as not in SHOW_AS:
        raise OutlookError(f"Show-as must be one of {', '.join(SHOW_AS)}.")

    with auto.UIAutomationInitializerInThread():
        win = _main_window()
        _open_calendar(win)
        _press(win.ButtonControl(Name="New event", searchDepth=40))
        form = auto.WindowControl(searchDepth=1, RegexName=r"^New event")
        if not form.Exists(10):
            raise OutlookError("The new-event form didn't open.")
        try:
            title_box = form.EditControl(Name="Add title", searchDepth=30)
            title_box.GetValuePattern().SetValue(title)
            # before the date panel opens: it covers these
            if location:
                form.ComboBoxControl(AutomationId="location-suggestions-picker-input", searchDepth=30) \
                    .GetValuePattern().SetValue(location)
            if notes:
                form.EditControl(Name="Event body", searchDepth=30).GetValuePattern().SetValue(notes)
            if show_as:
                menu = form.ButtonControl(RegexName=f"^({'|'.join(SHOW_AS)})$", searchDepth=30)
                if menu.Name != show_as:
                    menu.GetExpandCollapsePattern().Expand()
                    _press(form.Control(Name=show_as, searchDepth=40))
                    time.sleep(0.4)

            form.ButtonControl(RegexName=r"^\w{3} \d{1,2}/\d{1,2}/\d{4}", searchDepth=30) \
                .GetExpandCollapsePattern().Expand()
            all_day_box = form.CheckBoxControl(Name="All day", searchDepth=30)
            if not all_day_box.Exists(3):
                raise OutlookError("Couldn't find the date fields.")
            if _toggled(all_day_box) != all_day:
                _press(all_day_box)
                time.sleep(0.5)

            def set_field(label, value):
                # Outlook only takes a typed value once focus leaves the box
                box = form.ComboBoxControl(Name=label, searchDepth=30)
                box.SetFocus()
                box.GetValuePattern().SetValue(value)
                time.sleep(0.2)
                all_day_box.SetFocus()
                time.sleep(0.4)

            expected = {"Start date": f"{start.month}/{start.day}/{start.year}"}
            if all_day:
                expected["End date"] = f"{end.month}/{end.day}/{end.year}"
            else:
                expected["Start time"], expected["End time"] = _fmt_time(start), _fmt_time(end)
            for label, value in expected.items():  # start first: Outlook shifts the end to keep the length
                set_field(label, value)

            for label, value in expected.items():
                got = form.ComboBoxControl(Name=label, searchDepth=30).GetValuePattern().Value
                if got != value:
                    raise OutlookError(f"Outlook's {label.lower()} says {got}, not {value}.")

            # The open date panel hides the Save button from automation, so save with Ctrl+S -
            # only once the form is definitely in front, so the keys can't land anywhere else
            form.SetActive()
            if not _wait(lambda: auto.GetForegroundControl().NativeWindowHandle == form.NativeWindowHandle, 3):
                raise OutlookError("Couldn't bring the event form to the front to save it.")
            auto.SendKeys("{Ctrl}s", waitTime=0.3)
            if not _wait(lambda: not form.Exists(0), 8):
                raise OutlookError("Outlook didn't save the event.")
        except Exception:
            if form.Exists(0):
                _discard(form)
            raise

        day = start if all_day else start.date()
        label = _find_label(win, title, day)
        # Ticking "All day" resets free/busy to Free, and the form can't be reached to fix it until the
        # event is saved - so set it afterwards from the saved event
        if label and show_as and not label.endswith(", " + SHOW_AS_LABEL.get(show_as, show_as)):
            _set_show_as(win, title, day, show_as)
            label = _find_label(win, title, day)

        # Confirm from the calendar itself, in Outlook's own words
        if not label:
            return "Saved, but I couldn't find it on the calendar afterwards to double-check."
        dates = _dates(label)
        first, last = (start, end) if all_day else (day, day)
        ok = dates and (dates[0], dates[-1]) == (first, last) and (all_day or _fmt_time(start) in label) \
            and (not show_as or label.endswith(", " + SHOW_AS_LABEL.get(show_as, show_as)))
        return f"Added to Outlook: {label}" if ok else f"Saved, but Outlook shows it differently than asked - check it: {label}"


def _find_label(win, title: str, day: datetime.date) -> str | None:
    _go_to(win, day)
    return next((label for label in _event_labels(win) if title in label), None)


def _set_show_as(win, title: str, day: datetime.date, show_as: str):
    _go_to(win, day)
    _press(win.ButtonControl(RegexName=f".*{re.escape(title)}, ", searchDepth=60))
    edit = win.ButtonControl(Name="Edit", searchDepth=40)
    if not edit.Exists(3):
        raise OutlookError("Couldn't open the saved event to set its free/busy.")
    before = {w.NativeWindowHandle for w in auto.GetRootControl().GetChildren()}
    _press(edit)
    form = None
    for _ in range(50):
        new = [w for w in auto.GetRootControl().GetChildren()
               if w.ClassName == "Outlook Host" and w.NativeWindowHandle not in before]
        if new:
            form = new[0]
            break
        time.sleep(0.2)
    if form is None:
        raise OutlookError("The event didn't open for editing.")
    menu = form.ButtonControl(RegexName=f"^({'|'.join(SHOW_AS)})$", searchDepth=30)
    if not menu.Exists(5):
        _discard(form)
        raise OutlookError("Couldn't find the free/busy setting.")
    menu.GetExpandCollapsePattern().Expand()
    _press(form.Control(Name=show_as, searchDepth=40))
    time.sleep(0.8)
    # an existing event with no attendees saves each change by itself; there's no Save button
    handle = form.NativeWindowHandle
    form.ButtonControl(Name="Close", searchDepth=3).GetInvokePattern().Invoke()
    if not _wait(lambda: not ctypes.windll.user32.IsWindow(handle), 5):
        raise OutlookError("The event's window didn't close.")
    time.sleep(0.8)

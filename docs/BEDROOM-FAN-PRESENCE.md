# Bedroom fan presence and overnight protection

The running controller is **Home Assistant**, on the Pi. Jarvis does not run a
second presence/off loop. `scripts/bedroom_fan_presence.py` is a maintenance tool
that previews or updates the existing HA automation; it is not a background task.

Live automation ID: `bedroom_fan_on_when_back`.
Entity: `automation.bedroom_fan_back_on_when_you_return`.
Alias: “Bedroom fan: on when you come in, off when empty”.
The entities named “Bedroom fan auto off” and “Bedroom fan manual off” are
`input_boolean` helpers, not separate automations. Legacy separate off/manual
automation IDs returned 404 during this change.

## Nightly behavior

- **11:00 PM inclusive to 6:40 AM exclusive, every night:** the empty-room branch
  cannot run. Presence-based fan shutdown and that branch's manual-hold reset are
  suppressed. There is no scheduled forced turn-on and manual controls still work.
- **6:40 AM to 11:00 PM:** the **15-minute continuous absence** rule applies.
  A new 6:40 AM trigger also checks for a room that was already empty overnight;
  it shuts down only if occupancy is currently `off` for at least 15 minutes.
  Occupied, unknown and unavailable sensor states cannot pass that check.
- Hand/voice change branches are unchanged. No global condition blocks
  those branches. The absence state trigger and empty safety guard both use 15 minutes.
- Presence can turn the fan on only while Nap Mode is off. No clear/return
  transition bypasses an active nap. Existing weekday 06:40–07:10 arrival
  suppression is preserved. Nap activation can explicitly turn off the plug,
  including overnight, as before.
- Jarvis's weekday 6:40 AM wake-up still calls `fan.turn_off` independently. The
  alarm, briefing, morning music and HA 6:35 AM PC-wake automation are unchanged.

The user explicitly selected **11:00 PM** as the start, replacing the initial
9:00 PM fallback. The existing wake-up
time is 6:40 AM without an environment override. HA's configured timezone is
`America/North_Dakota/Center` (Central time); no timezone setting was changed.
The daytime time condition is inclusive at 6:40 and exclusive at 23:00, matching
[HA's time-condition semantics](https://www.home-assistant.io/docs/scripts/conditions/#time-condition).
Adjust the HA empty-branch time condition and matching maintenance constants/tests
if a different bedtime is desired. Do not change the wake-up alarm to do so.

## Maintenance and verification

From the Jarvis folder:

```powershell
.\.venv\Scripts\python.exe scripts/bedroom_fan_presence.py
# Only with authorization to change HA:
.\.venv\Scripts\python.exe scripts/bedroom_fan_presence.py --apply
.\.venv\Scripts\python.exe -m unittest tests.test_bedroom_fan_presence tests.test_morning_wakeup -v
```

The default command is read-only. Apply reads fresh HA config, validates its
expected shape, saves `before.json` and `proposed.json`, checks for concurrent
changes, saves only this automation, checks HA configuration, reloads automations
and verifies exact config readback plus the enabled state. It never prints the HA
token or directly sends fan commands. Backups are under
`data/reports/bedroom-fan-overnight-*/`. Restoration is an explicit authorized HA
config write using `before.json`, followed by validation/reload; it is not automatic.

## Verified November 8, 2026 update

Updated the known one-minute empty trigger and its safety condition to 15 minutes.
Manual-off rearming in that branch now also waits for 15 continuous empty minutes
and still respects overnight suppression. Arrival now strictly requires Nap Mode
off. Quiet hours, the 06:40 recheck, weekday morning guard, manual branches and
light five-minute timer were preserved. All 25 targeted tests passed. HA validation
was clean, targeted reloads succeeded and API readbacks matched. No device
commands were sent. See `docs/BEDROOM-NAP-MODE.md` for timeout/phone changes and
`data/reports/nap-fan-fix-20261108-203729/` for backups and exact verification.

## Applied October 29, 2026 (historical timing)

The named script, documentation and tests were absent from this checkout despite
older reports and compiled Python caches. This maintenance tool and regression
fixture were recreated from the **current live automation**, preserving its newer
context-based manual override behavior rather than restoring obsolete logic.

Saved/reloaded at about 11:37 PM Central. HA config check: valid, no warnings or
errors. Fourteen tests passed (eight overnight tests and six existing morning
tests). HA's native `test_condition` returned false for both the actual daytime
guard and the full empty-branch conditions with an `empty` trigger at night.
These tests evaluate conditions without executing device actions.

The fan had switched off before the protection was applied. One deliberate
`fan.turn_on` was sent for tonight: HA subsequently reported fan and plug **on**,
47.8 W, while occupancy remained **off**. No test turn-off was sent. An initial
manual automation trigger did not carry a trigger ID in HA and did not execute
any branch; it is not used as proof of the time guard. The native condition tests
provide that proof. The actual next-morning transition remains to occur naturally.

Applied backup/readback/verification:
`data/reports/bedroom-fan-overnight-20261029-233659-132211/`.
No Jarvis restart, alarm edit, helper reset, device deletion or unrelated automation
change was performed. Existing Clip Studio work was left untouched.

## Start changed to 11 PM (October 29, 11:41 PM Central)

Backed up the live 9 PM automation before editing. Replaced its daytime condition's
`before: 21:00:00` with `before: 23:00:00` and updated its description. No other
HA automation fields changed; the 6:40 trigger, alarm and morning routine remain.
The maintenance tool migrates the old guard instead of adding a second condition.

All 15 tests pass, including migration and 22:59:59/23:00/06:40 boundaries. HA
configuration is valid with no errors or warnings, reload succeeded and readback
matched. Native HA tests at 23:41 returned false for both the daytime guard and
full empty branch. Fan and plug stayed on, drawing 47.4 W while occupancy was off.
No device commands were sent during this update.

Backup and verification: `data/reports/bedroom-fan-overnight-20261029-234115-157469/`.

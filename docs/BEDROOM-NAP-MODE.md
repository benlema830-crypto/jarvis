# Bedroom Nap Mode

Use **Bedroom Nap** in the Home Assistant app/sidebar (including iPhone), then
**Start Nap Mode**. Or ask Jarvis to **activate nap mode**. The HA script is
`script.nap_mode`; name resolution was checked without calling it.

- `input_boolean.nap_mode` is the visible **Nap Mode** switch. Turning it on by
  script or toggle activates the same automation. Turn the switch off to end early.
- Activation sets a persistent deadline (`input_datetime.nap_mode_until`) using
  the adjustable timeout (default **two** hours), turns off `light.ceiling_light`, `light.bedroom_lamp`, and the actual
  plug `switch.bedroom_fan`. Failure of a light command does not prevent the fan
  command. The flag is set before any off commands so presence cannot re-enable
  devices during activation. Repeating Start while already on does not extend it.
- Presence turn-on is strictly suppressed until Nap Mode ends. **No amount of
  room absence, clear sensor readings, or re-entry ends a nap or bypasses this block.**
- Nap Mode ends only when switched off manually, its deadline expires, or the
  verified iPhone tracker `device_tracker.jarvis` leaves `home` for a known away
  state. Unknown/unavailable phone readings do not end a nap.
- Set **Nap timeout (hours)** on the Bedroom Nap dashboard before starting.
  `input_number.nap_duration_hours` defaults to 2, accepts 0.25–12 hours in 0.25-hour
  increments, and restores its setting after restart. Changing it affects the next
  nap; the displayed Automatic end deadline of a running nap stays unchanged.
- An absolute deadline handles the timeout, with startup and minute
  checks for recovery after HA restarts/reloads. If HA is offline at expiry, the
  mode ends when HA returns; offline automation cannot execute at the deadline.
- Ending manually or on timeout does not force devices on. Existing manual-off
  holds still apply until their usual clear/reset conditions. On a qualifying
  later presence detection, existing presence rules apply, including lighting quiet hours.

The existing five-minute light auto-off, light manual-off hold, light quiet window
(23:00-06:40), and fan overnight suppression remain intact. The fan now requires
**15 continuous empty minutes** for auto-off and manual-off rearming, including
its 06:40 empty-room recheck. Existing weekday morning protections are preserved.
Arrival branches in `bedroom_lights_presence` and `bedroom_fan_on_when_back`
require Nap Mode off; the old five-minute-clear bypass is removed. The manual-off companion, wake-up automations and
morning routine were not edited. Nap activation intentionally overrides the fan's
normal overnight behavior by directly turning its plug off.

## Components

- `input_boolean.nap_mode` ? Nap Mode, Bedroom area
- `input_datetime.nap_mode_until` ? Nap Mode Until, Bedroom area
- `script.nap_mode` ? Nap Mode, Bedroom area
- `automation.bedroom_nap_mode` ? Bedroom - Nap Mode, enabled
- New sidebar dashboard **Bedroom Nap**, `/bedroom-nap/nap`; existing dashboards unchanged
- Configuration builder: `scripts/bedroom_nap_mode.py` (pure functions; no device calls)

## Verification (October 31, 2026)

This section records the original version, superseded by the November 8 update below.

21 tests passed across Nap Mode, lighting manual-off and fan overnight regressions.
HA native condition tests confirmed 299 seconds clear does not qualify and 300
seconds does. Configuration check returned valid, no errors/warnings. Saved
script/automation/dashboard readbacks matched; all three relevant automations
were enabled. Jarvis's live resolver selects `script.nap_mode` for ?nap mode?.
No switch/light commands or script activation were used in tests. Nap Mode remains
off. Physical activation and the three-hour wait were not exercised.

Backups, proposed configuration and verification are saved under
`data/reports/nap-mode-20261031-161353/`. No Jarvis or Home Assistant restart needed.

## Verified update (November 8, 2026)

Original cause confirmed in live rules: a five-minute clear-to-detected transition
ended Nap Mode, and matching arrival guards could turn devices on even before the
nap flag cleared. Removed both paths. Added verified iPhone home-departure ending,
the two-hour adjustable timeout, strict nap guards, and the 15-minute fan trigger
and safety condition. Nap activation/off actions and the Start Nap script are unchanged.

All 25 targeted tests passed, covering unavailable phone/deadline data, timeout
calculation, removal of the return bypass, 899/900-second fan boundaries, quiet
hours and existing manual-off behavior. HA config check returned valid with no
errors or warnings. All three automations were reloaded individually and API
readbacks matched. The helper reads 2.0 hours and HA's template evaluator confirmed
7200 seconds. Dashboard readback matched; the manual-off companion and morning
wake rule were unchanged. Nap stayed off; no physical device commands or nap/phone
simulation were used in verification.

Backups, proposal and exact readbacks:
`data/reports/nap-fan-fix-20261108-203729/plan.json` and `verification.json`.

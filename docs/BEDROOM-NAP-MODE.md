# Bedroom Nap Mode

Use **Bedroom Nap** in the Home Assistant app/sidebar (including iPhone), then
**Start Nap Mode**. Or ask Jarvis to **activate nap mode**. The HA script is
`script.nap_mode`; name resolution was checked without calling it.

- `input_boolean.nap_mode` is the visible **Nap Mode** switch. Turning it on by
  script or toggle activates the same automation. Turn the switch off to end early.
- Activation sets a persistent deadline (`input_datetime.nap_mode_until`) three
  hours ahead, turns off `light.ceiling_light`, `light.bedroom_lamp`, and the actual
  plug `switch.bedroom_fan`. Failure of a light command does not prevent the fan
  command. The flag is set before any off commands so presence cannot re-enable
  devices during activation. Repeating Start while already on does not extend it.
- Presence turn-on is suppressed until Nap Mode ends. A return after **five
  continuous minutes clear** ends the nap. Brief clear blips do not end it.
  Arrival guards use the same transition timestamps as the end rule, avoiding
  an ordering race between the existing presence automations and the nap rule.
- An absolute deadline handles the three-hour backstop, with startup and minute
  checks for recovery after HA restarts/reloads. If HA is offline at expiry, the
  mode ends when HA returns; offline automation cannot execute at the deadline.
- Ending manually or on timeout does not force devices on. Existing manual-off
  holds still apply until their usual clear/reset conditions. On a qualifying
  return, existing presence rules apply, including lighting quiet hours.

The existing five-minute light auto-off, light manual-off hold, light quiet window
(23:00-06:40), fan one-minute auto-off, and fan overnight suppression remain intact.
Only arrival branches in `bedroom_lights_presence` and `bedroom_fan_on_when_back`
gained a Nap Mode condition. The manual-off companion, wake-up automations and
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

21 tests passed across Nap Mode, lighting manual-off and fan overnight regressions.
HA native condition tests confirmed 299 seconds clear does not qualify and 300
seconds does. Configuration check returned valid, no errors/warnings. Saved
script/automation/dashboard readbacks matched; all three relevant automations
were enabled. Jarvis's live resolver selects `script.nap_mode` for ?nap mode?.
No switch/light commands or script activation were used in tests. Nap Mode remains
off. Physical activation and the three-hour wait were not exercised.

Backups, proposed configuration and verification are saved under
`data/reports/nap-mode-20261031-161353/`. No Jarvis or Home Assistant restart needed.

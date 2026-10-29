# Home device defaults

Jarvis reads local, git-ignored `data/home-device-defaults.json` on each device
lookup. Each alias selects an exact friendly name, domain and effective Home
Assistant area. Matching ignores case and repeated spaces, but preserves brackets.

The saved `lg` and `lg tv` aliases require the `media_player` named
`LG webOS TV OLED65C4PUA` in `Living Room`. They do not select
`[LG] webOS TV OLED65C4PUA`. A missing or duplicated target, missing area or failed
area lookup produces an error instead of falling back to a similar device.
Existing availability and supported-action checks still apply.

An explicit entity ID takes precedence. Exact full names also bypass fuzzy word
matching, so bracketed and unbracketed names remain distinguishable. If multiple
entities have the same full name in the preferred domain, specify an entity ID.

The current selector uses name and area because live entity/device IDs could not
be verified during implementation. It does not establish a hardware identity;
renaming or moving the TV can make the alias stop resolving. A different entity
given the same exact name and area would satisfy the selector. Once connectivity
is available, verify the entity/device registry identities before diagnosing or
removing a duplicate integration. No device cleanup is part of this change.

Restart the assistant when no task is running to load the new resolver code.
Subsequent edits to the defaults file are read on the next lookup. A browser
refresh alone does not reload Python code. A read-only `home_status("LG")` check
can then verify live resolution without powering the TV on or off.

# Spotify MCP for Jarvis

Prepared 2026-10-22. Implementation is optional and inactive until approved setup.
Unit tests and synthetic transport checks do not establish Spotify connectivity.

Verification: all 18 `test_spotify_mcp.py` tests passed under the Windows owner
account, including actual DPAPI round-trip, synthetic loopback OAuth/PKCE,
invalid state/replay/denial, minimal scopes, input limits, sanitized API errors,
token refresh rotation, resume registration and the real Jarvis MCP client.
The sandbox's DPAPI check failed because it could not access the owner profile;
the same check passed with normal approval outside the sandbox. All 22 existing
`test_mcp*.py` tests also passed. Python compilation and diff whitespace checks
passed. No live Spotify sign-in or playback is implied by these results.

## Selection and review

Jarvis's `mcp_connections.py` supports Streamable HTTP protocol versions
2025-03-26, 2025-06-18 and 2025-11-25, JSON or SSE response bodies, bearer tokens,
and public-client OAuth via `mcp_oauth.py`. It does not launch stdio servers or
use legacy SSE endpoints. OAuth requires matching protected-resource metadata,
PKCE S256, public token authentication, and same-origin authorization endpoints.
Connections are encrypted with Windows DPAPI; each external tool execution still
passes through Jarvis's existing spoken approval in `tools.py`.

Reviewed [LibreChat-AI/spotify-mcp](https://github.com/LibreChat-AI/spotify-mcp)
at commit `c6812b27895df68a0fea07c29861284b43787861`, including its README,
package manifest, API router, auth helper, tool definitions, service refresh logic
and Wrangler configuration. It offers `/mcp` and legacy `/sse`, but requires the
Cloudflare Workers/Durable Objects stack, a Spotify client secret, and new npm
dependencies. Its router lacks the protected-resource metadata Jarvis requires;
dynamic registration records are not used to validate the authorize/token routes.
Authorization parameters including redirect URI are forwarded to Spotify. The
bearer middleware only checks the header prefix; Spotify performs later validation.
Service refresh expects a custom refresh-token header that Jarvis does not send.
Search defaults to 20 with documentation allowing 50; current development mode
allows at most 10. The default scope list includes email, private playlists,
playlist/library writes and listening history beyond this task. Service errors
are logged and Wrangler observability is enabled. These findings rule out
installing the example unchanged; this was a targeted source review, not a full audit.

Selected solution: `spotify_mcp.py`, a small local bridge using existing Python
libraries and the standard library. It binds only 127.0.0.1, validates Host,
rejects browser Origin headers, uses an independent random bearer token, and
serves stateless Streamable HTTP JSON. It forwards only fixed Spotify API routes.
No additional packages, hosted service, firewall rule, scheduled task or assistant
restart is required. OAuth goes directly to Spotify with PKCE; no client secret.
Only `user-read-playback-state` and `user-modify-playback-state` are requested.
Search requires no additional user scope. Tool inputs are validated at runtime.
Tokens are DPAPI encrypted in ignored `data/spotify-mcp.enc`; the local bearer
is also encrypted in Jarvis's existing MCP store. Refresh rotates under a file
lock. Callback queries, authorization codes and provider errors are not logged.
Same-user local processes remain within the Windows account trust boundary.

## Current Spotify requirements

The [development-mode migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
requires Premium for app owners, limits new user additions to five per app, and
reduces search results to ten per request. The later
[July changelog](https://developer.spotify.com/documentation/web-api/references/changes/july-2026)
raises the app limit to 25 per developer and shares development quotas across
their apps. The older migration guide's one-app limit is superseded.
[Quota-mode documentation](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
explains app user access; add the intended test account to the app's user list
where required. Signing in alone does not prove API access.

[Start/resume playback](https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback)
requires Premium and a Spotify client/Connect device; the bridge is a controller,
not an audio player. No subscriptions will be purchased. If Premium is absent,
this development-app setup is blocked, including search through that app.
[Redirect rules](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)
permit HTTP for literal loopback IPs, reject `localhost`, and require a matching
registered redirect. [PKCE instructions](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow)
support code exchange and refresh without a client secret.

## Approved activation and user steps

The user explicitly requires normal approval before dependency installation or
settings changes. No dependencies need installation. Obtain approval before
running the wizard, which saves credentials, registers a connection and starts
the separate bridge. Never enter credentials into conversation, command arguments,
environment examples, logs or committed files.

1. Confirm you already have Spotify Premium. Visit the
   [developer dashboard](https://developer.spotify.com/dashboard), create an app
   for personal Jarvis control, select Web API, and register exactly
   `http://127.0.0.1:8792/callback`. Add the account under User Management if needed.
2. After approval, run `.venv\Scripts\python.exe scripts\setup_spotify.py`.
   The setup opens directly to one form with two browser actions:
   **Open developer dashboard** opens Spotify's developer website to edit app
   settings; it requires no Client ID and does not connect the account.
   **Open Spotify sign-in** validates the local Client ID and callback confirmation,
   starts the callback server, and opens the pending PKCE authorization request.
   The displayed callback is selectable read-only text, not a browser link.
   Enter only the Client ID in the masked local window. No client secret is used.
   Confirm the callback is registered, then click **Open Spotify sign-in**.
   The Client ID dialog does not open a browser while waiting for input. Missing
   or invalid IDs keep the dialog open. The next window reports a browser launch
   request and waits for the callback; a successful OS launch request alone does
   not prove a browser page appeared. Use **Open Spotify sign-in again** to retry
   the same pending flow, or **Cancel sign-in** to close it without connecting.
   Sign in on Spotify's browser page and approve playback read/control.
3. The wizard tests live search, device listing, playback reads, and search through
   Jarvis's actual MCP client before registering the connection. It starts a
   separate hidden bridge and verifies that process responds. It never starts
   music during setup. Sanitized results go to `data/reports/spotify-setup.json`.
4. Open Spotify and start a track on the desired device. Ask Jarvis to search
   Spotify, then to pause Spotify; approve each normal external-tool prompt.
   Ask for playback state to confirm it paused. Resume similarly. Playback
   control remains unverified until this succeeds; an HTTP acceptance alone
   does not establish that music changed. Existing Jarvis connections are read
   dynamically; no assistant restart is needed.

## Restart, recovery and removal

No automatic startup is installed. After Windows restarts, start
`.venv\Scripts\python.exe spotify_mcp.py` (or launch it hidden via PowerShell
`Start-Process -WindowStyle Hidden` with that interpreter and script).
Only one bridge may bind port 8791. Port 8792 is used temporarily for OAuth.

If setup saved encrypted credentials but failed before completing, resolve the
reported account/network/port issue, ensure no bridge is already running, then
after approval run the wizard with `--resume`. This reuses the saved account,
refreshes tokens if needed and retries verification/registration without secrets
being entered again. It refuses to replace credentials or silently overwrite a
different existing connection. A running bridge can be checked through Jarvis's
Tool Armory and the normal approved search/playback tools. Reauthorization needs
explicit removal of the prior encrypted credential file after approval; do not
print or decrypt that file for troubleshooting.

Browser-flow diagnosis on 2026-10-22: the original wizard's Python child process
had a visible `JARVIS Spotify client ID` dialog. Neither Spotify port was listening,
and neither credentials nor the verification report existed. The original flow
had not reached its browser call; developer app/callback registration could not
be inferred from that state. No entry-field contents or browser pages were read.
The prior wizard had no separate setup log; absence of a report is not evidence
of a browser failure. The updated dialog explicitly names the launch action,
requires local ID validation and callback confirmation, and shows a cancellable
browser-wait window with a retry action. Only a real provider callback and live
API/MCP checks establish connectivity.

The corrected wizard was reopened after approval and its visible Client ID step
was confirmed. At that check no credentials/report existed and no callback
listener was active. Added regression coverage verifies invalid IDs never open
a listener/browser, callback confirmation is required, browser failure is
sanitized, retries reuse the same pending URL, and cancellation closes the
listener without exchanging tokens. All 16 Spotify tests passed outside the
sandbox, including DPAPI; compilation and whitespace checks passed.

Further link-handler review: no wizard process or Spotify listener was running
at the start of the next inspection. The earlier developer-app and callback text
had no link handler. The form now has explicit dashboard/sign-in buttons, a
selectable exact callback address, and no preceding instruction-only popup.
The always-on-top setting was removed so the form cannot cover a launched browser.
Browser targets are restricted to the developer dashboard and Spotify's authorization
endpoint; the callback address cannot accidentally be launched as a sign-in page.
All 18 unit tests and `tests/check_spotify_wizard_ui.py` passed. The latter invokes
the actual Tk buttons with synthetic local input and a mocked browser, checking
missing ID and callback confirmation before valid submission.

403: check Premium, granted scopes and app user access. 404 on player commands:
open Spotify and start playback manually. 429: wait; do not retry repeatedly or
create extra apps to evade quotas. Expired/revoked sign-in: reauthorize securely.

To remove, disable/remove Spotify in Tool Armory, stop only the separate Spotify
bridge process, and revoke this app under your Spotify account's Apps page.
Jarvis removal deletes its local bearer connection; it does not revoke Spotify
tokens stored by this bridge. After approval, delete `data/spotify-mcp.enc` and
its temporary/lock file if present. No assistant restart is required.

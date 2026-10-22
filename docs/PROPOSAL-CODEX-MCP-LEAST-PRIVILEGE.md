# Proposal: least-privilege native tools for Jarvis-started Codex processes

Status: **proposed, not merged.** Branch `proposal/codex-mcp-least-privilege` (on top of
`foundation-hardening`). Needs the owner's decision because it changes which tools Codex can use.

## Finding (verified live on 2026-10-22, no model turns run)
Every Codex app-server that Jarvis starts loads `~/.codex/config.toml` and the built-in ChatGPT apps:

| Process | Native tools visible today |
|---|---|
| Conversational brain (`codex_brain`) | Roblox_Studio 28, codex_apps 104 |
| Research-mode agent session | Roblox_Studio 28, codex_apps 104 |
| Work-mode agent session | Roblox_Studio 28, codex_apps 104 |

- `Roblox_Studio.execute_luau` has `approval_mode = "approve"`, so it runs with no prompt at all. A
  "research" session (meant to inspect and report only) can therefore run arbitrary Luau in Studio;
  the read-only sandbox does not cover MCP tools, which run in the MCP server's own process.
- `codex_apps` includes `sites.deploy_site_version`, `sites.delete_site`, `plugin_management.uninstall_app`,
  `safety_settings.update_parental_control` and similar. Whether each one prompts is decided by Codex,
  not Jarvis; the conversational brain declines Codex's own approval requests, but it cannot see calls
  that need none.
- None of these pass through Jarvis's approval channel. Jarvis's own MCP integrations
  (`call_mcp_tool`) do ask the user every time, and are not affected by this proposal.
- Prompt-injection path: text from a web search result or a note reaches the conversational brain,
  which can then call these tools.

## Change
- `agent_sessions.isolation_args()` → `--disable apps` plus `-c mcp_servers.<name>.enabled=false` for
  every server named in the Codex config (names only; values are never read or logged).
- `Connection(..., isolate_mcp=True)` passes those flags to `codex app-server`.
- Applied to: the conversational brain (always) and research-mode agent sessions.
- Work-mode sessions keep the user's configuration unchanged (Roblox Studio for Rocket Frontier work).

Result through the real code path (`scripts/check_codex_mcp_isolation.py`):
work sessions `{'Roblox_Studio': 28, 'codex_apps': 104}`; conversation and research `{'Roblox_Studio': 0}`.

## Trade-offs to decide
1. Research sessions lose read-only Studio tools (`script_read`, `get_studio_state`, `search_game_tree`).
   Alternative: keep Roblox_Studio for research but override `execute_luau` (and other mutating tools)
   to `approval_mode = "prompt"`, which Jarvis's session approval handler would then route to the user.
2. Work sessions still run `execute_luau` without asking. Option: same per-tool `prompt` override for work.
3. Your Codex desktop app and CLI are unaffected either way: overrides apply only to processes Jarvis starts.

## Tests
`tests/test_codex_mcp_isolation.py` (arguments, config parsing, which callers isolate) and the updated
`tests/test_agent_sessions.py` (research isolated, work not). Full suite: 357 passed.

## Apply / roll back
Apply: `git switch foundation-hardening && git merge proposal/codex-mcp-least-privilege`.
Roll back after merging: `git revert <merge commit>`. No configuration files are modified.

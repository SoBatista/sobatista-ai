# ADR-0005: Interactive session on bare `sobai`

- Status: Accepted
- Date: 2026-08-23

## Context

Users expect a modern AI CLI to open a conversational session when run with no
arguments (as Claude Code and Codex do), while automation expects a bare command
never to hang. SoBatista AI also has a stricter, provider-neutral security model
that the session must not weaken.

## Decision

Running `sobai` with no subcommand dispatches on context:

- **Interactive TTY** → a multi-turn conversational session with a restrained
  Rich welcome screen (version, active provider/model/profile, local/cloud,
  `--local-only` state — no identity, paths, or secrets) and slash commands
  (`/help /status /provider /model /profile /usage /clear /exit /quit`).
- **Non-interactive** (piped/CI) → prints actionable guidance pointing at `sobai
  ask` and exits without hanging.
- `--help` / `--version` never launch it; `--json` with no subcommand is refused.

The session reuses the existing provider interfaces, aliases, profiles, policy,
streaming, usage/audit accounting, timeouts, retries, and cancellation. It keeps
conversation context **in memory only**, with explicit bounds, and never persists
history to disk. Line editing uses the stdlib `readline` (in-memory history);
`prompt_toolkit` was evaluated and deferred to keep the dependency surface small
and testable.

## Consequences

- **Security preserved:** the session never enables connector tools, never
  executes shell/Python/`eval`/MCP/web tools, never falls back between providers,
  and sanitizes all model output (ANSI/OSC/control + Unicode bidirectional
  controls, the Trojan-Source class) before display. `--local-only` still fails
  closed. Provider bridges still receive prompts via stdin, never argv.
- **Testable without a TTY:** the reader is injectable and the session methods are
  callable directly, so behavior (dispatch, welcome, bounds, cancellation,
  no-secrets, no-tools) is covered by mocked tests with no live APIs.
- Slash-command switches apply to the session only and never rewrite persistent
  defaults; unknown commands are not sent to the model.

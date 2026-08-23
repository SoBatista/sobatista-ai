# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — YouTube connector (read-only)
- Installed-application OAuth 2.0 with loopback redirect, PKCE (S256), and state
  validation; tokens stored only in the OS keyring and redacted everywhere.
- Least-privilege scopes by default (`youtube.readonly`, `yt-analytics.readonly`);
  `--monetary` and `--captions` are separate opt-ins (the latter a broad scope).
- Official APIs only (Data API v3 + Analytics API v2) — never scrapes.
- Commands: `connect/disconnect youtube`, `youtube channel`, `analytics`,
  `compare`, `top`, `video`, `summarize`, `ideas`, `ask`.
- Typed, read-only JSON-Schema tools power `youtube ask` via the bounded tool loop.
- Feature-detection of unsupported metric/dimension combinations; unavailable
  metrics (thumbnail impressions/CTR, new-vs-returning) reported, never fabricated.
- Every report carries date range, timezone (Pacific), freshness, and query/source
  metadata, with observed facts kept separate from labeled AI interpretation.
- Caption/transcript precedence (authorized captions → user-supplied → local
  workflow), with a clear message when no authorized transcript exists.
- Cloud-egress consent + audit and `--local-only` enforcement for AI commands.
- Setup guide and API-limitation docs in `docs/youtube.md`.
- Neutral `core.retry` extracted so connectors and providers share retry/backoff
  without importing each other.

### Added — Phase 1 secure core
- Provider-neutral CLI `sobai` (Typer) with global `--provider/--model/--profile`,
  `--local-only`, `--dry-run`, `--apply`, `--json`, `--quiet`, `--no-color`.
- Providers over async HTTPX: `anthropic` (Messages API), `openai` (Responses
  API), `ollama` (local) — streaming, tool-call parsing, and model discovery.
- Optional CLI bridges `claude-cli` and `codex-cli` that fail safely when absent
  and never accept API keys or silently fall back.
- Provider/model/profile switching with logical model aliases (no hard-coded
  vendor model IDs); `providers list`, `models list`, `models discover`,
  `provider use`, `model use`, `profile create/use/list/delete`.
- Keyring-backed credential storage with runtime secret redaction across output,
  logs, and exceptions.
- Policy engine: `--local-only` hard-fail and cloud-egress consent with data
  classification; privacy audit log.
- Bounded tool-call orchestrator with read/write tool separation.
- SQLite local state: run history (`history`, `runs show`), audit (`audit`),
  tool calls, cache metadata, KB import table.
- `init`, `doctor`, `config show`, `connections`, `privacy explain`,
  `update-check`, `tools`.
- Safe shell wrappers via `aliases install {bash,zsh,fish}` (no `eval`).
- Documentation: README, ARCHITECTURE, SECURITY, PRIVACY, THREAT_MODEL,
  CONTRIBUTING, CODE_OF_CONDUCT, AI_GUIDE, CLAUDE/AGENTS, and ADRs 0001–0003.
- Test suite (unit, provider contract via `respx`, CLI) that runs without any
  live external API.

### Not yet implemented (planned)
- Connectors: YouTube (read-only analytics via OAuth), Notion (read-only search
  & weekly review).
- Natural-language → typed plan routing, `explain-plan`.
- MCP server (`mcp serve/list/doctor`).
- Controlled writes behind `--apply`; GitHub/Jira/website connectors.

_The first tagged release will be `0.1.0` once Phase 1 is complete and reviewed._

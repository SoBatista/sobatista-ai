# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

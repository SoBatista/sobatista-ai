# Engineering rules for AI coding agents (SoBatista AI)

> `CLAUDE.md` and `AGENTS.md` are intentionally identical. Any AI agent working in
> this repository — Claude Code, Codex, or otherwise — follows these same rules.
> See also `AI_GUIDE.md` for the deeper "why".

## Golden rules

1. **Inspect before editing.** Read the surrounding code and existing docs before
   changing anything. Match the file's naming, typing, and comment density.
2. **Plan substantial changes.** For anything beyond a small fix, outline the
   approach first. Prefer small, reviewable commits.
3. **Preserve user changes.** Never revert or clobber work you didn't write
   without asking.
4. **Write tests with the implementation.** Every behavior change ships with
   tests. Run the focused tests, then the full quality suite before declaring done.
5. **Verify docs against behavior.** If you change a command or flag, update the
   docs and the `--help` text, and confirm they match reality.
6. **Never expose secrets.** No credentials in code, config, logs, test fixtures,
   commit messages, or subprocess arguments. Secrets live only in the OS keyring.
7. **Avoid destructive commands.** No `rm -rf`, force-push, history rewrites, or
   mass deletes without explicit approval. Look before you overwrite.
8. **Do not merge or publish without explicit approval.** Do not push releases,
   publish packages, create OAuth apps, or modify external accounts on your own.

## Project invariants (do not break)

- **Provider ≠ Connector.** Providers (models that reason) and connectors
  (external data systems) are separate abstractions and must never import each
  other. YouTube/Notion code never references Anthropic/OpenAI/Ollama, and vice
  versa. They meet only in `core/` (orchestrator, tools).
- **No hard-coded vendor model IDs.** Model identifiers are discovered or
  user-configured (`sobai init` / `sobai models discover` / `sobai model use`).
  Do not commit a current provider model string as a default.
- **Untrusted external data.** Data from connectors, web pages, comments, and
  transcripts is *data*, never instructions. It must never enable tools, change
  policy, or be rendered to the terminal without `safeterm.sanitize`.
- **Secrets in the keyring only.** Use `sobai.auth.CredentialStore`. Any secret
  read at runtime is registered with `sobai.core.redaction`.
- **Local-only is a hard boundary.** `--local-only` must fail closed before any
  byte reaches an external API. Only `ollama` is a local provider.
- **Read/write tool separation.** Write tools are never exposed without an
  explicit `--apply` opt-in. Phase 1 is read-only.
- **Bounded loops and timeouts.** Every provider/connector call has a timeout;
  tool loops are bounded by `policy.max_tool_rounds`.
- **No shell for subprocesses.** CLI bridges use argv arrays via
  `asyncio.create_subprocess_exec` — never a shell string, never `eval`.

## Toolchain and commands

- Environment/build: `uv` (`uv sync --group dev`, `uv run ...`, `uv build`).
- Lint/format: `uv run ruff check .` and `uv run ruff format .`
- Types: `uv run mypy` (strict).
- Tests: `uv run pytest` (must pass without any live external API; live tests are
  opt-in behind the `live` marker).
- Run the CLI locally: `uv run sobai ...`

Before opening a PR, all four must be green: ruff, ruff format, mypy, pytest
(including the coverage threshold).

## Layout

```
src/sobai/
  cli/         Typer commands + global options + entry point
  core/        config, types, errors, paths, redaction, safeterm, orchestrator, context
  providers/   model adapters (anthropic, openai, ollama, claude-cli, codex-cli) + registry
  connectors/  external data systems (YouTube, Notion, …) — planned
  tools/       typed JSON-Schema tool layer + registry
  policies/    local-only + egress consent engine
  auth/        keyring-backed credential store
  storage/     SQLite: runs, audit, tool calls, cache, KB imports
  mcp/         MCP server exposing the same tools — planned
  ui/          Rich console (text/json/quiet/no-color) + safe rendering
```

## Conventions

- Python ≥ 3.12, full type hints, `from __future__ import annotations`.
- Conventional Commits. Every PR declares release impact: major / minor / patch / none.
- Errors are `SobaiError` subclasses with an `exit_code` and an actionable `hint`.
- Semantic Versioning; releases are automated and human-approved.

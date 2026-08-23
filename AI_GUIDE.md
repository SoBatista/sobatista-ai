# AI Guide

This document explains *why* SoBatista AI is built the way it is, for AI agents
(and humans) working on it or extending it. The operational rules are in
[`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md); this is the intent behind them.

## What this project is

An **orchestration layer**, not a model runtime. `sobai` connects models you
already have to tools you have explicitly authorized. Its job is to do that
*safely*, *uniformly*, and *auditably*.

## Mental model: providers vs connectors

Two abstractions that never touch each other:

- **Provider** = a thing that *reasons* (Claude, OpenAI, Ollama, a CLI bridge). It
  emits text and *requests* tool calls. It has no idea what YouTube or Notion are.
- **Connector** = a thing that *has data or can act* (YouTube, Notion, …). It
  exposes typed tools. It has no idea which model is calling it.

The `core/` orchestrator is the only place they meet. This is the single most
important design fact — respect it and everything else composes.

## Security is the product

The reason to use `sobai` instead of curl + a model is the safety boundary:

1. **Secrets never leak.** Keyring-only storage + runtime redaction. If you add
   code that reads a secret, it must go through `CredentialStore` (which registers
   it for redaction). Never log, print, or pass a secret as a subprocess arg.
2. **External data is untrusted.** Treat everything from a connector, URL, or
   document as data. It cannot enable tools, change the system prompt, or run
   shell. Sanitize before displaying (`safeterm`).
3. **The machine boundary is explicit.** `--local-only` fails closed. Cloud
   egress of connector data is classified and consented. No silent fallback.
4. **Actions are bounded and reversible-by-default.** Tool loops are capped;
   writes require `--apply`; read and write tools are separate.

When in doubt, choose the option that leaks less, asks first, and fails closed.

## How to extend it

- **New provider:** implement `providers.base.Provider`, reuse `providers/http.py`
  for HTTP concerns, translate to/from `core.types`, register in
  `providers/registry.py`. Add contract tests with `respx` (no live calls).
- **New connector:** model each capability as a `tools.Tool` with a JSON-Schema
  contract, a `writes` flag, and a `data_class`. Keep OAuth/token handling in the
  connector, secrets in the keyring. Never import a provider.
- **New command:** add to `cli/`, thread everything through `AppContext`
  (dependency injection) — never reach for globals. Support `--json`.

## Verification discipline

- Verify API behavior against official docs when you touch a provider/connector.
- Write the test with the code. Run ruff + mypy + pytest before saying "done".
- Update the docs and `--help` in the same change; they must match behavior.

## What not to do

- Don't invent current vendor model IDs. Discover or ask.
- Don't add a second way to do something that bypasses the safety boundary.
- Don't merge, release, publish, or create external accounts without approval.

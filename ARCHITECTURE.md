# Architecture

SoBatista AI is an orchestration layer, deliberately **not** a model runtime. It
connects models to authorized tools through two strict, dependency-injected
abstractions that never depend on each other.

## The two abstractions

```
        ┌──────────────────────────────────────────────────────────┐
        │                        CLI (Typer)                         │
        │        global options → AppContext (DI container)          │
        └───────────────┬──────────────────────────┬───────────────┘
                        │                          │
                 ┌──────▼──────┐            ┌──────▼──────────┐
                 │  Providers  │            │   Connectors    │
                 │ (reason +   │            │ (fetch/modify   │
                 │  tool calls)│            │  external data) │
                 │ anthropic   │            │ youtube  🚧     │
                 │ openai      │            │ notion   🚧     │
                 │ ollama      │            │ github…  🔭     │
                 │ claude-cli  │            └────────┬────────┘
                 │ codex-cli   │                     │ expose as
                 └──────┬──────┘                     ▼
                        │                     ┌──────────────┐
                        │                     │ Tools layer  │
                        │                     │ JSON-Schema  │
                        │                     │ read / write │
                        ▼                     └──────┬───────┘
                 ┌─────────────────────────────────▼───────────┐
                 │                  Core                         │
                 │  orchestrator (bounded tool loop) · types ·  │
                 │  config · policies · redaction · safeterm    │
                 └───┬───────────┬───────────┬───────────┬──────┘
                     │           │           │           │
                  auth        storage      policies      ui
                (keyring)   (SQLite)   (local-only,   (Rich, json,
                            runs/audit  egress consent) safe render)
```

**Providers** know how to talk to a model: send messages + a system prompt, stream
output, expose typed tool definitions, run tool-call loops, report usage, honor
timeouts/cancellation, and (where supported) discover models. They implement one
interface, `providers.base.Provider`.

**Connectors** know how to talk to an external system (YouTube, Notion, …). They
expose their capabilities as typed **tools** (JSON Schema), classify the data they
return, and are reusable both in-process and (later) over MCP.

The two never import each other. They meet only in `core/` — the orchestrator
runs a provider, and if the provider requests a tool the orchestrator executes it
from the tool registry (subject to policy). This is why *any* model can drive
*any* connector.

## Request lifecycle (`sobai ask`)

1. The root Typer callback builds a `GlobalOptions` and an `AppContext` (config
   store, credential store, UI, DB, policy engine).
2. `resolve_provider` resolves the effective `(provider, model)` from flags →
   profile → active config → provider default, then **enforces `--local-only`**
   before constructing anything.
3. The provider is built from config + keyring credentials (`providers.registry`).
4. The `Orchestrator` runs the provider (streaming or not). With connectors, it
   executes requested tools in a **bounded** loop, feeding results back.
5. The run is recorded in SQLite; egress of connector data is audited.

## Key modules

| Module | Responsibility |
|--------|----------------|
| `core/types.py` | Provider-neutral messages, tool specs, completions, stream events |
| `core/config.py` | Pydantic config model + TOML load/save (no secrets, no model IDs) |
| `core/orchestrator.py` | Generation + bounded tool-call loop; read/write gating |
| `core/redaction.py` | Secret redaction (registry + heuristics) + logging filter |
| `core/safeterm.py` | Strip terminal escape/control sequences from untrusted text |
| `policies/engine.py` | `--local-only` enforcement + egress consent decisions |
| `auth/keyring_store.py` | Keyring-backed credential store with auto-redaction |
| `storage/db.py` | Runs, tool calls, privacy audit, cache metadata, KB imports |
| `providers/*` | Adapters + registry + alias resolution |
| `tools/base.py` | `Tool` ABC + `ToolRegistry` (read/write separation) |
| `ui/console.py` | Rich output with text/json/quiet/no-color + safe rendering |

## Design decisions

Recorded as ADRs in [`docs/adr/`](docs/adr/):

- **ADR-0001** — Separate provider and connector abstractions.
- **ADR-0002** — Raw HTTPX for provider adapters (vs vendor SDKs).
- **ADR-0003** — OS keyring as the only credential store.

## Filesystem locations (XDG, via `platformdirs`)

```
~/.config/sobai/config.toml     configuration (no secrets)
~/.local/share/sobai/state.db   runs, audit, cache metadata, KB imports
~/.cache/sobai/                 regenerable cache payloads
```

All overridable via `SOBAI_CONFIG_DIR` / `SOBAI_DATA_DIR` / `SOBAI_CACHE_DIR`.

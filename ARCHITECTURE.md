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

**Skills** are a third thing, and deliberately the least powerful of the three.
A Skill is a versioned TOML manifest plus a Markdown prompt: prompt and data
only, never code. It is not a provider, not a connector, and not a plugin — it
adds no capability at all. `skills/` depends on `core/` and on the provider
*registry* (the neutral seam), and on no vendor or connector. A Skill run drives
the same orchestrator with no tool registry, so a Skill cannot call a tool
whatever its prompt says. See [`docs/skills.md`](docs/skills.md) and
[ADR-0007](docs/adr/0007-skills-not-executable-plugins.md).

## Request lifecycle (`sobai run NAME` — a Skill)

`sobai run` is bound to the same function as `sobai skills run`, so there is one
execution path. The order is itself a control: everything that can fail without
touching the network fails first.

1. Resolve the Skill from packaged built-ins and `~/.config/sobai/skills/` only,
   refusing an ambiguous short name rather than guessing.
2. Refuse up front if the Skill declares connector tools this run cannot provide.
3. Collect exactly one bounded input (argument, `--file`, or piped stdin) and
   reject binary or invalid content.
4. Validate every variable and render the prompt — the immutable policy first,
   the Skill's text beneath it as subordinate instructions, and the untrusted
   input in a *separate* user message inside boundary markers it cannot forge.
5. Resolve provider and model: CLI flags → `[skills.models]` alias → profile →
   defaults, recording which rule won.
6. **Enforce `--local-only`**, before a provider object exists.
7. Decide egress. Under `--dry-run`, emit the typed plan and stop here — no
   provider, network, or subprocess call is made, and the input is never printed.
8. Obtain consent, failing with instructions when a decision is required and
   there is no terminal.
9. Only now construct the provider and run the orchestrator, with `registry=None`.

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
| `skills/models.py` | Schema-versioned manifest, strict names, typed variables |
| `skills/loader.py` | Packaged built-ins + hostile-directory validation |
| `skills/registry.py` | `builtin:` / `user:` namespaces; no silent shadowing |
| `skills/renderer.py` | Single-pass substitution; policy/skill/input layering |
| `skills/provenance.py` | Stable SHA-256 digest over manifest + prompt |
| `skills/installer.py` | Atomic, race-safe, local-only installation |
| `skills/plan.py` | Typed dry-run plan (reused later by `explain-plan`) |
| `skills/runner.py` | Skill execution via the standard orchestrator |
| `ui/console.py` | Rich output with text/json/quiet/no-color + safe rendering |

## Design decisions

Recorded as ADRs in [`docs/adr/`](docs/adr/):

- **ADR-0001** — Separate provider and connector abstractions.
- **ADR-0002** — Raw HTTPX for provider adapters (vs vendor SDKs).
- **ADR-0003** — OS keyring as the only credential store.
- **ADR-0007** — Skills are prompt/data recipes, not executable plugins.

## Filesystem locations (XDG, via `platformdirs`)

```
~/.config/sobai/config.toml     configuration (no secrets)
~/.config/sobai/skills/         user-installed Skills (the only user Skill source)
~/.local/share/sobai/state.db   runs, audit, cache metadata, KB imports
~/.cache/sobai/                 regenerable cache payloads
```

Skills are never loaded from the working directory, the repository `sobai` is
run inside, `.sobai/`, or any environment-named path — otherwise a checkout
could supply a system prompt merely because you `cd`'d into it.

All overridable via `SOBAI_CONFIG_DIR` / `SOBAI_DATA_DIR` / `SOBAI_CACHE_DIR`.

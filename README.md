# SoBatista AI

**One CLI. Any model. Your tools.**

`sobai` is a provider-neutral AI command-line interface. It is *not* a model
runtime — it is a clean, secure orchestration layer that connects the models you
already use (Anthropic Claude, OpenAI, local Ollama, and optionally the Claude
Code / Codex CLIs) to explicitly authorized external tools (YouTube, Notion, and
more to come).

Built for Linux developers, ethical hackers, content creators, and technical
professionals who want one consistent, auditable interface across every model.

---

## Why SoBatista AI

- **Provider-neutral.** Switch between Claude, OpenAI, and local Ollama models
  with a flag, an alias, or a profile — no code changes, no vendor lock-in.
- **Secure by default.** Credentials live in your OS keyring, never in files.
  Tokens are redacted from all output. External data is treated as untrusted.
  `--local-only` guarantees nothing leaves your machine.
- **Two clean abstractions.** *Providers* reason and request tool calls;
  *connectors* fetch and modify external data. They are never coupled, so any
  model can drive any connector.
- **Auditable.** Every run and every cross-machine data movement is recorded
  locally so you can answer "what left my machine, and where did it go?"

## Status

This is an early, actively developed project. **Phase 1 secure core** is
implemented and working:

| Area | Status |
|------|--------|
| `sobai init`, `doctor`, `config`, `connections` | ✅ working |
| Providers: `anthropic`, `openai`, `ollama` (streaming, tools, discovery) | ✅ working |
| Provider bridges: `claude-cli`, `codex-cli` (fail safe when absent) | ✅ working |
| Provider / model / profile switching + logical aliases | ✅ working |
| Keyring credential storage + redaction | ✅ working |
| `--local-only` enforcement + cloud-egress consent + audit | ✅ working |
| Shell wrappers (`sobai aliases install …`) | ✅ working |
| **YouTube connector** (read-only analytics via OAuth) | ✅ working |
| **Notion connector** (read-only search / pages / weekly-review) | ✅ working |
| Natural-language → typed plan routing, MCP server | 🚧 next |
| Write actions (`--apply`), GitHub/Jira/website connectors | 🔭 roadmap |

See [`docs/adr/`](docs/adr/) for architecture decisions and
[`CHANGELOG.md`](CHANGELOG.md) for release history.

## Install

Requires Python ≥ 3.12.

```bash
# with uv (recommended)
uv tool install sobatista-ai        # once published
# or from a checkout
uv tool install .

# with pipx
pipx install sobatista-ai
```

For local development:

```bash
git clone https://github.com/sobatistacyber/sobatista-ai
cd sobatista-ai
uv sync --group dev
uv run sobai --help
```

On Linux, a Secret Service provider (gnome-keyring, KWallet, or equivalent) must
be installed and unlocked for credential storage. Run `sobai doctor` to check.

## Five-minute setup

```bash
sobai init          # detects your Claude Code / Codex subscriptions + Ollama first
sobai doctor        # verifies providers, auth/billing mode, keyring, and connectors
sobai ask "Explain this error"
```

`init` leads with **subscription-authenticated CLIs** (Claude Code, Codex) and
local Ollama; direct Anthropic/OpenAI API access is an optional, clearly-labeled
"separate metered billing" choice. It never asks you to edit a config file, and
never writes secrets to disk. See [`docs/subscriptions.md`](docs/subscriptions.md).

## Usage

```bash
# Interactive session (run in a terminal with no subcommand)
sobai                        # opens a conversational session (/help for commands)
sobai -p ollama -m qwen14b   # preselect a provider/model for the session
sobai --local-only           # session that refuses any cloud egress
# (non-interactive `sobai` prints guidance instead of hanging; use `sobai ask` in scripts)

# Ask any provider (one-shot; ideal for automation)
sobai ask "Explain this error"
sobai ask --provider claude  "Review this architecture"
sobai ask --provider openai  "Review this architecture"
sobai ask --provider ollama --model qwen2.5-coder:14b "Review this code"

# Pipe context in
git diff | sobai ask "Summarize these changes"

# Switch defaults
sobai providers list
sobai models list
sobai models discover --provider ollama
sobai provider use claude
sobai model use ollama:qwen2.5-coder:14b

# Subscription CLIs (use the CLI's own login; no API key, no metered billing)
sobai -p codex-cli  -m default ask "Hello"
sobai -p claude-cli -m default ask "Hello"

# Local usage & cost visibility (labeled actual / estimated / unavailable)
sobai usage
sobai usage --period 30d --provider claude-cli

# Short flags and profiles
sobai -p ollama -m qwen14b ask "..."
sobai profile create creator
sobai profile use creator

# YouTube (read-only, official APIs — see docs/youtube.md for setup)
sobai connect youtube                      # installed-app OAuth (PKCE), tokens -> keyring
sobai youtube channel
sobai youtube analytics --period 30d
sobai youtube top --period 90d --metric watch-time --limit 10
sobai youtube compare --period 30d --previous
sobai youtube ask --provider claude "Explain my last 30 days"

# Notion (read-only, official API — see docs/notion.md for setup)
sobai connect notion                       # integration token (hidden prompt) -> keyring
sobai notion search "roadmap"
sobai notion recent --since 7d
sobai notion weekly-review --provider claude
sobai notion ask --provider claude "What did I work on this week?"

# Privacy controls
sobai --local-only ask "..."        # hard-fails if anything would leave the machine
sobai privacy explain
sobai audit
sobai config show --redacted
sobai connections

# Keep the installed tool fresh after the checkout changes
sobai update --source .     # validate + remember this checkout
sobai update                # reuse the remembered checkout, from anywhere
sobai update --check        # just check for a newer release

# Safe shell shortcuts (no eval; args forwarded verbatim)
sobai aliases install bash  # yb-claude, yb-cx, notion-claude, notion-cx, sobai-update
sobai aliases install zsh
sobai aliases install fish
```

### Keeping the installed tool updated

When the local `sobatista-ai` checkout changes (e.g. after edits), refresh the
globally installed `sobai` from it — no `git`, no network, no publishing:

```bash
cd /path/to/sobatista-ai
sobai update --source .     # validates the checkout and remembers its path
sobai update                # later runs reuse the remembered path
```

`update` validates the source (`pyproject.toml` project name must be
`sobatista-ai`), builds it, reinstalls with `uv tool install --force`, and
verifies the result — all via safe argv arrays (never a shell). The generated
`sobai-update` wrapper simply forwards to `sobai update`.

Everything supports `--json` for automation, plus `--quiet` and `--no-color`.

### Provider comparison

| Provider | Kind | Auth | Streaming | Tools | Discovery |
|----------|------|------|-----------|-------|-----------|
| `anthropic` | cloud | API key (keyring) | ✅ | ✅ | `/v1/models` |
| `openai` | cloud | API key (keyring) | ✅ | ✅ | `/v1/models` |
| `ollama` | **local** | none | ✅ | ✅ | `/api/tags` |
| `claude-cli` | cloud (bridge) | the CLI's own login | one-shot | — | — |
| `codex-cli` | cloud (bridge) | the CLI's own login | one-shot | — | — |

The CLI bridges use the installed CLI's **own** authentication (e.g. a Claude
Code / ChatGPT subscription). SoBatista AI never treats a subscription as an API
key, and never silently falls back from one provider to another.

## Privacy boundary

- Local providers (Ollama) never send data off your machine.
- `--local-only` fails closed before any external call.
- Connector data is classified `public` / `internal` / `sensitive` / `restricted`.
  Before it is sent to a cloud model you are shown what connector and class will
  leave — unless you have set an explicit persistent policy.

See [`PRIVACY.md`](PRIVACY.md) and [`SECURITY.md`](SECURITY.md).

## Screenshots / terminal recordings

Terminal recordings are not yet committed. We do not fabricate screenshots. To
contribute a recording, run the exact commands you want shown and capture them
(e.g. with [`asciinema`](https://asciinema.org/)); see
[`docs/screenshots.md`](docs/screenshots.md) for the requested captures and
filenames.

## Troubleshooting

- **`No usable OS keyring backend`** — install/unlock gnome-keyring or KWallet,
  then `sobai doctor`.
- **`No model selected`** — run `sobai init`, or pass `-m` / `sobai model use …`.
- **Ollama unreachable** — start it with `ollama serve`; check `sobai doctor`.
- **Cloud call under `--local-only`** — expected: it fails closed by design.

## Roadmap

- **Now:** YouTube read-only analytics ([docs](docs/youtube.md)) and Notion
  read-only search/pages/weekly-review ([docs](docs/notion.md)).
- **Next:** natural-language plan routing (`--dry-run`/`explain-plan`), MCP
  server, GitHub/Jira.
- **Later:** controlled writes behind `--apply` with preview/confirmation.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
AI agents working in this repo must follow [`CLAUDE.md`](CLAUDE.md) /
[`AGENTS.md`](AGENTS.md).

## License

[MIT](LICENSE).

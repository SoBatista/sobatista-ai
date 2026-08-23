# Subscription-authenticated CLI providers

SoBatista AI treats your installed **Claude Code** and **Codex** CLIs as
first-class providers that use their **own subscription login** (a Claude
subscription / a ChatGPT subscription). This is a distinct mode from direct
Anthropic/OpenAI **API** access, which is separately metered billing.

## Setup

```bash
sobai init
```

`init` detects what you already have and leads with subscriptions:

```text
Detected model access
  ✓ Ollama        installed, 4 local models
  ✓ Claude Code   authenticated via Claude subscription (max)
  ✓ Codex CLI     authenticated via ChatGPT
  ○ Anthropic API not configured — separate usage billing
  ○ OpenAI API    not configured — separate usage billing

Choose your default:
  1. Codex CLI (ChatGPT subscription)
  2. Claude Code CLI (Claude subscription)
  3. Ollama (local)
  4. Configure direct API access
```

Detection is safe: executables are found with `shutil.which`, and authentication
is read with the CLI's own status subcommand (`claude auth status`,
`codex login status`) via an argv array with a short timeout. SoBatista AI never
reads credential files (`~/.claude/.credentials.json`, `~/.codex/auth.json`),
never imports CLI credentials into its keyring, and never displays your account
identity. A subscription tier is shown only when the status output states one.

If a CLI is installed but not logged in, `init` offers to launch its own login
(`claude auth login` / `codex login`) — only after you confirm, and never in
non-interactive/CI runs.

## Using a subscription provider

```bash
sobai -p codex-cli  -m default ask "Hello"
sobai -p claude-cli -m default ask "Hello"

sobai provider use claude-cli && sobai model use claude-subscription
sobai provider use codex-cli  && sobai model use codex-subscription
```

### The `default` model sentinel

`init` creates aliases without inventing vendor model IDs:

```toml
[models]
claude-subscription = "claude-cli:default"
codex-subscription  = "codex-cli:default"
```

`default` is a **documented internal sentinel** meaning *"let the installed CLI
select its configured default model."* SoBatista AI never passes
`--model default` to either CLI — when the model is the sentinel, the `--model`
flag is simply omitted.

No provider ever silently falls back to an API or to another CLI. If the chosen
bridge is unavailable or unauthenticated, the command fails on that provider.

## Security hardening of the bridges

For an ordinary `sobai ask`, both bridges are locked down and each flag is
feature-detected against the installed CLI — if a required boundary cannot be
enforced, the bridge **fails closed**.

**Claude Code** (`claude -p --output-format json`):

- prompt delivered over **stdin** (never argv / process list)
- `--tools ""` — all built-in tools disabled
- `--strict-mcp-config --mcp-config '{"mcpServers":{}}'` — no MCP servers
- `--safe-mode` — no CLAUDE.md, hooks, plugins, custom commands/agents
- `--disable-slash-commands`, `--no-session-persistence`, `--setting-sources ""`
- runs from an application-controlled empty working directory
- `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` stripped from the environment so
  the subscription login is used (we do **not** use `--bare`, which the official
  docs state does not use subscription login)

**Codex** (`codex exec --json`):

- prompt delivered over **stdin** via the supported `-` form
- `--sandbox read-only` (never `workspace-write` or `danger-full-access`)
- `--ephemeral`, `--skip-git-repo-check`, and an empty working directory
- `--ignore-user-config`, `--ignore-rules`
- `-c tools.web_search=false`, `-c mcp_servers={}` to disable web search and MCP
- `OPENAI_API_KEY` / `CODEX_API_KEY` stripped so the ChatGPT login is used
- final assistant text from `--output-last-message`; usage from the
  `turn.completed` event
- never uses `--yolo`, `--dangerously-bypass-approvals-and-sandbox`, or
  `danger-full-access`

## Usage & cost visibility

```bash
sobai usage
sobai usage --period 30d
sobai usage --provider codex-cli
sobai runs show RUN_ID
```

Each run records provider, model (or `provider-default`), billing mode, tokens
(input, cached-input, reasoning, output when reported), duration, tool rounds,
and a cost figure labeled by how it was obtained:

| Provider | Billing shown | Cost |
|----------|---------------|------|
| `claude-cli` | `subscription` | `total_cost_usd` when returned, labeled an **API-equivalent client estimate** — *not* an amount billed to your subscription |
| `codex-cli` | `subscription` | token usage recorded; **no monetary cost** (unavailable) |
| `anthropic` / `openai` | `metered-api` | any calculated cost is an **estimate** |
| `ollama` | `local` | API cost **$0** (excludes hardware/electricity) |

**Your provider's billing dashboard is always authoritative.**

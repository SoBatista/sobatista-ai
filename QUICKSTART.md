# Quickstart

Get productive with SoBatista AI (`sobai`) in five minutes.

## 1. Install

Requires Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
# from a local checkout
uv tool install .
# or, once published
uv tool install sobatista-ai      # or: pipx install sobatista-ai
```

On Linux, a Secret Service keyring (gnome-keyring / KWallet) must be installed
and unlocked for credential storage — `sobai doctor` checks this.

## 2. Set up

```bash
sobai init
```

`init` detects what you already have and leads with **subscriptions**:

```text
Detected model access
  ✓ Ollama        installed, 4 local models
  ✓ Claude Code   authenticated via Claude subscription (max)
  ✓ Codex CLI     authenticated via ChatGPT
  ○ Anthropic API not configured — separate metered billing
  ○ OpenAI API    not configured — separate metered billing

Choose your default:
  1. Codex CLI (ChatGPT subscription)
  2. Claude Code CLI (Claude subscription)
  3. Ollama (local)
  4. Configure direct API access
```

Direct API keys are optional and clearly labeled as separate metered billing.
See [`docs/subscriptions.md`](docs/subscriptions.md).

## 3. Chat or ask

Run `sobai` with no arguments in a terminal to open an interactive session
(type `/help` for commands, `/exit` to quit). For scripts and one-shots, use
`sobai ask`:

```bash
sobai                                  # interactive session
sobai ask "Explain this error"
sobai -p codex-cli  -m default ask "Summarize this design"
sobai -p ollama -m qwen2.5-coder:14b ask "Review this code"
git diff | sobai ask "Summarize these changes"
```

## 4. See what you're spending

```bash
sobai usage
sobai usage --period 30d --provider claude-cli
```

Costs are labeled `actual` / `estimated` / `unavailable`; `claude-cli` cost is an
API-equivalent client estimate, never a subscription charge. Vendor dashboards
are authoritative.

## 5. Keep the installed tool fresh

When the local `sobatista-ai` checkout changes, refresh the globally installed
`sobai` from it:

```bash
cd /path/to/sobatista-ai
sobai update --source .        # validates + remembers this checkout
# later, from anywhere:
sobai update                   # reuses the remembered checkout
sobai update --check           # just check for a newer release
sobai update --yes             # skip the confirmation prompt
```

`update` validates the checkout, builds it, then reinstalls with
`uv tool install --force` and verifies the result — using safe argv arrays only,
and never running `git`, fetching remote code, or publishing anything.

## Connect your tools (read-only)

```bash
sobai connect youtube      # YouTube analytics — see docs/youtube.md
sobai connect notion       # Notion (integration token via hidden prompt) — see docs/notion.md
sobai notion search "roadmap"
sobai notion weekly-review --provider claude
```

Notion reads only pages/databases you explicitly share with your integration;
the token is stored only in your OS keyring.

## Handy extras

```bash
sobai doctor                       # verify providers, auth/billing, keyring
sobai providers list               # billing + auth at a glance
sobai --local-only ask "..."       # hard-fail if anything would leave the machine
sobai aliases install bash         # yb-claude, yb-cx, notion-claude, sobai-update, …
sobai --json ask "..."             # machine-readable output
```

More: [`README.md`](README.md), [`PRIVACY.md`](PRIVACY.md),
[`SECURITY.md`](SECURITY.md).

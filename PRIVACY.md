# Privacy

SoBatista AI is designed so you always know what leaves your machine and where it
goes. This document describes the privacy boundary and the controls you have.

## What stays local

- **Your credentials.** API keys and OAuth tokens live in your OS keyring on your
  machine. They are never uploaded, never written to config or logs.
- **Local model use.** When you use a local provider (Ollama), your prompts and
  data never leave the machine.
- **Local state.** Run history, the audit log, and cache metadata are stored in a
  local SQLite database (`~/.local/share/sobai/state.db`), readable only by you.

## What can leave your machine

Only when you use a **cloud** provider (Anthropic, OpenAI) or a **CLI bridge**
(Claude Code, Codex, which relay to their cloud backends):

- The prompt and any context you include (e.g. piped input) are sent to that
  provider's API under your own account.
- When connectors are enabled, connector data you ask a cloud model to analyze is
  sent to that provider — subject to the egress policy below.

SoBatista AI itself has no servers and collects no telemetry.

## Data classification

Connector data is labeled with one of four classes:

| Class | Meaning | Default egress policy |
|-------|---------|-----------------------|
| `public` | Already public information | allow |
| `internal` | Your own routine data | ask |
| `sensitive` | Private or personal data | ask |
| `restricted` | Highly sensitive | deny |

Before connector data of a given class is sent to a cloud model, you are shown
exactly what connector and class will leave — unless you have configured a
persistent policy for that class in `config.toml` (`[policy.egress]`).

**Notion** content is classified `internal` by default. `notion search`,
`recent`, and `projects` are deterministic and never call a model; `summarize`,
`weekly-review`, and `ask` send retrieved Notion content to the selected
provider, subject to the egress rules above (local Ollama keeps it on-machine;
`--local-only` hard-fails before any cloud disclosure). The Notion integration
token lives only in your OS keyring. See [`docs/notion.md`](docs/notion.md).

## Controls

```bash
sobai --local-only ...     # hard-fail if anything would leave the machine
sobai privacy explain      # show the boundary and your effective policy
sobai audit                # what data class left, to which provider, when
sobai config show --redacted
sobai connections          # what is connected
sobai disconnect <name>    # remove stored credentials
```

## Retention & deletion

- Everything is on your machine. Delete `~/.config/sobai/`,
  `~/.local/share/sobai/`, and `~/.cache/sobai/` to remove all local state.
- Remove credentials with `sobai disconnect <provider|connector>`.
- Data already sent to a third-party model provider is subject to *that
  provider's* retention policy — review their terms.

## A note on retrieved content

Content retrieved from external systems is treated strictly as data. It is never
executed, never used to change SoBatista AI's behavior, and is sanitized before
being shown in your terminal.

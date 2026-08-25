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
  It records *that* a run happened and its shape — never your prompts or the
  model's answers. See [Run history](#run-history) below.

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

## Skills

A Skill is a recipe, not a data source. Running one sends **only what you
explicitly supplied** — a positional argument, a `--file`, or piped stdin — plus
the Skill's own prompt. A Skill never fetches a URL found in your input, never
opens a path found in it, and never reaches any external system.

Each Skill recommends a data classification and `--data-class` overrides it; the
default is `internal`, and `builtin:security-review` recommends `sensitive`. The
ordinary egress rules then apply, so a local provider keeps everything on the
machine and `--local-only` hard-fails before any cloud disclosure.

**What is recorded is identity and shape, never content.** A Skill run's history
entry is summarised as `skill builtin:summarize@1.0.0` — not your input. The
audit record holds the Skill's qualified name, version, and digest, and the
input's source, size, and SHA-256 hash. Your prompt and the model's output are
not stored, and neither is anything a connector returned.

That input hash is provenance, not confidentiality: it lets you prove two runs
used the same input without disclosing it, but a **short or predictable** input
could be guessed and confirmed against the hash by someone who already had your
database. Nothing else records a hash of what you typed.

`--dry-run` shows exactly what *would* be sent, described by size and hash
rather than content, so a plan is safe to paste into a ticket or a CI log.

Skills you write are private by default: they live in `~/.config/sobai/skills/`,
are never uploaded, and are never shared unless you copy them somewhere yourself.

## Run history

Every model-backed command — `sobai ask`, the interactive session, `sobai run`,
and the connector `ask` commands — records one row in the local run history. The
row is **content-free**: it describes the run rather than quoting it.

| Recorded | Not recorded |
|---|---|
| command, provider, model, profile, `local-only` | your prompt, or any part of it |
| billing/auth mode, token counts, cost kind, duration, tool rounds | the model's answer |
| status and exit code | connector content |
| a summary such as `ask · stdin · 412 bytes · 409 chars` | a hash or digest of your prompt |

The summary is deliberately not a prompt digest. A hash cannot be reversed, but
a short or predictable question can simply be guessed and checked against it,
and nothing here needs to correlate two runs by content.

Audit records follow the same rule: they hold what data *class* left the
machine, to which provider, via which connector — never the data.

### Databases from earlier development builds

Development builds before 0.2.0 stored the **first 200 characters of each
prompt** in the run summary for `ask`, the session, and the connector `ask`
commands. If you ran one of those builds, rows already in your database still
contain those prefixes; nothing rewrites or deletes your history behind you.

To check, and to clear it if you want to:

```bash
sobai --json history --limit 100   # review every summary you still have
sobai runs show <run-id>           # inspect one row, including its summary
rm ~/.local/share/sobai/state.db   # discard all local run history and audit records
```

Removing the database is a full reset of local history and the audit log; a new
one is created on the next run. There is no selective-erase command, and this
document will not invent one.

## Controls

```bash
sobai --local-only ...     # hard-fail if anything would leave the machine
sobai privacy explain      # show the boundary and your effective policy
sobai audit                # what data class left, to which provider, when
sobai --dry-run run NAME --file f.md   # what would be sent, without sending it
sobai skills paths         # where skills load from, and what is never searched
sobai config show --redacted
sobai connections          # what is connected
sobai disconnect <name>    # remove stored credentials
```

## Interactive session

The `sobai` interactive session keeps its conversation **in memory for the
current process only** — the full conversation content is never written to disk,
and command-line history is kept in memory only (no history file). Each turn is
recorded in the local run history/usage log as metadata only (provider, model,
token counts, cost kind, and a content-free summary), the same as `sobai ask`.
`/clear` drops the in-memory conversation immediately.

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

These defenses **reduce prompt-injection risk; they do not eliminate it.** The
durable guarantees are the ones outside the model — no tools during a Skill run,
no shell, no filesystem, no network, no silent egress, and `--local-only` failing
closed. What a model *says* in response to hostile input is not a guarantee any
prompt arrangement can make, so treat model output as untrusted too.

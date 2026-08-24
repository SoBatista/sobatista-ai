# Skills

A **Skill** is a versioned, inspectable task recipe: a TOML manifest plus a
Markdown prompt. It transforms input you explicitly supply, through whichever
provider you have configured.

```bash
sobai skills list
cat article.md | sobai run summarize
sobai run explain-code --file src/parser.py --var audience=reviewer
sobai --dry-run run security-review --file diff.patch
```

`sobai run NAME` and `sobai skills run NAME` are the same command — the top-level
spelling is bound to the same function, so there is exactly one execution path.

## What a Skill is, and is not

A Skill is **prompt and data only**. It adds no capability to the system.

| A Skill is | A Skill is not |
|---|---|
| A reusable task recipe | A Python module or plugin |
| Provider-neutral | Tied to any vendor or model |
| Typed and schema-validated | Free-form text with `{{holes}}` |
| Namespaced and versioned | Silently overridable |
| Content-addressed by SHA-256 | Anonymous |
| Private by default when you write it | Automatically shared or downloaded |

It cannot execute code, call a tool, open a file, reach the network, spawn a
process, read an environment variable, or change any policy. Those are not
restrictions applied to Skills — there is simply no code in the Skills package
that can do them. See [ADR-0007](adr/0007-skills-not-executable-plugins.md).

## Related concepts, kept separate

These are distinct ideas, deliberately not merged:

| Concept | Meaning | Status |
|---|---|---|
| **Skill** | One reusable task recipe | Available |
| **Strategy** | An optional prompt transformation applied to a Skill | Deferred |
| **Context** | Named reusable supporting material injected into a run | Deferred |
| **Workflow** | A typed composition of Skills and connectors | Deferred |
| **MCP** | An external protocol adapter exposing tools | Deferred |

A Skill is not a connector: connectors fetch external data and expose typed
tools. A Skill never fetches anything.

## Built-in Skills

| Skill | Purpose | Data class | Variables |
|---|---|---|---|
| `builtin:summarize` | Faithful summary at a chosen depth | internal | `length` |
| `builtin:extract-insights` | Substantive ideas, stated vs inferred | internal | `count` |
| `builtin:analyze-claims` | Claims and how well the material supports them | internal | — |
| `builtin:explain-code` | What supplied code does, for a chosen audience | internal | `audience` |
| `builtin:security-review` | Defensive review of supplied material | **sensitive** | — |
| `builtin:creator-ideas` | Grounded content ideas from supplied material | internal | `count`, `format` |
| `builtin:rewrite` | Rewrite preserving meaning exactly | internal | `tone`, `audience`, `length` |

Every built-in prompt is original work written for SoBatista AI. See
[Acknowledgements](acknowledgements.md).

## Namespaces and precedence

Skills live in exactly two namespaces:

- `builtin:` — the pack shipped inside the installed package.
- `user:` — Skills you installed into `~/.config/sobai/skills/`.

A short name resolves **only when it is unambiguous**. If both namespaces hold a
Skill of that name, `sobai` refuses to guess:

```console
$ sobai run security-review --file diff.patch
✗ 'security-review' is ambiguous: it matches builtin:security-review, user:security-review.
  Use the fully qualified name, e.g. `builtin:security-review`.
```

This is the point of the namespace design. A Skill you install can never
*replace* a built-in one by taking its name — the worst it can do is make the
short name ambiguous, which you are told about before anything runs.

The namespace is assigned by **where a Skill was loaded from**, never read from
its manifest, so a user Skill cannot claim to be a built-in.

### Name syntax

Names are strict and portable: lowercase ASCII letters, digits, and single
hyphens, starting with a letter, at most 64 characters. Path separators,
traversal, control characters, non-ASCII look-alikes, leading or trailing
hyphens, and reserved names (`builtin`, `user`, `con`, `nul`, `com1`…) are all
rejected. A Skill name becomes a directory name, so it must be safe to be one.

## Where Skills come from

```console
$ sobai skills paths
User skills     ~/.config/sobai/skills
Built-in skills sobai.skills.builtin

Never searched
  · the current working directory
  · the repository you are running inside
  · ./.sobai/
  · paths named by environment variables
  · any remote or network location
```

### Why the current directory is never searched

If `sobai` loaded Skills from the directory it happens to be run in, then
cloning a repository and typing `sobai run summarize` inside it would let that
repository supply your system prompt. Untrusted content would be promoted from
data to instructions by nothing more than your working directory.

So it does not happen. There is no auto-discovery, no `.sobai/skills`
convention, and no environment variable that adds a search path. A Skill runs
only if you installed it, on purpose, with `sobai skills install`.

### Why remote installation is deferred

Installing from a URL means trusting a network fetch to deliver a system prompt.
Doing that safely needs signatures, a trust root, pinning, and revocation — none
of which exist yet. Until they do, the answer is: clone it yourself, read it,
and install the directory. `sobai skills install` accepts only a local path.

## Installing a Skill

```bash
sobai skills validate ./my-skill      # check it without installing
sobai skills install ./my-skill       # copy it into ~/.config/sobai/skills/
sobai skills install ./my-skill --force   # replace a different version
sobai skills show user:my-skill       # read exactly what will be sent
```

Validation is unforgiving, on purpose. A Skill directory must contain exactly
`skill.toml` and `prompt.md` — nothing else. Symlinks, hard links, device files,
FIFOs, oversized files, invalid UTF-8, binary content, filenames that differ only
in case, and terminal-control or Unicode bidirectional characters in the text are
all refused rather than cleaned up.

That last one is worth naming: a prompt containing a right-to-left override can
**display** differently from how it reads. A prompt nobody can review honestly is
not installable.

Installation is atomic (staged, then a single rename), race-safe (an exclusive
lock), and faithful — the bytes written are the bytes that were validated and
hashed, held in memory, so a source directory modified mid-install cannot
substitute different content. A failed replacement rolls back to the previous
version.

## The Skill format

```
my-skill/
  skill.toml
  prompt.md
```

### `skill.toml`

```toml
schema_version = 1

[skill]
name = "security-report"          # lowercase, hyphens, matches the directory
version = "1.0.0"                 # exact SemVer
description = "Turn a scan export into a prioritized report."
author = "Your Name"
license = "private"               # an SPDX id, or "private"
tags = ["security", "reporting"]

[input]
description = "A vulnerability scanner export in text form."
required = true
max_bytes = 262144
max_chars = 200000

[output]
format = "markdown"               # markdown | text | json
description = "A ranked report with evidence and remediation."
# schema = { type = "object", ... }   # optional JSON Schema, for format = "json"

[policy]
recommended_data_class = "sensitive"   # public | internal | sensitive | restricted
required_tools = []                    # declaring a need, never a grant

[[variables]]
name = "audience"
type = "string"                   # string | integer | number | boolean
description = "Who the report is for."
required = false
default = "an engineering team"
choices = ["an engineering team", "an executive"]   # optional closed set
max_length = 60

[provenance]
source = "internal security tooling"
created = "2026-08-24"
notes = "Original prompt."
```

Every field is validated, and **unknown keys are an error** — a Skill that asks
for something this build does not understand fails loudly instead of running as
if the request had been honoured.

Two things a manifest may **not** contain:

- **A provider or model id.** Per-Skill model preference is user configuration,
  not part of the recipe, so a shared Skill never pins you to a vendor.
- **A namespace.** It is assigned by where the Skill loads from.

`schema_version` is the format contract. A Skill declaring a version newer than
your build refuses to run and tells you to upgrade.

### `prompt.md`

Plain Markdown, with `{{variable}}` placeholders for variables the manifest
declares. Nothing else is interpreted.

## Writing a good Skill prompt

The built-ins follow a shape worth copying:

1. **One sentence of purpose** — what this Skill does to the input.
2. **The work** — what to produce, and what to leave out.
3. **Honesty rules** — what the model must not invent, and what it must say when
   the material does not support an answer.
4. **An explicit output contract** — the exact shape of the answer, and what must
   *not* appear (preamble, process commentary, invented identifiers).

Some rules that consistently pay off:

- Tell it to distinguish **stated** from **inferred**, and to attach a basis to
  each claim it makes.
- Tell it what it *cannot* see. A Skill has no repository, no analytics, no
  browser, and no earlier conversation. Saying so stops confident invention.
- Make "I cannot do this with what I was given" an explicit, acceptable answer.
- Do not ask for hidden reasoning to be disclosed; ask for the conclusion and
  its evidence.
- Do not write vendor-specific instructions. The same Skill runs on a local
  7B model and a frontier cloud model.

### Variables

Variables carry **parameters**, not content. They are scalars, validated before
anything is sent, and capped at 512 characters — bulk text belongs in the input.

```bash
sobai run rewrite "..." --var tone=formal --var length=shorter
```

An unknown name, a missing required value, a wrong type, or a value outside a
declared `choices` set fails immediately, with the declared list in the hint.

## Safe rendering

The renderer does exactly one thing: substitute values for variables the
manifest declared, after validating them. There is no expression language, so
there is nothing to escape into.

Not supported — by construction, not by filtering: `eval`, Python expressions,
Jinja or any other execution, attribute access, function calls, loops,
conditionals, includes, filters, environment expansion, filesystem reads,
network access, command substitution, shell interpolation, dynamic imports.

Substitution is a **single pass**. A value that happens to contain `{{other}}`
produces those literal characters; it is never rescanned as template source.

A placeholder must be a bare declared name. Anything else is a clear error
rather than silent passthrough:

```console
$ sobai skills validate ./my-skill
✗ invalid placeholder '{{ config.SECRET }}' in the prompt.
  A placeholder must be a bare declared variable name, e.g. {{language}} —
  expressions, filters, attribute access, and function calls are not supported.
```

## Layering: policy, Skill, input

Every run is assembled in three layers that never mix:

```
┌─ system ─────────────────────────────────────────────┐
│ 1. SoBatista AI policy   (immutable, always first)   │
│ 2. The Skill's prompt    (labelled, subordinate)     │
└──────────────────────────────────────────────────────┘
┌─ user message ───────────────────────────────────────┐
│ 3. Your input, inside explicit boundary markers       │
└──────────────────────────────────────────────────────┘
```

The immutable policy states that input is data and never instructions, that the
run has no tools, no shell, no filesystem, and no network, that credentials are
never revealed or requested, that facts and citations are never fabricated, and
that a missing source must be reported rather than imagined.

A Skill prompt is **subordinate** to that policy. It cannot override privacy
policy, enable a connector or tool, raise tool rounds or size limits, request
credentials, authorize writes, disable redaction, bypass `--local-only`, or
select an external data source.

Your input never reaches the system layer. It is a separate user message inside
boundary markers, and any text in the input that impersonates those markers is
defanged first, so input cannot close its own block and pose as instructions.

## Input

Exactly one source per run:

```bash
sobai run summarize "Text passed directly"
sobai run summarize --file article.md
cat article.md | sobai run summarize
```

- Passing both a positional argument and `--file` is an error, not a precedence
  rule.
- stdin is used only when neither is given, so a pipe your script inherited
  cannot silently replace the argument you passed.
- With no input and stdin attached to a terminal, the run fails immediately with
  instructions. It never blocks waiting for someone to type, which is what makes
  `sobai run` safe in a script or CI job.
- Input is bounded in both bytes and decoded characters, per Skill.
- Binary content, invalid UTF-8, directories, devices, and FIFOs are refused
  with an actionable message.

Input is inert. A URL inside it is never fetched, a path inside it is never
opened, a command inside it is never run.

## Choosing a model per Skill

Precedence, most specific first:

1. `-p/--provider` and `-m/--model` on the command line
2. `[skills.models]` in `~/.config/sobai/config.toml`
3. the active profile
4. the configured default provider and model

```toml
[skills.models]
"builtin:summarize" = "fast"
"user:security-report" = "qwen14b"
```

Keys are **fully qualified** names, and values are **logical aliases** already
defined in `[models]` — never vendor model ids. That keeps the mapping portable
and means a Skill you share never carries a model preference at all.

`sobai skills show NAME` and `--dry-run` both print which rule won and why:

```console
  model          ollama/qwen2.5:7b ([skills.models] maps 'builtin:summarize' to alias 'fast')
```

## Dry run

`--dry-run` builds a typed plan and stops. It makes **no** provider, connector,
network, or subprocess call, and needs no credentials configured.

```console
$ sobai --dry-run run summarize --file article.md
Plan builtin:summarize 1.0.0 (nothing was sent)
  digest         sha256:f7c97f27ac5f5ad2429e5800f39f226bf7b0c6bbbfee5fbcaaf2e434eabbe24b
  input          file · 4821 bytes · 4821 chars
  input digest   sha256:3b1f…
  data class     internal (skill-recommendation)
  provider       ollama
  model          qwen2.5:7b
  model source   config-default — the configured default provider and model
  leaves machine no (local provider)
  egress         allow — local provider — data does not leave the machine
  requires tools none
  limits         input ≤ 262144B / 200000 chars · output ≤ 4096 tokens · timeout 120s
  shape          1 provider call, 0 tools, streaming on, writes off

Input content is never printed or transmitted by --dry-run.
```

The plan describes your input by **source, size, and hash** — never by content —
so it is safe to paste into a ticket or capture in CI logs. `--json` returns the
same plan as a typed document.

This is a deterministic Skill execution plan, not the general natural-language
planner. Its typed models are written to be reused by the later `explain-plan`
work.

## Data classification and egress

```bash
sobai run summarize --data-class public   --file public-post.md
sobai run summarize --data-class internal --file plan.md
sobai run summarize --data-class sensitive --file notes.md
```

Each Skill recommends a class; `--data-class` overrides it. The default is
`internal` — conservative, because most of what you pipe into a Skill is your
own work. `builtin:security-review` recommends `sensitive`.

The existing egress policy then applies. Before anything leaves for a cloud
provider you are shown the Skill, the data class, the destination provider and
model, and the input's source and size:

```console
! About to send [internal] data from skill 'user:security-report' to cloud provider 'anthropic'.
• skill user:security-report@1.0.0 · input file (notes.md), 4821 bytes · destination anthropic/some-model
Allow this data to leave your machine? [y/N]
```

- **Non-interactive runs never bypass this.** If policy requires a decision and
  there is no terminal, the run fails with instructions — it does not proceed.
- `restricted` is denied outright by default.
- `--local-only` hard-fails **before** a provider object is constructed, a
  credential is read, or a byte is prepared. It never silently switches to
  Ollama or anything else.

## What is recorded

A Skill run records identity and shape, never content:

- Run history: command, provider, model, tokens, cost kind, duration, and the
  summary `skill builtin:summarize@1.0.0` — not your input.
- Audit: the Skill's qualified name, version, and digest; the input's source,
  size, and hash; the data class and destination provider.

Your prompt and the model's output are not stored. See [PRIVACY.md](https://github.com/SoBatista/sobatista-ai/blob/main/PRIVACY.md).

## Provenance

Every Skill carries a stable SHA-256 digest over its normalized manifest and
prompt, so the same content always yields the same digest regardless of TOML key
order, line endings, or trailing whitespace.

```bash
sobai skills show builtin:summarize   # digest, source, author, licence, prompt
sobai skills list --json | jq '.skills[] | {qualified_name, version, digest}'
```

The digest is what you quote in a review. It is computed, never asserted by the
author, and it identifies exactly the bytes that will be sent.

## JSON output

Every command has a stable, versioned, discriminated JSON document:

| Command | `kind` |
|---|---|
| `skills list` | `skill-list` |
| `skills show` | `skill-detail` |
| `skills validate` | `skill-validation` |
| `skills install` | `skill-install` |
| `skills paths` | `skill-paths` |
| `run --dry-run` | `skill-run-plan` |
| `run` | `skill-run-result` |
| any failure | `{"error": {...}}` |

No decorative text appears in JSON mode; the whole of stdout is one document.

## In the interactive session

`/skills` lists what is available and shows how to run one. The session does not
execute Skills yet — doing so would create a second path around the input
bounds, egress consent, and audit that `sobai run` enforces, and that deserves
its own review.

## Pipelines

Skills compose through the shell, because their input and output are just text:

```bash
cat transcript.md \
  | sobai run summarize --var length=brief \
  | sobai run creator-ideas --var count=5
```

Each stage is a separate, independently audited run with its own policy check.
Typed in-process composition is the **Workflow** concept above, and is deferred.

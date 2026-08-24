# Acknowledgements

## Fabric

The Skills system in SoBatista AI was influenced conceptually by
**[Fabric](https://github.com/danielmiessler/Fabric)** by Daniel Miessler, which
popularised the idea of a named, reusable library of task-specific prompts —
"Patterns" — invoked from a command line over piped input. Fabric is MIT
licensed, as is SoBatista AI.

The official repository was inspected on **2026-08-24** for its README, Pattern
documentation and directory layout, custom-Pattern behaviour, Strategies,
Contexts, and the chaining ("stitches") concept.

### No Fabric material is reused

**Every built-in Skill prompt in SoBatista AI is original work written for this
project.** No Fabric prompt text, source code, documentation, branding, or
directory structure has been copied or adapted, so no Fabric attribution is
owed beyond the acknowledgement on this page. Should any protectable Fabric
content ever be reused, its MIT attribution would be preserved explicitly here
and in the affected file — but the intent is to keep that unnecessary.

The two projects are also not compatible: a Fabric Pattern is a directory of
Markdown, while a SoBatista Skill is a schema-versioned TOML manifest plus a
prompt. Neither can load the other's files, and nothing here claims otherwise.

### What was adopted

- The core idea: named, reusable task recipes as a first-class CLI concept.
- stdin-oriented execution, so a Skill composes with ordinary shell pipelines.
- A short, memorable invocation (`sobai run summarize`).
- Distinguishing built-in recipes from ones a user writes and keeps private.

### What was adapted, and why

| Fabric idea | What SoBatista AI does instead | Why |
|---|---|---|
| Pattern = `system.md` (+ optional files) | `skill.toml` manifest + `prompt.md`, schema-versioned | Typed validation, declared variables, licence, provenance, and a stable digest |
| Custom Patterns configured via a setup wizard | Explicit `sobai skills install PATH` into `~/.config/sobai/skills/` | Installation should be a deliberate act with validation, not a remembered directory |
| Per-pattern model via an environment variable | `[skills.models]` in config, mapping to logical aliases | Config is reviewable and diffable; aliases keep the mapping provider-neutral |
| `--dry-run` previews the assembled prompt | Typed, zero-call execution plan reporting sizes and hashes | A plan you can capture in CI without disclosing the input |
| `-v` variables | `--var name=value`, declared in the manifest and validated by type | Unknown, missing, or ill-typed variables fail before a provider is contacted |

### What was deliberately rejected

- **A user Pattern silently overriding a built-in of the same name.** SoBatista
  AI uses `builtin:` / `user:` namespaces and reports an ambiguity instead. A
  user Skill must never quietly replace `security-review`.
- **Auto-loading recipes from a directory the tool happens to be run in.** Only
  packaged built-ins and the user's own Skills directory are ever searched, so a
  repository cannot supply a system prompt. See
  [ADR-0007](adr/0007-skills-not-executable-plugins.md).
- **Built-in URL scraping, YouTube fetching, and file attachments as part of
  running a recipe.** Retrieving external data is a *connector* concern with its
  own authorization, classification, and audit. A Skill never fetches anything.
- **A general template engine inside prompts.** Substitution is limited to
  declared scalars; there is no expression language to escape from.
- **An HTTP serving mode.** Exposing tools over a protocol is the deferred MCP
  work, which needs its own threat model.

### Deferred, and kept distinct

Fabric's **Strategies** (prompt transformations), **Contexts** (reusable
supporting material), **Sessions**, and **stitches** (chaining Patterns) are all
useful ideas. They are deliberately *not* folded into the Skill format: each is
named as a separate future concept in [Skills](skills.md) so that the recipe
format does not accumulate them field by field. Typed composition is the
Workflow concept; chaining works through ordinary shell pipes today.

## Others

- **[Typer](https://typer.tiangolo.com/)** and **[Rich](https://rich.readthedocs.io/)**
  for the CLI and terminal rendering.
- **[Pydantic](https://docs.pydantic.dev/)** for the typed schemas that make
  manifest validation strict and cheap.
- The **[Trojan Source](https://trojansource.codes/)** research, which is why a
  Skill carrying Unicode bidirectional controls is refused rather than cleaned:
  a prompt that displays differently from how it reads cannot be reviewed.

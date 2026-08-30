# ADR-0007: Skills are prompt/data recipes, not executable plugins

- Status: Accepted
- Date: 2026-08-24
- Related: [ADR-0001](0001-provider-connector-separation.md) (provider/connector
  separation), [ADR-0005](0005-interactive-session.md) (session scope)

## Context

Users want to save and reuse task-specific prompts — summarize this the way I
always summarize things, review this diff the way our team reviews diffs — and
to share them. Prompt-library projects have shown the shape works;
[Fabric](https://github.com/danielmiessler/Fabric) popularised it as "Patterns"
(inspected 2026-08-24). The demand is real and the ergonomics are proven.

The question is what a saved recipe is *allowed to be*.

The tempting answer is an extension point: let a Skill ship Python, declare
dependencies, register tools, add commands. That is how most CLI ecosystems
grow, and it makes the first ten use cases trivial.

It also inverts this project's security model. SoBatista AI's entire value over
`curl` plus a model is a boundary: secrets stay in the keyring, external data is
data and never instructions, `--local-only` fails closed, writes need `--apply`,
tool loops are bounded. Every one of those controls assumes the code deciding
what to do is code the user installed deliberately and can review. An executable
Skill is arbitrary code obtained for its prompt, and it would sit *inside* the
boundary — able to read the keyring, spawn processes, and reach the network,
with none of the review a dependency gets.

Two further pressures pointed the same way:

1. **Discovery is an injection vector.** Prompt libraries conventionally
   auto-load from a configured directory, and some tools search the working
   directory. If `sobai` did that, cloning a repository and running `sobai run`
   inside it would let that repository supply the system prompt — promoting
   untrusted content to instructions via nothing but `cd`.
2. **Name collision is a privilege question.** The usual convention is that a
   user's own pattern silently overrides a built-in of the same name. Applied to
   `security-review`, that means anything that can write one file can replace
   the prompt a user believes they are running, invisibly.

## Decision

**A Skill is a TOML manifest plus a Markdown prompt. Nothing else.**

- **No executable content.** No Python, no shell, no declared dependencies, no
  registered tools, no commands. The Skills package contains no code that can
  execute, fetch, or open anything, so a Skill's inability to do those things is
  structural rather than a check that could be forgotten.
- **A Skill adds no capability.** It may *declare* required connector tools, but
  declaring is not granting: a Skill needing tools that are unavailable is
  refused, never quietly run without them. Skills execute with no tool registry
  at all.
- **A Skill is subordinate to system policy.** The immutable policy layer is
  always first in the system prompt; the Skill's text follows, explicitly
  labelled as subordinate. It cannot change privacy policy, raise limits,
  request credentials, authorize writes, disable redaction, or bypass
  `--local-only`.
- **The renderer is minimal by construction.** Single-pass substitution of
  declared scalars. No expression language exists to escape from.
- **Two namespaces, and no silent shadowing.** `builtin:` and `user:`. A short
  name that matches both is an actionable ambiguity error naming both
  candidates. The namespace is assigned by load location, never read from the
  manifest.
- **Explicit installation only.** Packaged built-ins and `~/.config/sobai/skills/`
  are the only sources. The working directory, the repository, `.sobai/`, and
  environment-named paths are never searched. Remote installation is deferred
  until signing and a trust root exist.
- **Content-addressed.** A SHA-256 digest over the normalized manifest and
  prompt is computed, never asserted, and shown wherever a Skill is identified.

## Consequences

- A Skill is safe to read, diff, review, and share the way a configuration file
  is. The worst a malicious one can do is produce bad output from input you
  already chose to supply — it cannot reach your keyring, your filesystem, or
  the network.
- Some genuinely useful things are out of reach for Skills: fetching a URL,
  querying an API, post-processing with a script. Those are **connectors** and
  **workflows**, which have their own review and their own trust boundary. Users
  will occasionally want a Skill to do one of them; the correct answer is to
  point at the other abstraction rather than to widen this one.
- Sharing a Skill is a copy-and-install flow, not a package install. That is
  more friction than `sobai skills install <url>`, and it is friction we are
  choosing until the supply-chain story is real.
- The no-shadowing rule means a user Skill named after a built-in makes the
  short name unusable rather than taking it over. This is mildly annoying and
  exactly the intent: the annoyance is visible, whereas a silent override is not.
- Strategies, Contexts, Workflows, and MCP remain separate, named, deferred
  concepts. Keeping them out of the Skill format is what stops "just one more
  field" from turning a recipe back into a plugin.

## Alternatives considered

- **Executable plugins with a permission manifest.** Rejected: a permission
  system for in-process Python is only as strong as the sandbox behind it, and
  there is no sandbox here. Declaring `network = false` in a manifest does not
  make `import httpx` fail.
- **Sandboxed execution (subprocess, WASM).** Rejected for now: a real sandbox
  is a large, ongoing security commitment, and nothing in the current use cases
  needs one. Prompts cover them.
- **A general template engine (Jinja).** Rejected: template engines are an
  execution environment, and their sandbox-escape history is long. Variable
  substitution is all a recipe needs.
- **Silent user-over-builtin precedence.** Rejected, as above.
- **Auto-loading from the working directory.** Rejected, as above.

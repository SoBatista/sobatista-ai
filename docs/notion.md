# Notion connector (read-only)

SoBatista AI connects to Notion through the **official Notion API**. The
integration can read only the pages and databases you **explicitly share** with
it, and Phase 1 is strictly read-only: nothing is ever created, edited, archived,
restored, commented on, or deleted.

## 1. Create a personal/internal integration (you do this once)

SoBatista AI never creates or modifies a Notion integration for you.

1. Go to <https://www.notion.so/my-integrations> and **create a new integration**
   (type: internal). Give it a name.
2. Under **Capabilities**, keep only **Read content** (SoBatista AI never writes).
3. Copy the **Internal Integration Secret** (the token). Keep it private — it is
   entered later through a hidden prompt, never on the command line.

## 2. Share pages/databases with the integration

The integration sees **nothing** until you share content with it. In Notion, open
a page or database → **•••** menu → **Connections** → add your integration.
Sharing a page also shares its child pages. Repeat for each top-level page or
database you want SoBatista AI to read.

## 3. Connect (without exposing the token)

```bash
sobai connect notion
```

You'll be prompted (hidden input) for the integration token. It is validated
against the API (`GET /v1/users/me`) and stored **only in your OS keyring** —
never in config, environment files, SQLite, arguments, logs, exceptions, or the
audit log. Disconnect and remove it anytime:

```bash
sobai disconnect notion
```

## 4. Use

```bash
sobai notion search "roadmap"
sobai notion recent --since 7d
sobai notion projects
sobai notion summarize PAGE_ID_OR_URL
sobai notion weekly-review --since 7d --provider claude
sobai notion ask --provider claude "What did I work on this week?"
```

- `search`, `recent`, and `projects` are **deterministic** (no AI provider is
  called).
- `summarize`, `weekly-review`, and `ask` require a provider; for cloud providers
  they prompt for cloud-egress consent (or honor your policy) and record the
  egress in `sobai audit`. Use `--local-only -p ollama` to keep everything local.

Every report keeps **observed facts** (retrieved from Notion, with page
title/URL/timestamp source references) separate from any **AI interpretation**,
which is always clearly labeled. `--json` gives machine-readable output.

Page references accept a 32-character page id or a `notion.so` URL; arbitrary or
non-Notion URLs are refused (we only extract an id and look it up via the API).

## What the connector can read

- **Search** (`POST /v1/search`) — pages and data sources shared with the
  integration, matched by **title**.
- **Pages** (`GET /v1/pages/{id}`) — properties, timestamps, URL, parent.
- **Block content** (`GET /v1/blocks/{id}/children`) — paragraphs, headings,
  lists, to-dos (checked/unchecked), quotes, callouts, toggles, and code, read
  recursively within explicit depth/total bounds.

## API limitations & behavior (documented, never fabricated)

- **Only shared content is visible.** Anything not shared with the integration
  is invisible; requests for it return 404/403, reported clearly as "not shared".
- **Search matches titles**, not full text, and returns items by
  `last_edited_time` order.
- **Data sources vs databases.** On the current API version (`2026-03-11`) a
  database is represented by **data sources**; search returns `data_source`
  objects. The connector feature-detects `page` / `data_source` (and legacy
  `database`) rather than assuming one shape.
- **Traversal is bounded** (default depth 4, total 400 blocks per page; per-page
  scan limits for weekly-review). Deeply nested or very large pages are
  truncated, and the report says so. Cycles and duplicate blocks are prevented;
  child pages/databases are recorded as references but not traversed (they are
  separate shared objects); synced-block mirrors are skipped to avoid duplicates;
  unsupported block types are counted, never invented.
- **Rate limits.** ~3 requests/second per integration. HTTP 429 responses (and
  529 overloads) are retried honoring the `Retry-After` header (seconds), with
  bounded retries and timeouts.
- **`projects` is heuristic** — pages/data sources whose title contains
  "project"/"initiative"/"epic". It is not authoritative; no dedicated project
  database is assumed.
- **`weekly-review` observed sections** (created, edited, completed/open tasks,
  decisions, blockers, projects) come from to-do blocks and documented keyword
  heuristics and may miss or over-match; recurring topics / gaps are AI
  interpretation, clearly separated.

## Privacy boundaries

- Notion content is classified **internal** by default. Before it is sent to a
  **cloud** model (Anthropic, OpenAI, or a subscription CLI) the egress policy
  applies: you are shown that the connector is `notion` and the data class, and
  are asked for consent unless a persistent policy allows it.
- `--local-only` with a local Ollama provider keeps everything on your machine
  and **hard-fails** before any Notion content would reach an external provider.
  Providers never silently switch.
- Retrieved Notion content is treated as untrusted **data**, not instructions: it
  cannot change policy, enable tools, raise limits, request secrets, or authorize
  writes, and terminal escape sequences are stripped before display.

## Troubleshooting

- **"not found or not shared" (404)** — share the page/database with your
  integration (step 2); confirm the id/URL.
- **"access denied" (403)** — the integration lacks access; re-share, or check
  its capabilities include reading content.
- **"authentication failed" (401)** — the token is wrong/revoked; re-run
  `sobai connect notion`.
- **Rate limited** — the connector backs off and retries automatically; heavy
  use across many pages may still hit workspace limits.
- **Empty results** — nothing is shared with the integration yet, or search by
  title didn't match.

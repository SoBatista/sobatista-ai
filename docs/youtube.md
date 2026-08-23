# YouTube connector (read-only)

SoBatista AI connects to YouTube through the **official** YouTube Data API v3 and
YouTube Analytics API v2. It never scrapes YouTube or YouTube Studio. All access
is read-only, authorized by you via installed-app OAuth, and your tokens live only
in your OS keyring.

## 1. Create a Google Desktop OAuth client (you do this once)

SoBatista AI cannot create an OAuth application for you. Create your own:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create
   (or select) a project.
2. **APIs & Services → Library**: enable **YouTube Data API v3** and
   **YouTube Analytics API**.
3. **APIs & Services → OAuth consent screen**: configure it. While the app is in
   "Testing", add your own Google account under **Test users**.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   choose **Desktop app**. You'll get a **client ID** and **client secret**.
5. You do **not** need to add a redirect URI manually — Desktop clients allow the
   loopback redirect (`http://127.0.0.1:<port>`) that SoBatista AI uses.

Keep the client ID and secret handy for the next step. They are not the same as an
API key, and SoBatista AI never writes them to disk in plaintext.

## 2. Connect

```bash
sobai connect youtube                 # read-only analytics + data (least privilege)
sobai connect youtube --monetary      # also request revenue analytics (separate consent)
sobai connect youtube --captions      # also request caption access (broad scope; see below)
sobai connect youtube --no-browser    # print the auth URL instead of opening a browser
```

You'll be prompted (hidden input) for the client ID and secret, a browser opens for
Google's consent screen, and the loopback listener captures the result. The flow
uses **PKCE (S256)** and validates the CSRF **state**. Tokens are stored in the OS
keyring and refreshed automatically.

Scopes requested:

| Flag | Scope | Purpose |
|------|-------|---------|
| (default) | `youtube.readonly` | channel/video/caption metadata (read) |
| (default) | `yt-analytics.readonly` | non-monetary analytics |
| `--monetary` | `yt-analytics-monetary.readonly` | revenue metrics |
| `--captions` | `youtube.force-ssl` | list/download **your own** captions ⚠️ |

> ⚠️ `youtube.force-ssl` is a broad, read/write-capable scope (it also permits
> editing videos and comments). SoBatista AI only ever performs read operations,
> but you are granting more than read. It is off by default and only requested
> when you pass `--captions`.

Disconnect and remove tokens at any time:

```bash
sobai disconnect youtube
```

## 3. Use

```bash
sobai youtube channel
sobai youtube analytics --period 30d
sobai youtube analytics --start 2026-07-01 --end 2026-07-31
sobai youtube compare --period 30d --previous
sobai youtube top --period 90d --metric watch-time --limit 10
sobai youtube video VIDEO_ID_OR_URL --period 30d
sobai youtube summarize VIDEO_ID_OR_URL --transcript path/to/transcript.txt
sobai youtube ideas --period 90d --provider claude
sobai youtube ask --provider claude "Check my last 30 days and explain the trends"
```

Deterministic commands (`channel`, `analytics`, `compare`, `top`, `video`) never
call a model. The AI commands (`summarize`, `ideas`, `ask`) require a provider and,
for cloud providers, prompt for cloud-egress consent (or honor your configured
policy) and record the egress in `sobai audit`. Use `--local-only` to forbid any
cloud egress.

Every report shows its **date range, timezone, freshness, and the exact
query/source metadata**, keeps **observed facts** separate from any **AI
interpretation**, and adds `--json` for automation.

## Important API limitations (SoBatista AI never fabricates around these)

- **Thumbnail impressions and impression click-through rate (CTR) are not
  available** in the public YouTube Analytics API — they exist only in YouTube
  Studio. Reports say so and omit them; they are never estimated.
- **New vs. returning viewers** has no API dimension/filter — reported as
  unavailable, never guessed.
- **Reporting timezone is Pacific Time** (`America/Los_Angeles`); day boundaries
  follow it. Every report states the timezone.
- **Data freshness:** analytics typically finalize after ~24–72 hours, so the most
  recent day(s) of a relative window may be incomplete. Every report notes this.
- **Metric/dimension constraints** (enforced by the API; we feature-detect and
  report cleanly, never fabricate):
  - Top-videos reports require a sort and cap at `maxResults = 200`.
  - `averageViewPercentage` cannot be combined with `liveOrOnDemand`.
  - For video-dimensioned reports, `#videos × #days` must not exceed 50,000.
  - Invalid combinations return HTTP 400 `badRequest`; SoBatista AI surfaces this
    as "this metric/dimension/filter combination is not supported."
- **Captions:** `captions.download` works only for videos you can edit (your own
  channel); others return 403. It requires the `--captions` scope and costs 200
  quota units per download. Auto-generated (ASR) track download may be restricted
  by Google.
- **Quota:** Data API calls cost quota (most reads are 1 unit; caption downloads
  200). Analytics API has its own separate query quota. Heavy use can hit limits.

## Transcript precedence for `summarize`

1. **Authorized captions** from your own channel (only if `--captions` was granted).
2. A **transcript you supply** with `--transcript FILE`.
3. An explicitly authorized local media/transcript workflow (not implemented yet).

If none is available, `summarize` says so plainly and does **not** invent a
transcript. SoBatista AI never scrapes arbitrary public captions.

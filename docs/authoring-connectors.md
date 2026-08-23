# Authoring a connector

A **connector** is an external data system (YouTube, Notion, …). Connectors
expose typed tools and must never import providers — the two abstractions meet
only in `core/`. See
[ADR-0001](adr/0001-provider-connector-separation.md) and the engineering rules
in [CLAUDE.md](https://github.com/SoBatista/sobatista-ai/blob/main/CLAUDE.md).

## The interface

Subclass `sobai.connectors.base.Connector` and expose a `ToolRegistry`:

```python
from sobai.connectors.base import Connector, ConnectorStatus
from sobai.core.classification import DataClass
from sobai.tools.base import Tool, ToolRegistry


class MyConnector(Connector):
    name = "myconnector"
    data_class = DataClass.INTERNAL  # default classification of its data

    def is_connected(self) -> bool: ...
    def status(self) -> ConnectorStatus: ...
    def tools(self) -> ToolRegistry: ...
```

Each tool subclasses `sobai.tools.base.Tool`:

```python
class SearchTool(Tool):
    name = "myconnector.search"
    description = "Search items the integration can access."
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    writes = False  # Phase 1 is read-only
    data_class = DataClass.INTERNAL

    async def run(self, arguments: dict[str, Any]) -> str: ...
```

Follow the existing layout (see `connectors/notion/` and `connectors/youtube/`):
`client.py` (raw httpx client), `auth.py` (keyring token), `tools.py` (Tool
subclasses), `connector.py` (the `Connector`), plus focused helpers.

## Rules to follow

- **Read/write separation.** Write tools set `writes=True` and are exposed only
  behind an explicit `--apply` opt-in. Phase 1 connectors are **read-only**
  (`writes=False`).
- **Untrusted data.** Everything a connector returns is *data, not
  instructions*: it can never enable a tool, change policy, raise limits, request
  secrets, or authorize writes. Sanitize any text rendered to the terminal with
  `safeterm.sanitize`.
- **Classification & egress.** Set an accurate `data_class`
  (`public`/`internal`/`sensitive`/`restricted`). Cloud egress of connector data
  is gated by the policy engine and recorded (metadata only) in the audit log.
- **Credentials** live only in the OS keyring via `CredentialStore` and are
  registered with `sobai.core.redaction`. Never store a token in TOML, env,
  SQLite, argv, logs, exceptions, fixtures, or audit records.
- **Robust I/O.** Every HTTP call has a timeout; honor `Retry-After`; bound any
  traversal with cycle/duplicate prevention. Accept only well-formed identifiers
  (e.g. ids or the provider's own URLs), never arbitrary URLs.
- **Never import a provider.** Connectors are provider-agnostic; any model can
  drive any connector.

## Testing

- Mock HTTP with `respx`; tests pass with **no live API and no real
  credentials**.
- Cover the untrusted-data guarantees (injection attempts, terminal-escape
  stripping), token redaction, bounded traversal, and error/rate-limit handling.

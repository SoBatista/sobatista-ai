# ADR-0003: OS keyring as the only credential store

- Status: Accepted
- Date: 2026-08-23

## Context

The tool handles multiple secrets: provider API keys, OAuth client secrets, and
OAuth token bundles. Common but unsafe places to keep them are TOML config,
`.env` files, environment variables, and — worst — subprocess arguments (visible
in the process table) or shell history.

## Decision

Store **all** secrets in the OS keyring (Secret Service / libsecret / KWallet)
via the `keyring` library, namespaced under the `sobai` service
(`auth/keyring_store.py`). Configuration (`config.toml`) holds no secrets — only
non-sensitive metadata (which account, granted scopes, timestamps).

Any secret read at runtime is immediately registered with the redaction engine
(`core/redaction.py`) so it is scrubbed from all output, logs, and exceptions.
OAuth token bundles are stored as a single JSON keyring entry.

## Consequences

- Secrets never touch disk in plaintext, shell history, or argv.
- Requires a working Secret Service backend on Linux; `sobai doctor` diagnoses
  its absence and gives actionable guidance, and credential writes fail closed
  with a clear error if none is available.
- Tests use an in-memory keyring backend so no real secret store is touched.

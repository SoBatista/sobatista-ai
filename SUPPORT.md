# Support

Thanks for using SoBatista AI. Here is how to get help.

## Before asking

1. Run `sobai doctor` — it checks providers, auth/billing mode, keyring, and
   connectors and usually pinpoints setup problems.
2. Check the [README](README.md) (install, five-minute setup, troubleshooting)
   and the topic docs under [`docs/`](docs/).
3. Search [existing issues](https://github.com/SoBatista/sobatista-ai/issues).

## Where to ask

- **Bug reports** and **feature requests:** open an issue using the
  [issue forms](https://github.com/SoBatista/sobatista-ai/issues/new/choose).
- **Questions / discussion:** open a normal issue describing what you are trying
  to do.
- **Security vulnerabilities:** do **not** open a public issue. Report privately
  via [Security Advisories](https://github.com/SoBatista/sobatista-ai/security/advisories/new)
  — see [`SECURITY.md`](SECURITY.md).

## When reporting a problem

Include your OS, Python version, `sobai --version`, the exact command, and the
output. **Never paste real credentials or tokens** — `sobai` redacts secrets from
its own output, but double-check anything you copy from elsewhere. `sobai config
show --redacted` is safe to share.

## Support scope

This is an early, actively developed project maintained on a best-effort basis.
Only the most recent released version is supported (see
[`RELEASING.md`](RELEASING.md) and [`SECURITY.md`](SECURITY.md#supported-versions)).

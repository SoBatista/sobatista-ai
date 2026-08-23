# Maintainers

Maintainers review and merge changes, cut releases, and safeguard the project's
security invariants. See [`GOVERNANCE.md`](GOVERNANCE.md) for roles and
decision-making.

| Maintainer | GitHub | Areas |
|------------|--------|-------|
| SoBatista  | [@SoBatista](https://github.com/SoBatista) | Overall, security, providers, connectors, releases |

> The GitHub handles here and in [`.github/CODEOWNERS`](.github/CODEOWNERS) must
> match accounts (or teams) that actually have write access to the repository.
> Verify them when onboarding a new maintainer.

## Becoming a maintainer

Sustained, high-quality contributions and good judgment on the project's
security invariants are the path to maintainership. Existing maintainers extend
an invitation by consensus.

## Responsibilities

- Uphold the [project invariants](GOVERNANCE.md#project-invariants) in review.
- Keep security-sensitive areas (auth, policies, redaction, workflows, release
  config) under owner review via [`CODEOWNERS`](.github/CODEOWNERS).
- Follow [`RELEASING.md`](RELEASING.md) for every release; never publish without
  the documented checks passing.

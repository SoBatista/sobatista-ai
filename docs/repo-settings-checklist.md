# Repository settings handoff checklist

The code and workflows in this repository are configured for a hardened OSS
release pipeline, **but the following are GitHub/PyPI account settings that a
maintainer must apply manually.** This automation intentionally does **not**
change any repository, organization, or PyPI settings, create environments or
secrets, register OAuth apps, or publish anything.

Work top to bottom. Items marked **(required to publish)** must be done before
the first real release.

## GitHub — repository settings

- [ ] **Default branch** is `main`.
- [ ] **Branch protection / ruleset on `main`:**
  - [ ] Require a pull request before merging (≥ 1 approval; 2 once there are
        multiple maintainers).
  - [ ] Require review from Code Owners.
  - [ ] Require status checks to pass, and select at least: `Lint, type-check,
        test (py3.12)`, `(py3.13)`, `Build distribution`, `Install smoke`,
        `Docs (mkdocs strict) + link check`, `Lockfile consistency`, the
        `Security` jobs (actionlint, zizmor, secret scan, license policy),
        `Dependency Review`, `CodeQL`, and `Validate release-impact declaration`.
  - [ ] Require branches to be up to date before merging.
  - [ ] Require linear history (optional but recommended).
  - [ ] Do not allow force pushes or deletions.
- [ ] **Tag protection rule** for `v*` so only maintainers can create release tags.
- [ ] **Actions → General:**
  - [ ] Workflow permissions default to **read-only**; "Allow GitHub Actions to
        create and approve pull requests" can stay **disabled** — no workflow
        here opens pull requests (see ADR-0006).
  - [ ] Fork PRs from outside collaborators require approval to run workflows.

## GitHub — security features

- [ ] **Secret scanning** and **push protection** enabled.
- [ ] **Dependabot alerts** and **security updates** enabled (config already in
      `.github/dependabot.yml`).
- [ ] **Code scanning**: this repo uses the committed **advanced** CodeQL
      workflow — ensure default CodeQL setup is **off** to avoid duplication.
- [ ] **Private vulnerability reporting** enabled (Security Advisories) — matches
      the link in `SECURITY.md`.

## Labels

- [ ] **`release:major`**, **`release:minor`**, **`release:patch`** exist.
      Every pull request needs exactly one; `PR release metadata` fails
      without it (see ADR-0006 and `RELEASING.md`).

## Tokens / secrets

- [ ] **No personal access token is needed.** `release.yml` triggers on a
      successful CI `workflow_run`, which fires normally for `GITHUB_TOKEN`,
      so nothing depends on a long-lived credential to cascade.
- [ ] No PyPI API token is needed or wanted (publishing uses OIDC).

## GitHub — release environment **(required to publish)**

- [ ] Create an **Environment** named `pypi`.
- [ ] Add **required reviewers** (the maintainers) so every publish is manually
      approved.
- [ ] Optionally restrict the environment to the `main` branch / `v*` tags.

## PyPI — Trusted Publishing **(required to publish)**

- [ ] Register the project name `sobatista-ai` on PyPI (or use "pending
      publisher" before the first upload).
- [ ] Add a **Trusted Publisher** (GitHub Actions):
  - Owner: `SoBatista`
  - Repository: `sobatista-ai`
  - Workflow: `release.yml`
  - Environment: `pypi`
- [ ] (Recommended) Configure the same on **TestPyPI** first and do a dry-run
      pre-release to validate the pipeline end to end.

## OpenSSF Scorecard (optional, recommended)

- [ ] For the public Scorecard API/badge, no token is required for public repos
      (`scorecard.yml` uses OIDC). If you later make results private or run on a
      schedule that needs elevated read, add a `SCORECARD_TOKEN` PAT.

## Verify CODEOWNERS

- [ ] Confirm every handle/team in `.github/CODEOWNERS` and `MAINTAINERS.md`
      actually has write access; CODEOWNERS silently ignores unknown owners.

## Incident response (credential/publisher compromise)

1. Disable the PyPI Trusted Publisher for `release.yml` and delete the `pypi`
   environment (or remove its reviewers) to stop all publishing immediately.
2. Review recent Actions runs and the audit log for unexpected publishes.
3. Yank affected versions on PyPI and ship a corrected patch (see
   [`RELEASING.md`](https://github.com/SoBatista/sobatista-ai/blob/main/RELEASING.md)).
5. Re-establish the Trusted Publisher and environment only after review.

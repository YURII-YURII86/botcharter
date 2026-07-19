# Public release checklist

## Repository hygiene

- [ ] Working tree is clean.
- [ ] No absolute home, mounted-volume, drive-letter, or private infrastructure paths are tracked.
- [ ] No `.env`, token, database, log, session, credential, or user export is tracked.
- [ ] Public examples are synthetic or explicitly licensed.
- [ ] No private project names, architecture counts, table/event registries, or closed-audit results are published.
- [ ] Commit authors use a public noreply address; no local-host email is present.

## Product surface

- [ ] README explains the problem, audience, limits, and ten-minute workflow.
- [ ] Russian entrypoint links to the English source of truth.
- [ ] LICENSE, SECURITY, CONTRIBUTING, and CHANGELOG are present.
- [ ] Version is a PEP 440 prerelease.
- [ ] Public demo passes without private repositories or network access.

## Verification

- [ ] JSON and YAML artifacts parse.
- [ ] All synthetic smoke tests pass.
- [ ] Wheel and source distribution build.
- [ ] Source tree, complete public Git history, wheel, and source archive pass secret and indirect-disclosure scans.
- [ ] Wheel installs into a clean virtual environment.
- [ ] Installed `botctl --help` works.
- [ ] Installed public demo passes.
- [ ] CI passes on supported Python versions.

## Publication — requires explicit owner approval

- [ ] Create a public GitHub repository.
- [ ] Configure private vulnerability reporting.
- [ ] Add final project URLs to `pyproject.toml`.
- [ ] Push the release branch.
- [ ] Create a signed or annotated prerelease tag.
- [ ] Publish to TestPyPI first.
- [ ] Install and verify the TestPyPI artifact.
- [ ] Publish to PyPI only after TestPyPI verification.
- [ ] Announce as public alpha, not as an industry standard.

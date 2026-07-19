# Handoff

- Current state: BotCharter `0.8.0a1` (CLI `botctl`) is undergoing a privacy remediation before any renewed public release. Runtime apply remains deliberately blocked.
- Last verified step: the GitHub repository and prerelease were made private after superseded public commits were found to expose a local-host author email and current files were found to contain private project names and architecture fingerprints. Public profiles/specs/docs are being replaced with fictional artifacts and stronger release checks. PyPI/TestPyPI publication has not been performed.
- Safety: target modules are not imported; `.env`, databases, logs, sessions, `.botctl`, and unsafe paths are skipped; no network or target writes occur.
- Next step: finish synthetic tests and archive inspection, create a new clean public-history candidate, verify it independently, then replace the private GitHub repository. Do not publish to TestPyPI/PyPI before that review.
- Main risks: static heuristics may need adapters for dynamically generated handlers/SQL; audit findings are specification drift, not proof that the live bot is broken.

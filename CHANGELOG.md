# Changelog

All notable public changes will be documented here.

## [0.8.0-alpha.1] - Unreleased

First BotCharter public-alpha candidate.

### Added

- one-command guarded adoption of existing projects;
- machine-readable architecture, UX, storage, dependency, event, and contract specs;
- design artifact review, confirmation, ChangePlan approval, and design gate;
- read-only Python source audit with portable bot profiles;
- explicit PID/heartbeat, HTTP HEAD, and immutable SQLite probes;
- installable CLI, CI smoke tests, and reproducible public demo.

### Safety

- runtime apply remains disabled;
- source audit does not import target code or access secrets, databases, logs, or networks;
- probes require explicit targets and confirmation where external access occurs.

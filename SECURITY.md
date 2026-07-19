# Security policy

## Supported version

Only the latest public-alpha release receives security fixes.

## Reporting a vulnerability

Do not open a public issue containing tokens, personal data, private repository content, production paths, or exploit details. Contact the maintainers privately through the security-reporting channel configured on the public repository. Until that channel exists, do not publish sensitive details.

## Safety boundaries

`botctl` source audit:

- does not import or execute target modules;
- skips `.env`, databases, logs, sessions, credentials, secrets, virtual environments, and `.botctl`;
- does not contact a network or write to the target project.

`botctl adopt`:

- is preview-only without `--confirm`;
- creates only a new `.botctl/` directory;
- refuses to overwrite any existing `.botctl/`;
- does not modify root `AGENTS.md` or runtime source;
- removes the newly created control directory if verification fails.

Explicit probes:

- require an explicit PID, file, URL, or database path;
- require `--confirm-network` before one HTTP HEAD request;
- require `--confirm-database-read` before immutable SQLite access;
- never accept tokens, cookies, authorization headers, arbitrary SQL, or deployment commands.

## Out of scope in the public alpha

- production code generation or mutation;
- service restart, container control, SSH, or deployment;
- Telegram API calls;
- secret-manager access;
- automatic remediation of audit findings.

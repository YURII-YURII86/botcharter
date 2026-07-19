# Documentation rules

These rules exist to prevent `CONTEXT.md`, ADRs and specs from becoming stale prose.

## 1. CONTEXT.md maintenance

`CONTEXT.md` is the operational orientation document. It answers:

- why this project exists;
- which runtime bot is the current reference example;
- where to inspect the reference bot;
- how to compare specs with runtime reality;
- what is production truth;
- what the current first milestone is.

### Update CONTEXT.md when

- the reference runtime bot changes;
- a new reference bot is added;
- the audit workflow changes;
- production truth changes in a way that affects audits;
- the first milestone / current milestone changes;
- important paths in the reference bot change;
- a new class of incident becomes part of the motivation.

### Do not put in CONTEXT.md

- daily implementation notes;
- long debug history;
- volatile command output;
- secrets, tokens, database dumps, logs with PII;
- one-off facts that belong in `.ai_context/handoff.md`.

### Freshness rule

Temporal facts must be phrased as temporal and must say how to verify them.

Good:

```text
Chrome Web Store production version must be verified from the live listing before audit.
```

Bad:

```text
Chrome extension version is 0.3.1.
```

If a version/status is included, add a note that it is current only at the time of writing and must be rechecked.

## 2. ADR maintenance

ADRs record structural decisions, not every small task.

Use ADR when a decision changes or defines:

- project boundaries;
- architecture workflow;
- spec format;
- validator behavior;
- runtime/control-layer separation;
- security/privacy rules;
- cross-bot convention;
- long-term tradeoff.

Do not use ADR for:

- typo fixes;
- routine docs edits;
- one-off runtime bugfixes;
- temporary implementation notes.

### ADR statuses

Allowed statuses:

- `Proposed`
- `Accepted`
- `Superseded`
- `Deprecated`
- `Rejected`

Never silently edit history to reverse a decision. If a decision changes, create a new ADR and mark the old one as `Superseded` with a link to the replacement ADR.

### ADR numbering

Use sequential numbers:

```text
docs/adr/0001-title.md
docs/adr/0002-title.md
docs/adr/0003-title.md
```

File title should be short, lowercase, hyphenated.

## 3. Spec maintenance

Specs are the machine-readable source of architecture truth.

Update specs when:

- a flow is added/removed/renamed;
- a button/screen/callback is added;
- an event is emitted or retired;
- a table is added or ownership changes;
- a dependency/risk/guard changes;
- a contract check becomes required.

Specs must stay concise. Put explanation in ADR or docs, not inside giant YAML comments.

## 4. Handoff vs CONTEXT vs ADR

Use the right layer:

```text
CONTEXT.md      stable orientation and audit workflow
ADRs            structural decisions and tradeoffs
specs/*.yaml    machine-readable architecture truth
.ai_context/    current operational state and next steps
README.md       human overview and entrypoint
```

If a fact is likely to change next week, it probably belongs in `.ai_context/handoff.md`, not `CONTEXT.md`.

If a rule should guide future agents for months, it probably belongs in `CONTEXT.md`, an ADR, or `AGENTS.md`.

## 5. Review checklist

Before committing documentation/spec changes, check:

- Does `CONTEXT.md` still say where to verify production truth?
- Does every ADR have status, context, decision, consequences?
- Are old ADRs marked superseded instead of silently rewritten?
- Are specs updated with the same concept described in prose?
- Is volatile session state kept out of stable docs?
- Are secrets/user data absent?

## 6. Anti-staleness policy

Every meaningful project session should end with one of:

- update `.ai_context/handoff.md` if only operational state changed;
- update specs if architecture surface changed;
- add/update ADR if structural decision changed;
- update CONTEXT.md if orientation/audit workflow changed.

Do not leave architectural changes only in chat history.

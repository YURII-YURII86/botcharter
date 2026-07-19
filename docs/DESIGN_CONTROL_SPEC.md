# Botctl Design-Control Engine Spec

Status: implemented milestone / evolving contract
Scope: botctl v0.4 design-control layer
Implemented gate: `botctl design gate`

Runtime generation/build/apply is outside this milestone and remains blocked.

## 1. Product contract

Botctl must become a standardized bot design/build/control engine, not a checklist.

The target product is a transparent control layer for designing, reviewing, building and maintaining complex Telegram bots. It must prevent menu chaos, blind agent edits, unclear UX paths, random buttons, weak copy, hidden coupling and untracked impact.

The engine must model and control the complete path:

```text
product purpose
→ roles
→ role journeys
→ menus/screens
→ buttons
→ callbacks
→ handlers
→ state
→ responses/status/error copy
→ tests
→ impact graph
→ change plan
```

Agents must be able to answer before changing anything:

- what changes;
- where it changes;
- which roles are affected;
- which journeys are affected;
- which menus/buttons/callbacks are affected;
- which handlers/states/responses/tests are affected;
- which risks/guards are required;
- how to verify;
- how to roll back.

## 2. Milestone 1

Milestone 1 is **Design-control engine**, not code generation.

Botctl first becomes a high-quality design/control layer:

- product model;
- role model;
- journey map;
- menu proposal;
- response system;
- state model;
- impact graph;
- test matrix;
- change plans;
- validation, critique, compare and readiness gates.

Code generation/build/apply is a later layer and is blocked until confirmed design artifacts plus approved ChangePlan exist.

## 3. Artifact architecture

Design-control uses separate artifacts linked by a manifest, not one monolithic design file.

Source-of-truth directory:

```text
.botctl/design/
├─ manifest.yaml
├─ product.model.yaml
├─ roles.model.yaml
├─ journeys.map.yaml
├─ menu.proposal.yaml
├─ responses.system.yaml
├─ state.model.yaml
├─ impact.graph.yaml
├─ test.matrix.yaml
├─ changeplans/
└─ README.md
```

Machine-readable YAML files are authoritative. `README.md` is a human/agent overview derived from them.

`docs/design/` may exist later as a human-readable export, but it is not the source of truth.

## 4. Core artifacts

### 4.1 BotDesignManifest

`manifest.yaml` aggregates artifact statuses and readiness.

Required responsibilities:

- list all design artifacts and paths;
- show each artifact status;
- show missing/draft/reviewed/confirmed/deprecated status;
- expose `production_design_allowed`;
- expose open questions and blockers;
- expose last generated/confirmed metadata.

Example shape:

```yaml
apiVersion: botctl.dev/v0
kind: BotDesignManifest
knowledge_status: draft
production_design_allowed: false
artifacts:
  product_model:
    path: .botctl/design/product.model.yaml
    knowledge_status: draft
  role_model:
    path: .botctl/design/roles.model.yaml
    knowledge_status: draft
  journey_map:
    path: .botctl/design/journeys.map.yaml
    knowledge_status: missing
```

### 4.2 BotProductModel

`product.model.yaml` is the first required artifact before roles, journeys and menus.

It is strict and mandatory for production-grade design.

Required fields:

- purpose;
- target users;
- primary jobs-to-be-done;
- non-goals;
- business rules;
- success metrics;
- risk constraints;
- assumptions;
- open questions;
- knowledge status.

Short user requests may produce `BotProductModelDraft`, but it must be marked:

```yaml
knowledge_status: draft
assumptions_required_confirmation: true
production_design_allowed: false
```

A draft helps thinking but must not be treated as confirmed truth.

### 4.3 BotRoleModel

`roles.model.yaml` defines user/system roles and permissions.

Roles should not be technical labels detached from product value. They depend on `BotProductModel`.

Required responsibilities:

- role ids and titles;
- role goals;
- allowed actions;
- forbidden actions;
- visible journeys/menus;
- permission boundaries;
- escalation/support routes.

### 4.4 BotJourneyMap

`journeys.map.yaml` is the source of truth for menu structure.

Menus are derived from role journeys, not designed as primary button lists.

Required responsibilities:

- role → goal → steps;
- decision points;
- happy path;
- empty states;
- error paths;
- retry/timeout paths;
- exit paths;
- status/progress requirements;
- required responses;
- required state;
- required tests.

This prevents menu tourism: buttons exist because a journey needs them, not because an agent invented a button list.

### 4.5 BotMenuDesignProposal

`menu.proposal.yaml` defines screens, buttons and callback contracts derived from journeys.

Required responsibilities:

- menus/screens;
- button purpose;
- role visibility;
- callback namespace;
- callback data pattern;
- handler hint;
- expected result;
- navigation requirements;
- guard/confirmation/idempotency requirements;
- linked journey and response ids.

### 4.6 BotResponseSystem

`responses.system.yaml` is a required separate source-of-truth for copy, status, error, empty-state, confirmation and success messages.

Handlers and menus must reference `response_id`; copy must not be scattered through handlers.

The response system is a template library plus tone/formatting rules, not a flat list of hardcoded texts.

Each response should model:

- id;
- intent;
- role;
- tone;
- message template;
- variables;
- required next action;
- fallback;
- formatting rules;
- examples.

Global rules:

- clear and human-readable;
- no technical garbage;
- no vague/stupid error messages;
- explicit next action;
- human-readable errors;
- live status for long tasks;
- consistent emoji/formatting policy.

### 4.7 BotStateModel

`state.model.yaml` defines state and persistence assumptions.

Required responsibilities:

- transient vs persistent state;
- per-role state;
- journey state;
- idempotency keys;
- retry/attempt counters;
- locks/leases;
- storage backend assumptions;
- migration risks.

### 4.8 BotImpactGraph

`impact.graph.yaml` is a required artifact for change impact and dependency awareness.

It is built before implementation as expected graph, then compared with observed graph after code exists.

Expected edge chain:

```text
role → journey → menu → button → callback → handler → state → response → test
```

Required responsibilities:

- explicit dependencies;
- impact queries;
- expected vs observed comparison;
- missing link detection;
- extra link detection;
- risky change detection.

### 4.9 BotTestMatrix

`test.matrix.yaml` defines required tests before implementation is production-ready.

Required categories:

- role visibility;
- onboarding;
- journey happy paths;
- empty states;
- permission denied;
- human-readable errors;
- long-running status/progress;
- back/cancel/help escape paths;
- dangerous action confirmation;
- idempotency/double-click protection;
- state persistence;
- impact graph coverage.

### 4.10 ChangePlan

ChangePlan is the mandatory unit of change for production-grade modifications.

Required fields:

- change_id;
- intent;
- affected roles;
- affected journeys;
- affected menus;
- affected callbacks;
- affected handlers;
- affected responses;
- affected states;
- affected tests;
- risk level;
- verification plan;
- rollback plan.

No production bot code/runtime change is allowed without an approved ChangePlan.

## 5. Knowledge status contract

Every design/control artifact must explicitly carry status metadata:

```yaml
knowledge_status: draft | reviewed | confirmed | deprecated
confirmed_by: null
confirmed_at: null
assumptions: []
open_questions: []
```

Status is inside the artifact, not only in chat/memory/logs.

Artifacts are confirmed individually. `BotDesignManifest` aggregates package readiness.

Legacy extracted design is always draft until reviewed and confirmed:

```yaml
knowledge_status: draft
source: observed_code
production_design_allowed: false
requires_review: true
```

Working code does not imply confirmed design. Legacy code may encode accidental or chaotic UX.

## 6. Implementation/build gate

Implementation is allowed only when all core artifacts are confirmed and manifest allows production design.

Required confirmed artifacts:

- BotProductModel;
- BotRoleModel;
- BotJourneyMap;
- BotMenuDesignProposal;
- BotResponseSystem;
- BotImpactGraph;
- BotTestMatrix;
- ChangePlan.

Manifest must say:

```yaml
production_design_allowed: true
```

Future code generation is allowed only from confirmed design artifacts plus approved ChangePlan.

Forbidden:

- generate handlers from raw brief;
- generate code from unconfirmed proposal;
- edit production bot without impact graph;
- change callbacks/responses/states without ChangePlan;
- restart/apply runtime as part of design commands.

## 7. Navigation complexity policy

Do not use one fixed universal menu-depth limit.

Use depth budgets by type:

- menu navigation depth;
- guided flow depth;
- admin workflow depth;
- object detail/action depth;
- confirmation/result depth.

Menu navigation should stay shallow and understandable.

Guided flows may be deeper if they have:

- progress/status;
- back/cancel/help;
- clear step title;
- expected result;
- timeout/retry/error path;
- tests.

Bad depth:

```text
Main → Settings → More settings → Advanced → Misc → Management → Item 7
```

Acceptable guided flow:

```text
Task → Detail → Submit work → Upload file → Preview → Confirm → Status
```

## 8. `botctl design init-system`

### 8.1 Purpose

`botctl design init-system` is the first implementation of the design-control layer.

It creates `.botctl/design/` source-of-truth skeleton and observed draft artifacts.

### 8.2 Legacy behavior

On legacy bots, `init-system` creates skeleton plus observed draft artifacts from current code/passport evidence.

It must use existing `.botctl` passport and agent context as evidence, not as confirmed design truth.

Evidence sources:

- `.botctl/graph.desired.yaml`;
- `.botctl/agent_context.md/json`;
- `design extract-menu`;
- `design critique`;
- rulepack results;
- `design normalize`;
- code evidence.

Rule:

```text
passport = evidence
design artifacts = source of truth only after review/confirmation
```

### 8.3 Minimal observed draft

`init-system` creates a minimal observed draft, not a full inferred product system.

It may fill:

- `manifest.yaml`;
- `roles.model.yaml`;
- `menu.proposal.yaml`;
- `impact.graph.yaml` partial;
- `test.matrix.yaml` partial;
- `README.md`.

It must create placeholders for risky layers:

- `product.model.yaml`;
- `journeys.map.yaml`;
- `responses.system.yaml`;
- `state.model.yaml`.

Placeholders must include:

```yaml
knowledge_status: draft
source: placeholder
requires_review: true
production_design_allowed: false
open_questions: []
```

`init-system` must not pretend it recovered ProductModel/JourneyMap/ResponseSystem perfectly from code.

### 8.4 Output

`init-system` outputs both machine artifacts and human-readable report:

```text
.botctl/design/manifest.yaml
.botctl/design/product.model.yaml
.botctl/design/roles.model.yaml
.botctl/design/journeys.map.yaml
.botctl/design/menu.proposal.yaml
.botctl/design/responses.system.yaml
.botctl/design/state.model.yaml
.botctl/design/impact.graph.yaml
.botctl/design/test.matrix.yaml
.botctl/design/changeplans/
.botctl/design/README.md
```

README must explain:

- what was created;
- what is draft;
- what is missing;
- what requires review;
- UX debts found;
- next steps;
- forbidden actions without confirmation/ChangePlan.

### 8.5 Overwrite policy

`init-system` never overwrites existing `.botctl/design/` by default.

If design layer already exists, command must stop.

Allowed behavior when `.botctl/design/` exists:

```bash
botctl design init-system --preview --output /tmp/design-init-preview/
```

Preview writes proposed artifacts into an external output directory only and does not touch the project.

No `--force` overwrite of draft artifacts in v0.4. Even draft artifacts may contain manual work.

Future updates require separate commands like:

- `design migrate`;
- `design update-draft`;
- `design diff`;
- `design accept`.

## 9. From-scratch bot creation lifecycle

For a new bot, the safe lifecycle is:

```text
short idea
→ BotProductModelDraft with explicit assumptions
→ confirmed BotProductModel
→ BotRoleModel
→ BotJourneyMap
→ BotResponseSystem
→ BotMenuDesignProposal
→ BotStateModel
→ BotImpactGraph expected
→ BotTestMatrix
→ approved ChangePlan
→ implementation/build later
→ extract observed map/graph from code
→ compare expected vs observed
→ verify tests and impact coverage
```

Short prompts produce drafts, not confirmed truth.

A short prompt like `build a creator task bot` may create a product draft with assumptions, but must mark:

```yaml
knowledge_status: draft
assumptions_required_confirmation: true
production_design_allowed: false
```

## 10. Existing commands and how they fit

Current v0.3 commands remain useful but must be reframed under design-control:

- `design extract-menu`: observed implementation evidence;
- `design critique`: UX/rulepack critique of observed map;
- `design validate-brief`: strict input guard for brief-level design;
- `design from-brief`: draft menu proposal, not production design;
- `design normalize`: observed menu map → draft proposal;
- `design plan`: plan-only implementation skeleton;
- `design compare`: desired proposal vs observed menu map.

They are not sufficient alone for production-grade build until core design-control artifacts are confirmed.

## 11. Non-goals for v0.4 init-system

`design init-system` must not:

- generate production handlers;
- edit runtime code;
- read or print `.env`/secrets;
- restart services;
- modify launchd/systemd/docker runtime;
- send Telegram messages;
- mark extracted legacy design as confirmed;
- infer full ProductModel/JourneyMap/ResponseSystem from code as truth;
- overwrite existing `.botctl/design/`.

## 12. Readiness checklist for implementing `init-system`

Before implementation, ensure schemas exist or are added for:

- BotDesignManifest;
- BotProductModel;
- BotRoleModel;
- BotJourneyMap;
- BotResponseSystem;
- BotStateModel;
- BotImpactGraph;
- BotTestMatrix;
- ChangePlan.

Smoke must verify:

- init-system creates all expected files on fixture project;
- artifacts have `knowledge_status=draft` or `missing` as appropriate;
- `production_design_allowed=false`;
- placeholders exist for product/journeys/responses/state;
- observed drafts exist for roles/menu/impact/test matrix;
- README exists and mentions review/forbidden actions;
- existing `.botctl/design/` blocks init;
- preview mode writes only external output;
- no `.env` or runtime files are read;
- no runtime process/service is touched.

## 13. Core principle

The framework must make bot architecture understandable before implementation and maintainable after implementation.

No agent should edit a complex bot without seeing the whole design context and impact graph.

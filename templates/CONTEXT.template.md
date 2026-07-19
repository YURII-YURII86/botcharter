# CONTEXT

## Project

`<project-name>` is `<one-sentence identity>`.

It is `<what it is>` and is not `<important boundary>`.

## Why this exists

Explain the problem this project solves and the class of failures it should prevent.

## Core principle

State the primary rule that should guide future agents/developers.

## Project boundaries

### This project owns

- ...

### This project does not own

- ...

## Main artifacts

```text
path/to/artifact    purpose
```

## Reference runtime/project

Reference project:

```text
/path/to/reference/project
```

Why this reference was chosen:

- ...

Important reference paths:

```text
path    purpose
```

Temporal facts must include verification method:

```text
Fact: <current fact at time of writing>
Verify: <command/link/source of truth>
```

## How to compare specs with runtime reality

### Flow comparison

Spec:

```text
specs/FLOWS.yaml
```

Runtime paths:

```text
...
```

Check:

- ...

### UI graph comparison

Spec:

```text
specs/UI_GRAPH.yaml
```

Runtime paths/search:

```text
...
```

Check:

- ...

### Event comparison

Spec:

```text
specs/EVENTS.yaml
```

Runtime paths/search:

```text
...
```

Check:

- ...

### Storage comparison

Spec:

```text
specs/STORAGE.yaml
```

Runtime paths/search:

```text
...
```

Check:

- ...

### Dependency comparison

Spec:

```text
specs/DEPENDENCIES.yaml
```

Runtime paths/search:

```text
...
```

Check:

- ...

### Contract comparison

Spec:

```text
specs/CONTRACTS.yaml
```

Runtime tests:

```text
...
```

Check:

- ...

## Manual audit command checklist

```bash
# commands
```

## Definition of done for current milestone

- ...

## Maintenance rule

Update this file when orientation, reference project, audit workflow or stable project boundaries change. Put volatile state in `.ai_context/handoff.md`.

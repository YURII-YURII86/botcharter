# Описание проекта — BotCharter

## Назначение
Separate control/spec/tooling project for managing Telegram bots as transparent, machine-readable systems: flows, UI graph, events, storage, dependencies, contracts, validators and templates.

## Основные принципы
- Specs first, runtime code second
- Do not store secrets or production runtime data
- Audit runtime bots from this project without mixing code
- Keep architecture truth machine-readable

## Текущее состояние

Botctl `0.8.0a1` public-alpha candidate includes adoption, graph/inspect/verify, design artifacts, semantic review/confirm, ChangePlan approval, consolidated design gate, source/spec drift audit, and guarded diagnostics. Runtime apply remains disabled.

## Точки входа
- `README.md`
- `CONTEXT.md`
- `AGENTS.md`
- `.ai_context/handoff.md`
- `specs/*.yaml`
- `tools/botctl.py`
- `docs/BOTCTL_V0.md`

_Updated 2026-07-19 for public-alpha preparation._

# Botctl v0

Botctl v0 — минимальный исполняемый вертикальный срез BotCharter.

## Audit runtime source

```bash
python3 tools/botctl.py audit-runtime --project "<bot-project>" --format json
```

Read-only static audit сверяет Python source/tests с `FLOWS`, `EVENTS`, `UI_GRAPH`, `STORAGE`, `DEPENDENCIES` и `CONTRACTS`. Он отчитывает:

- callback namespaces без handler coverage;
- handler namespaces вне UI graph;
- emitted events вне registry;
- SQL tables без storage declaration;
- external calls без dependency declaration;
- flow contracts без найденных tests;
- technical transport events в product analytics.

Safety contract: target modules не импортируются, runtime data не читаются, network не вызывается, target project не изменяется. Report contract: `schemas/runtime-audit.schema.json`.

## Что строим

Botctl не является runtime-фреймворком бота и не меняет production. Его задача в v0 — дать AI-агенту безопасный вход в проект бота через локальную папку и `.botctl/`:

1. прочитать проект без изменений;
2. построить локальный observed graph;
3. сравнить desired graph с observed_local;
4. проверить ChangePlan;
5. выдать agent_context для безопасного следующего действия.

## Команды v0

```bash
python tools/botctl.py inspect --project "<bot-project>"
python tools/botctl.py inspect --project "<bot-project>" --format json
python tools/botctl.py inspect --project "<bot-project>" --format agent
python tools/botctl.py snapshot --project "<bot-project>"
python tools/botctl.py verify --project "<bot-project>"
python tools/botctl.py diff --project "<bot-project>"
python tools/botctl.py plan validate --project "<bot-project>"
```

## Политика authored/generated и UX

В `.botctl/` v0 есть два класса артефактов:

```text
Authored source-truth, версионируется:
- .botctl/project.yaml
- .botctl/graph.desired.yaml
- .botctl/change_plans/*.yaml

Generated snapshots, воспроизводятся через snapshot и обычно игнорируются git:
- .botctl/architecture.brief.json
- .botctl/graph.observed.json
- .botctl/drift.report.json
- .botctl/agent_context.json
- .botctl/agent_context.md
```

Это не только git-policy, но и UX-policy. `verify` должен падать, если:

- проект не задаёт `artifact_policy`;
- проект не задаёт `ux_policy`;
- человеко-видимые названия выглядят как raw enum/id;
- generated `agent_context` не содержит понятные русские allowed/blocked действия;
- generated drift/status labels не являются понятными русскими текстами;
- desired graph не содержит `ux_structure.sections`;
- UX-разделы не покрывают важные Product/Capability/Flow узлы;
- UX-раздел или действие ссылается на неизвестный узел графа.

`ux_structure` — это человеко-понятная карта управления поверх графа. Она не заменяет nodes/edges, а объясняет, какие разделы должен видеть человек или агент, зачем эти разделы нужны и какие основные действия доступны.

`ux_structure.checks` — обязательный список UX/production checks, перенесённый из прочитанных источников:

- sanitized Telegram Bot Builder UX contract;
- `skill-telegram-rich-messages-для-обогащения-ответов-ботов`;
- `case-технический-кейс-красивый-ux-для-долгих-telegram-video-jobs`;
- `case-сессия-расширение-tg-id-username-bot-в-двухрежимный-telegram`.

Обязательные checks v0.1:

```text
command_design
start_onboarding
inline_keyboard_layout
unknown_input_fallback
progress_status
human_readable_errors
empty_states
rate_limiting
persistent_user_state
global_error_handler
token_env_safety
analytics_or_observability
webhook_or_polling_model
```

Каждый check должен иметь русский `title`, русский `why`, `status`, `source` из допустимого списка и `evidence_nodes` для статуса `covered`.

Пример:

```yaml
ux_structure:
  sections:
    - id: ux.section.main_flow
      title: "Основной сценарий репоста"
      purpose: "Показывает главный путь от публикации Telegram до сообщения VK."
      nodes:
        - product.tg_vk_reposter
        - capability.forward_channel_posts
        - flow.telegram_post_to_vk_message
      primary_actions:
        - id: ux.action.inspect_forwarding_flow
          title: "Проверить сценарий репоста"
          node: flow.telegram_post_to_vk_message
```

`snapshot` добавляет UX-оценку в `architecture.brief.json`, `agent_context.json` и `agent_context.md`.

### Remediation hints for missing UX checks

Если authored check имеет `status: missing` и локальный скан не нашёл observed evidence, `snapshot` добавляет подсказку в `ux_structure.checks[].remediation_hint` и общий список `agent_context.remediation_hints`.

Формат подсказки:

```json
{
  "check_id": "global_error_handler",
  "title": "Добавить глобальный обработчик ошибок Telegram app",
  "why": "Без global handler неожиданные ошибки могут теряться или ломать UX.",
  "look_in": ["src/app.py", "src/*telegram*.py"],
  "suggested_evidence": ["Application.add_error_handler(...)"],
  "graph_source": "telegram-bot-builder",
  "evidence_nodes": []
}
```

`agent_context.md` для таких случаев содержит раздел `Что добавить для пропущенных UX-проверок`. Эти подсказки не являются автоматическим runtime/apply планом; это read-only guidance для следующего агента: где искать, какой тип evidence добавить, и какой UX/production риск закрывается.

После `snapshot` команда `inspect --format agent` остаётся read-only, но подтягивает уже сгенерированный `.botctl/agent_context.json` и отдаёт `remediation_hints`, `ux_structure`, `summary` и `full_artifacts` прямо в inspect payload. Если generated context отсутствует или не читается, `inspect --format agent` не пишет файлы и возвращает пустой `remediation_hints`.

Если `.botctl/graph.desired.yaml` ещё нет, `inspect --format agent` не создаёт его автоматически. Вместо этого он добавляет read-only `bootstrap_hints`: найденные безопасные project files, Python modules, observed UX signal ids и observed UX evidence. Это bootstrap-вход для следующего агента, чтобы создать authored graph осознанно, а не угадывать проект с нуля.

## Bootstrap preview

`bootstrap-preview` — read-only команда для проекта без паспорта:

```bash
python3 tools/botctl.py bootstrap-preview --project "<bot-project>" --format yaml
```

Она строит черновик `.botctl/graph.desired.yaml` по `bootstrap_hints`, но по умолчанию **не пишет файлы в проект**. Вывод идёт в stdout в YAML или JSON формате.

Опционально preview можно записать во внешний файл:

```bash
python3 tools/botctl.py bootstrap-preview --project "<bot-project>" --format yaml --output /tmp/bot.graph.desired.yaml
```

Защиты `--output`:

- draft перед записью проходит `validate_graph`;
- запись внутрь `<bot-project>/.botctl/` запрещена;
- существующий output-файл не перезаписывается без `--force`;
- команда не создаёт `.botctl` в target bot project.

Команда создаёт draft graph с:

- `Product`, `Capability`, `Flow` узлами;
- найденными Python modules как `Handler` nodes с code evidence;
- `ConfigRef` для Telegram token reference без чтения секрета;
- `TraceSink`, `Policy`, опциональный `DeployTarget`;
- `ux_structure.sections` и все обязательные Telegram UX checks;
- check statuses `covered` только для observed UX signals, иначе `planned`.

Черновик имеет `knowledge_status: inferred/candidate` и `draft_notice`. Его нельзя считать финальным authored graph без ручного уточнения названий, сценариев, рисков и evidence.

Aiogram regression smoke проверяет:

- positive fixture с `Router`, `Command`, `BotCommand`, `InlineKeyboardButton/Markup`, `router.errors.register`, `Dispatcher.start_polling`, state/storage/progress/error patterns даёт все 13 UX-signals;
- local-name false-positive fixture с локальными `Router`, `Command`, `BotCommand`, `Dispatcher.start_polling` не создаёт `command_design`, `start_onboarding` или `webhook_or_polling_model`.

Smoke проверяет, что `bootstrap-preview`:

- не создаёт `.botctl`;
- видит no-graph layout `app/main.py`;
- генерирует schema-valid `BotArchitectureGraph`;
- включает все обязательные UX checks;
- помечает observed checks как `covered`;
- пишет preview во внешний `--output` файл;
- блокирует повторную запись без `--force`;
- блокирует запись внутрь target `.botctl`.

## Design status/readiness

`design status` — read-only readiness check для `.botctl/design/`:

```bash
python3 tools/botctl.py design status --project "<bot-project>" --format json
```

Возвращает `BotDesignReadiness`:

- `design_exists`;
- `readiness_status`: `missing_design_layer`, `invalid`, `blocked`, `ready`;
- `readiness_score` по confirmed core artifacts;
- `production_design_allowed`;
- per-artifact paths/statuses/open questions;
- schema validation results;
- blockers and next steps.

Production readiness требует confirmed core artifacts:

```text
product_model
role_model
journey_map
menu_proposal
response_system
impact_graph
test_matrix
```

И `manifest.production_design_allowed=true`. Draft init-system layer ожидаемо получает `readiness_status=blocked`, `production_design_allowed=false`, blockers по unconfirmed artifacts. Проект без `.botctl/design/` получает `missing_design_layer` и nonzero exit.

Smoke проверяет:

- `design_status_ok=True`;
- `design_status_missing_guard_ok=True`;
- result validates against `schemas/design-readiness.schema.json`.

## Design init-system

`design init-system` — первая команда v0.4 design-control слоя. Она создаёт `.botctl/design/` как machine-control source of truth по `docs/DESIGN_CONTROL_SPEC.md`.

Actual init для проекта без design layer:

```bash
python3 tools/botctl.py design init-system --project "<bot-project>" --format json
```

Создаёт:

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

Behavior:

- legacy code/passport используется как evidence, не confirmed truth;
- observed drafts заполняются для `roles.model.yaml`, `menu.proposal.yaml`, `impact.graph.yaml`, `test.matrix.yaml`;
- risky product/UX layers создаются как placeholders: `product.model.yaml`, `journeys.map.yaml`, `responses.system.yaml`, `state.model.yaml`;
- все artifacts стартуют `knowledge_status=draft`, `requires_review=true`, `production_design_allowed=false`;
- `.botctl/design/` не перезаписывается: второй actual init падает;
- если design layer уже существует, доступен только external preview:

```bash
python3 tools/botctl.py design init-system --project "<bot-project>" --preview --output /tmp/design-init-preview
```

Preview пишет proposed artifacts во внешний каталог и не трогает проект. `--force` разрешён только для непустого preview-output, не для `.botctl/design/`.

Smoke проверяет:

- `design_init_system_ok=True`;
- `design_init_system_no_overwrite_ok=True`;
- `design_init_system_preview_ok=True`;
- `design_init_system_schemas_ok=True`.

## Design review/confirm

Каждый design artifact проходит два явных шага:

```bash
python3 tools/botctl.py design review --project "<bot-project>" --artifact product_model --actor "reviewer" --note "Проверена цель продукта"
python3 tools/botctl.py design confirm --project "<bot-project>" --artifact product_model --actor "reviewer" --confirm
```

`review` переводит artifact из `draft` в `reviewed`. `confirm` разрешён только после review и требует:

- явный `--confirm`;
- непустой `--actor`;
- пустой `open_questions`;
- `assumptions_required_confirmation=false`, если это поле есть.

Каждое изменение пишется в `review_history`. Manifest обновляется автоматически. Production gate открывается только когда все семь core artifacts имеют статус `confirmed` и проходят schema/readiness checks.

Smoke flags:

- `design_review_confirm_ok=True`;
- `design_confirm_explicit_guard_ok=True`;
- `design_confirm_open_questions_guard_ok=True`.

### Semantic validation

Schema validation проверяет форму YAML, а `validate-artifact` — минимальную осмысленность содержания:

```bash
python3 tools/botctl.py design validate-artifact --project "<bot-project>" --artifact product_model --format json
```

Проверка блокирует placeholder-артефакты и пустые ключевые разделы. Например, ProductModel должен содержать purpose, target users, primary jobs, non-goals, business rules, success metrics и risk constraints. JourneyMap должен связывать роль, цель и шаги. ImpactGraph не может ссылаться на неизвестные nodes.

Semantic validation запускается:

- отдельно через `design validate-artifact`;
- автоматически перед `design confirm`;
- повторно в `design status` для защиты от ручной подмены статуса.

Smoke flag: `design_semantic_validation_guard_ok=True`.

## Design ChangePlan approval

Design ChangePlan создаётся только после `design status = ready`:

```bash
python3 tools/botctl.py design change-plan-new --project "<bot-project>" --id "menu.main-v2" --intent "Упростить главное меню" --risk-level medium
python3 tools/botctl.py design change-plan-validate --project "<bot-project>" --id "menu.main-v2"
python3 tools/botctl.py design change-plan-review --project "<bot-project>" --id "menu.main-v2" --actor "reviewer"
python3 tools/botctl.py design change-plan-approve --project "<bot-project>" --id "menu.main-v2" --actor "approver" --confirm
```

Lifecycle: `draft → reviewed → confirmed/approved`.

До review план должен содержать intent, risk level, хотя бы один affected-* элемент, verification plan, rollback plan и не иметь open questions. Approval требует имя подтверждающего и явный `--confirm`.

Каждый id в `affected_roles`, `affected_journeys`, `affected_menus`, `affected_callbacks`, `affected_handlers`, `affected_responses`, `affected_states` и `affected_tests` сверяется с confirmed design artifacts и ImpactGraph. Выдуманная ссылка блокирует review, approval и design gate.

Даже approved ChangePlan имеет `runtime_apply_allowed=false`: v0.4 управляет дизайном и планом, но не меняет runtime.

Smoke flags:

- `design_change_plan_approval_ok=True`;
- `design_change_plan_incomplete_guard_ok=True`;
- `design_change_plan_review_guard_ok=True`;
- `design_change_plan_explicit_approval_guard_ok=True`.
- `design_change_plan_unknown_reference_guard_ok=True`.

## Consolidated design gate

`design gate` даёт один итоговый machine-readable отчёт по design-пакету и ChangePlan:

```bash
python3 tools/botctl.py design gate --project "<bot-project>" --format json
python3 tools/botctl.py design gate --project "<bot-project>" --id "menu.main-v2" --format json
```

Статусы gate:

- `missing_design_layer` — design layer не создан;
- `design_blocked` — core artifacts не готовы;
- `missing_change_plan` — design ready, но ChangePlan нет;
- `change_plan_blocked` — план невалиден или не approved;
- `ready_for_implementation_planning` — design ready и есть valid approved ChangePlan.

Поле `implementation_planning_allowed=true` разрешает только готовить детальный план реализации. `runtime_apply_allowed` в v0.4 всегда `false`.

Отчёт проходит `schemas/design-gate.schema.json`.

Smoke flags:

- `design_gate_ok=True`;
- `design_gate_missing_plan_guard_ok=True`.

## Design schemas

Design artifacts имеют formal JSON Schema contracts:

```text
schemas/design-brief.schema.json
schemas/ux-rulepack.schema.json
schemas/menu-map.schema.json
schemas/menu-design-proposal.schema.json
schemas/menu-implementation-plan.schema.json
schemas/menu-design-diff.schema.json
schemas/design-manifest.schema.json
schemas/product-model.schema.json
schemas/role-model.schema.json
schemas/journey-map.schema.json
schemas/response-system.schema.json
schemas/state-model.schema.json
schemas/impact-graph.schema.json
schemas/test-matrix.schema.json
schemas/change-plan-design.schema.json
schemas/design-readiness.schema.json
```

Назначение:

- `design-brief.schema.json` — входной `BotDesignBrief` для проектирования до кода;
- `ux-rulepack.schema.json` — machine-readable UX rulepacks, включая `telegram_bot_builder_ux`;
- `menu-map.schema.json` — extracted `BotMenuMap` из кода;
- `menu-design-proposal.schema.json` — desired `BotMenuDesignProposal`;
- `menu-implementation-plan.schema.json` — plan-only `BotMenuImplementationPlan`;
- `menu-design-diff.schema.json` — compare output `BotMenuDesignDiff`.

Schemas intentionally permissive on extra fields (`additionalProperties: true`), but strict on identity/safety fields: `apiVersion`, `kind`, `read_only=true`, `implementation_policy.mode=proposal_only`, `summary.mode=plan_only`, command shape, required sections and diff status.

Full smoke validates:

- `telegram_bot_builder_ux.yaml` against `ux-rulepack.schema.json`;
- generated `BotMenuMap` against `menu-map.schema.json`;
- generated `BotMenuDesignProposal` against `menu-design-proposal.schema.json`;
- generated `BotMenuImplementationPlan` against `menu-implementation-plan.schema.json`;
- generated `BotMenuDesignDiff` against `menu-design-diff.schema.json`;
- smoke `BotDesignBrief` against `design-brief.schema.json`;
- negative schema check: broken proposal with `read_only=false` must fail.

Smoke flags: `design_schemas_ok=True`, `design_schema_negative_ok=True`.

## Design extraction

`design extract-menu` — read-only команда v0.3 для извлечения фактической структуры меню/ролей/callbacks из кода бота:

```bash
python3 tools/botctl.py design extract-menu --project "<bot-project>" --format json
```

Она возвращает `BotMenuMap`:

- `roles` — роли, выведенные из команд, callbacks и имён (`user`, `allowed_user`, `admin`, `creator`, `lead`, `guest`, `owner`);
- `commands` — slash/native menu commands с source path/line/context;
- `menus` — группы inline-кнопок по function/context;
- `callback_contract` — namespaces, patterns, role hints, handlers hints и risk notes;
- `handlers_hint` — функции/методы, похожие на menu/command/callback/flow handlers;
- `quality_gates` — базовые gates: namespace callbacks, explicit roles, menu buttons, visible commands.

Команда использует расширенный, но safe scanner: читает обычные Python code files в `src`, `app`, `bot`, `bots`, но не читает `.env`, sessions, credentials, secrets, data/runtime paths и слишком большие/секретные файлы. Это extractor фактического UX, а не финальный дизайн-документ: `allowed_roles_hint` эвристический и должен подтверждаться access-control кодом.

Запись разрешена только во внешний output-файл:

```bash
python3 tools/botctl.py design extract-menu --project "<bot-project>" --output /tmp/menu.map.json
```

Как и `bootstrap-preview`, команда не пишет внутрь target `.botctl`.

Smoke проверяет:

- `design_extract_menu_ok=True` на no-graph fixture с `/start` и inline callback;
- запись во внешний `--output`;
- блокировку записи внутрь `.botctl`;
- idempotent temp cleanup.

Дополнительные закрытые проверки не публикуют названия, пути или количественные отпечатки частных проектов.

### Design critique

`design critique` — read-only анализ `BotMenuMap`:

```bash
python3 tools/botctl.py design critique --project "<bot-project>" --format json
```

Или по заранее сохранённой карте:

```bash
python3 tools/botctl.py design critique --project "<bot-project>" --input /tmp/menu.map.json --output /tmp/menu.critique.json
```

Он возвращает `BotMenuDesignCritique`:

- `summary.status/score` — общая оценка menu design;
- `issues[]` — ошибки/предупреждения/info с evidence и recommendation;
- checks для `/start`, `/help`, menu buttons, role explicitness, dangerous callback guards, back/cancel/help navigation, role menu coverage и callback namespace quality;
- `rulepack_evaluation` — результаты skill-based rulepack;
- `recommended_next_steps` для следующего агента.

#### Telegram Bot Builder UX rulepack

`design critique` подключает machine-readable rulepack:

```text
 tools/botctl/rulepacks/telegram_bot_builder_ux.yaml
```

Rulepack извлечён из установленного skill `telegram-bot-builder` и содержит 16 правил:

- `/start` onboarding;
- `/help` и понятность commands;
- inline keyboard layout;
- back/cancel/help escape paths;
- unknown input fallback;
- progress/typing/status для долгих операций;
- human-readable errors;
- empty states;
- rate limiting/idempotency/concurrency guards;
- persistent sessions/state;
- global error handler;
- token/env safety;
- analytics/observability;
- polling/webhook model;
- monetization guardrails.

`rulepack_evaluation.results[]` даёт status per rule: `covered`, `missing`, `weak`, `not_applicable`, `not_evaluated`. `missing/weak` правила добавляются в `issues[]` с id вида `rulepack.tbb.*`.

Команда не пишет target `.botctl`; `--output` разрешён только во внешний файл. Smoke проверяет `design_critique_ok=True`, `design_critique_rulepack_ok=True`, `design_critique_output_ok=True`, `design_critique_dotbotctl_guard_ok=True`. На синтетической fixture critique специально находит UX-долги (`/help`, back/cancel), включая недоказанные empty-state сценарии.

### Design brief validation

`design validate-brief` — strict read-only validator для `BotDesignBrief` перед генерацией меню:

```bash
python3 tools/botctl.py design validate-brief --project "<future-bot-name>" --input brief.yaml --format json
```

Возвращает `BotDesignBriefValidation`:

- `valid`;
- `summary.errors/warnings/roles/flows/commands`;
- `issues[]` и `warnings[]` с `id`, `severity`, `title`, `why`, `evidence`, `recommendation`.

Проверки:

- `name` или `title` обязателен;
- `roles` обязателен;
- `flows` или `features` обязателен;
- role id и flow id должны быть snake_case, начинаться с буквы и быть короткими;
- запрещены reserved role ids: `system`, `bot`, `runtime`, `secret`, `token`, `env`;
- запрещены reserved flow ids: `nav`, `admin`;
- дубли role ids, flow ids и commands — error;
- `flow.roles` должны ссылаться только на роли из `roles`;
- commands не должны конфликтовать с default `/start`, `/help`, `/status`, `/admin`;
- отсутствие базовой user/creator/allowed_user роли, flow title или flow roles даёт warning.

`design from-brief` по умолчанию блокирует генерацию, если validation невалидна. Для аварийного debug существует `--allow-invalid`; тогда proposal всё равно содержит `brief_validation.valid=false`.

Smoke проверяет:

- `design_validate_brief_ok=True` на валидном creator-task brief;
- `design_validate_brief_invalid_guard_ok=True` на невалидном brief;
- invalid `from-brief` блокируется без `--allow-invalid`;
- `--allow-invalid` генерирует proposal, но сохраняет `brief_validation.valid=false`.

### Design from brief

`design from-brief` — read-only generator для проектирования меню до кода:

```bash
python3 tools/botctl.py design from-brief --project "<future-bot-name>" --input brief.yaml --format yaml
```

Минимальный `BotDesignBrief`:

```yaml
name: creator-task-bot
roles:
  - id: guest
    title: Гость
  - id: creator
    title: Креатор
  - id: lead
    title: Лид
  - id: admin
    title: Администратор
  - id: owner
    title: Владелец
flows:
  - id: task_board
    title: Задания
    command: tasks
    roles: [creator, lead, admin, owner]
  - id: submit_work
    title: Сдать работу
    command: submit
    roles: [creator]
```

Команда возвращает тот же `BotMenuDesignProposal`, что и `design normalize`, но с `source_kind=BotDesignBrief` и вложенным `brief_validation`. Она автоматически добавляет `/start`, `/help`, `/status`, admin menu если есть admin/owner, navigation callbacks `nav:back`, `nav:cancel`, `nav:help`, callback namespaces по flows, confirmation/idempotency flags для опасных действий и `implementation_policy.mode=proposal_only`.

На smoke brief с creator/lead/admin/owner и flows `task_board`, `submit_work`, `moderation_queue`, `payments` команда генерирует proposal с ролями, командами `/tasks`, `/submit`, `/moderate`, `/payments`, callbacks `nav/admin/task/submit/moderation/payments`, и блокирует запись внутрь `.botctl`.

### Design compare

`design compare` — read-only diff между желаемым `BotMenuDesignProposal` и фактическим `BotMenuMap`:

```bash
python3 tools/botctl.py design compare \
  --project "<bot-project>" \
  --input /tmp/menu.proposal.yaml \
  --actual /tmp/menu.actual.json \
  --format json
```

Возвращает `BotMenuDesignDiff`:

- `summary.status`: `aligned`, `partial` или `diverged`;
- `summary.score`;
- missing/extra по roles, commands, callback namespaces и callback patterns;
- missing navigation actions;
- dangerous namespaces, где proposal требует permission/confirmation/idempotency, а extracted map не подтверждает guards;
- `issues[]` с id `compare.*` и рекомендациями.

Типичный workflow:

```bash
python3 tools/botctl.py design extract-menu --project "<bot>" --output /tmp/menu.actual.json
python3 tools/botctl.py design from-brief --project "<bot>" --input brief.yaml --output /tmp/menu.proposal.yaml
python3 tools/botctl.py design compare --project "<bot>" --input /tmp/menu.proposal.yaml --actual /tmp/menu.actual.json
```

Smoke проверяет `design_compare_ok=True`, output во внешний файл и запрет записи внутрь `.botctl`. На искусственном неполном implementation map diff ловит missing roles, commands, callback namespaces, navigation и dangerous guards.

`extract-menu` теперь добавляет в `callback_contract[]` guard-доказательства:

- `guard_evidence.permission_guard` — markers вроде `is_admin`, `owner`, `allowed`, `allowlist`, `check_access`, `creator`, `lead`;
- `guard_evidence.confirmation` — markers вроде `confirm`, `confirmation`, `preview`, `approve`, `подтверд`;
- `guard_evidence.idempotency` — markers вроде `already`, `active`, `pending`, `lock`, `retry`, `attempt`, `queue`;
- `guard_status.supported=true`, если есть permission guard и confirmation или idempotency.

Для dangerous namespaces и role-scoped namespaces (`admin`, `owner`, `creator`, `lead`) extractor может использовать project-level guard evidence, если конкретный callback line не содержит все markers. `design compare` считает dangerous namespace реализованным только при `guard_status.supported=true`.

Синтетический self-compare extracted→normalized proposal проверяет, что menu map находит кнопки/callbacks и project-level evidence для access-control, confirmation/idempotency guards.

### Design plan

`design plan` — read-only implementation-plan skeleton из `BotMenuDesignProposal` или `BotMenuMap`:

```bash
python3 tools/botctl.py design plan --project "<bot-project>" --input /tmp/menu.proposal.yaml --format yaml
```

Если input — `BotMenuMap`, команда сначала делает `normalize`, потом plan. Если input отсутствует, команда извлекает menu map из проекта, нормализует и строит plan.

Возвращает `BotMenuImplementationPlan`:

- `summary.mode=plan_only`;
- `suggested_files`: handlers/keyboards/roles/callbacks/tests/state;
- `handler_skeleton`: имена handler skeleton из command/callback hints;
- `phases`: contract → scaffold → UX quality → botctl passport;
- `test_matrix`: commands, callbacks, roles, navigation, dangerous actions, empty/error states;
- `dangerous_callbacks`: namespaces/actions requiring guards, confirmation, idempotency;
- `rollback_strategy`;
- `blocked_actions`: create runtime handlers without ChangePlan, edit service, read secrets, touch runtime DB, restart service, send Telegram messages without runtime approval.

Это **не генератор кода** и не apply. Это безопасный план для следующего агента перед ChangePlan. Smoke проверяет `design_plan_ok=True`, output во внешний файл и запрет записи внутрь `.botctl`. На creator-task proposal plan содержит: 6 roles, 8 commands, 6 callback namespaces, 4 phases, 6 tests, 6 blocked actions.

### Design normalize

`design normalize` — read-only proposal generator поверх `BotMenuMap` и `BotMenuDesignCritique`:

```bash
python3 tools/botctl.py design normalize --project "<bot-project>" --format yaml
```

Или по заранее сохранённой карте меню:

```bash
python3 tools/botctl.py design normalize --project "<bot-project>" --input /tmp/menu.map.json --output /tmp/menu.proposal.yaml
```

Он возвращает `BotMenuDesignProposal`:

- `roles` — нормализованные роли с флагом `requires_manual_confirmation` для admin/owner/creator/lead;
- `command_contract` — команды, видимость по ролям, handler hints и source;
- `menus` — меню с нормализованными buttons, `action_id`, `callback_namespace`, confirmation/idempotency flags и navigation requirements;
- `callback_contract` — namespaces, patterns, action hints, allowed roles, handler hints, permission/confirmation/idempotency requirements;
- `global_navigation_requirements` — обязательные navigation/error states и missing элементы из critique;
- `design_debt` — короткий список долгов из critique;
- `implementation_policy.mode=proposal_only` и запреты без ChangePlan.

Команда не пишет target `.botctl`; `--output` разрешён только во внешний файл. Smoke проверяет `design_normalize_ok=True`, `design_normalize_output_ok=True`, `design_normalize_dotbotctl_guard_ok=True`. Синтетический proposal проверяет roles, command contracts, menus, callback namespaces, design debt и `mode=proposal_only`.

## Bootstrap save

`bootstrap-save` — явная команда первичного сохранения паспорта:

```bash
python3 tools/botctl.py bootstrap-save --project "<bot-project>" --confirm
```

Она создаёт:

- `.botctl/project.yaml` — минимальный project contract;
- `.botctl/graph.desired.yaml` — draft graph из `bootstrap-preview`;
- generated artifacts через `snapshot`: `graph.observed.json`, `drift.report.json`, `architecture.brief.json`, `agent_context.json`, `agent_context.md`.

Защиты:

- без `--confirm` команда не пишет файлы;
- если проект находится в dirty git worktree, запись блокируется без `--allow-dirty`;
- существующий `graph.desired.yaml` блокирует запись без `--force`;
- при `--force` создаются backup-файлы для старых `project.yaml`/`graph.desired.yaml`;
- после записи выполняется `verify`; если verify падает, созданные/заменённые authored files откатываются;
- после успешного verify выполняется `snapshot`;
- команда не читает `.env` и не меняет runtime.

`bootstrap-save` — это still graph/bootstrap operation, не runtime apply. Сгенерированный graph остаётся draft с `knowledge_status: inferred/candidate`; его нужно ревьюить и уточнять перед production-gate.

Smoke проверяет:

- no-confirm guard;
- dirty git guard;
- успешное сохранение с `--allow-dirty` в fixture;
- наличие `project.yaml`, `graph.desired.yaml`, generated artifacts;
- existing graph guard;
- `--force` с backup;
- `verify` после сохранения.

## Observed UX evidence promotion

С v0.1 evidence promotion использует check-specific extractors: Python AST для вызовов, импортов и символов, и line-pattern fallback только для текстовых/конфиговых признаков. Комментарии, docstring и строковые упоминания вроде `add_error_handler`, `CommandHandler`, `run_polling` или `InlineKeyboardMarkup` не считаются Telegram UX evidence сами по себе.

`snapshot` также выполняет безопасный локальный скан кода и добавляет в `graph.observed.json` блок `observed_ux_evidence`. Он читает только безопасные проектные файлы (`src/*.py`, `Makefile`, `compose.yml`, `Dockerfile`) и не читает `.env`, session-файлы, runtime DB или credentials.

### AST precision guarantees

Botctl v0.1 не должен повышать UX-check по одному только короткому имени метода или класса. Для практических false-positive рисков действуют такие ограничения:

- `Application.add_handler`, `Application.add_error_handler`, `run_polling`, `run_webhook` и `Application.builder()` засчитываются только при явном признаке `telegram.ext.Application`: import/alias, type annotation или цепочка `Application.builder().build()`;
- `MessageHandler`, `CommandHandler`, `CallbackQueryHandler` засчитываются только как импортированные символы из `telegram.ext`;
- aiogram `Router.message`, `Router.callback_query`, `Command(...)`, `BotCommand(...)`, `router.errors.register(...)` и `Dispatcher.start_polling(...)` засчитываются только при явных импортных признаках `aiogram`, `aiogram.filters` или `aiogram.types`; локальные классы с такими именами не считаются Telegram evidence;
- `InlineKeyboardMarkup`, `InlineKeyboardButton` и `callback_data` засчитываются только как импортированные Telegram symbols из `telegram` или `aiogram.types`; `callback_data` должен быть keyword у `InlineKeyboardButton(...)`, а не произвольным атрибутом или локальным именем;
- `os.getenv` засчитывается только через реальный `import os` или `from os import getenv`;
- `sleep` засчитывается только через `asyncio.sleep`, `time.sleep` или импортированный `sleep` из `asyncio`/`time`;
- `logging.error`, `logging.exception`, `logging.basicConfig`, `logging.getLogger` засчитываются только через реальный `import logging` или logger-переменную, созданную через `logging.getLogger(...)`;
- `write_heartbeat` засчитывается только как локальная или импортированная функция, не как произвольный метод объекта;
- `send_chat_action` засчитывается только как метод `bot` / `context.bot`-подобного receiver.

Если проект строит Telegram app динамически нестандартным способом, v0.1 может не повысить check автоматически. В этом случае authored `graph.desired.yaml` остаётся источником намерения, а observed evidence нужно расширять отдельной fixture и точечным extractor.

Observed evidence может повысить UX-check в generated context:

```text
declared status: planned
observed evidence: найдено в коде
effective_status: observed_covered
```

Это не меняет authored `graph.desired.yaml`; это только generated truth о том, что botctl реально нашёл в проекте.

Каждый observed signal обязан содержать проверяемые указатели:

```json
{
  "confidence": "high",
  "validity": {"status": "current", "checked_at": "..."},
  "source_fingerprints": {"src/app.py": "sha256:..."},
  "matches": [
    {
      "path": "src/app.py",
      "line": 14,
      "symbol": "error_handler",
      "pattern": "add_error_handler|error_handler|...",
      "snippet": "async def error_handler(update: object, context: Any) -> None:"
    }
  ]
}
```

Smoke test падает, если evidence не содержит `matches`, `line`, `symbol`, `confidence`, `validity` и `source_fingerprints`. False-positive fixtures проверяют, что комментарии/строки, docstring, локальные классы/методы с Telegram-похожими именами, локальные `os`/`logging`/`Application` обманки и произвольные `sleep/getenv/callback_data/write_heartbeat/send_chat_action` не создают AST-derived evidence.

Сейчас v0.1 ищет признаки:

- Telegram handlers/filters для `command_design`;
- `/start` или импортированный `telegram.ext.CommandHandler(start)` для `start_onboarding`;
- импортированные Telegram inline keyboard symbols и `callback_data` keyword для `inline_keyboard_layout`;
- skip/fallback branches для `unknown_input_fallback`;
- локальная/imported heartbeat-функция, `bot.send_chat_action`, queue/progress для `progress_status`;
- Telegram error handler и реальный logging API для `human_readable_errors` и `global_error_handler`;
- DLQ/empty/skip states для `empty_states`;
- queue batch/lease/retry/attempts и реальный `asyncio/time.sleep` для `rate_limiting`;
- SQLite/store/state DB для `persistent_user_state`;
- real `os.getenv` token refs для `token_env_safety`;
- real logging API, heartbeat/health для `analytics_or_observability`;
- Telegram Application polling/webhook/deploy признаки для `webhook_or_polling_model`.

## Границы безопасности

- `adopt` без `--confirm` выводит только preview; с подтверждением создаёт новую `.botctl/`, не меняя runtime и корневой `AGENTS.md`.
- `inspect` строго read-only и не пишет файлы.
- `snapshot` явно обновляет generated artifacts в `.botctl/`.
- `verify` проверяет локальный архитектурный контракт и ChangePlan.
- `diff` сравнивает только desired ↔ observed_local.
- `probe-runtime` проверяет только явно переданный локальный PID или metadata heartbeat-файла.
- `probe-http` делает один явно подтверждённый `HEAD`-запрос к заданному HTTPS health URL; body, redirects, auth, cookies и environment proxy отключены.
- `probe-sqlite` выполняет только фиксированный `quick_check(1)` для явно указанной SQLite-базы в `ro+immutable` режиме; user rows, schema и имена таблиц не выводятся.
- Telegram API, реальные токены, `.env`, логи, systemd/docker control и автоматический remote discovery не трогаются в v0.8.
- `apply` и `rollback` не входят в v0.

## Reference bot

Публичный synthetic reference project:

```text
examples/existing-service
```

В нём v0 использует локальную `.botctl/` структуру:

```text
.botctl/project.yaml
.botctl/graph.desired.yaml
.botctl/change_plans/example.yaml
.botctl/architecture.brief.json
.botctl/graph.observed.json
.botctl/drift.report.json
.botctl/agent_context.json
.botctl/agent_context.md
```

## Критерий готовности v0

v0 считается рабочим только если на reference bot проходят:

```bash
python tools/botctl.py inspect --project "<reference-bot>" --format json
python tools/botctl.py snapshot --project "<reference-bot>"
python tools/botctl.py verify --project "<reference-bot>"
python tools/botctl.py diff --project "<reference-bot>"
python tools/botctl.py plan validate --project "<reference-bot>"
```

Дополнительно проверяется, что:

- `inspect` не меняет `.botctl/`;
- `verify` ловит битый edge endpoint;
- `verify` ловит плохой русский title;
- `verify` ловит missing affected_node;
- `verify` ловит medium+ ChangePlan без rollback;
- `verify` ловит отсутствие `.botctl` artifact policy;
- `verify` ловит плохие generated UX labels вроде `action.inspect` вместо русского названия;
- `verify` ловит отсутствие `ux_structure`;
- `verify` ловит UX-раздел со ссылкой на неизвестный node;
- `verify` ловит отсутствие `ux_structure.checks`;
- `verify` ловит неизвестный source у UX-check, например `fantasy`;
- `verify` ловит отсутствие обязательного check из прочитанных Telegram skills/cases;
- `snapshot` добавляет `remediation_hints` в `agent_context.json` и раздел `Что добавить для пропущенных UX-проверок` в `agent_context.md`, когда UX-check остаётся missing без observed evidence;
- `inspect --format agent` после `snapshot` read-only подтягивает generated `.botctl/agent_context.json` и показывает `remediation_hints` в inspect payload;
- `inspect --format agent` без authored graph показывает `bootstrap_hints` и observed UX signals, но не пишет `.botctl` файлы;
- `bootstrap-preview` без authored graph выводит read-only draft `graph.desired.yaml` в stdout или во внешний `--output` файл, но не создаёт target `.botctl`;
- `bootstrap-save --confirm` создаёт минимальный `.botctl/project.yaml`, `.botctl/graph.desired.yaml` и generated artifacts, но не трогает runtime;
- `design critique` применяет skill-based `telegram_bot_builder_ux` rulepack к extracted menu map;
- `design validate-brief` строго валидирует `BotDesignBrief` и блокирует невалидный design-from-brief;
- `design from-brief` принимает валидный `BotDesignBrief` и генерирует read-only `BotMenuDesignProposal` для будущего бота до кода;
- `design plan` превращает `BotMenuDesignProposal` или `BotMenuMap` в read-only `BotMenuImplementationPlan` без генерации кода и без runtime apply;
- `design compare` сравнивает desired proposal с extracted implementation map и показывает missing roles/commands/callbacks/navigation/guards.

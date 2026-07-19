# BotCharter

**Архитектурный контроль и safety gates для ботов, создаваемых AI-агентами.**

BotCharter устанавливает команду `botctl` для проектирования, проверки и безопасного сопровождения Telegram-ботов.

Это публичная alpha-версия. Она умеет:

- подключать существующий проект командой `botctl adopt`;
- хранить flows, UI, события, storage, зависимости и контракты в машинном виде;
- проверять design package и ChangePlan;
- находить расхождения между Python-кодом и specs;
- создавать понятный контекст для следующего AI-агента;
- выполнять явно подтверждённые безопасные probes.

Она намеренно не генерирует production-код, не разворачивает ботов, не читает токены и не изменяет runtime.

## Быстрый старт

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/botctl adopt --project "/path/to/project"
.venv/bin/botctl adopt --project "/path/to/project" --confirm
```

После подтверждения создаётся только новая `.botctl/`. Исходный код и существующий `AGENTS.md` не меняются.

Полный публичный walkthrough: [docs/PUBLIC_ALPHA.md](docs/PUBLIC_ALPHA.md).

Проверяемое демо без сети и реального бота:

```bash
python tools/demo_public_alpha.py
```

Лицензия: MIT.

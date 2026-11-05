# Плагины Cursor для прав доступа 1С

Репозиторий-маркетплейс плагинов Cursor для работы с правами доступа в конфигурациях 1С на БСП.

## Плагины

| Плагин | Назначение |
|---|---|
| [1c-access-profiles](plugins/1c-access-profiles/README.md) | Профили групп доступа через MCP Toolkit: анализ, сравнение, проверка, сборка |

## Установка

### Team Marketplace (рабочий путь)

1. Dashboard → **Plugins & MCPs** → **Team Marketplaces** → **Import from Repo**
2. Указать `https://github.com/Yevgeniy1212/1c-access-profiles`
3. Cursor читает `.cursor-plugin/marketplace.json` и показывает список плагинов

Для **приватного** репозитория нужен установленный **Cursor GitHub App** с доступом к нему
(Dashboard → Integrations → GitHub). Без этого импорт не увидит манифест.

### Локальная проверка

```powershell
Copy-Item -Recurse "plugins\1c-access-profiles" "$env:USERPROFILE\.cursor\plugins\local\1c-access-profiles"
```

Затем в Cursor — `Developer: Reload Window`, плагин появится в Customize.

## Требования к содержимому плагина

Каждый плагин — отдельная папка в `plugins/` со своим `.cursor-plugin/plugin.json`.
Компоненты (`rules/`, `skills/`, `commands/`, `agents/`) обнаруживаются по стандартным каталогам.

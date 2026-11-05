#!/usr/bin/env python3
"""Настройка подключения к базе 1С через MCP Toolkit.

Создаёт `.roles-access.yaml` в корне проекта и проверяет связь с базой.
Пользователю достаточно указать адрес сервера — остальное определится само.

    python scripts/init_access.py --url http://10.20.0.100:6004
    python scripts/init_access.py            # если адрес уже есть в .cursor/mcp.json

Что определяется автоматически:
  * имя и версия конфигурации, режим совместимости;
  * версия БСП;
  * роль-мастер шаблонов RLS и роли-эталоны (проверяется их существование).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_client import Client, add_common_args, fail, resolve_url, setup_stdout  # noqa: E402

ROOT = Path.cwd()
CONFIG_FILE = ROOT / ".roles-access.yaml"
WORKDIR_DIRS = ("matrix", "reports", "registry", "staging")

# Скрипты плагина копируются в проект, чтобы команды работали по стабильному пути
# независимо от того, куда Cursor установил сам плагин.
VENDOR_DIR = ROOT / ".cursor" / "1c-access-profiles" / "scripts"
PLUGIN_SCRIPTS = Path(__file__).resolve().parent

INFO_CODE = """
Рез = Новый Структура;
Рез.Вставить("Имя", Метаданные.Имя);
Рез.Вставить("Синоним", Метаданные.Синоним);
Рез.Вставить("Версия", Метаданные.Версия);
Рез.Вставить("Совместимость", Строка(Метаданные.РежимСовместимости));
Рез.Вставить("Поставщик", Метаданные.Поставщик);
БСП = "";
Попытка
	БСП = СтандартныеПодсистемыСервер.ВерсияБиблиотеки();
Исключение
	БСП = "";
КонецПопытки;
Результат = Рез.Имя + "|" + Рез.Синоним + "|" + Рез.Версия + "|" + Рез.Совместимость
	+ "|" + Рез.Поставщик + "|" + БСП;
"""

MASTER_CHECK = """
Имя = {role};
Рез = "MISS";
Если Метаданные.Роли.Найти(Имя) <> Неопределено Тогда
	Рез = "OK";
КонецЕсли;
Результат = Рез;
"""

ROLE_EXISTS = """
Рез = "";
Для Каждого Н Из СтрРазделить({roles}, ",") Цикл
	Есть = "НЕТ";
	Если Метаданные.Роли.Найти(СокрЛП(Н)) <> Неопределено Тогда
		Есть = "ДА";
	КонецЕсли;
	Рез = Рез + СокрЛП(Н) + "|" + Есть + Символы.ПС;
КонецЦикла;
Результат = Рез;
"""

REFERENCE_ROLES = {
    "document_read": "ЧтениеПоступлениеТоваровУслуг",
    "document_edit": "ДобавлениеИзменениеПоступлениеТоваровУслуг",
    "catalog_read": "ЧтениеНоменклатуры",
    "catalog_edit": "ДобавлениеИзменениеНоменклатуры",
    "info_register_read": "ЧтениеЦенНоменклатуры",
    "info_register_edit": "ДобавлениеИзменениеЦенНоменклатуры",
}
MASTER_ROLE = "ИзменениеУчастниковГруппДоступа"


def config_name_text(synonym: str, name: str, version: str) -> str:
    base = synonym or name
    return f"{base} {version}".strip()


def yaml_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_config(url: str, info: list[str], references: dict[str, str]) -> None:
    name, synonym, version, compat, vendor, bsp = info
    content = f"""# Профиль подключения к базе 1С для работы с профилями доступа.
# Создан скриптом init_access.py. Правьте только при смене базы или ролей-эталонов.
version: 1

config_name: "{yaml_quote(config_name_text(synonym, name, version))}"
config_full_name: "{yaml_quote(name)}"
config_version: "{yaml_quote(version)}"
vendor: "{yaml_quote(vendor or '')}"
compatibility_mode: "{yaml_quote(compat or '')}"
bsp_version: "{yaml_quote(bsp or '')}"

# Работаем только с профилями: роли не создаются и не изменяются.
scope: "profiles_only"
roles_source: "existing_in_infobase"

prefix: ""

xml_dump_path: ""

mcp:
  live: "{url}"

ib:
  mcp_url: "{url}"

rls:
  master_role: "{MASTER_ROLE}"
  reference_roles:
"""
    for key, value in references.items():
        content += f'    {key}: "{value}"\n'
    content += f"""
batch_size: 25

policies:
  delete_rights: "keep_typical"
  subsystem_choice: "first_sorted"

workdir: "{yaml_quote(str(ROOT / 'workdir'))}"
"""
    CONFIG_FILE.write_text(content, encoding="utf-8")


def main() -> int:
    setup_stdout()
    parser = argparse.ArgumentParser(description="Настроить подключение к базе 1С")
    add_common_args(parser)
    args = parser.parse_args()

    url = resolve_url(args.url)
    print(f"Адрес сервера: {url}")

    client = Client(url)
    health = client.health()
    print(f"Сервер отвечает: {health.get('status', '?')} (режим {health.get('mode', '?')})")

    raw = client.run(INFO_CODE)
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 6:
        fail(f"не удалось прочитать сведения о конфигурации: {raw[:200]}")
    name, synonym, version, compat, vendor, bsp = parts[:6]

    print()
    print("База данных:")
    print(f"  Конфигурация : {synonym or name}")
    print(f"  Имя          : {name}")
    print(f"  Версия       : {version}")
    print(f"  Совместимость: {compat}")
    print(f"  Поставщик    : {vendor}")
    print(f"  БСП          : {bsp or 'не определена'}")
    print()

    master = client.run(MASTER_CHECK.format(role='"' + MASTER_ROLE + '"')).strip()
    if master != "OK":
        fail(
            f"роль-мастер шаблонов RLS «{MASTER_ROLE}» не найдена в базе.\n"
            "     Это признак конфигурации не на БСП либо иной версии библиотеки."
        )
    print(f"Роль-мастер RLS: {MASTER_ROLE} — найдена")

    resolved: dict[str, str] = {}
    missing: list[str] = []
    for key, role in REFERENCE_ROLES.items():
        answer = client.run(ROLE_EXISTS.format(roles='"' + role + '"')).strip()
        exists = answer.endswith("ДА")
        resolved[key] = role if exists else ""
        if not exists:
            missing.append(role)
    print(
        f"Роли-эталоны: найдено {len(REFERENCE_ROLES) - len(missing)} "
        f"из {len(REFERENCE_ROLES)}"
    )
    if missing:
        print("  Отсутствуют (функция останется без эталона):")
        for m in missing:
            print(f"    - {m}")

    write_config(url, [name, synonym, version, compat, vendor, bsp], resolved)
    print()
    print(f"Создан файл: {CONFIG_FILE}")

    for folder in WORKDIR_DIRS:
        (ROOT / "workdir" / folder).mkdir(parents=True, exist_ok=True)
    print(f"Рабочий каталог: {ROOT / 'workdir'}")

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for py_file in sorted(PLUGIN_SCRIPTS.glob("*.py")):
        if py_file.resolve() == Path(__file__).resolve():
            continue
        shutil.copyfile(py_file, VENDOR_DIR / py_file.name)
        copied += 1
    print(f"Скрипты плагина: {copied} файлов в {VENDOR_DIR}")

    print()
    print("Готово. Дальше:")
    print("  1) /access-profiles-list    — посмотреть существующие профили")
    print("  2) /access-profile-builder  — собрать новый профиль")
    print("  3) /access-profile-compare  — сравнить профили")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

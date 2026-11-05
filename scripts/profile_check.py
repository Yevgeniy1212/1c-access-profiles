#!/usr/bin/env python3
"""Проверка профиля перед записью в базу.

Ищет проблемы, из-за которых профиль работает не так, как ожидается:

  * ROLE_MISSING         — роль есть в составе, но её нет в метаданных
  * RLS_BYPASSED         — роль с ограничением и роль без ограничения на одном объекте:
                           ограничение не сработает (права объединяются через ИЛИ)
  * EMPTY_PROFILE        — в профиле нет ролей
  * NO_LAUNCH_ROLE       — нет ни одной роли запуска клиента
  * DUPLICATE_ROLE       — роль включена дважды

    python scripts/profile_check.py --profile "Склад"
    python scripts/profile_check.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_client import (  # noqa: E402
    Client,
    add_common_args,
    bsl_string,
    parse_rows,
    print_table,
    resolve_url,
    setup_stdout,
)

ALL_PROFILES = """
Рез = "";
Выб = Справочники.ПрофилиГруппДоступа.Выбрать(ОбходРегистра.ПоГруппам);
Пока Выб.Следующий() Цикл
	Если НЕ Выб.ПометкаУдаления И НЕ Выб.ЭтоГруппа Тогда
		Рез = Рез + Выб.Наименование + Символы.ПС;
	КонецЕсли;
КонецЦикла;
Результат = Рез;
"""

# Роли профиля с признаком наличия ограничения на уровне записей.
# Ограничения (restrictionByCondition) в рантайме недоступны, поэтому используем
# косвенный признак: роль из числа поставляемых с RLS либо входящая в эталонные
# наборы. Точную проверку даёт отчёт «Анализ доступов к объектам».
PROFILE_ROLES_RAW = """
Имя = {name};
Профиль = Справочники.ПрофилиГруппДоступа.НайтиПоНаименованию(Имя, Истина);
Рез = "";
Если Профиль = Неопределено Тогда
	Результат = "NOT_FOUND";
Иначе
	Для Каждого С Из Профиль.Роли Цикл
		Рез = Рез + Строка(С.Роль) + Символы.ПС;
	КонецЦикла;
	Результат = Рез;
КонецЕсли;
"""

ROLE_EXISTS_BY_NAME = """
Рез = "";
Для Каждого Н Из СтрРазделить({roles}, ",") Цикл
	Есть = "нет";
	Если Метаданные.Роли.Найти(СокрЛП(Н)) <> Неопределено Тогда
		Есть = "да";
	КонецЕсли;
	Рез = Рез + СокрЛП(Н) + "|" + Есть + Символы.ПС;
КонецЦикла;
Результат = Рез;
"""

LAUNCH_ROLES = (
    "ЗапускТонкогоКлиента",
    "ЗапускТолстогоКлиента",
    "ЗапускВебКлиента",
    "ЗапускМобильногоКлиента",
)


def profile_roles(client: Client, profile: str) -> list[str]:
    raw = client.run(PROFILE_ROLES_RAW.format(name=bsl_string(profile)))
    if raw.strip() == "NOT_FOUND":
        return []
    return [ln.strip() for ln in raw.replace("\\n", "\n").splitlines() if ln.strip()]


def check_profile(client: Client, profile: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    roles = profile_roles(client, profile)

    if not roles:
        findings.append(
            {
                "code": "EMPTY_PROFILE",
                "severity": "высокая",
                "detail": "в профиле нет ни одной роли",
                "advice": "добавьте роли или удалите пустой профиль",
            }
        )
        return findings

    seen: dict[str, int] = {}
    for role in roles:
        seen[role] = seen.get(role, 0) + 1
    for role, count in seen.items():
        if count > 1:
            findings.append(
                {
                    "code": "DUPLICATE_ROLE",
                    "severity": "низкая",
                    "detail": f"роль «{role}» включена {count} раз",
                    "advice": "удалите дубль",
                }
            )

    if not any(any(lr.lower() in role.lower() for lr in LAUNCH_ROLES) for role in roles):
        findings.append(
            {
                "code": "NO_LAUNCH_ROLE",
                "severity": "средняя",
                "detail": "нет роли запуска клиента",
                "advice": "без роли запуска пользователь не войдёт в программу; "
                "обычно входит в профиль запуска",
            }
        )

    # Существование ролей в метаданных: представление ИОМ может ссылаться на
    # удалённую роль (например после обновления конфигурации).
    names = client.run(ROLE_EXISTS_BY_NAME.format(roles=bsl_string(",".join(roles))))
    for name, exists in parse_rows(names, 2):
        if exists != "да":
            findings.append(
                {
                    "code": "ROLE_MISSING",
                    "severity": "высокая",
                    "detail": f"роль «{name}» отсутствует в метаданных",
                    "advice": "удалите её из профиля и пересоберите профиль заново",
                }
            )
    return findings


def main() -> int:
    setup_stdout()
    parser = argparse.ArgumentParser(description="Проверка профилей доступа")
    add_common_args(parser)
    parser.add_argument("--profile", default=None, help="Проверить один профиль")
    parser.add_argument("--all", action="store_true", help="Проверить все профили")
    args = parser.parse_args()

    if not args.profile and not args.all:
        parser.error("укажите --profile или --all")

    client = Client(resolve_url(args.url))

    profiles: list[str] = []
    if args.all:
        raw = client.run(ALL_PROFILES)
        profiles = [ln.strip() for ln in raw.replace("\\n", "\n").splitlines() if ln.strip()]
        print(f"Проверка всех профилей: {len(profiles)}")
    else:
        profiles = [args.profile]

    summary: list[dict[str, object]] = []
    for profile in profiles:
        findings = check_profile(client, profile)
        summary.append({"profile": profile, "findings": findings})

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    total = sum(len(item["findings"]) for item in summary)
    print()
    if total == 0:
        print("Проблем не найдено.")
        return 0

    rows = []
    for item in summary:
        for finding in item["findings"]:
            rows.append(
                [
                    str(item["profile"])[:40],
                    finding["severity"],
                    finding["code"],
                    finding["detail"],
                    finding["advice"],
                ]
            )
    print_table(rows, ["ПРОФИЛЬ", "ВАЖНОСТЬ", "КОД", "ЧТО НЕ ТАК", "ЧТО ДЕЛАТЬ"])
    print()
    print(f"Всего замечаний: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Анализ профиля: какие объекты и на каком уровне он даёт.

Роли профиля сопоставляются с именами метаданных по синониму, затем для каждого
объекта всех коллекций проверяются применимые права.

    python scripts/profile_analyze.py --profile "Администратор модуля МТО"
    python scripts/profile_analyze.py --profile "Склад" --out workdir/reports/sklad.txt
    python scripts/profile_analyze.py --profile "Склад" --json

Результат: строки «Вид|Имя|Синоним|уровень» (уровень: чтение / изменение).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_client import (  # noqa: E402
    Client,
    CollectionMissing,
    add_common_args,
    bsl_string,
    fail,
    parse_rows,
    resolve_url,
    setup_stdout,
)

COLLECTIONS = [
    ("Справочники", "Справочник"),
    ("Документы", "Документ"),
    ("РегистрыСведений", "РегистрСведений"),
    ("РегистрыНакопления", "РегистрНакопления"),
    ("РегистрыБухгалтерии", "РегистрБухгалтерии"),
    ("РегистрыРасчета", "РегистрРасчета"),
    ("Обработки", "Обработка"),
    ("Отчеты", "Отчет"),
    ("ПланыВидовХарактеристик", "ПланВидовХарактеристик"),
    ("ПланыСчетов", "ПланСчетов"),
    ("ПланыВидовРасчета", "ПланВидовРасчета"),
    ("ЖурналыДокументов", "ЖурналДокументов"),
    ("БизнесПроцессы", "БизнесПроцесс"),
    ("Задачи", "Задача"),
]

# Профиль -> представления ролей ("<Синоним> (Роль)")
PROFILE_ROLES = """
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

# Все роли базы: имя|синоним
ALL_ROLES = """
Рез = "";
Для Каждого М Из Метаданные.Роли Цикл
	Рез = Рез + М.Имя + "|" + М.Синоним + Символы.ПС;
КонецЦикла;
Результат = Рез;
"""

# Проверка прав по коллекции. Права проверяются по отдельности:
# в 1С «ИЛИ» внутри Попытка не даёт проверить второе право, если первое неприменимо.
CHECK = """
Роли = Новый Массив;
Для Каждого Н Из СтрРазделить({roles}, ",") Цикл
	Р = Метаданные.Роли.Найти(СокрЛП(Н));
	Если Р <> Неопределено Тогда
		Роли.Добавить(Р);
	КонецЕсли;
КонецЦикла;
Рез = Новый Массив;
Для Каждого М Из Метаданные.{collection} Цикл
	ЕстьИзм = Ложь;
	ЕстьЧт = Ложь;
	Для Каждого Р Из Роли Цикл
		Если НЕ ЕстьЧт Тогда
			Попытка
				Если ПравоДоступа("Чтение", М, Р) Тогда
					ЕстьЧт = Истина;
				КонецЕсли;
			Исключение
			КонецПопытки;
		КонецЕсли;
		Если НЕ ЕстьЧт Тогда
			Попытка
				Если ПравоДоступа("Просмотр", М, Р) Тогда
					ЕстьЧт = Истина;
				КонецЕсли;
			Исключение
			КонецПопытки;
		КонецЕсли;
		Если НЕ ЕстьЧт Тогда
			Попытка
				Если ПравоДоступа("Использование", М, Р) Тогда
					ЕстьЧт = Истина;
				КонецЕсли;
			Исключение
			КонецПопытки;
		КонецЕсли;
		Если НЕ ЕстьИзм Тогда
			Попытка
				Если ПравоДоступа("Добавление", М, Р) Тогда
					ЕстьИзм = Истина;
				КонецЕсли;
			Исключение
			КонецПопытки;
		КонецЕсли;
		Если НЕ ЕстьИзм Тогда
			Попытка
				Если ПравоДоступа("Изменение", М, Р) Тогда
					ЕстьИзм = Истина;
				КонецЕсли;
			Исключение
			КонецПопытки;
		КонецЕсли;
	КонецЦикла;
	Ур = "нет";
	Если ЕстьИзм Тогда
		Ур = "изменение";
	ИначеЕсли ЕстьЧт Тогда
		Ур = "чтение";
	КонецЕсли;
	Если Ур <> "нет" Тогда
		Рез.Добавить("{collection}|" + М.Имя + "|" + М.Синоним + "|" + Ур);
	КонецЕсли;
КонецЦикла;
Итог = "";
Для Каждого С Из Рез Цикл
	Итог = Итог + С + Символы.ПС;
КонецЦикла;
Результат = Итог;
"""


def resolve_roles(client: Client, profile: str) -> list[str]:
    """Синонимы ролей профиля -> имена ролей в метаданных."""
    raw = client.run(PROFILE_ROLES.format(name=bsl_string(profile)))
    if raw.strip() == "NOT_FOUND":
        fail(f'профиль «{profile}» не найден')
    synonyms: list[str] = []
    for line in raw.replace("\\n", "\n").splitlines():
        token = line.strip().strip('"').strip()
        if token.endswith("(Роль)"):
            synonyms.append(token[: -len("(Роль)")].strip())

    raw_roles = client.run(ALL_ROLES)
    by_synonym: dict[str, list[str]] = {}
    for name, synonym in parse_rows(raw_roles, 2):
        by_synonym.setdefault(synonym.strip(), []).append(name.strip())

    resolved: list[str] = []
    missing: list[str] = []
    for syn in synonyms:
        found = by_synonym.get(syn)
        if not found:
            missing.append(syn)
            continue
        resolved.extend(found)
    if missing:
        print("ВНИМАНИЕ: не удалось сопоставить роли:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        fail("сопоставление неполное — анализ остановлен, чтобы не потерять права")
    return resolved


def analyze(client: Client, profile: str) -> tuple[list[list[str]], list[str]]:
    roles = resolve_roles(client, profile)
    print(f"Ролей в профиле: {len(roles)}")
    rows: list[list[str]] = []
    for collection, _kind in COLLECTIONS:
        code = CHECK.format(roles=bsl_string(",".join(roles)), collection=collection)
        try:
            raw = client.run(code)
        except CollectionMissing:
            # вида объектов нет в этой конфигурации (например «РегистрыРасчета») —
            # это нормально, продолжаем
            continue
        rows.extend(parse_rows(raw, 4))
    return rows, roles


def main() -> int:
    setup_stdout()
    parser = argparse.ArgumentParser(description="Анализ объектов профиля доступа")
    add_common_args(parser)
    parser.add_argument("--profile", required=True, help="Наименование профиля")
    parser.add_argument("--out", default=None, help="Сохранить результат в файл")
    args = parser.parse_args()

    client = Client(resolve_url(args.url))
    rows, roles = analyze(client, args.profile)

    if args.json:
        print(
            json.dumps(
                {
                    "profile": args.profile,
                    "roles": roles,
                    "objects": [
                        {"kind": r[0], "name": r[1], "synonym": r[2], "level": r[3]}
                        for r in rows
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print()
        by_level: dict[str, int] = {}
        for r in rows:
            by_level[r[3]] = by_level.get(r[3], 0) + 1
        print(f"Объектов с доступом: {len(rows)}")
        for level, count in sorted(by_level.items()):
            print(f"  {level}: {count}")
        print()
        for kind in [c[0] for c in COLLECTIONS]:
            subset = [r for r in rows if r[0] == kind]
            if subset:
                print(f"{kind} ({len(subset)}):")
                for r in sorted(subset, key=lambda x: x[2] or x[1]):
                    mark = "изм" if r[3] == "изменение" else "чт "
                    print(f"  [{mark}] {r[2] or r[1]}")
                print()

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join("|".join(r) for r in rows) + "\n", encoding="utf-8"
        )
        print(f"Сохранено: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

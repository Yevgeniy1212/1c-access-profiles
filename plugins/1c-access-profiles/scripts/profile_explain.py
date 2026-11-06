#!/usr/bin/env python3
"""Какая роль профиля даёт конкретный объект.

Нужно, когда в профиле виден лишний документ и непонятно, какая роль его принесла.
Роли не изменяются.

    python scripts/profile_explain.py --profile "Инициатор" --object "ГТД по импорту"
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
from profile_analyze import ALL_ROLES, COLLECTIONS, resolve_roles  # noqa: E402

FIND = """
Искомое = НРег(СокрЛП({query}));
Рез = "";
Для Каждого М Из Метаданные.{collection} Цикл
	ИмяН = НРег(М.Имя);
	СинН = НРег(М.Синоним);
	Точно = (ИмяН = Искомое) Или (СинН = Искомое);
	Частично = (Не Точно) И ((СтрНайти(СинН, Искомое) > 0) Или (СтрНайти(ИмяН, Искомое) > 0));
	Если Точно Или Частично Тогда
		Метка = "частично";
		Если Точно Тогда
			Метка = "точно";
		КонецЕсли;
		Рез = Рез + Метка + "|{collection}|" + М.Имя + "|" + М.Синоним + Символы.ПС;
	КонецЕсли;
КонецЦикла;
Результат = Рез;
"""

EXPLAIN = """
Объект = Метаданные.{collection}.Найти({name});
Если Объект = Неопределено Тогда
	Результат = "NOT_FOUND";
Иначе
	Рез = "";
	Для Каждого ИмяРоли Из СтрРазделить({roles}, ",") Цикл
		РольМ = Метаданные.Роли.Найти(СокрЛП(ИмяРоли));
		Если РольМ = Неопределено Тогда
			Продолжить;
		КонецЕсли;
		ЕстьИзм = Ложь;
		ЕстьЧт = Ложь;
		Попытка
			Если ПравоДоступа("Чтение", Объект, РольМ) Тогда
				ЕстьЧт = Истина;
			КонецЕсли;
		Исключение
		КонецПопытки;
		Если Не ЕстьЧт Тогда
			Попытка
				Если ПравоДоступа("Просмотр", Объект, РольМ) Тогда
					ЕстьЧт = Истина;
				КонецЕсли;
			Исключение
			КонецПопытки;
		КонецЕсли;
		Если Не ЕстьЧт Тогда
			Попытка
				Если ПравоДоступа("Использование", Объект, РольМ) Тогда
					ЕстьЧт = Истина;
				КонецЕсли;
			Исключение
			КонецПопытки;
		КонецЕсли;
		Если Не ЕстьИзм Тогда
			Попытка
				Если ПравоДоступа("Добавление", Объект, РольМ) Тогда
					ЕстьИзм = Истина;
				КонецЕсли;
			Исключение
			КонецПопытки;
		КонецЕсли;
		Если Не ЕстьИзм Тогда
			Попытка
				Если ПравоДоступа("Изменение", Объект, РольМ) Тогда
					ЕстьИзм = Истина;
				КонецЕсли;
			Исключение
			КонецПопытки;
		КонецЕсли;
		Если Не ЕстьЧт И Не ЕстьИзм Тогда
			Продолжить;
		КонецЕсли;
		Уровень = "чтение";
		Если ЕстьИзм Тогда
			Уровень = "изменение";
		КонецЕсли;
		ДокСч = 0;
		Для Каждого Док Из Метаданные.Документы Цикл
			Дает = Ложь;
			Попытка
				Если ПравоДоступа("Чтение", Док, РольМ) Тогда
					Дает = Истина;
				КонецЕсли;
			Исключение
			КонецПопытки;
			Если Не Дает Тогда
				Попытка
					Если ПравоДоступа("Просмотр", Док, РольМ) Тогда
						Дает = Истина;
					КонецЕсли;
				Исключение
				КонецПопытки;
			КонецЕсли;
			Если Не Дает Тогда
				Попытка
					Если ПравоДоступа("Добавление", Док, РольМ) Тогда
						Дает = Истина;
					КонецЕсли;
				Исключение
				КонецПопытки;
			КонецЕсли;
			Если Не Дает Тогда
				Попытка
					Если ПравоДоступа("Изменение", Док, РольМ) Тогда
						Дает = Истина;
					КонецЕсли;
				Исключение
				КонецПопытки;
			КонецЕсли;
			Если Дает Тогда
				ДокСч = ДокСч + 1;
			КонецЕсли;
		КонецЦикла;
		Рез = Рез + СокрЛП(ИмяРоли) + "|" + Уровень + "|" + Формат(ДокСч, "ЧГ=0") + Символы.ПС;
	КонецЦикла;
	Результат = Рез;
КонецЕсли;
"""


def find_objects(client: Client, query: str) -> tuple[list[list[str]], list[list[str]]]:
    exact: list[list[str]] = []
    partial: list[list[str]] = []
    for collection, _kind in COLLECTIONS:
        code = FIND.format(query=bsl_string(query), collection=collection)
        try:
            raw = client.run(code)
        except CollectionMissing:
            continue
        for row in parse_rows(raw, 4):
            if row[0] == "точно":
                exact.append(row[1:])
            else:
                partial.append(row[1:])
    return exact, partial


def synonyms_by_name(client: Client) -> dict[str, str]:
    found: dict[str, str] = {}
    for name, synonym in parse_rows(client.run(ALL_ROLES), 2):
        found[name.strip()] = synonym.strip()
    return found


def explain_object(
    client: Client, collection: str, name: str, roles: list[str]
) -> list[list[str]]:
    code = EXPLAIN.format(
        collection=collection,
        name=bsl_string(name),
        roles=bsl_string(",".join(roles)),
    )
    raw = client.run(code)
    if raw.strip() == "NOT_FOUND":
        fail(f"объект {collection}.{name} не найден")
    return parse_rows(raw, 3)


def main() -> int:
    setup_stdout()
    parser = argparse.ArgumentParser(description="Какая роль профиля даёт объект")
    add_common_args(parser)
    parser.add_argument("--profile", required=True, help="Наименование профиля")
    parser.add_argument(
        "--object",
        required=True,
        help="Имя или синоним объекта, например «ГТД по импорту»",
    )
    args = parser.parse_args()

    client = Client(resolve_url(args.url))
    roles = resolve_roles(client, args.profile)
    exact, partial = find_objects(client, args.object)
    chosen = exact or partial
    if not chosen:
        fail(f"объект «{args.object}» не найден")
    if not exact and len(partial) > 8:
        print(f"По «{args.object}» слишком много похожих объектов. Уточните имя:")
        for collection, name, synonym in partial[:15]:
            print(f"  {synonym or name} ({collection}.{name})")
        return 0

    role_synonyms = synonyms_by_name(client)
    report: list[dict[str, object]] = []
    for collection, name, synonym in chosen:
        hits = explain_object(client, collection, name, roles)
        explained = []
        for role_name, level, doc_count in hits:
            explained.append(
                {
                    "role": role_name,
                    "synonym": role_synonyms.get(role_name, role_name),
                    "level": level,
                    "documents": int(doc_count),
                }
            )
        report.append(
            {
                "collection": collection,
                "name": name,
                "synonym": synonym,
                "match": "точно" if exact else "частично",
                "roles": explained,
            }
        )

    if args.json:
        print(
            json.dumps(
                {"profile": args.profile, "query": args.object, "objects": report},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"Профиль: {args.profile}")
    print(f"Ролей в профиле: {len(roles)}")
    print()
    for item in report:
        title = item["synonym"] or item["name"]
        print(f"{title} ({item['collection']}.{item['name']})")
        roles_found = item["roles"]
        if not roles_found:
            print("  Ни одна роль этого профиля объект не даёт.")
            print()
            continue
        for role in roles_found:
            print(
                f"  {role['synonym']} [{role['level']}]"
                f" — документов у этой роли: {role['documents']}"
            )
            print(f"    имя: {role['role']}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

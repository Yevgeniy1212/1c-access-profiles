#!/usr/bin/env python3
"""Список профилей групп доступа в базе.

    python scripts/profiles_list.py
    python scripts/profiles_list.py --mask МТО
    python scripts/profiles_list.py --details "Администратор модуля МТО"
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
    fail,
    parse_rows,
    print_table,
    resolve_url,
    setup_stdout,
)

# Запрос собирается конкатенацией строк: переносы строк внутри литерала
# MCP Toolkit не принимает.
LIST_CODE = """
Фильтр = "";
ИмяФ = {mask};
Если НЕ ПустаяСтрока(ИмяФ) Тогда
	Фильтр = " И (П.Наименование ПОДОБНО ""%" + ИмяФ + "%"" ИЛИ П.Комментарий ПОДОБНО ""%" + ИмяФ + "%"")";
КонецЕсли;
ТекстЗапроса =
"ВЫБРАТЬ " +
"П.Наименование КАК Имя, " +
"П.Комментарий КАК Коммент, " +
"П.ИдентификаторПоставляемыхДанных КАК ИдПост, " +
"ЕСТЬNULL(Р.Кол, 0) КАК Ролей " +
"ИЗ Справочник.ПрофилиГруппДоступа КАК П " +
"ЛЕВОЕ СОЕДИНЕНИЕ (ВЫБРАТЬ Т.Ссылка КАК Ссылка, КОЛИЧЕСТВО(*) КАК Кол " +
"  ИЗ Справочник.ПрофилиГруппДоступа.Роли КАК Т СГРУППИРОВАТЬ ПО Т.Ссылка) КАК Р " +
"  ПО Р.Ссылка = П.Ссылка " +
"ГДЕ НЕ П.ПометкаУдаления" + Фильтр + " " +
"УПОРЯДОЧИТЬ ПО Имя";
Запрос = Новый Запрос(ТекстЗапроса);
Выб = Запрос.Выполнить().Выбрать();
Рез = "";
Пока Выб.Следующий() Цикл
	ИдТекст = Строка(Выб.ИдПост);
	Свой = "нет";
	Если ИдТекст = "00000000-0000-0000-0000-000000000000" ИЛИ ПустаяСтрока(ИдТекст) Тогда
		Свой = "да";
	КонецЕсли;
	Рез = Рез + Выб.Имя + "|" + Строка(Выб.Ролей) + "|" + Свой + "|" + Выб.Коммент + Символы.ПС;
КонецЦикла;
Результат = Рез;
"""

DETAIL_CODE = """
Имя = {name};
Рез = "";
Профиль = Справочники.ПрофилиГруппДоступа.НайтиПоНаименованию(Имя, Истина);
Если Профиль = Неопределено Тогда
	Результат = "NOT_FOUND";
Иначе
	Рез = "Профиль=" + Профиль.Наименование + Символы.ПС;
	Рез = Рез + "Комментарий=" + Профиль.Комментарий + Символы.ПС;
	Рез = Рез + "Ролей=" + Строка(Профиль.Роли.Количество()) + Символы.ПС;
	Рез = Рез + "ВидовДоступа=" + Строка(Профиль.ВидыДоступа.Количество()) + Символы.ПС;
	Рез = Рез + "ЗначенийДоступа=" + Строка(Профиль.ЗначенияДоступа.Количество()) + Символы.ПС;
	Для Каждого С Из Профиль.Роли Цикл
		Рез = Рез + "Роль|" + Строка(С.Роль) + Символы.ПС;
	КонецЦикла;
	Для Каждого С Из Профиль.ВидыДоступа Цикл
		Все = "нет";
		Если С.ВсеРазрешены Тогда
			Все = "да";
		КонецЕсли;
		Рез = Рез + "Вид|" + Строка(С.ВидДоступа) + "|" + Все + Символы.ПС;
	КонецЦикла;
	Результат = Рез;
КонецЕсли;
"""


def list_profiles(client: Client, mask: str, as_json: bool) -> int:
    text = client.run(LIST_CODE.format(mask=bsl_string(mask)))
    rows = parse_rows(text, 4)
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "name": r[0],
                        "roles": int(r[1]),
                        "custom": r[2] == "да",
                        "comment": r[3],
                    }
                    for r in rows
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print_table(rows, ["ПРОФИЛЬ", "РОЛЕЙ", "СВОЙ", "КОММЕНТАРИЙ"])
    print()
    print(f"Всего профилей: {len(rows)}")
    return 0


def show_details(client: Client, name: str, as_json: bool) -> int:
    text = client.run(DETAIL_CODE.format(name=bsl_string(name)))
    if text.strip() == "NOT_FOUND":
        fail(f'профиль «{name}» не найден')
    header: dict[str, str] = {}
    roles: list[str] = []
    kinds: list[dict[str, str]] = []
    for line in text.replace("\\n", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("Роль|"):
            roles.append(line.split("|", 1)[1])
        elif line.startswith("Вид|"):
            parts = line.split("|")
            kinds.append({"kind": parts[1], "all_allowed": parts[2]})
        elif "=" in line:
            key, value = line.split("=", 1)
            header[key] = value

    if as_json:
        print(
            json.dumps(
                {"header": header, "roles": roles, "access_kinds": kinds},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"Профиль: {header.get('Профиль', name)}")
    if header.get("Комментарий"):
        print(f"Комментарий: {header['Комментарий']}")
    print(f"Ролей: {header.get('Ролей', '?')}")
    print(f"Видов доступа: {header.get('ВидовДоступа', '?')}")
    print(f"Значений доступа: {header.get('ЗначенийДоступа', '?')}")
    if kinds:
        print()
        print("Виды доступа:")
        for k in kinds:
            allowed = "все разрешены" if k["all_allowed"] == "да" else "ограничены"
            print(f"  {k['kind']} ({allowed})")
    print()
    print(f"Состав ролей ({len(roles)}):")
    for i, role in enumerate(roles, 1):
        print(f"  {i:>3}. {role}")
    return 0


def main() -> int:
    setup_stdout()
    parser = argparse.ArgumentParser(description="Список профилей групп доступа")
    add_common_args(parser)
    parser.add_argument("--mask", default="", help="Фильтр по наименованию или комментарию")
    parser.add_argument("--details", default=None, help="Показать состав указанного профиля")
    args = parser.parse_args()

    client = Client(resolve_url(args.url))
    if args.details:
        return show_details(client, args.details, args.json)
    return list_profiles(client, args.mask, args.json)


if __name__ == "__main__":
    raise SystemExit(main())

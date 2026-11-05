#!/usr/bin/env python3
"""Сравнение двух профилей групп доступа.

Показывает, что даёт один профиль и не даёт другой, пересечения ролей и
конфликты ограничений.

    python scripts/profile_compare.py --left "Склад" --right "Менеджер по закупкам"
    python scripts/profile_compare.py --left A --right B --objects
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
from profile_analyze import analyze  # noqa: E402

ROLE_NAMES = """
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


def role_set(client: Client, profile: str) -> set[str]:
    raw = client.run(ROLE_NAMES.format(name=bsl_string(profile)))
    if raw.strip() == "NOT_FOUND":
        fail(f'профиль «{profile}» не найден')
    result = set()
    for line in raw.replace("\\n", "\n").splitlines():
        token = line.strip()
        if token:
            result.add(token)
    return result


def main() -> int:
    setup_stdout()
    parser = argparse.ArgumentParser(description="Сравнение двух профилей доступа")
    add_common_args(parser)
    parser.add_argument("--left", required=True, help="Первый профиль")
    parser.add_argument("--right", required=True, help="Второй профиль")
    parser.add_argument(
        "--objects", action="store_true", help="Показать разницу по объектам"
    )
    args = parser.parse_args()

    client = Client(resolve_url(args.url))

    print(f"Анализ: {args.left}")
    left_rows, left_roles = analyze(client, args.left)
    print(f"Анализ: {args.right}")
    right_rows, right_roles = analyze(client, args.right)

    left_set, right_set = set(left_roles), set(right_roles)
    common = left_set & right_set
    only_left = left_set - right_set
    only_right = right_set - left_set

    print()
    print("=" * 70)
    print("РОЛИ")
    print("=" * 70)
    print(f"{args.left}: {len(left_set)}")
    print(f"{args.right}: {len(right_set)}")
    print(f"Общих: {len(common)}")
    print(f"Только в «{args.left}»: {len(only_left)}")
    print(f"Только в «{args.right}»: {len(only_right)}")

    if only_left:
        print()
        print(f"Только в «{args.left}»:")
        for r in sorted(only_left):
            print(f"  - {r}")
    if only_right:
        print()
        print(f"Только в «{args.right}»:")
        for r in sorted(only_right):
            print(f"  - {r}")

    if args.objects:
        left_objs = {(r[0], r[1]): r for r in left_rows}
        right_objs = {(r[0], r[1]): r for r in right_rows}
        only_l = sorted(set(left_objs) - set(right_objs))
        only_r = sorted(set(right_objs) - set(left_objs))
        diff_level = []
        for key in set(left_objs) & set(right_objs):
            if left_objs[key][3] != right_objs[key][3]:
                diff_level.append((key, left_objs[key][3], right_objs[key][3]))

        print()
        print("=" * 70)
        print("ОБЪЕКТЫ")
        print("=" * 70)
        print(f"Объектов в «{args.left}»: {len(left_objs)}")
        print(f"Объектов в «{args.right}»: {len(right_objs)}")

        if only_l:
            print()
            print(f"Есть в «{args.left}», нет в «{args.right}» ({len(only_l)}):")
            for kind, name in only_l:
                print(f"  [{kind}] {left_objs[(kind, name)][2] or name}")
        if only_r:
            print()
            print(f"Есть в «{args.right}», нет в «{args.left}» ({len(only_r)}):")
            for kind, name in only_r:
                print(f"  [{kind}] {right_objs[(kind, name)][2] or name}")
        if diff_level:
            print()
            print(f"Разный уровень доступа ({len(diff_level)}):")
            rows = [
                [
                    f"{kind}.{name}",
                    left_objs[(kind, name)][2] or name,
                    lvl_l,
                    lvl_r,
                ]
                for (kind, name), lvl_l, lvl_r in diff_level
            ]
            print_table(rows, ["ОБЪЕКТ", "НАЗВАНИЕ", args.left, args.right])

    if args.json:
        print()
        print(
            json.dumps(
                {
                    "left": {
                        "name": args.left,
                        "roles": len(left_set),
                        "only_roles": sorted(only_left),
                    },
                    "right": {
                        "name": args.right,
                        "roles": len(right_set),
                        "only_roles": sorted(only_right),
                    },
                    "common_roles": len(common),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

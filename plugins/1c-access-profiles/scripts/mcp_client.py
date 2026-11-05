#!/usr/bin/env python3
"""Общий клиент MCP Toolkit 1С.

Работает через REST-эндпоинты встроенного сервера (`/api/execute_code`),
поэтому:
  * не требует регистрации MCP-сервера в Cursor;
  * не зависит от формата ответов (TOON / JSON) — BSL возвращает строку,
    которую скрипты разбирают сами.

Требования: Python 3.9+, только стандартная библиотека.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:6003"
FIELD_SEP = "|"
ROW_SEP = "\n"


def setup_stdout() -> None:
    """UTF-8 в консоли Windows, иначе кириллица ломается."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def fail(message: str, code: int = 1) -> "NoReturn":  # noqa: F821
    setup_stdout()
    print(f"ОШИБКА: {message}", file=sys.stderr)
    raise SystemExit(code)


def clean_url(url: str) -> str:
    """http://host:6004/mcp -> http://host:6004"""
    u = (url or "").strip().strip('"').strip("'")
    if not u:
        return ""
    u = u.rstrip("/")
    if u.endswith("/mcp"):
        u = u[: -len("/mcp")]
    return u.rstrip("/")


def _url_from_config(path: Path) -> str:
    """ib.mcp_url из .roles-access.yaml (сам файл читаем без PyYAML)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for pattern in (r"^\s*mcp_url:\s*\"?([^\"\n#]+)", r"^\s*live:\s*\"?([^\"\n#]+)"):
        match = re.search(pattern, text, re.M)
        if not match:
            continue
        value = match.group(1).strip()
        if value.startswith("http"):
            return value
    return ""


def _url_from_mcp_json(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    servers = data.get("mcpServers") or {}
    for cfg in servers.values():
        url = (cfg or {}).get("url")
        if url:
            return url
    return ""


def resolve_url(explicit: str | None = None, start: Path | None = None) -> str:
    """Порядок: --url -> env ONEC_MCP_URL -> .roles-access.yaml -> .cursor/mcp.json -> default."""
    if explicit:
        return clean_url(explicit)

    env = os.environ.get("ONEC_MCP_URL", "")
    if env:
        return clean_url(env)

    current = (start or Path.cwd()).resolve()
    for folder in [current, *current.parents]:
        cfg = folder / ".roles-access.yaml"
        if cfg.is_file():
            url = _url_from_config(cfg)
            if url:
                return clean_url(url)
        mcp = folder / ".cursor" / "mcp.json"
        if mcp.is_file():
            url = _url_from_mcp_json(mcp)
            if url:
                return clean_url(url)

    return DEFAULT_URL


def unwrap(payload: dict) -> str:
    """data приходит JSON-строкой; достаём значение."""
    data = payload.get("data")
    if data is None:
        return ""
    if isinstance(data, str):
        try:
            value = json.loads(data)
        except ValueError:
            return data
        return value if isinstance(value, str) else data
    return str(data)


class CollectionMissing(Exception):
    """Коллекции метаданных нет в этой конфигурации."""


class Client:
    """REST-клиент MCP Toolkit."""

    def __init__(self, url: str, timeout: int = 300) -> None:
        self.url = clean_url(url)
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}{path}",
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            fail(f"HTTP {exc.code} от {self.url}{path}: {detail}")
        except urllib.error.URLError as exc:
            fail(
                f"нет связи с MCP Toolkit по адресу {self.url} ({exc.reason}).\n"
                "     Проверьте, что обработка MCP Toolkit открыта в 1С и сервер запущен."
            )
        except TimeoutError:
            fail(f"таймаут {self.timeout} с при обращении к {self.url}{path}")
        return {}

    def health(self) -> dict:
        request = urllib.request.Request(f"{self.url}/health")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            fail(f"сервер {self.url} не отвечает на /health: {exc}")
        return {}

    def run(self, code: str, safe_mode: bool = False) -> str:
        """Выполнить BSL-фрагмент, вернуть строковый результат."""
        payload = {"code": code}
        if safe_mode:
            payload["safeMode"] = False
        result = self._post("/api/execute_code", payload)
        if not result.get("success"):
            error = str(result.get("error") or "")
            if "не является значением объектного типа" in error or "Метаданные." in error:
                raise CollectionMissing(error[:200])
            fail(f"BSL завершился с ошибкой:\n{error}")
        return unwrap(result)


def parse_rows(text: str, fields: int) -> list[list[str]]:
    """Разбор строк 'a|b|c'; строки с числом полей != fields отбрасываются."""
    rows: list[list[str]] = []
    for line in (text or "").replace("\\n", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(FIELD_SEP)
        if len(parts) == fields:
            rows.append(parts)
    return rows


def bsl_string(value: str) -> str:
    """Строковый литерал BSL с экранированием кавычек."""
    return '"' + str(value).replace('"', '""') + '"'


def bsl_list(values: list[str]) -> str:
    return ",".join(bsl_string(v) for v in values)


def print_table(rows: list[list[str]], headers: list[str]) -> None:
    """Простая выровненная таблица без внешних зависимостей."""
    if not rows:
        print("(нет данных)")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def add_common_args(parser) -> None:  # noqa: ANN001
    parser.add_argument(
        "--url",
        default=None,
        help="Адрес MCP Toolkit, например http://10.20.0.100:6004 "
        "(иначе ONEC_MCP_URL, .roles-access.yaml, .cursor/mcp.json)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Вывести результат в JSON вместо таблицы"
    )

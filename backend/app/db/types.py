from __future__ import annotations

import json

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


class JSONList(TypeDecorator):
    """Guarda una lista de Python como un string JSON en una columna TEXT.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return "[]"
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if isinstance(value, list):
            return value
        try:
            result = json.loads(value)
            return result if isinstance(result, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

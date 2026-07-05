"""Parser y matcher de expresiones cron de 5 campos, sin dependencias externas.

Campos: minuto hora dia-del-mes mes dia-de-semana.
Soporta: `*`, listas `a,b`, rangos `a-b`, pasos `*/n` y `a-b/n`.
"""

from datetime import datetime

_FIELDS = [
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day", 1, 31),
    ("month", 1, 12),
    ("weekday", 0, 6),  # 0 = lunes … 6 = domingo (datetime.weekday())
]


def _parse_field(spec: str, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step_str = part.split("/", 1)
            step = int(step_str)
        if part in ("*", ""):
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start < lo or end > hi or start > end or step < 1:
            raise ValueError(f"Campo cron fuera de rango: {spec!r}")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expression: str) -> list[set[int]]:
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError("La expresión cron debe tener 5 campos")
    return [_parse_field(p, lo, hi) for p, (_, lo, hi) in zip(parts, _FIELDS)]


def matches(expression: str, when: datetime) -> bool:
    minute, hour, day, month, weekday = parse_cron(expression)
    return (
        when.minute in minute
        and when.hour in hour
        and when.day in day
        and when.month in month
        and when.weekday() in weekday
    )

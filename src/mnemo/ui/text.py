"""Склонение русских существительных."""

from __future__ import annotations


def plural(n: int, one: str, few: str, many: str) -> str:
    """plural(1, 'карточка', 'карточки', 'карточек') -> 'карточка'."""
    n = abs(n)
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def cards_count(n: int) -> str:
    return f"{n} {plural(n, 'карточка', 'карточки', 'карточек')}"

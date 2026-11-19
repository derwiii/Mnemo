"""Нормализация и сравнение ответа (spec FR-S10, FR-S11)."""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Iterable

from mnemo.settings import ANSWER_ONE_EDIT_LENGTH, ANSWER_TWO_EDITS_LENGTH
from mnemo.domain.markup import MarkupError, expand_answers

_SPACES = re.compile(r"\s+")
_BRACKETS = re.compile(r"\([^)]*\)")
_EDGE_PUNCT = " .,!?;:"


def normalize(text: str) -> str:
    """casefold, ё=е, схлопывание пробелов, обрезка пробелов и знаков (. , ! ? ; :) по краям."""
    text = text.casefold().replace("ё", "е")
    text = _SPACES.sub(" ", text).strip()
    return text.strip(_EDGE_PUNCT)


def accepted_forms(translation: str) -> set[str]:
    """Each expanded alternative, with and without its parenthetical explanation."""
    try:
        variants = expand_answers(translation)
    except MarkupError:
        # Preserve pre-notation cards literally; never partially expand invalid data.
        variants = (translation,)
    forms = {form for variant in variants
             for form in (normalize(variant), normalize(_BRACKETS.sub("", variant)))}
    forms.discard("")
    return forms


def typo_limit(left: str, right: str) -> int:
    length = min(len(left.replace(" ", "")), len(right.replace(" ", "")))
    return (0 if length < ANSWER_ONE_EDIT_LENGTH
            else 1 if length < ANSWER_TWO_EDITS_LENGTH else 2)


def within_distance(left: str, right: str, limit: int) -> bool:
    """Bounded, unrestricted Damerau–Levenshtein distance in a narrow band.

    Cells outside the band cannot participate in a path of at most limit edits.
    Last occurrences allow overlapping transpositions (unlike OSA distance).
    """
    n, m = len(left), len(right)
    if abs(n - m) > limit:
        return False
    if limit == 0:
        return left == right
    inf = n + m + 1
    cells = {(i + 1, 1): i for i in range(min(n, limit) + 1)}
    cells.update({(1, j + 1): j for j in range(min(m, limit) + 1)})
    positions: dict[str, list[int]] = {}
    for j, char in enumerate(right, 1):
        positions.setdefault(char, []).append(j)
    last: dict[str, int] = {}
    for i, char in enumerate(left, 1):
        start = max(1, i - limit)
        occurrences = positions.get(char, [])
        index = bisect_left(occurrences, start)
        match = occurrences[index - 1] if index else 0
        for j in range(start, min(m, i + limit) + 1):
            previous_i, previous_j = last.get(right[j - 1], 0), match
            cost = int(char != right[j - 1])
            if not cost:
                match = j
            cells[i + 1, j + 1] = min(
                cells.get((i, j), inf) + cost,
                cells.get((i + 1, j), inf) + 1,
                cells.get((i, j + 1), inf) + 1,
                cells.get((previous_i, previous_j), inf)
                + (i - previous_i - 1) + 1 + (j - previous_j - 1),
            )
        last[char] = i
    return cells.get((n + 1, m + 1), inf) <= limit


def is_correct(answer: str, translations: Iterable[str]) -> bool:
    normalized = normalize(answer)
    if not normalized:
        return False
    # The notation is a template, never an answer to enter. Do not let typo
    # tolerance accept its delimiters for a valid template.
    translations = tuple(translations)
    if any(symbol in answer for symbol in "{}|"):
        for translation in translations:
            try:
                if len(expand_answers(translation)) > 1:
                    return False
            except MarkupError:
                pass
    forms = {form for t in translations for form in accepted_forms(t)}
    if normalized in forms:
        return True
    words = normalized.split(" ")
    for form in forms:
        if len(words) == 2 and form.split(" ") == words[::-1]:
            return True
        if within_distance(normalized, form, typo_limit(normalized, form)):
            return True
    return False

"""Демонстрационные данные для экрана сессии (в боевой версии карточки приходят из хранилища)."""

from __future__ import annotations

from dataclasses import dataclass, field

DEMO_DECK_NAME = "Демо-колода: английский"


@dataclass
class DemoCard:
    front: str
    translations: list[str]
    examples: list[tuple[str, str]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    card_id: str | None = None  # id карточки в хранилище (для демо-данных нет)


def demo_cards() -> list[DemoCard]:
    return [
        DemoCard(
            "to give up",
            ["сдаваться", "бросать (привычку)"],
            [("Don't give up on your dreams.", "Не отказывайся от своих мечтаний.")],
            ["Начинается на «сда…»", "Противоположность слову «продолжать»"],
        ),
        DemoCard(
            "reluctant",
            ["неохотный", "нерешительный"],
            [("She was reluctant to admit her mistake.", "Она неохотно признала свою ошибку.")],
            ["Прилагательное", "Начинается на «нео…»"],
        ),
        DemoCard(
            "to look forward to",
            ["с нетерпением ждать"],
            [("I'm looking forward to the weekend.", "Я с нетерпением жду выходных.")],
            ["Речь об ожидании чего-то приятного"],
        ),
        DemoCard(
            "hedgehog",
            ["ёж", "ёжик"],
            [("A hedgehog curled into a ball.", "Ёж свернулся в клубок.")],
            ["Животное с иголками"],
        ),
        DemoCard(
            "ubiquitous",
            ["вездесущий", "повсеместный"],
            [("Smartphones have become ubiquitous.", "Смартфоны стали повсеместными.")],
            ["Прилагательное", "Корень связан со словом «везде»"],
        ),
        DemoCard(
            "ephemeral",
            ["недолговечный", "мимолётный"],
            [("Fame can be ephemeral.", "Слава может быть недолговечной.")],
            [],
        ),
        DemoCard(
            "to come across",
            ["случайно наткнуться", "встретить (случайно)"],
            [
                ("I came across an old photo yesterday.", "Вчера я наткнулся на старую фотографию."),
                ("Did you come across her at the party?", "Ты встретил её на вечеринке?"),
            ],
            ["Глагол с предлогом", "Речь о неожиданной находке"],
        ),
    ]

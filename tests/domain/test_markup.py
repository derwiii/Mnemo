import pytest

from mnemo.domain.answers import accepted_forms, is_correct
from mnemo.domain.markup import (
    MarkupError, display_text, expand_answers, parse_markup, target_text,
)
from mnemo.domain.validation import ValidationError, clean_card_fields
from mnemo.settings import MARKUP_MAX_COMBINATIONS


def test_shared_answer_parts_and_optional_explanations():
    text = "выглядеть {молодо для своего возраста|моложе своих лет} (о внешности)"
    assert "выглядеть моложе своих лет" in accepted_forms(text)
    assert is_correct("Выглядеть молодо для своего возраста!", [text])
    assert is_correct("выглядеть моложе своих лет (о внешности)", [text])
    assert not is_correct("моложе своих лет", [text])
    assert not is_correct(text, [text])


def test_independent_groups_and_whole_dependent_branches():
    assert set(expand_answers("Ты {хорошо|отлично} выглядишь {для своего возраста|для своих лет}")) == {
        "Ты хорошо выглядишь для своего возраста", "Ты хорошо выглядишь для своих лет",
        "Ты отлично выглядишь для своего возраста", "Ты отлично выглядишь для своих лет",
    }
    assert accepted_forms("{Он пришёл|Она пришла}") == {"он пришел", "она пришла"}
    assert is_correct("перенести", ["{отложить|перенести} (встречу)"])
    assert is_correct("сдаватсья", ["{сдаваться|отступить}"])
    assert is_correct("хорошо выглядеть", ["{выглядеть хорошо|смотреться отлично}"])


def test_contexts_share_a_target_and_display_preserves_group_bounds():
    front = "[[short]] {hair|nose}"
    assert target_text(front) == "short"
    assert display_text(front, front=True) == "short [hair / nose]"
    assert display_text("выглядеть {молодо|хорошо} (о внешности)") == "выглядеть молодо / хорошо (о внешности)"
    clean = clean_card_fields(front, ["короткий (о длине)"])
    assert clean.front == front
    assert is_correct("короткий", clean.translations)
    assert not is_correct("короткие волосы", clean.translations)


def test_compact_translation_display_keeps_shared_text_and_accepts_full_answers():
    text = "Выглядеть старше {своих лет|своего возраста}"
    assert display_text(text) == "Выглядеть старше своих лет / своего возраста"
    assert is_correct("Выглядеть старше своих лет", [text])
    assert is_correct("Выглядеть старше своего возраста", [text])
    assert not is_correct("своего возраста", [text])
    assert not is_correct(display_text(text), [text])
    assert display_text("{полные|пухлые} губы") == "полные / пухлые губы"
    assert display_text("Ты {хорошо|отлично} выглядишь {для своих лет|для своего возраста}") == (
        "Ты хорошо / отлично выглядишь для своих лет / для своего возраста"
    )


@pytest.mark.parametrize("front", [
    "[[word", "word]]", "[[]]", "[[one]] [[two]]", "[[one [[two]]",
    "[[{one|two}]]", "[[word]] {one|}", "[[word]] {one}",
    "[[word]] {one|{two|three}}", "{hair|nose}", "word}",
    "[[word]] {one|[[two]]}",
])
def test_bad_front_rejected_with_field_error(front):
    with pytest.raises(ValidationError) as error:
        clean_card_fields(front, ["перевод"])
    assert "front" in error.value.fields


@pytest.mark.parametrize("text", ["{one|}", "{one}", "{a|{b|c}}", "{one|two", "one}", "[[word]]"])
def test_bad_translation_rejected(text):
    with pytest.raises(ValidationError) as error:
        clean_card_fields("word", [text])
    assert "translations" in error.value.fields


def test_combination_bound_prevents_exponential_expansion():
    at_limit = "{a|b}" * (MARKUP_MAX_COMBINATIONS.bit_length() - 1)
    assert len(expand_answers(at_limit)) == MARKUP_MAX_COMBINATIONS
    with pytest.raises(MarkupError):
        expand_answers(at_limit + "{a|b}")
    with pytest.raises(ValidationError):
        clean_card_fields("word", [at_limit + "{a|b}"])


def test_legacy_malformed_text_is_literal_without_partial_expansion():
    assert display_text("[[word]] {one|}", front=True) == "[[word]] {one|}"
    assert target_text("[[word]] {one|}") is None
    assert accepted_forms("{светлый|}") == {"{светлый|}"}
    assert not is_correct("светлый", ["{светлый|}"])
    assert display_text("[IPA] 2 < 3 & 4", front=True) == "[IPA] 2 < 3 & 4"
    assert parse_markup("[IPA]", front=True)

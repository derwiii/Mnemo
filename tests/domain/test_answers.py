from mnemo.domain.answers import is_correct, normalize


def test_normalize_basic():
    assert normalize("  ЁЖИК!  ") == "ежик"
    assert normalize("to   Give\tUp.") == "to give up"
    assert normalize("?!") == ""


def test_yo_equals_ye():
    assert is_correct("  ЁЖИК  ", ["ёж", "ёжик"])
    assert is_correct("ежик", ["ёжик"])


def test_bracket_forms():
    translations = ["сдаваться", "бросать (привычку)"]
    assert is_correct("бросать", translations)
    assert is_correct("Бросать (привычку)", translations)
    assert not is_correct("привычку", translations)


def test_any_translation_matches():
    assert is_correct("мимолётный", ["недолговечный", "мимолётный"])


def test_wrong_and_empty():
    assert not is_correct("", ["ёж"])
    assert not is_correct("   ", ["ёж"])
    assert not is_correct("еж ик", ["ежик"])  # короткое слово проверяется строго


def test_inner_punctuation_kept():
    assert not is_correct("а б", ["а, б"])


def test_typo_operations_and_length_boundaries():
    from mnemo.domain.answers import typo_limit, within_distance

    assert not is_correct("кит", ["кот"])
    assert not is_correct("ежки", ["ежик"])
    for answer in ("кошкa", "кошкии", "кокши"):
        assert is_correct(answer, ["кошки"])
    assert is_correct("кошечк", ["кошечка"])
    assert not is_correct("кошк", ["кошки"])
    assert not is_correct("кшк", ["кошки"])
    assert typo_limit("1234", "12345") == 0
    assert typo_limit("12345", "123456") == 1
    assert typo_limit("123456789", "1234567890") == 1
    assert typo_limit("12345 67890", "1234567890") == 2
    assert is_correct("параллелxx", ["параллельный"]) is False
    assert is_correct("распространенеи", ["распространение"])
    # True DL supports a transposition followed by an insertion, unlike OSA.
    assert within_distance("ca", "abc", 2)


def test_two_word_order_only_and_no_combined_relaxation():
    assert is_correct("выглядеть хорошо", ["хорошо выглядеть"])
    assert is_correct("  Выглядеть   хорошо! ", ["хорошо выглядеть (внешне)"])
    assert not is_correct("выглдеть хорошо", ["хорошо выглядеть"])
    assert not is_correct("я хорошо выгляжу", ["хорошо я выгляжу"])
    assert not is_correct("отказаться", ["сдаваться"])
    assert not is_correct("?!", ["()"])

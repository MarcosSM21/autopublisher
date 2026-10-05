from app.normalization import clean_handle, clean_text, normalize_key


def test_normalize_key_ignores_case() -> None:
    assert normalize_key("L4i4") == normalize_key("l4i4")


def test_normalize_key_applies_full_case_folding() -> None:
    assert normalize_key("Straße") == normalize_key("STRASSE")


def test_normalize_key_treats_composed_and_decomposed_forms_as_equal() -> None:
    assert normalize_key("café") == normalize_key("café")


def test_normalize_key_folds_compatibility_characters() -> None:
    assert normalize_key("Ａbc") == normalize_key("abc")


def test_normalize_key_keeps_different_values_apart() -> None:
    assert normalize_key("cyber") != normalize_key("cyb3r")


def test_clean_text_turns_blank_into_none() -> None:
    assert clean_text("   ") is None
    assert clean_text(None) is None
    assert clean_text("  L4i4 ") == "L4i4"


def test_clean_handle_strips_whitespace_and_one_at_sign() -> None:
    assert clean_handle(" @l4i4 ") == "l4i4"
    assert clean_handle("l4i4") == "l4i4"
    assert clean_handle("@@x") == "@x"
    assert clean_handle("@") == ""

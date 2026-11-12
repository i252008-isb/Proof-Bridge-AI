from proofbridge_ai.services.text_normalizer import normalize_text, truncate_text


def test_collapses_excess_whitespace():
    assert normalize_text("Hello   world\t\t!") == "Hello world !"


def test_collapses_repeated_blank_lines():
    assert normalize_text("a\n\n\n\n\nb") == "a\n\nb"


def test_normalizes_line_endings():
    assert normalize_text("a\r\nb\rc") == "a\nb\nc"


def test_strips_stray_control_characters():
    assert normalize_text("a\x00b\x07c") == "abc"


def test_normalizes_common_ocr_punctuation_artifacts():
    assert normalize_text("He said \u201chello\u201d \u2014 really\u2026") == 'He said "hello" - really...'


def test_preserves_unicode_letters():
    text = "\u00dcberweisung caf\u00e9 na\u00efve"
    assert normalize_text(text) == text


def test_empty_text_stays_empty():
    assert normalize_text("") == ""
    assert normalize_text("   ") == ""


def test_preserve_whitespace_mode_keeps_indentation():
    code = "def f():\n    return 1"
    assert normalize_text(code, preserve_whitespace=True) == code


def test_preserve_whitespace_mode_still_collapses_blank_lines():
    assert normalize_text("a\n\n\n\n\nb", preserve_whitespace=True) == "a\n\nb"


def test_truncate_text():
    assert truncate_text("abcdef", 3) == ("abc", True)
    assert truncate_text("ab", 3) == ("ab", False)
    assert truncate_text("abc", 3) == ("abc", False)

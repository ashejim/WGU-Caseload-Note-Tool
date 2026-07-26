"""Tests for the offline spell-check logic (src.spellcheck). The Tk widget
binding isn't exercised here — just the pure word logic, which is what decides
what gets underlined and suggested.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import spellcheck  # noqa: E402

_HAVE = spellcheck.is_available()


def test_word_regex_extracts_words_and_contractions():
    words = spellcheck._WORD_RE.findall(
        "Hi Joshua, don't forget Task 2 — it's due!")
    assert "don't" in words and "it's" in words and "Task" in words
    # No standalone digits / punctuation.
    assert "2" not in words


def test_looks_checkable_skips_short_caps_and_digits():
    assert not spellcheck._looks_checkable("ok")      # too short
    assert not spellcheck._looks_checkable("WGU")     # acronym
    assert not spellcheck._looks_checkable("EMA")     # acronym
    assert not spellcheck._looks_checkable("C769")    # has a digit
    assert spellcheck._looks_checkable("receive")


def test_misspelled_flags_typos_not_real_words():
    if not _HAVE:
        return  # pyspellchecker not installed in this env — logic still imports
    assert spellcheck.misspelled("teh")
    assert spellcheck.misspelled("recieve")
    assert not spellcheck.misspelled("receive")
    assert not spellcheck.misspelled("don't")      # contraction is fine
    assert not spellcheck.misspelled("WGU")        # acronym skipped


def test_suggestions_offer_the_correction():
    if not _HAVE:
        return
    sugg = spellcheck.suggestions("recieve")
    assert "receive" in sugg
    assert sugg[0] == "receive"      # best-first


def test_add_to_dictionary_makes_a_word_known():
    if not _HAVE:
        return
    made_up = "zzqwx"
    # Not a real word → flagged (length ok, no digits/caps).
    assert spellcheck.misspelled(made_up)
    try:
        spellcheck.add_to_dictionary(made_up)
        assert not spellcheck.misspelled(made_up)
    finally:
        # Best-effort cleanup of the persisted custom-dict entry.
        p = spellcheck._custom_dict_path()
        try:
            if p and p.exists():
                lines = [x for x in p.read_text(encoding="utf-8").splitlines()
                         if x.strip() and x.strip() != made_up]
                p.write_text("\n".join(lines) + ("\n" if lines else ""),
                             encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)

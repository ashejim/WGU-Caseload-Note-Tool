"""Lightweight offline spell-check for the Tk text editors.

Underlines misspelled words in red and offers suggestions on right-click. Backed
by pyspellchecker — pure-Python, a bundled ~160k-word English frequency
dictionary; nothing leaves the machine. Degrades to a silent no-op if the
library isn't available, so the editors keep working regardless.

Attach it with ``spellcheck.attach(widget)`` where `widget` is a raw ``tk.Text``,
a CustomTkinter ``CTkTextbox``, or the app's ``RichTextEditor``.
"""
import re
import tkinter as tk
from typing import Optional

# A word = letters with optional INTERNAL apostrophes (don't, it's). Leading /
# trailing apostrophes fall outside the match.
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")
_UNDERLINE = "#e03131"        # red

_spell = None                 # lazy singleton: None=unset, False=unavailable
_custom_path = None           # persisted user dictionary (set on first load)


def _custom_dict_path():
    try:
        from src.config import USER_CONFIG_DIR
        return USER_CONFIG_DIR / "spell_custom.txt"
    except Exception:
        return None


def _get_spell():
    """The shared SpellChecker (loading the user's custom words once), or False
    if pyspellchecker isn't installed."""
    global _spell, _custom_path
    if _spell is None:
        try:
            from spellchecker import SpellChecker
            sp = SpellChecker()
            _custom_path = _custom_dict_path()
            if _custom_path is not None and _custom_path.exists():
                words = [w.strip().lower() for w in
                         _custom_path.read_text(encoding="utf-8").splitlines()
                         if w.strip()]
                if words:
                    sp.word_frequency.load_words(words)
            _spell = sp
        except Exception:
            _spell = False
    return _spell


def is_available() -> bool:
    return bool(_get_spell())


def add_to_dictionary(word: str) -> None:
    """Teach the checker a word, persisted across sessions."""
    sp = _get_spell()
    w = (word or "").strip()
    if not sp or not w:
        return
    sp.word_frequency.load_words([w.lower()])
    if _custom_path is not None:
        try:
            with _custom_path.open("a", encoding="utf-8") as f:
                f.write(w + "\n")
        except Exception:
            pass


def _looks_checkable(word: str) -> bool:
    """Skip things spell-check shouldn't flag: short words, ALL-CAPS acronyms
    (WGU, EMA, PA), and anything with a digit."""
    if len(word) < 3:
        return False
    if word.isupper():
        return False
    if any(ch.isdigit() for ch in word):
        return False
    return True


def misspelled(word: str) -> bool:
    """True iff `word` is checkable and not in the dictionary."""
    if not _looks_checkable(word):
        return False
    sp = _get_spell()
    if not sp:
        return False
    return bool(sp.unknown([word.lower()]))


def suggestions(word: str, limit: int = 6) -> list:
    """Best-first spelling suggestions for `word` (up to `limit`)."""
    sp = _get_spell()
    if not sp:
        return []
    wl = word.lower()
    best = sp.correction(wl)
    cands = sp.candidates(wl) or set()
    out = ([best] if best and best != wl else [])
    out += [c for c in sorted(cands) if c != best]
    return out[:limit]


class TextSpellCheck:
    """Red-underline spell-check bound to one ``tk.Text`` widget."""

    def __init__(self, text: tk.Text):
        self.text = text
        self._after = None
        self._ignored: set = set()      # session-only "ignore this word"
        self.enabled = is_available()
        if not self.enabled:
            return
        try:
            text.tag_configure("spell_bad", underline=True,
                               underlinefg=_UNDERLINE)
        except tk.TclError:
            text.tag_configure("spell_bad", underline=True)
        text.bind("<KeyRelease>", self._schedule, add="+")
        text.bind("<<Paste>>", self._schedule, add="+")
        text.bind("<Button-3>", self._popup, add="+")
        self._schedule()

    def _schedule(self, _e=None):
        if not self.enabled:
            return
        if self._after:
            try: self.text.after_cancel(self._after)
            except Exception: pass
        self._after = self.text.after(400, self.recheck)

    def recheck(self):
        """Re-tag every misspelled word (debounced from edits)."""
        self._after = None
        t = self.text
        try:
            content = t.get("1.0", "end-1c")
        except Exception:
            return
        t.tag_remove("spell_bad", "1.0", "end")
        for m in _WORD_RE.finditer(content):
            w = m.group(0)
            if w.lower() not in self._ignored and misspelled(w):
                t.tag_add("spell_bad", f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    def _word_at(self, event):
        """(word, start, end) of a flagged word under the click, or (None,)*3."""
        t = self.text
        idx = t.index(f"@{event.x},{event.y}")
        rng = t.tag_prevrange("spell_bad", f"{idx}+1c")
        if rng and t.compare(rng[0], "<=", idx) and t.compare(idx, "<", rng[1]):
            return t.get(rng[0], rng[1]), rng[0], rng[1]
        return None, None, None

    def _popup(self, event):
        if not self.enabled:
            return
        word, start, end = self._word_at(event)
        if not word:
            return
        menu = tk.Menu(self.text, tearoff=0)
        sugg = suggestions(word)
        if sugg:
            for c in sugg:
                menu.add_command(
                    label=c, command=lambda c=c: self._replace(start, end, c))
        else:
            menu.add_command(label="(no suggestions)", state="disabled")
        menu.add_separator()
        menu.add_command(label="Ignore", command=lambda: self._ignore(word))
        menu.add_command(label="Add to dictionary",
                         command=lambda: self._add(word))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _replace(self, start, end, repl):
        t = self.text
        orig = t.get(start, end)
        if orig[:1].isupper():
            repl = repl[:1].upper() + repl[1:]
        t.delete(start, end)
        t.insert(start, repl)
        self._schedule()

    def _ignore(self, word):
        self._ignored.add(word.lower())
        self.recheck()

    def _add(self, word):
        add_to_dictionary(word)
        self.recheck()


def attach(widget) -> Optional[TextSpellCheck]:
    """Attach spell-check to a tk.Text / CTkTextbox / RichTextEditor. Returns the
    checker, or None if unavailable or not a text widget (never raises)."""
    txt = None
    if isinstance(widget, tk.Text):
        txt = widget
    elif isinstance(getattr(widget, "_textbox", None), tk.Text):   # CTkTextbox
        txt = widget._textbox
    elif isinstance(getattr(widget, "text", None), tk.Text):       # RichTextEditor
        txt = widget.text
    if txt is None or not is_available():
        return None
    try:
        return TextSpellCheck(txt)
    except Exception:
        return None

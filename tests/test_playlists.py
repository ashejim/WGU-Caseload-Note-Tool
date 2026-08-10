"""Tests for queue playlists — the Playlist model + its scenarios.yaml
serialize/load round-trip (src.scenarios.playlist_to_dict / load_playlists /
_playlist_from_dict).

Run: python tests/test_playlists.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scenarios import (  # noqa: E402
    Playlist, playlist_to_dict, load_playlists, _playlist_from_dict,
)


def _write_yaml(text: str) -> Path:
    fd, p = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    path = Path(p)
    path.write_text(text, encoding="utf-8")
    return path


def test_playlist_to_dict_roundtrip():
    p = Playlist(name="Welcome", actions=["C769 welcome", "D502 welcome"])
    d = playlist_to_dict(p)
    assert d == {"name": "Welcome",
                 "actions": ["C769 welcome", "D502 welcome"]}
    back = _playlist_from_dict(d)
    assert back.name == p.name
    assert back.actions == p.actions


def test_playlist_defaults_empty_actions():
    assert Playlist(name="x").actions == []
    assert playlist_to_dict(Playlist(name="x")) == {"name": "x", "actions": []}


def test_from_dict_drops_nameless_and_blanks_actions():
    assert _playlist_from_dict({"name": "", "actions": ["a"]}) is None
    assert _playlist_from_dict({"actions": ["a"]}) is None
    assert _playlist_from_dict("notadict") is None
    # blank / whitespace action names are dropped, order preserved
    p = _playlist_from_dict(
        {"name": "P", "actions": ["a", "", "  ", "b", " c "]})
    assert p.actions == ["a", "b", "c"]


def test_from_dict_non_list_actions():
    p = _playlist_from_dict({"name": "P", "actions": "oops"})
    assert p.actions == []
    p2 = _playlist_from_dict({"name": "P"})
    assert p2.actions == []


def test_load_playlists_from_yaml():
    path = _write_yaml(
        "scenarios: {}\n"
        "playlists:\n"
        "  - name: Welcome\n"
        "    actions: [C769 welcome, D502 welcome, C964 welcome]\n"
        "  - name: Nudge\n"
        "    actions: []\n"
    )
    try:
        pls = load_playlists(path)
        assert [p.name for p in pls] == ["Welcome", "Nudge"]
        assert pls[0].actions == ["C769 welcome", "D502 welcome",
                                  "C964 welcome"]
        assert pls[1].actions == []
    finally:
        os.unlink(path)


def test_load_playlists_missing_block_is_empty():
    path = _write_yaml("scenarios: {}\n")
    try:
        assert load_playlists(path) == []
    finally:
        os.unlink(path)


def test_load_playlists_bad_entries_skipped():
    path = _write_yaml(
        "playlists:\n"
        "  - name: Good\n"
        "    actions: [a]\n"
        "  - actions: [b]\n"        # no name -> dropped
        "  - name: ''\n"            # empty name -> dropped
    )
    try:
        pls = load_playlists(path)
        assert [p.name for p in pls] == ["Good"]
    finally:
        os.unlink(path)


def test_load_playlists_non_list_block():
    path = _write_yaml("playlists: not-a-list\n")
    try:
        assert load_playlists(path) == []
    finally:
        os.unlink(path)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
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

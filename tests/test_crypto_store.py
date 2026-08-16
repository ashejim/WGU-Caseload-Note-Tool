"""Tests for src.crypto_store — the cipher round-trip and, critically, the
ManagedFiles.decrypt_all lifecycle rule that decides whether to decrypt the
.enc or keep an existing plaintext.

Regression: a leftover 0-byte plaintext (from an interrupted shred on the
previous exit) must NOT be treated as a "newer crash leftover to keep" — doing
so silently shadowed the encrypted history with an empty DB (and the next clean
exit then re-encrypted the empty DB over the good .enc). decrypt_all must fall
through and decrypt the .enc in that case.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import crypto_store  # noqa: E402


def _vault(dirp):
    v = crypto_store.DataVault(Path(dirp) / "vault.json")
    v.setup("correct horse battery staple")   # sets up + unlocks in-process
    return v


def _mtime(path, t):
    os.utime(path, (t, t))


def test_cipher_roundtrip_and_bad_key():
    master = crypto_store.derive_master("pw", b"0123456789abcdef")
    blob = crypto_store.encrypt(master, b"hello world")
    assert crypto_store.is_encrypted(blob)
    assert crypto_store.decrypt(master, blob) == b"hello world"
    other = crypto_store.derive_master("pw2", b"0123456789abcdef")
    try:
        crypto_store.decrypt(other, blob)
        assert False, "wrong key should raise"
    except ValueError:
        pass


def test_decrypt_all_when_no_plaintext():
    with tempfile.TemporaryDirectory() as d:
        v = _vault(d)
        plain = Path(d) / "history.db"
        plain.write_bytes(b"REAL-DATA")
        mf = crypto_store.ManagedFiles(v, [plain])
        mf.lock_all()                       # encrypt + shred plaintext
        assert not plain.exists()
        errs = mf.decrypt_all()
        assert errs == []
        assert plain.read_bytes() == b"REAL-DATA"


def test_decrypt_all_keeps_nonempty_newer_leftover():
    # A genuine crash leftover (non-empty, newer than .enc) is preserved.
    with tempfile.TemporaryDirectory() as d:
        v = _vault(d)
        plain = Path(d) / "history.db"
        enc = crypto_store.ManagedFiles.enc_path(plain)
        plain.write_bytes(b"OLD")
        v.encrypt_file(plain, enc)
        _mtime(enc, 1000)
        plain.write_bytes(b"NEWER-REAL-DATA")   # session wrote more after enc
        _mtime(plain, 2000)                      # strictly newer
        mf = crypto_store.ManagedFiles(v, [plain])
        assert mf.decrypt_all() == []
        assert plain.read_bytes() == b"NEWER-REAL-DATA"   # kept, not clobbered


def test_decrypt_all_overwrites_older_plaintext():
    with tempfile.TemporaryDirectory() as d:
        v = _vault(d)
        plain = Path(d) / "history.db"
        enc = crypto_store.ManagedFiles.enc_path(plain)
        plain.write_bytes(b"FRESH-IN-ENC")
        v.encrypt_file(plain, enc)
        _mtime(enc, 2000)
        plain.write_bytes(b"STALE")
        _mtime(plain, 1000)                      # older than enc
        mf = crypto_store.ManagedFiles(v, [plain])
        assert mf.decrypt_all() == []
        assert plain.read_bytes() == b"FRESH-IN-ENC"


def test_decrypt_all_ignores_zero_byte_newer_leftover():
    # THE REGRESSION: a 0-byte plaintext newer than the .enc must NOT be kept;
    # decrypt_all must restore from the .enc instead of leaving an empty DB.
    with tempfile.TemporaryDirectory() as d:
        v = _vault(d)
        plain = Path(d) / "history.db"
        enc = crypto_store.ManagedFiles.enc_path(plain)
        plain.write_bytes(b"THE-REAL-HISTORY")
        v.encrypt_file(plain, enc)
        _mtime(enc, 1000)
        plain.write_bytes(b"")                    # 0-byte leftover (bad shred)
        _mtime(plain, 5000)                       # newer mtime than .enc
        assert plain.stat().st_size == 0
        mf = crypto_store.ManagedFiles(v, [plain])
        assert mf.decrypt_all() == []
        assert plain.read_bytes() == b"THE-REAL-HISTORY"   # restored, not empty


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

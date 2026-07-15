from pathlib import Path

import pytest

from cyber_catgirl.security.credential_store import (
    BilibiliCredentialData,
    CredentialStore,
    CredentialUnreadable,
    DpapiProtector,
)


class PrefixProtector:
    def protect(self, value: bytes) -> bytes:
        return b"encrypted:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        if not value.startswith(b"encrypted:"):
            raise ValueError("invalid ciphertext")
        return value.removeprefix(b"encrypted:")[::-1]


def test_store_round_trip_never_writes_plaintext(tmp_path: Path):
    path = tmp_path / "secrets" / "bilibili-credential.bin"
    store = CredentialStore(path, PrefixProtector())
    secret = BilibiliCredentialData(
        sessdata="sess-secret",
        bili_jct="csrf-secret",
        dedeuserid="123",
        ac_time_value="refresh-secret",
    )

    store.save(secret)

    assert store.configured() is True
    assert b"sess-secret" not in path.read_bytes()
    assert store.load() == secret


def test_store_overwrites_atomically_and_deletes(tmp_path: Path):
    path = tmp_path / "bilibili-credential.bin"
    store = CredentialStore(path, PrefixProtector())
    store.save(BilibiliCredentialData("old", "old-csrf"))
    store.save(BilibiliCredentialData("new", "new-csrf"))

    assert store.load().sessdata == "new"
    assert not path.with_suffix(".tmp").exists()

    store.delete()

    assert store.configured() is False
    assert store.load() is None


def test_store_maps_corrupt_ciphertext_to_domain_error(tmp_path: Path):
    path = tmp_path / "bilibili-credential.bin"
    path.write_bytes(b"not-encrypted")

    with pytest.raises(CredentialUnreadable, match="无法解密"):
        CredentialStore(path, PrefixProtector()).load()


def test_dpapi_round_trip_uses_current_windows_user():
    protector = DpapiProtector()
    plaintext = b"local-only-test-secret"

    ciphertext = protector.protect(plaintext)

    assert plaintext not in ciphertext
    assert protector.unprotect(ciphertext) == plaintext

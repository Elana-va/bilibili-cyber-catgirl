from pathlib import Path

import pytest

from cyber_catgirl.security.credential_store import (
    CredentialUnreadable,
    DeepSeekCredentialData,
    DeepSeekCredentialStore,
)


class PrefixProtector:
    def protect(self, value: bytes) -> bytes:
        return b"encrypted:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        if not value.startswith(b"encrypted:"):
            raise ValueError("invalid ciphertext")
        return value.removeprefix(b"encrypted:")[::-1]


def test_deepseek_store_round_trip_never_writes_plaintext(tmp_path: Path):
    path = tmp_path / "secrets" / "deepseek-credential.bin"
    store = DeepSeekCredentialStore(path, PrefixProtector())
    credential = DeepSeekCredentialData(
        api_key="sk-secret-value",
        model="deepseek-v4-flash",
        verified_at="2026-07-15T08:00:00+00:00",
    )

    store.save(credential)

    assert b"sk-secret-value" not in path.read_bytes()
    assert store.load() == credential
    assert not path.with_suffix(".tmp").exists()


def test_deepseek_store_overwrites_and_deletes(tmp_path: Path):
    path = tmp_path / "deepseek-credential.bin"
    store = DeepSeekCredentialStore(path, PrefixProtector())
    store.save(DeepSeekCredentialData("old", "deepseek-v4-flash", "old-time"))
    store.save(DeepSeekCredentialData("new", "deepseek-v4-pro", "new-time"))

    assert store.load().api_key == "new"
    store.delete()
    assert store.configured() is False
    assert store.load() is None


def test_deepseek_store_maps_corrupt_ciphertext_to_domain_error(tmp_path: Path):
    path = tmp_path / "deepseek-credential.bin"
    path.write_bytes(b"not-encrypted")

    with pytest.raises(CredentialUnreadable, match="DeepSeek 凭证无法解密"):
        DeepSeekCredentialStore(path, PrefixProtector()).load()

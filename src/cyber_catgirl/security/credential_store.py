from __future__ import annotations

import ctypes
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


class SecureStorageUnavailable(RuntimeError):
    """Raised when credentials cannot be protected by the operating system."""


class CredentialUnreadable(RuntimeError):
    """Raised when stored credential ciphertext cannot be recovered safely."""


@dataclass(frozen=True)
class BilibiliCredentialData:
    sessdata: str
    bili_jct: str
    dedeuserid: str | None = None
    ac_time_value: str | None = None
    buvid3: str | None = None


class DataProtector(Protocol):
    def protect(self, value: bytes) -> bytes: ...

    def unprotect(self, value: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class DpapiProtector:
    """Protect bytes for the current Windows user with DPAPI."""

    _ui_forbidden = 0x01

    def _libraries(self):
        if sys.platform != "win32":
            raise SecureStorageUnavailable("当前系统不支持 Windows DPAPI")
        return ctypes.WinDLL("crypt32", use_last_error=True), ctypes.WinDLL(
            "kernel32", use_last_error=True
        )

    @staticmethod
    def _blob(value: bytes) -> tuple[_DataBlob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(value)
        blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    def protect(self, value: bytes) -> bytes:
        crypt32, kernel32 = self._libraries()
        source, source_buffer = self._blob(value)
        result = _DataBlob()
        _ = source_buffer
        ok = crypt32.CryptProtectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            self._ui_forbidden,
            ctypes.byref(result),
        )
        if not ok:
            raise SecureStorageUnavailable(
                f"Windows DPAPI 加密失败 ({ctypes.get_last_error()})"
            )
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            kernel32.LocalFree(result.pbData)

    def unprotect(self, value: bytes) -> bytes:
        crypt32, kernel32 = self._libraries()
        source, source_buffer = self._blob(value)
        result = _DataBlob()
        _ = source_buffer
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            self._ui_forbidden,
            ctypes.byref(result),
        )
        if not ok:
            raise CredentialUnreadable(
                f"Windows DPAPI 解密失败 ({ctypes.get_last_error()})"
            )
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            kernel32.LocalFree(result.pbData)


class CredentialStore:
    def __init__(self, path: Path, protector: DataProtector):
        self.path = path
        self.protector = protector

    def configured(self) -> bool:
        return self.path.is_file()

    def save(self, data: BilibiliCredentialData) -> None:
        plaintext = json.dumps(asdict(data), ensure_ascii=False).encode("utf-8")
        ciphertext = self.protector.protect(plaintext)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(ciphertext)
        temporary.replace(self.path)

    def load(self) -> BilibiliCredentialData | None:
        if not self.configured():
            return None
        try:
            plaintext = self.protector.unprotect(self.path.read_bytes())
            payload = json.loads(plaintext.decode("utf-8"))
            return BilibiliCredentialData(**payload)
        except CredentialUnreadable:
            raise
        except Exception as exc:
            raise CredentialUnreadable("B站凭证无法解密") from exc

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)

"""Small local credential vault used by autonomous provisioning.

On Windows this uses DPAPI through the system cryptography API, so values are
bound to the current Windows user and never written to the repository in clear.
A restrictive-permission file fallback is used on other platforms.
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import stat
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
VAULT_FILE = ROOT / "config" / ".local_vault.json"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi(protect: bool, data: bytes) -> bytes:
    if os.name != "nt":
        raise OSError("DPAPI is only available on Windows")
    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    src = ctypes.create_string_buffer(data)
    inp = _Blob(len(data), ctypes.cast(src, ctypes.POINTER(ctypes.c_byte)))
    out = _Blob()
    if protect:
        ok = crypt.CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out))
    else:
        ok = crypt.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError(f"Windows credential operation failed: {kernel.GetLastError()}")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel.LocalFree(out.pbData)


def _load() -> dict[str, str]:
    try:
        return json.loads(VAULT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict[str, str]) -> None:
    VAULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = VAULT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        tmp.replace(VAULT_FILE)
    finally:
        if os.name != "nt":
            try:
                os.chmod(VAULT_FILE, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass


def set_value(name: str, value: str) -> None:
    raw = str(value or "").encode("utf-8")
    if os.name == "nt":
        encoded = "dpapi:" + base64.b64encode(_dpapi(True, raw)).decode("ascii")
    else:
        encoded = "plain:" + base64.b64encode(raw).decode("ascii")
    data = _load()
    data[str(name)] = encoded
    _save(data)


def get_value(name: str) -> Optional[str]:
    encoded = _load().get(str(name))
    if not encoded or ":" not in encoded:
        return None
    kind, payload = encoded.split(":", 1)
    try:
        raw = base64.b64decode(payload.encode("ascii"))
        if kind == "dpapi":
            raw = _dpapi(False, raw)
        elif kind != "plain":
            return None
        return raw.decode("utf-8")
    except Exception:
        return None


def has_value(name: str) -> bool:
    return bool(get_value(name))


def delete_value(name: str) -> None:
    data = _load()
    if str(name) in data:
        data.pop(str(name), None)
        _save(data)

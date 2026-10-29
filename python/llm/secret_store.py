"""Read-only view of the server secret store (BROWSER_STORAGE_POLICY, section 11c).

`scripts/secret-store.js` is the only writer of data/secrets/. This module only reads `ai.json`:

    { "<provider>": { "key": "...", "baseUrl": "https://...", "setAt": "ISO" } }

Rules:
- It returns the entry of ONE provider, the one the caller names. It never builds a list of keys, never reads
  another provider's entry out of the file for use, and never puts a key in os.environ (child processes inherit it).
- It looks at the file only for a provider the store can hold; any other provider (deepseek, groq, ollama...) never opens it.
- Absent file, or no usable entry for the provider: None (the caller may use its .env fallback).
  A file that is there but cannot be trusted (not regular, group or other can access it, not a JSON object, a bad
  baseUrl) refuses with SecretStoreError; there is no fallback after that.
- Error text is fixed. It never holds a path, a key or file content, and it is raised outside the `except` block
  that caught the parse error, so no traceback chains the file text (JSONDecodeError keeps the whole document).
- `register()` / `mask()`: the exact value of a key this process resolved is masked (with its URL-encoded form) in
  ledger rows, log lines and error text. Only values resolved for a call are registered, never other entries.

The name is not `secrets.py` on purpose: python/llm is on sys.path and would shadow the standard library module.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]

# Providers the store can hold (scripts/secret-store.js KEYED_AI_PROVIDERS).
KEYED_AI_PROVIDERS = ("openai", "openrouter", "claude", "gemini")
AI_FILE = "ai.json"
MAX_FILE_BYTES = 1_000_000
# Values shorter than this are never used for masking: they would mangle ordinary text.
MIN_MASK_LENGTH = 8


class SecretStoreError(RuntimeError):
    """The store file is there but cannot be trusted or read. The message is fixed text."""


@dataclass(frozen=True)
class Credential:
    api_key: str = field(repr=False)  # a traceback or log of the object must not show it
    base_url: str | None
    source: str  # "store" or "env"


def root() -> Path:
    return Path(os.environ.get("HOLOJOB_SECRETS_DIR") or ROOT / "data" / "secrets")


_BAD_FILE = "The secret store file cannot be used (not a private regular file, or not valid JSON); nothing was sent. Fix it in Settings > Privacy."
_BAD_URL = "The base URL stored with the key is not a plain http or https URL; nothing was sent. Set the key again in Settings > Privacy."


def _read_ai() -> dict | None:
    """The parsed ai.json, None when the file does not exist. SecretStoreError for anything else."""
    path = root() / AI_FILE
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        return None
    except OSError:
        fd = None  # unreadable, a symlink, a permission problem
    if fd is None:
        raise SecretStoreError(_BAD_FILE) from None
    data, bad = None, False
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > MAX_FILE_BYTES:
            bad = True
        else:
            with os.fdopen(fd, "rb", closefd=False) as handle:
                try:
                    data = json.loads(handle.read().decode("utf-8"))
                except ValueError:  # JSONDecodeError and UnicodeDecodeError
                    bad = True
    except OSError:
        bad = True
    finally:
        os.close(fd)
    if bad or not isinstance(data, dict):
        raise SecretStoreError(_BAD_FILE)
    return data


def get_credential(provider: str) -> Credential | None:
    """The stored key and pinned base URL for this one provider, or None when the store has none for it."""
    if provider not in KEYED_AI_PROVIDERS:
        return None
    data = _read_ai()
    entry = data.get(provider) if data else None
    key = entry.get("key") if isinstance(entry, dict) else None
    if not isinstance(key, str) or not key:
        return None
    base_url = entry.get("baseUrl")
    pinned = None
    if base_url not in (None, ""):
        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")) or any(c.isspace() for c in base_url):
            raise SecretStoreError(_BAD_URL)
        pinned = base_url.rstrip("/")
    register(key)
    return Credential(api_key=key, base_url=pinned, source="store")


_masked: set[str] = set()


def register(value: str | None) -> None:
    """Mask this exact value (and its URL-encoded form) from now on."""
    text = value if isinstance(value, str) else ""
    if len(text) >= MIN_MASK_LENGTH:
        _masked.add(text)
        encoded = quote(text, safe="")
        if encoded != text:
            _masked.add(encoded)


def mask(text):
    """Replace every registered value in a string with [secret]; anything else passes through."""
    if not isinstance(text, str) or not _masked:
        return text
    for value in sorted(_masked, key=len, reverse=True):
        text = text.replace(value, "[secret]")
    return text


def describe(provider: str) -> dict:
    """{ source, last4, baseUrl } for one provider, never the key; for the owner's check (`status <provider>`)."""
    cred = get_credential(provider)
    if cred is None:
        return {"set": False}
    return {"set": True, "source": "store", "last4": cred.api_key[-4:] if len(cred.api_key) >= 12 else "****",
            "baseUrl": cred.base_url}


def main(argv: list[str]) -> int:
    """`python secret_store.py status <provider>`: says whether the store holds a key for it, and the last 4 characters."""
    if len(argv) != 2 or argv[0] != "status" or argv[1] not in KEYED_AI_PROVIDERS:
        print(f"usage: secret_store.py status <{'|'.join(KEYED_AI_PROVIDERS)}>", file=sys.stderr)
        return 2
    try:
        print(json.dumps(describe(argv[1])))
    except SecretStoreError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

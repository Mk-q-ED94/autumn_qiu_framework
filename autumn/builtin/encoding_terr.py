"""Encoding / hashing capability domain.

Base64, hex, URL percent-encoding, cryptographic digests, UUID generation,
HMAC signing, random token generation, and JSON/base64 round-trips — all
stdlib, no I/O. The model reaches for these constantly when massaging a
tool's stringified payload, fingerprinting content for dedup, or building a
request URL, so shipping them built-in saves every agent author the boilerplate.
Inputs are size-bounded to keep a pathological payload from pinning the loop.

Primitive tools (standalone-callable):
    base64_encode, base64_decode, hash_text, hex_encode, hex_decode,
    url_encode, url_decode, uuid_generate, hmac_sign, random_token,
    json_to_base64, base64_to_json

Compound skills (orchestrate multiple primitives):
    fingerprint
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac as _hmac
import json
import re
import secrets
import urllib.parse
import uuid
from typing import Any

from ..core.components.skill import Skill
from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter

_MAX_INPUT = 1_000_000  # 1MB cap; protects the framework from OOM on bad input.
_HASH_ALGOS = ("md5", "sha1", "sha256", "sha512")
_HMAC_ALGOS = ("sha256", "sha512", "sha1", "md5")

_TOKEN_CHARSETS = {
    "alphanumeric": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "hex": "0123456789abcdef",
    "alpha": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "numeric": "0123456789",
    "urlsafe": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
}


def _check_size(value: str, label: str = "text") -> None:
    if len(value) > _MAX_INPUT:
        raise ValueError(f"{label} exceeds {_MAX_INPUT} chars")


# ── Primitive tool functions (exported for standalone use) ────────────────────


async def _base64_encode(text: str, urlsafe: bool = False) -> str:
    _check_size(text)
    raw = text.encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw) if urlsafe else base64.b64encode(raw)
    return encoded.decode("ascii")


async def _base64_decode(data: str, urlsafe: bool = False) -> str:
    _check_size(data, "data")
    try:
        raw = base64.urlsafe_b64decode(data) if urlsafe else base64.b64decode(data)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"invalid base64: {exc}") from exc
    return raw.decode("utf-8")


async def _hash_text(text: str, algorithm: str = "sha256") -> str:
    _check_size(text)
    algo = algorithm.lower()
    if algo not in _HASH_ALGOS:
        raise ValueError(f"unsupported algorithm: {algorithm!r}; use one of {_HASH_ALGOS}")
    return hashlib.new(algo, text.encode("utf-8")).hexdigest()


async def _hex_encode(text: str) -> str:
    _check_size(text)
    return text.encode("utf-8").hex()


async def _hex_decode(data: str) -> str:
    _check_size(data, "data")
    try:
        return bytes.fromhex(data).decode("utf-8")
    except ValueError as exc:
        raise ValueError(f"invalid hex: {exc}") from exc


async def _url_encode(text: str, safe: str = "") -> str:
    _check_size(text)
    return urllib.parse.quote(text, safe=safe)


async def _url_decode(text: str) -> str:
    _check_size(text)
    return urllib.parse.unquote(text)


async def _uuid_generate(count: int = 1) -> list[str]:
    if count < 1 or count > 1000:
        raise ValueError("count must be between 1 and 1000")
    return [str(uuid.uuid4()) for _ in range(count)]


async def _hmac_sign(message: str, key: str, algorithm: str = "sha256") -> str:
    """HMAC-sign a message with a key. Returns hex digest."""
    algo = algorithm.lower()
    if algo not in _HMAC_ALGOS:
        raise ValueError(
            f"unsupported algorithm: {algorithm!r}; use one of {_HMAC_ALGOS}"
        )
    _check_size(message)
    sig = _hmac.new(key.encode("utf-8"), message.encode("utf-8"), algo)
    return sig.hexdigest()


async def _random_token(length: int = 32, charset: str = "alphanumeric") -> str:
    """Generate a cryptographically random token string."""
    if length < 1 or length > 1024:
        raise ValueError("length must be between 1 and 1024")
    if charset in _TOKEN_CHARSETS:
        alphabet = _TOKEN_CHARSETS[charset]
    else:
        alphabet = charset  # treat as a literal alphabet string
    if not alphabet:
        raise ValueError("charset cannot be empty")
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _json_to_base64(data: Any) -> str:
    """Serialize ``data`` to compact JSON then encode as URL-safe base64."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    _check_size(text, "serialized data")
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


async def _base64_to_json(data: str) -> Any:
    """Decode a URL-safe base64 string and parse it as JSON."""
    _check_size(data, "data")
    try:
        raw = base64.urlsafe_b64decode(data)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"invalid base64: {exc}") from exc
    return json.loads(raw.decode("utf-8"))


def _b64url_segment(seg: str) -> bytes:
    """Decode a single base64url JWT segment, adding the padding JWTs omit."""
    padded = seg + "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(padded)


async def _jwt_decode(token: str) -> dict[str, Any]:
    """Decode a JWT's header and payload WITHOUT verifying its signature.

    Splits the three dot-separated segments, base64url-decodes the header and
    payload as JSON, and returns ``{header, payload, signature}``. The signature
    is returned as its raw base64url string — this is an inspection tool, it does
    NOT validate authenticity. Never trust a decoded payload for authorization
    without verifying the signature out of band.
    """
    _check_size(token, "token")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT: expected three dot-separated segments")
    try:
        header = json.loads(_b64url_segment(parts[0]).decode("utf-8"))
        payload = json.loads(_b64url_segment(parts[1]).decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid JWT segment: {exc}") from exc
    return {"header": header, "payload": payload, "signature": parts[2]}


_HEX_ALPHABET = set("0123456789abcdefABCDEF")
_B64_ALPHABET = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=-_"
)


async def _detect_encoding(data: str) -> str:
    """Best-effort guess of how a string is encoded.

    Returns one of: ``hex``, ``base64``, ``url`` (percent-encoded), or ``plain``.
    Heuristic, not authoritative — a string can be valid under several schemes;
    the most specific plausible match is reported.
    """
    _check_size(data, "data")
    s = data.strip()
    if not s:
        return "plain"
    # Percent-encoding: contains %XX escapes.
    if re.search(r"%[0-9A-Fa-f]{2}", s):
        return "url"
    # Hex: even length, all hex digits.
    if len(s) % 2 == 0 and all(c in _HEX_ALPHABET for c in s):
        return "hex"
    # Base64: length multiple of 4, base64 alphabet, decodes cleanly.
    if len(s) >= 4 and len(s) % 4 == 0 and all(c in _B64_ALPHABET for c in s):
        try:
            base64.b64decode(s, validate=True)
            return "base64"
        except (binascii.Error, ValueError):
            try:
                base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
                return "base64"
            except (binascii.Error, ValueError):
                pass
    return "plain"


# ── Compound skill functions (exported for standalone use) ────────────────────


async def _fingerprint(data: Any) -> str:
    """Canonical JSON → SHA-256 hex digest.

    Serialises ``data`` with sorted keys and no whitespace (canonical form),
    then SHA-256 hashes the result. Identical data structures always produce
    the same fingerprint regardless of dict key order — useful for content
    deduplication, change detection, and cache keying.
    """
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Terr factory ──────────────────────────────────────────────────────────────


def encoding_terr() -> Terr:
    """Build the ``encoding`` Terr.

    Primitive tools (standalone-callable):
        base64_encode/decode(text, urlsafe)     → base64 codec
        hash_text(text, algorithm)              → md5/sha1/sha256/sha512 digest
        hex_encode/decode(text)                 → hex codec
        url_encode/decode(text, safe)           → percent-encoding codec
        uuid_generate(count)                    → random UUID v4 strings
        hmac_sign(message, key, algorithm)      → HMAC-SHA256/512/1 hex digest
        random_token(length, charset)           → cryptographically random string
        json_to_base64(data)                    → JSON → URL-safe base64
        base64_to_json(data)                    → URL-safe base64 → JSON

    Compound skills (orchestrate primitives):
        fingerprint(data)                       → canonical SHA-256 for any JSON value
    """
    return Terr(
        name="encoding",
        description=(
            "Base64/hex/URL encoding, cryptographic hashing, HMAC signing, "
            "UUID generation, random tokens, and JSON/base64 round-trips."
        ),
        tools=[
            Tool(
                name="base64_encode",
                description="Encode UTF-8 text to a base64 string.",
                fn=_base64_encode,
                parameters=[
                    ToolParameter("text", "string", "The text to encode."),
                    ToolParameter("urlsafe", "boolean",
                                  "Use the URL-safe alphabet (- and _).",
                                  required=False),
                ],
            ),
            Tool(
                name="base64_decode",
                description="Decode a base64 string back to UTF-8 text.",
                fn=_base64_decode,
                parameters=[
                    ToolParameter("data", "string", "The base64 text to decode."),
                    ToolParameter("urlsafe", "boolean",
                                  "Input uses the URL-safe alphabet.",
                                  required=False),
                ],
            ),
            Tool(
                name="hash_text",
                description="Hash text and return the hex digest. Algorithms: md5, sha1, sha256, sha512.",
                fn=_hash_text,
                parameters=[
                    ToolParameter("text", "string", "The text to hash."),
                    ToolParameter("algorithm", "string",
                                  "md5 | sha1 | sha256 | sha512.",
                                  required=False,
                                  extra={"enum": list(_HASH_ALGOS)}),
                ],
            ),
            Tool(
                name="hex_encode",
                description="Encode UTF-8 text to a hexadecimal string.",
                fn=_hex_encode,
                parameters=[
                    ToolParameter("text", "string", "The text to encode."),
                ],
            ),
            Tool(
                name="hex_decode",
                description="Decode a hexadecimal string back to UTF-8 text.",
                fn=_hex_decode,
                parameters=[
                    ToolParameter("data", "string", "The hex text to decode."),
                ],
            ),
            Tool(
                name="url_encode",
                description="Percent-encode text for safe use in a URL component.",
                fn=_url_encode,
                parameters=[
                    ToolParameter("text", "string", "The text to encode."),
                    ToolParameter("safe", "string",
                                  "Characters to leave un-escaped, e.g. '/'.",
                                  required=False),
                ],
            ),
            Tool(
                name="url_decode",
                description="Decode a percent-encoded URL component.",
                fn=_url_decode,
                parameters=[
                    ToolParameter("text", "string", "The percent-encoded text."),
                ],
            ),
            Tool(
                name="uuid_generate",
                description="Generate one or more random (v4) UUID strings.",
                fn=_uuid_generate,
                parameters=[
                    ToolParameter("count", "integer",
                                  "How many UUIDs to generate (1-1000).",
                                  required=False),
                ],
            ),
            Tool(
                name="hmac_sign",
                description=(
                    "HMAC-sign a message with a secret key and return the hex digest. "
                    "Algorithms: sha256 (default), sha512, sha1, md5."
                ),
                fn=_hmac_sign,
                parameters=[
                    ToolParameter("message", "string", "The message to sign."),
                    ToolParameter("key", "string", "The secret key."),
                    ToolParameter("algorithm", "string",
                                  "sha256 | sha512 | sha1 | md5.",
                                  required=False,
                                  extra={"enum": list(_HMAC_ALGOS)}),
                ],
            ),
            Tool(
                name="random_token",
                description=(
                    "Generate a cryptographically random token string. "
                    "Charsets: alphanumeric (default), hex, alpha, numeric, urlsafe, "
                    "or pass a literal alphabet string."
                ),
                fn=_random_token,
                parameters=[
                    ToolParameter("length", "integer",
                                  "Token length in characters (1–1024). Default 32.",
                                  required=False),
                    ToolParameter("charset", "string",
                                  "alphanumeric | hex | alpha | numeric | urlsafe | custom alphabet.",
                                  required=False),
                ],
            ),
            Tool(
                name="json_to_base64",
                description=(
                    "Serialize a JSON-serializable value to compact JSON, "
                    "then URL-safe base64-encode it. Useful for embedding structured "
                    "data in URLs or headers."
                ),
                fn=_json_to_base64,
                parameters=[
                    ToolParameter("data", "object",
                                  "Any JSON-serializable value.",
                                  extra={"description": "Any JSON-serializable value."}),
                ],
            ),
            Tool(
                name="base64_to_json",
                description="Decode a URL-safe base64 string and parse it as JSON.",
                fn=_base64_to_json,
                parameters=[
                    ToolParameter("data", "string", "The URL-safe base64-encoded JSON."),
                ],
            ),
            Tool(
                name="jwt_decode",
                description=(
                    "Decode a JWT's header and payload as JSON WITHOUT verifying the "
                    "signature. Returns {header, payload, signature}. Inspection only — "
                    "does NOT validate authenticity."
                ),
                fn=_jwt_decode,
                parameters=[
                    ToolParameter("token", "string", "The JWT (three dot-separated segments)."),
                ],
            ),
            Tool(
                name="detect_encoding",
                description=(
                    "Best-effort guess of how a string is encoded: "
                    "hex, base64, url (percent-encoded), or plain."
                ),
                fn=_detect_encoding,
                parameters=[
                    ToolParameter("data", "string", "The string to classify."),
                ],
            ),
        ],
        skills=[
            Skill(
                name="fingerprint",
                description=(
                    "Compute a canonical SHA-256 fingerprint for any JSON-serializable value. "
                    "Uses sorted keys and compact serialization so identical structures always "
                    "produce the same digest regardless of key order. Use for deduplication, "
                    "change detection, or cache keying."
                ),
                handler=_fingerprint,
                parameters=[
                    ToolParameter("data", "object",
                                  "Any JSON-serializable value to fingerprint.",
                                  extra={"description": "Any JSON-serializable value."}),
                ],
            ),
        ],
    )


__all__ = [
    "encoding_terr",
    "_MAX_INPUT",
    "_HASH_ALGOS",
    "_HMAC_ALGOS",
    # primitive fns
    "_base64_encode", "_base64_decode", "_hash_text", "_hex_encode", "_hex_decode",
    "_url_encode", "_url_decode", "_uuid_generate",
    "_hmac_sign", "_random_token", "_json_to_base64", "_base64_to_json",
    "_jwt_decode", "_detect_encoding",
    # compound skill fns
    "_fingerprint",
]

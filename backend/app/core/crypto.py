"""Authenticated encryption for user-supplied secrets (AES-256-GCM).

Keys come from ``SECRET_ENCRYPTION_KEYS`` (or a secret manager that injects
that variable). The first key in the ring encrypts; every key can decrypt,
which enables zero-downtime rotation:

1. Prepend a new key: ``SECRET_ENCRYPTION_KEYS=k2:<new>,k1:<old>``.
2. Run ``python -m app.cli rotate-keys`` to re-encrypt stored secrets.
3. Remove the old key.

Ciphertext format: ``v1.<kid>.<b64 nonce>.<b64 ciphertext+tag>``. The
associated data binds a ciphertext to its owner row, so a value copied into
another user's row fails to decrypt.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoError(Exception):
    pass


@dataclass(frozen=True)
class KeyRing:
    keys: dict[str, bytes]
    primary_kid: str

    @classmethod
    def parse(cls, spec: str) -> KeyRing:
        keys: dict[str, bytes] = {}
        primary: str | None = None
        for part in [p.strip() for p in spec.split(",") if p.strip()]:
            kid, sep, b64 = part.partition(":")
            if not sep or not kid or "." in kid:
                raise CryptoError("Invalid SECRET_ENCRYPTION_KEYS entry (expected kid:base64)")
            try:
                raw = base64.b64decode(b64, validate=True)
            except ValueError as exc:
                raise CryptoError("Encryption key is not valid base64") from exc
            if len(raw) != 32:
                raise CryptoError("Encryption keys must be 32 bytes (AES-256)")
            keys[kid] = raw
            primary = primary or kid
        if primary is None:
            raise CryptoError("No encryption keys configured")
        return cls(keys=keys, primary_kid=primary)

    def encrypt(self, plaintext: str, aad: str) -> str:
        nonce = os.urandom(12)
        ct = AESGCM(self.keys[self.primary_kid]).encrypt(nonce, plaintext.encode(), aad.encode())
        return ".".join(["v1", self.primary_kid, base64.b64encode(nonce).decode(), base64.b64encode(ct).decode()])

    def decrypt(self, token: str, aad: str) -> str:
        try:
            version, kid, nonce_b64, ct_b64 = token.split(".")
        except ValueError as exc:
            raise CryptoError("Malformed ciphertext") from exc
        if version != "v1" or kid not in self.keys:
            raise CryptoError("Unknown key id or version")
        try:
            pt = AESGCM(self.keys[kid]).decrypt(base64.b64decode(nonce_b64), base64.b64decode(ct_b64), aad.encode())
        except Exception as exc:  # InvalidTag and decoding errors
            raise CryptoError("Decryption failed") from exc
        return pt.decode()

    def needs_rotation(self, token: str) -> bool:
        parts = token.split(".")
        return len(parts) != 4 or parts[1] != self.primary_kid


def generate_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()

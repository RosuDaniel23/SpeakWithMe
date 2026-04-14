"""
AES-256-GCM Encryption Module for Patient Data
================================================
Protects sensitive patient data at rest using AES-256 in GCM mode.

Why AES-256-GCM?
- AES-256: Military-grade symmetric encryption, approved by NIST
- GCM mode: Provides both confidentiality AND authenticity (AEAD)
  - Confidentiality: data is unreadable without the key
  - Authenticity: detects if encrypted data was tampered with
- Each encryption uses a unique 12-byte nonce (IV) for semantic security
  - Same plaintext encrypted twice produces different ciphertext
  - Prevents pattern analysis attacks

Storage format: base64(nonce[12] || ciphertext || tag[16])
- Nonce is prepended so decryption knows which IV was used
- Tag is appended by GCM automatically for integrity verification

Key management:
- Key is loaded from ENCRYPTION_KEY environment variable
- If no key exists on first run, one is securely generated using os.urandom(32)
- Key is 32 bytes = 256 bits, stored as hex string in .env
- NEVER hardcode keys in source code
- NEVER commit .env to git
"""

import os
import base64
import logging
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_NONCE_SIZE = 12  # bytes — recommended by NIST for AES-GCM
_KEY_SIZE = 32    # bytes — 256 bits


def generate_key() -> bytes:
    """Generate a cryptographically secure 256-bit AES key.

    Uses os.urandom which pulls from the OS CSPRNG (e.g. /dev/urandom on Linux,
    CryptGenRandom on Windows). This is the correct source for key material.
    """
    return os.urandom(_KEY_SIZE)


def key_to_hex(key: bytes) -> str:
    """Convert a raw key to a hex string for safe storage in .env.

    Hex is chosen over base64 because it is unambiguous, has no padding
    issues, and is easy to copy-paste without line-wrapping problems.
    """
    return key.hex()


def hex_to_key(hex_string: str) -> bytes:
    """Convert a hex string back to raw key bytes.

    Validates that the string represents exactly 32 bytes (256 bits).
    Raises ValueError with a clear message if the key is malformed so the
    operator knows immediately what went wrong.
    """
    if len(hex_string) != 64:
        raise ValueError(
            f"ENCRYPTION_KEY must be a 64-character hex string (32 bytes / 256 bits), "
            f"got {len(hex_string)} characters. "
            "Re-generate with: python -c \"import os; print(os.urandom(32).hex())\""
        )
    return bytes.fromhex(hex_string)


def load_or_generate_key() -> bytes:
    """Load the encryption key from the environment, generating one if absent.

    On first run (no ENCRYPTION_KEY in .env), a secure key is auto-generated
    and appended to backend/.env so subsequent runs use the same key.

    IMPORTANT: The key must never change after data has been encrypted — doing
    so makes all previously encrypted records unreadable. Back up the key
    before rotating it.
    """
    hex_key = os.environ.get("ENCRYPTION_KEY", "").strip()
    if hex_key:
        try:
            key = hex_to_key(hex_key)
            logger.info("Encryption key loaded from environment.")
            return key
        except ValueError as exc:
            raise RuntimeError(f"Invalid ENCRYPTION_KEY in environment: {exc}") from exc

    # No key found — generate one and persist it to .env
    key = generate_key()
    hex_key = key_to_hex(key)

    # Append to .env (or create it) — one line, no overwrite of existing values
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env_path = os.path.normpath(env_path)
    with open(env_path, "a") as f:
        f.write(f'\nENCRYPTION_KEY="{hex_key}"\n')

    logger.warning(
        "No ENCRYPTION_KEY found — a new AES-256 key has been generated and "
        "appended to backend/.env. Back up this key; losing it means losing "
        "access to all encrypted patient data."
    )
    return key


def encrypt(plaintext: str, key: bytes) -> str:
    """Encrypt a UTF-8 string using AES-256-GCM and return a base64 token.

    Each call generates a fresh random nonce so the same plaintext produces
    different ciphertext every time (semantic security). The nonce is prepended
    to the ciphertext so decrypt() can recover it without extra storage.

    Storage layout: base64( nonce[12] || ciphertext+tag )
    The GCM tag (16 bytes) is appended automatically by the AESGCM primitive.
    """
    try:
        nonce = os.urandom(_NONCE_SIZE)
        aesgcm = AESGCM(key)
        ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        token = base64.b64encode(nonce + ciphertext_with_tag).decode("ascii")
        return token
    except Exception as exc:
        raise RuntimeError(f"Encryption failed: {exc}") from exc


def decrypt(encrypted_b64: str, key: bytes) -> str:
    """Decrypt a base64 token produced by encrypt() and return the plaintext.

    Raises descriptive ValueError for the three failure modes operators are
    likely to encounter: bad base64, truncated data, wrong key / tampered data.
    """
    try:
        raw = base64.b64decode(encrypted_b64)
    except Exception:
        raise ValueError("Corrupted encrypted data — not valid base64")

    if len(raw) < _NONCE_SIZE:
        raise ValueError(
            f"Encrypted data too short — missing nonce "
            f"(got {len(raw)} bytes, need at least {_NONCE_SIZE})"
        )

    nonce = raw[:_NONCE_SIZE]
    ciphertext_with_tag = raw[_NONCE_SIZE:]

    try:
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
        return plaintext.decode("utf-8")
    except Exception:
        raise ValueError(
            "Decryption failed — wrong key or data has been tampered with"
        )


def encrypt_dict(data: dict, key: bytes, fields: list[str]) -> dict:
    """Encrypt specific fields in a dictionary, leaving others untouched.

    Returns a new dict (does not mutate the input). The list of encrypted
    field names is stored under '_encrypted_fields' so decrypt_dict() knows
    which fields to decrypt without guessing.

    Fields that do not exist in the dict are silently skipped — this makes the
    function safe to call on records that may not have all fields populated.

    Example:
        encrypt_dict({"summary": "pain", "id": "abc"}, key, ["summary"])
        → {"summary": "base64...", "id": "abc", "_encrypted_fields": ["summary"]}
    """
    result = dict(data)
    encrypted_fields = []
    for field in fields:
        if field in result and result[field] is not None:
            result[field] = encrypt(str(result[field]), key)
            encrypted_fields.append(field)
    result["_encrypted_fields"] = encrypted_fields
    return result


def decrypt_dict(data: dict, key: bytes) -> dict:
    """Decrypt fields in a dictionary that were encrypted by encrypt_dict().

    Reads the '_encrypted_fields' marker to know which fields to decrypt.
    If the marker is absent the dict is returned as-is — this provides
    backward compatibility with records written before encryption was enabled.

    If a field fails to decrypt, raises ValueError naming the problematic field
    so the operator can diagnose key mismatches or data corruption precisely.
    """
    encrypted_fields = data.get("_encrypted_fields")
    if not encrypted_fields:
        # Unencrypted legacy record — return unchanged
        return data

    result = dict(data)
    for field in encrypted_fields:
        if field in result:
            try:
                result[field] = decrypt(result[field], key)
            except ValueError as exc:
                raise ValueError(f"Failed to decrypt field '{field}': {exc}") from exc

    del result["_encrypted_fields"]
    return result


# ---------------------------------------------------------------------------
# Self-test — run with: python -m security.encryption
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    key = generate_key()
    original = "Patient has severe pain in the head area"

    encrypted = encrypt(original, key)
    decrypted = decrypt(encrypted, key)

    assert decrypted == original, "Decryption failed!"
    assert encrypted != original, "Data was not encrypted!"

    print(f"Original:  {original}")
    print(f"Encrypted: {encrypted[:60]}...")
    print(f"Decrypted: {decrypted}")

    # Dict round-trip
    record = {"summary": "head pain", "session_id": "abc-123", "labels": ["pain", "head"]}
    enc_record = encrypt_dict(record, key, ["summary", "labels"])
    assert enc_record["session_id"] == "abc-123", "Non-encrypted field mutated"
    assert enc_record["summary"] != "head pain", "summary not encrypted"
    assert "_encrypted_fields" in enc_record

    dec_record = decrypt_dict(enc_record, key)
    assert dec_record["summary"] == "head pain"
    assert dec_record["labels"] == str(["pain", "head"])  # stored as str via str()
    assert "_encrypted_fields" not in dec_record

    # Backward compat: unencrypted dict passes through unchanged
    plain_record = {"summary": "old record", "session_id": "xyz"}
    assert decrypt_dict(plain_record, key) == plain_record

    print("All encryption tests passed!")

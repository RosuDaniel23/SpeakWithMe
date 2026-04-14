"""
GDPR-Compliant Data Retention & Lifecycle Management
=====================================================
Manages the complete lifecycle of patient data:

1. Retention: Auto-delete sessions older than configured period
2. Erasure: On-demand deletion with secure overwrite
3. Export: Data portability in standard JSON format
4. Anonymization: Strip personal content while keeping structure for analytics

Secure deletion process:
- Read the data to confirm it exists
- Overwrite the file on disk with random bytes of the same size
- Write the updated (reduced or empty) content
- This prevents recovery via disk forensics tools

Why not just delete?
When you "delete" a file, the OS marks the disk space as available
but doesn't erase the bits. Tools like PhotoRec, Recuva, or TestDisk
can recover "deleted" data. Overwriting ensures the original content
is physically replaced on disk.

Note on SSD wear leveling:
SSDs may remap writes to different physical cells, meaning a single
overwrite pass may not reach the original cell. This is a hardware
limitation. Application-level overwriting is still the standard
best-practice approach and defeats casual/software-based recovery.

Audit logging:
Operations are logged at WARNING level with the prefix [AUDIT] so
they are always visible in server logs regardless of log level
configuration.
"""

import json
import logging
import os
import pathlib
import time
from datetime import datetime, timezone

from security.encryption import decrypt_dict, encrypt_dict, encrypt

logger = logging.getLogger(__name__)

# Fields encrypted in each session record
_SENSITIVE_FIELDS = ["summary", "path"]


def _audit(action: str, detail: str = "") -> None:
    """Emit a structured audit log entry.

    Uses WARNING level so audit events are always visible. When Module 2
    (dedicated audit trail) is implemented, this function can be updated
    to route there without changing any call sites.
    """
    logger.warning("[AUDIT] action=%s %s", action, detail)


def _read_raw(data_file: pathlib.Path) -> list:
    """Read raw (encrypted) records from the sessions file.

    Returns an empty list if the file is missing or unreadable rather
    than raising, so callers never crash on a missing file.
    """
    if not data_file.exists():
        return []
    try:
        return json.loads(data_file.read_text())
    except Exception as exc:
        logger.error("Could not read sessions file %s: %s", data_file, exc)
        return []


def _write_raw(data_file: pathlib.Path, records: list) -> None:
    """Serialize and write encrypted records to disk with a secure overwrite.

    The secure overwrite step fills the file with random bytes of the same
    length before writing the new content, so no plaintext from the previous
    write is recoverable at the application level.
    """
    data_file.parent.mkdir(parents=True, exist_ok=True)
    new_content = json.dumps(records, indent=2).encode()
    secure_overwrite(data_file, new_content)


def secure_overwrite(file_path: pathlib.Path, new_content: bytes | None = None) -> None:
    """Overwrite a file with random bytes before writing new content (or leaving empty).

    If new_content is None, the file is overwritten with random bytes and then
    deleted — leaving no recoverable data. If new_content is provided, the file
    is overwritten with random bytes first, then the new content is written.

    os.fsync() is called to ensure the random-byte pass reaches physical storage
    before the new content is written.
    """
    file_path = pathlib.Path(file_path)
    if file_path.exists():
        file_size = file_path.stat().st_size
        if file_size > 0:
            with open(file_path, "r+b") as f:
                f.write(os.urandom(file_size))
                f.flush()
                os.fsync(f.fileno())

    if new_content is None:
        # Deletion requested — file is already zeroed, now remove it
        if file_path.exists():
            file_path.unlink()
    else:
        file_path.write_bytes(new_content)


def get_all_sessions(data_file: pathlib.Path, encryption_key: bytes) -> list[dict]:
    """Read and decrypt all sessions from the data file.

    Returns a list of fully decrypted session dicts. Records that fail
    decryption are included with a placeholder summary so no data is silently
    lost from the caller's view.
    """
    raw = _read_raw(data_file)
    result = []
    for rec in raw:
        try:
            result.append(decrypt_dict(rec, encryption_key))
        except Exception:
            rec = dict(rec)
            rec["summary"] = "[DECRYPTION FAILED — wrong key?]"
            rec.pop("_encrypted_fields", None)
            result.append(rec)
    return result


def purge_expired_sessions(
    retention_days: int,
    data_file: pathlib.Path,
    encryption_key: bytes,
) -> dict:
    """Delete sessions older than retention_days and return a status report.

    Only the session_id (timestamp string) is included in the audit log —
    never the summary or path — so the audit trail itself does not become
    a privacy risk.

    Returns a dict with deleted_count, remaining_count, and oldest_remaining.
    """
    cutoff = time.time() - retention_days * 86_400
    raw = _read_raw(data_file)

    kept = []
    deleted_count = 0
    for rec in raw:
        ts = rec.get("timestamp", time.time())
        if ts < cutoff:
            session_id = str(rec.get("session_id", rec.get("timestamp", "unknown")))
            _audit("DATA_DELETED", f"session_id={session_id} reason=retention_expired")
            deleted_count += 1
        else:
            kept.append(rec)

    if deleted_count:
        _write_raw(data_file, kept)

    oldest_remaining = None
    if kept:
        oldest_ts = min(r.get("timestamp", 0) for r in kept)
        oldest_remaining = datetime.fromtimestamp(oldest_ts, tz=timezone.utc).isoformat()

    return {
        "deleted_count": deleted_count,
        "remaining_count": len(kept),
        "oldest_remaining": oldest_remaining,
    }


def delete_session(
    session_id: str,
    data_file: pathlib.Path,
    encryption_key: bytes,
) -> dict:
    """Delete a single session by session_id (its timestamp as a string).

    Raises ValueError if the session is not found, so the caller can return
    a 404 rather than silently doing nothing.
    """
    raw = _read_raw(data_file)
    original_count = len(raw)

    kept = [
        rec for rec in raw
        if str(rec.get("session_id", rec.get("timestamp", ""))) != session_id
    ]

    if len(kept) == original_count:
        raise ValueError(f"Session not found: {session_id}")

    _write_raw(data_file, kept)
    _audit("DATA_DELETED", f"session_id={session_id} reason=user_request")

    return {"deleted": True, "session_id": session_id}


def delete_all_sessions(data_file: pathlib.Path, encryption_key: bytes) -> dict:
    """Delete every session record with a secure overwrite of the file.

    After the overwrite pass the file is replaced with an empty JSON array
    so the application continues to function without a missing file error.
    """
    raw = _read_raw(data_file)
    count = len(raw)

    # Overwrite with random bytes then write empty list
    _write_raw(data_file, [])
    _audit("DATA_DELETED", f"count={count} reason=full_erasure_request")

    return {"deleted_count": count, "remaining_count": 0}


def export_sessions(data_file: pathlib.Path, encryption_key: bytes) -> dict:
    """Return all decrypted sessions with GDPR-compliant export metadata.

    The date_range covers all records in the file. If there are no records,
    from/to are None.
    """
    sessions = get_all_sessions(data_file, encryption_key)
    _audit("DATA_EXPORTED", f"count={len(sessions)}")

    date_range = {"from": None, "to": None}
    if sessions:
        timestamps = [s.get("timestamp", 0) for s in sessions]
        date_range = {
            "from": datetime.fromtimestamp(min(timestamps), tz=timezone.utc).isoformat(),
            "to": datetime.fromtimestamp(max(timestamps), tz=timezone.utc).isoformat(),
        }

    return {
        "export_metadata": {
            "exported_at": datetime.now(tz=timezone.utc).isoformat(),
            "total_records": len(sessions),
            "date_range": date_range,
            "format": "JSON",
            "application": "SpeakWithMe v1.0",
        },
        "sessions": sessions,
    }


def anonymize_sessions(data_file: pathlib.Path, encryption_key: bytes) -> dict:
    """Replace sensitive content with [ANONYMIZED] while preserving structure.

    Keeps session_id, timestamp, and the count of labels so aggregate
    analytics (how many selections, when) remain possible without any
    personal data being present.
    """
    raw = _read_raw(data_file)
    anonymized_raw = []
    count = 0

    for rec in raw:
        # Work on a copy — never mutate the original dict
        anon = dict(rec)

        # If encrypted, decrypt first so we can re-encrypt the anonymized version
        try:
            decrypted = decrypt_dict(anon, encryption_key)
        except Exception:
            # Already unreadable — anonymize the raw fields in place
            decrypted = anon

        decrypted["summary"] = "[ANONYMIZED]"
        if isinstance(decrypted.get("path"), list):
            decrypted["path"] = ["[ANONYMIZED]"] * len(decrypted["path"])
        elif "path" in decrypted:
            decrypted["path"] = "[ANONYMIZED]"

        # Re-encrypt anonymized content
        re_enc = encrypt_dict(decrypted, encryption_key, _SENSITIVE_FIELDS)
        anonymized_raw.append(re_enc)
        count += 1

    _write_raw(data_file, anonymized_raw)
    _audit("DATA_ANONYMIZED", f"count={count}")

    return {"anonymized_count": count}

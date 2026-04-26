"""
Tamper-Evident Audit Trail with SHA-256 Hash Chain
====================================================
Provides an append-only audit log where each entry is cryptographically
linked to the previous entry via SHA-256 hashing.

Security properties:
- Integrity: Any modification to a past entry breaks the hash chain
- Non-repudiation: Each action is permanently recorded with timestamp and source
- Append-only: The log is designed for appending only; deletions are detected
- Privacy: Patient medical content is NEVER logged — only action metadata

Hash chain construction:
  hash_n = SHA256(timestamp_n | action_n | details_n | ip_n | hash_{n-1})

The first entry uses "GENESIS" as its previous hash.

Storage: JSONL format (one JSON object per line) in data/audit.jsonl
- JSONL is ideal for append-only: just append a new line
- No need to parse the entire file to add an entry
- Easy to stream/tail for monitoring
"""

import fcntl
import hashlib
import json
import logging
import os
import pathlib
from collections import Counter
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Fields that may contain patient medical content — never allowed in audit details.
# The audit trail must not itself become a privacy risk.
_BLOCKED_DETAIL_FIELDS = {
    "summary", "labels", "path", "text", "content",
    "communication", "message", "patient_text",
}

_HERE = pathlib.Path(__file__).parent
AUDIT_FILE = pathlib.Path(os.getenv("AUDIT_FILE", str(_HERE.parent / "data/audit.jsonl")))


class AuditAction:
    """Enumeration of all auditable actions in the system."""
    CALIBRATION_START       = "CALIBRATION_START"
    CALIBRATION_COMPLETE    = "CALIBRATION_COMPLETE"
    CALIBRATION_FAILED      = "CALIBRATION_FAILED"
    SESSION_START           = "SESSION_START"
    SELECTION_MADE          = "SELECTION_MADE"
    SUMMARY_GENERATED       = "SUMMARY_GENERATED"
    SUMMARY_VIEWED          = "SUMMARY_VIEWED"
    EMERGENCY_TRIGGERED     = "EMERGENCY_TRIGGERED"
    DATA_EXPORTED           = "DATA_EXPORTED"
    DATA_DELETED            = "DATA_DELETED"
    DATA_ANONYMIZED         = "DATA_ANONYMIZED"
    SECURITY_CHAIN_VERIFIED = "SECURITY_CHAIN_VERIFIED"
    ENCRYPTION_KEY_GENERATED = "ENCRYPTION_KEY_GENERATED"
    PROMPT_INJECTION_BLOCKED = "PROMPT_INJECTION_BLOCKED"
    VALIDATION_FAILED       = "VALIDATION_FAILED"
    RATE_LIMIT_EXCEEDED     = "RATE_LIMIT_EXCEEDED"
    SERVER_START            = "SERVER_START"
    SERVER_SHUTDOWN         = "SERVER_SHUTDOWN"
    DOCTOR_REGISTERED       = "DOCTOR_REGISTERED"


def _compute_hash(
    timestamp: str,
    action: str,
    details: str,
    source_ip: str,
    previous_hash: str,
) -> str:
    """Return the SHA-256 hex digest chaining this entry to the previous one.

    All five fields are joined with '|' so that changing any single field
    produces a completely different digest. This is a pure, deterministic
    function with no side effects.
    """
    raw = f"{timestamp}|{action}|{details}|{source_ip}|{previous_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_last_hash(audit_file: pathlib.Path) -> str:
    """Return the hash of the most recent audit entry, or 'GENESIS' if none exists.

    Reads only the last line of the file so performance is O(1) relative to
    file size. If the last line is corrupted (not valid JSON), a recovery hash
    is derived from the raw bytes so the chain can continue rather than crash.
    """
    if not audit_file.exists() or audit_file.stat().st_size == 0:
        return "GENESIS"

    last_line = b""
    try:
        with open(audit_file, "rb") as f:
            # Seek to a reasonable tail window to find the last non-empty line
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4096))
            last_line = f.readlines()[-1].strip()
        entry = json.loads(last_line)
        return entry["hash"]
    except (json.JSONDecodeError, KeyError):
        # Corrupted last line — derive a recovery sentinel so we can continue
        recovery = hashlib.sha256(last_line).hexdigest()
        logger.warning("Audit: corrupted last entry — using recovery hash %s", recovery[:16])
        return f"RECOVERY_{recovery}"
    except Exception as exc:
        logger.error("Audit: could not read last hash: %s", exc)
        return "GENESIS"


def _sanitize_details(details: dict | None) -> dict:
    """Remove any fields that might contain patient medical content.

    Only metadata fields (counts, IDs, scores, zone names) are permitted.
    This ensures the audit log itself never becomes a privacy liability.
    """
    if not details:
        return {}
    return {k: v for k, v in details.items() if k not in _BLOCKED_DETAIL_FIELDS}


def log_event(
    action: str,
    details: dict | None = None,
    source_ip: str = "system",
    audit_file: pathlib.Path | None = None,
) -> None:
    """Append a tamper-evident entry to the audit log.

    Uses fcntl.flock for file-level locking so concurrent requests (FastAPI
    runs in a thread pool) cannot interleave their writes and corrupt the JSONL.
    Errors are caught and logged — audit failures must never crash the app.
    """
    if audit_file is None:
        audit_file = AUDIT_FILE

    try:
        audit_file = pathlib.Path(audit_file)
        audit_file.parent.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(tz=timezone.utc).isoformat()
        safe_details = _sanitize_details(details)
        details_str = json.dumps(safe_details, separators=(",", ":"), sort_keys=True)
        previous_hash = _get_last_hash(audit_file)
        entry_hash = _compute_hash(timestamp, action, details_str, source_ip, previous_hash)

        entry = {
            "timestamp": timestamp,
            "action": action,
            "details": safe_details,
            "source_ip": source_ip,
            "previous_hash": previous_hash,
            "hash": entry_hash,
        }

        with open(audit_file, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry) + "\n")
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    except Exception as exc:
        # Audit logging must never crash the application
        logger.error("Audit log write failed (action=%s): %s", action, exc)


def verify_chain(audit_file: pathlib.Path | None = None) -> dict:
    """Read the entire audit log and verify every entry's hash chain link.

    For each entry, the hash is recomputed from its stored fields and compared
    to the stored hash. The stored previous_hash is also compared to the actual
    preceding entry's hash. Any discrepancy means the chain is broken at that
    entry — either from tampering or file corruption.

    Returns a summary dict so callers can expose this via an HTTP endpoint
    without sending raw hash values to the client.
    """
    if audit_file is None:
        audit_file = AUDIT_FILE

    audit_file = pathlib.Path(audit_file)

    result = {
        "valid": True,
        "total_entries": 0,
        "verified_entries": 0,
        "broken_at_entry": None,
        "first_entry": None,
        "last_entry": None,
        "actions_summary": {},
    }

    if not audit_file.exists():
        return result

    action_counts: Counter = Counter()
    previous_hash = "GENESIS"

    try:
        with open(audit_file) as f:
            for line_num, raw_line in enumerate(f, start=1):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue

                result["total_entries"] += 1

                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    result["valid"] = False
                    result["broken_at_entry"] = line_num
                    break

                # Track timestamps
                ts = entry.get("timestamp", "")
                if result["first_entry"] is None:
                    result["first_entry"] = ts
                result["last_entry"] = ts

                action_counts[entry.get("action", "UNKNOWN")] += 1

                # Recompute hash and compare
                details_str = json.dumps(
                    entry.get("details", {}),
                    separators=(",", ":"),
                    sort_keys=True,
                )
                expected_hash = _compute_hash(
                    entry.get("timestamp", ""),
                    entry.get("action", ""),
                    details_str,
                    entry.get("source_ip", ""),
                    entry.get("previous_hash", ""),
                )

                stored_hash = entry.get("hash", "")
                stored_prev = entry.get("previous_hash", "")

                if expected_hash != stored_hash or stored_prev != previous_hash:
                    result["valid"] = False
                    result["broken_at_entry"] = line_num
                    break

                previous_hash = stored_hash
                result["verified_entries"] += 1

    except Exception as exc:
        logger.error("Audit chain verification failed: %s", exc)
        result["valid"] = False

    result["actions_summary"] = dict(action_counts)
    return result


def get_recent_events(
    n: int = 50,
    audit_file: pathlib.Path | None = None,
) -> list[dict]:
    """Return the last N audit events, stripped of internal hash fields.

    Hash and previous_hash are omitted from the output because they are
    internal chain-integrity data — callers should use verify_chain() if
    they need chain verification, not inspect raw hashes.
    """
    if audit_file is None:
        audit_file = AUDIT_FILE

    audit_file = pathlib.Path(audit_file)

    if not audit_file.exists():
        return []

    lines = []
    try:
        with open(audit_file) as f:
            lines = f.readlines()
    except Exception as exc:
        logger.error("Audit: could not read events: %s", exc)
        return []

    events = []
    for raw_line in reversed(lines):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            entry = json.loads(raw_line)
            events.append({
                "timestamp": entry.get("timestamp"),
                "action": entry.get("action"),
                "details": entry.get("details", {}),
                "source_ip": entry.get("source_ip"),
            })
        except json.JSONDecodeError:
            continue
        if len(events) >= n:
            break

    return list(reversed(events))

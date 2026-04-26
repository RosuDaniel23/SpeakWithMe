"""
SQLite database for SpeakWithMe — doctors, patients, sessions tables.
Uses Python built-in sqlite3.
"""
import hashlib
import json
import os
import pathlib
import secrets
import sqlite3
from datetime import datetime, timezone

_HERE = pathlib.Path(__file__).parent
DB_FILE = pathlib.Path(os.getenv("DB_FILE", str(_HERE / "data/speakwithme.db")))


def _conn() -> sqlite3.Connection:
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db() -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doctor_id INTEGER NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                age INTEGER,
                room_number TEXT,
                diagnosis TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doctor_id) REFERENCES doctors(id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (patient_id) REFERENCES patients(id),
                FOREIGN KEY (doctor_id) REFERENCES doctors(id)
            );
        """)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, h = password_hash.split(":", 1)
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == h
    except Exception:
        return False


def create_doctor(username: str, password: str, full_name: str) -> int:
    with _conn() as db:
        cur = db.execute(
            "INSERT INTO doctors (username, password_hash, full_name) VALUES (?, ?, ?)",
            (username, hash_password(password), full_name),
        )
        return cur.lastrowid


def register_doctor(username: str, password: str, full_name: str) -> int:
    """Register a new doctor. Raises ValueError('username_taken') if the username exists."""
    with _conn() as db:
        if db.execute("SELECT 1 FROM doctors WHERE username=?", (username,)).fetchone():
            raise ValueError("username_taken")
        cur = db.execute(
            "INSERT INTO doctors (username, password_hash, full_name) VALUES (?, ?, ?)",
            (username, hash_password(password), full_name),
        )
        return cur.lastrowid


def authenticate_doctor(username: str, password: str) -> dict | None:
    with _conn() as db:
        row = db.execute(
            "SELECT * FROM doctors WHERE username=?", (username,)
        ).fetchone()
    if row and verify_password(password, row["password_hash"]):
        return {"id": row["id"], "username": row["username"], "full_name": row["full_name"]}
    return None


def create_patient(
    doctor_id: int,
    first_name: str,
    last_name: str,
    age: int | None,
    room_number: str | None,
    diagnosis: str | None,
    notes: str | None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as db:
        cur = db.execute(
            "INSERT INTO patients "
            "(doctor_id, first_name, last_name, age, room_number, diagnosis, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (doctor_id, first_name, last_name, age, room_number, diagnosis, notes, now),
        )
        return cur.lastrowid


def get_patients(doctor_id: int) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            "SELECT p.*, COUNT(s.id) as session_count, MAX(s.created_at) as last_session "
            "FROM patients p "
            "LEFT JOIN sessions s ON s.patient_id = p.id "
            "WHERE p.doctor_id = ? "
            "GROUP BY p.id "
            "ORDER BY p.last_name, p.first_name",
            (doctor_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_patient(patient_id: int) -> dict | None:
    with _conn() as db:
        row = db.execute(
            "SELECT * FROM patients WHERE id=?", (patient_id,)
        ).fetchone()
    return dict(row) if row else None


def update_patient(patient_id: int, **fields) -> bool:
    allowed = {"first_name", "last_name", "age", "room_number", "diagnosis", "notes"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    cols = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [patient_id]
    with _conn() as db:
        db.execute(f"UPDATE patients SET {cols} WHERE id=?", vals)
    return True


def delete_patient(patient_id: int) -> bool:
    with _conn() as db:
        db.execute("DELETE FROM sessions WHERE patient_id=?", (patient_id,))
        cur = db.execute("DELETE FROM patients WHERE id=?", (patient_id,))
    return cur.rowcount > 0


def save_session(
    patient_id: int,
    doctor_id: int,
    path: list,
    summary: str,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as db:
        cur = db.execute(
            "INSERT INTO sessions (patient_id, doctor_id, path, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (patient_id, doctor_id, json.dumps(path), summary, now),
        )
        return cur.lastrowid


def get_sessions(patient_id: int) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM sessions WHERE patient_id=? ORDER BY created_at DESC",
            (patient_id,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["path"] = json.loads(d["path"])
        result.append(d)
    return result


def get_all_sessions_for_doctor(doctor_id: int) -> list[dict]:
    with _conn() as db:
        rows = db.execute(
            "SELECT s.*, p.first_name, p.last_name "
            "FROM sessions s "
            "JOIN patients p ON s.patient_id = p.id "
            "WHERE s.doctor_id=? "
            "ORDER BY s.created_at DESC",
            (doctor_id,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["path"] = json.loads(d["path"])
        result.append(d)
    return result


def seed_demo_data() -> None:
    with _conn() as db:
        if db.execute("SELECT COUNT(*) FROM doctors").fetchone()[0] > 0:
            return

    create_doctor("admin", "admin123", "Dr. Administrator")

    with _conn() as db:
        doc_id = db.execute(
            "SELECT id FROM doctors WHERE username='admin'"
        ).fetchone()[0]

    create_patient(doc_id, "Ion", "Popescu", 72, "A12",
                   "Post-stroke aphasia, right-side hemiplegia", "")
    create_patient(doc_id, "Maria", "Ionescu", 58, "B04",
                   "ALS stage 3, respiratory support", "")
    create_patient(doc_id, "Andrei", "Vasile", 45, "C07",
                   "Post-intubation, temporary vocal cord paralysis", "")

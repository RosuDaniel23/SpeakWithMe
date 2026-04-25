from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
import logging
from pydantic import BaseModel
import asyncio
from fastapi.middleware.cors import CORSMiddleware
import threading
import time
import os
import textwrap
import json
import pathlib
import html as html_lib
from datetime import datetime, timezone

# Safe import for Anthropic + dotenv — if unavailable, provide a simple fallback client so the
# server can start without installing the anthropic package during local dev.
try:
    from anthropic import Anthropic
except Exception:
    Anthropic = None

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv():
        return None

load_dotenv()

import secrets
from database import init_db, seed_demo_data
from auth import active_tokens, generate_token, get_current_doctor
from security.encryption import load_or_generate_key, encrypt, decrypt, encrypt_dict, decrypt_dict
from security.audit import AuditAction, log_event, verify_chain, get_recent_events
from security.data_retention import (
    purge_expired_sessions as _purge_expired,
    delete_session as _delete_session,
    delete_all_sessions as _delete_all_sessions,
    export_sessions as _export_sessions,
    anonymize_sessions as _anonymize_sessions,
)

# Encryption key — loaded once at startup; auto-generated if absent from .env
_ENCRYPTION_KEY: bytes = load_or_generate_key()
# Note: we log "Encryption initialized" after logger is created below

# Try to import heavy native libs (OpenCV, mediapipe, numpy). If unavailable, fall back to a simulated tracker.
try:
    import cv2
    import numpy as np
    import mediapipe as mp
    HAS_MEDIAPIPE = True
    mp_face_mesh = mp.solutions.face_mesh
except Exception:
    cv2 = None
    np = None
    mp = None
    mp_face_mesh = None
    HAS_MEDIAPIPE = False

logger = logging.getLogger("eye_tracking")
logger.info("Encryption initialized: AES-256-GCM")

# Landmarks we need
RIGHT_EYE_CORNERS = [33, 133]
LEFT_EYE_CORNERS  = [263, 362]
RIGHT_TOP, RIGHT_BOTTOM = 159, 145
LEFT_TOP,  LEFT_BOTTOM  = 386, 374
RIGHT_IRIS = [468, 469, 470, 471]
LEFT_IRIS  = [473, 474, 475, 476]
# --- Configuration ---
EAR_CLOSED_THR   = 0.20
GRID_ROWS        = 2
GRID_COLS        = 2
ACTIVE_RADIUS_PX = 300
DWELL_SECONDS    = 3.0
SMOOTH_ALPHA     = 0.25
ALLOWED_ORIGINS  = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
LLM_MODEL        = os.getenv("LLM_MODEL", "claude-sonnet-4-20250514")
_HERE            = pathlib.Path(__file__).parent
SESSIONS_FILE    = pathlib.Path(os.getenv("SESSIONS_FILE",    str(_HERE / "data/sessions.json")))
CALIBRATION_FILE = pathlib.Path(os.getenv("CALIBRATION_FILE", str(_HERE / "data/calibration.json")))

# -------------------- Calibration persistence --------------------
def _save_calibration(W):
    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.dumps({"W": W.tolist()})
        encrypted = encrypt(payload, _ENCRYPTION_KEY)
        CALIBRATION_FILE.write_text(json.dumps({"data": encrypted, "timestamp": time.time()}))
        logger.info("Calibration saved (encrypted) to %s", CALIBRATION_FILE)
    except Exception as e:
        logger.error("Failed to save calibration: %s", e)

def _load_calibration():
    if not CALIBRATION_FILE.exists():
        return None
    try:
        data = json.loads(CALIBRATION_FILE.read_text())
        if "data" in data:
            # Encrypted format
            payload = json.loads(decrypt(data["data"], _ENCRYPTION_KEY))
            W = np.array(payload["W"], dtype=np.float32)
        else:
            # Legacy unencrypted format — backward compatibility
            W = np.array(data["W"], dtype=np.float32)
        logger.info("Calibration loaded from %s", CALIBRATION_FILE)
        return W
    except Exception as e:
        logger.warning(
            "Could not load calibration (key changed or corrupt) — forcing recalibration: %s", e
        )
        return None

# -------------------- Session store --------------------
_sessions_lock = threading.Lock()

def _load_sessions() -> list:
    if SESSIONS_FILE.exists():
        try:
            raw = json.loads(SESSIONS_FILE.read_text())
            result = []
            for rec in raw:
                try:
                    result.append(decrypt_dict(rec, _ENCRYPTION_KEY))
                except Exception:
                    rec["summary"] = "[DECRYPTION FAILED — wrong key?]"
                    rec.pop("_encrypted_fields", None)
                    result.append(rec)
            return result
        except Exception:
            return []
    return []

def _save_session(entry: dict):
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _sessions_lock:
        # Encrypt sensitive fields before persisting
        enc_entry = encrypt_dict(entry, _ENCRYPTION_KEY, ["summary", "path"])
        # Re-load raw (already-encrypted) records to avoid double-decrypting
        raw_sessions = json.loads(SESSIONS_FILE.read_text()) if SESSIONS_FILE.exists() else []
        raw_sessions.append(enc_entry)
        SESSIONS_FILE.write_text(json.dumps(raw_sessions, indent=2))

def _migrate_unencrypted_sessions():
    """Encrypt any legacy sessions written before encryption was enabled.

    Reads the raw file directly, skips records that already have
    '_encrypted_fields', encrypts the rest in-place, and rewrites the file.
    Safe to call multiple times — already-encrypted records are never touched.
    """
    if not SESSIONS_FILE.exists():
        return
    with _sessions_lock:
        try:
            raw = json.loads(SESSIONS_FILE.read_text())
        except Exception as exc:
            logger.warning("Migration: could not read sessions file: %s", exc)
            return
        migrated = 0
        updated = []
        for rec in raw:
            if "_encrypted_fields" not in rec:
                rec = encrypt_dict(rec, _ENCRYPTION_KEY, ["summary", "path"])
                migrated += 1
            updated.append(rec)
        if migrated:
            SESSIONS_FILE.write_text(json.dumps(updated, indent=2))
            logger.info("Migration: encrypted %d legacy session(s) with AES-256-GCM.", migrated)
        else:
            logger.info("Migration: all sessions already encrypted — nothing to do.")

# Human labels in draw order
ZONE_LABELS = ["top", "bottom", "right", "left", "center"]

# -------------------- Shared state --------------------
class EyeTrackingState:
    def __init__(self):
        self._lock = threading.Lock()
        self.calibrated = False
        self.hover_idx = None         # int in [0..3] or None
        self.selected_idx = None      # last dwell-activated zone (sticky) or None
        self.last_activation_ts = None
        self.eyes_closed = False
        self.camera_connected = True

    def set_calibrated(self, v: bool):
        with self._lock:
            self.calibrated = v

    def set_hover(self, idx):
        with self._lock:
            self.hover_idx = idx

    def set_selected(self, idx):
        now = time.time()
        with self._lock:
            self.selected_idx = idx
            self.last_activation_ts = now

    def set_eyes_closed(self, closed: bool):
        with self._lock:
            self.eyes_closed = closed

    def set_camera_connected(self, connected: bool):
        with self._lock:
            self.camera_connected = connected

    def snapshot(self):
        with self._lock:
            return {
                "calibrated": self.calibrated,
                "hover_idx": self.hover_idx,
                "selected_idx": self.selected_idx,
                "last_activation_ts": self.last_activation_ts,
                "eyes_closed": self.eyes_closed,
                "camera_connected": self.camera_connected,
            }

STATE = EyeTrackingState()

# -------------------- Vision utils --------------------
# Note: The functions below reference numpy/cv2/mediapipe only when actually used in the
# mediapipe-enabled run_eye_tracking. When those packages are missing, a simulated tracker
# will be used that doesn't require them.

def iris_center_px(lms, idxs, w, h):
    pts = np.array([[lms[i].x * w, lms[i].y * h] for i in idxs], dtype=np.float32)
    return pts.mean(axis=0)

def landmark_px(lms, idx, w, h):
    return np.array([lms[idx].x * w, lms[idx].y * h], dtype=np.float32)

def eye_features(lms, w, h):
    r_outer = landmark_px(lms, RIGHT_EYE_CORNERS[0], w, h)
    r_inner = landmark_px(lms, RIGHT_EYE_CORNERS[1], w, h)
    r_top   = landmark_px(lms, RIGHT_TOP, w, h)
    r_bot   = landmark_px(lms, RIGHT_BOTTOM, w, h)
    r_center_eye = 0.5 * (r_outer + r_inner)
    r_width  = np.linalg.norm(r_outer - r_inner) + 1e-6
    r_height = np.linalg.norm(r_top - r_bot) + 1e-6
    r_iris   = iris_center_px(lms, RIGHT_IRIS, w, h)
    r_dx_norm = (r_iris[0] - r_center_eye[0]) / r_width
    r_dy_norm = (r_iris[1] - r_center_eye[1]) / r_height

    l_outer = landmark_px(lms, LEFT_EYE_CORNERS[0], w, h)
    l_inner = landmark_px(lms, LEFT_EYE_CORNERS[1], w, h)
    l_top   = landmark_px(lms, LEFT_TOP, w, h)
    l_bot   = landmark_px(lms, LEFT_BOTTOM, w, h)
    l_center_eye = 0.5 * (l_outer + l_inner)
    l_width  = np.linalg.norm(l_outer - l_inner) + 1e-6
    l_height = np.linalg.norm(l_top - l_bot) + 1e-6
    l_iris   = iris_center_px(lms, LEFT_IRIS, w, h)
    l_dx_norm = (l_iris[0] - l_center_eye[0]) / l_width
    l_dy_norm = (l_iris[1] - l_center_eye[1]) / l_height

    return np.array([r_dx_norm, r_dy_norm, l_dx_norm, l_dy_norm], dtype=np.float32), r_iris, l_iris

def fit_regression(X, Y):
    X = np.asarray(X, dtype=np.float32)
    Y = np.asarray(Y, dtype=np.float32)
    ones = np.ones((X.shape[0], 1), dtype=np.float32)
    A = np.hstack([X, ones])             # (N,5)
    W, *_ = np.linalg.lstsq(A, Y, rcond=None)
    return W                              # (5,2)

def predict_gaze(W, feat):
    A = np.hstack([feat, 1.0]).astype(np.float32)
    return (A @ W).astype(np.float32)

def draw_grid_points(frame, w, h, idx, activated=None):
    pts = grid_points(w, h)
    # When cv2 is unavailable, frame may be None; guard drawing.
    for k, (x, y) in enumerate(pts):
        if cv2 is not None:
            if k == idx:
                cv2.circle(frame, (x, y), 12, (0, 255, 0), -1)
            if activated is not None and activated == k:
                cv2.circle(frame, (x, y), 250, (255, 0, 0), -1)
            else:
                cv2.circle(frame, (x, y), 8, (0, 0, 255), -1)
    return pts

def activate_zone_and_update_state(frame, gaze_xy, w, h):
    if gaze_xy is None:
        STATE.set_hover(None)
        return
    STATE.set_eyes_closed(False)
    pts = grid_points(w, h)
    gx, gy = int(gaze_xy[0]), int(gaze_xy[1])
    dists = [((gx - x)**2 + (gy - y)**2)**0.5 for (x, y) in pts]
    ci = int(min(range(len(dists)), key=lambda i: dists[i]))

    radius = ACTIVE_RADIUS_PX * (0.45 if ci == 4 else 1.0)  # smaller active area for center
    if dists[ci] <= radius:
        STATE.set_hover(ci)
        if ci == 4 and cv2 is not None:
            cv2.circle(frame, pts[ci], 75, (255, 0, 0), -1)
        elif cv2 is not None:
            cv2.circle(frame, pts[ci], 150, (255, 0, 0), -1)
    else:
        STATE.set_hover(None)

def eye_aspect_ratio(landmarks, top, bottom, left_corner, right_corner, w, h):
    top_pt = np.array([landmarks[top].x * w, landmarks[top].y * h])
    bottom_pt = np.array([landmarks[bottom].x * w, landmarks[bottom].y * h])
    left_pt = np.array([landmarks[left_corner].x * w, landmarks[left_corner].y * h])
    right_pt = np.array([landmarks[right_corner].x * w, landmarks[right_corner].y * h])

    eye_height = np.linalg.norm(top_pt - bottom_pt)
    eye_width = np.linalg.norm(left_pt - right_pt)
    return eye_height / (eye_width + 1e-6)
    


class CalibrationStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.samples_X = []  # list of feature vectors
        self.samples_Y = []  # list of target (x,y)
        self.target_index = None
        self.W = None
        self.last_feat = None
        self.frame_size = (0, 0)
        self.ema_gaze = None
        self.samples_per_target = {0:0,1:0,2:0,3:0,4:0}

    def reset(self):
        with self.lock:
            self.samples_X.clear(); self.samples_Y.clear()
            self.target_index = None
            self.W = None
            self.ema_gaze = None
            self.samples_per_target = {0:0,1:0,2:0,3:0,4:0}

    def set_target(self, idx:int):
        with self.lock:
            self.target_index = idx

    def add_sample(self, feat, target_xy):
        with self.lock:
            self.samples_X.append(feat.copy())
            self.samples_Y.append(target_xy.copy())
            # infer target index membership
            if self.target_index is not None:
                self.samples_per_target[self.target_index] += 1

    def compute(self):
        with self.lock:
            if len(self.samples_X) < 4:
                raise ValueError("Not enough samples")
            W = fit_regression(self.samples_X, self.samples_Y)
            self.W = W
        # Release CALIB.lock before acquiring STATE._lock to avoid nested lock deadlock
        STATE.set_calibrated(True)
        _save_calibration(W)
        return W                              # (5,2)

CALIB = CalibrationStore()

def grid_points(w, h):
    margin_x, margin_y = int(w * 0.08), int(h * 0.08)
    return [
        (w // 2,            margin_y),        # 0: top
        (w // 2,            h - margin_y),    # 1: bottom
        (w - margin_x,      h // 2),          # 2: right
        (margin_x,          h // 2),          # 3: left
        (w // 2,            h // 2),          # 4: center
    ]

if HAS_MEDIAPIPE:
    # Original run_eye_tracking implementation using cv2 + mediapipe
    def run_eye_tracking():
        # Keep retrying camera open so the app can recover if camera permissions/devices are delayed.
        cap = None
        while not _shutdown_event.is_set() and cap is None:
            #cap = cv2.VideoCapture(1)  # change to 1 if your camera is on index 1
            candidate = cv2.VideoCapture(0)
            candidate.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            candidate.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            if candidate.isOpened():
                cap = candidate
                logger.info("Camera opened on index 0")
                break
            candidate.release()
            logger.info("Waiting for camera on index 0...")
            time.sleep(1.0)

        try:
            consecutive_failures = 0
            with mp_face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.6,
                min_tracking_confidence=0.6
            ) as fm:
                while not _shutdown_event.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        consecutive_failures += 1
                        if consecutive_failures >= 100:
                            # ~5s of failures: camera likely disconnected
                            STATE.set_camera_connected(False)
                            STATE.set_calibrated(False)
                            logger.error("Camera disconnected after %d consecutive read failures", consecutive_failures)
                        time.sleep(0.05)
                        continue
                    if consecutive_failures > 0:
                        consecutive_failures = 0
                        STATE.set_camera_connected(True)
                        logger.info("Camera reconnected")
                    h, w = frame.shape[:2]
                    CALIB.frame_size = (w, h)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    res = fm.process(rgb)
                    gaze_point = None

                    if res.multi_face_landmarks:
                        lms = res.multi_face_landmarks[0].landmark
                        feat, r_iris_px, l_iris_px = eye_features(lms, w, h)
                        with CALIB.lock:
                            CALIB.last_feat = feat
                        # If calibrated -> predict gaze
                        if CALIB.W is not None:
                            gaze_xy = predict_gaze(CALIB.W, feat)
                            if CALIB.ema_gaze is None:
                                CALIB.ema_gaze = gaze_xy.copy()
                            else:
                                CALIB.ema_gaze = (1 - SMOOTH_ALPHA) * CALIB.ema_gaze + SMOOTH_ALPHA * gaze_xy
                            gaze_point = CALIB.ema_gaze.astype(int)
                            activate_zone_and_update_state(frame, gaze_point, w, h)

                            #handle closed eyes
                            right_ear = eye_aspect_ratio(lms, RIGHT_TOP, RIGHT_BOTTOM, RIGHT_EYE_CORNERS[0], RIGHT_EYE_CORNERS[1], w, h)
                            left_ear  = eye_aspect_ratio(lms, LEFT_TOP,  LEFT_BOTTOM,  LEFT_EYE_CORNERS[0],  LEFT_EYE_CORNERS[1],  w, h)
                            eyes_closed = (right_ear < EAR_CLOSED_THR) and (left_ear < EAR_CLOSED_THR)
                            if eyes_closed:
                                STATE.set_eyes_closed(True)
                                STATE.set_hover(None)

                    time.sleep(0.01)  # yield
        finally:
            if cap is not None:
                cap.release()
else:
    # Lightweight simulated eye-tracking runner for development/demo when mediapipe/cv2 are unavailable.
    import random

    def run_eye_tracking():
        """Simulate hover/selection events so the frontend can function without camera or mediapipe.
        This will toggle a hover over the four zones in a loop and occasionally trigger a selection.
        """
        w, h = 1280, 720
        CALIB.frame_size = (w, h)
        zones = [0, 1, 2, 3, 4]
        idx = 0
        hover_time = 0
        while not _shutdown_event.is_set():
            # cycle hover through zones 0..3, with center as neutral
            cur = zones[idx % len(zones)]
            if cur == 4:
                STATE.set_hover(None)
            else:
                STATE.set_hover(cur)
            # Randomly mark eyes closed occasionally
            STATE.set_eyes_closed(random.random() < 0.02)
            # Simulate dwell: after hovering on a non-center zone for a few seconds, select it
            if hover_time >= DWELL_SECONDS and cur != 4:
                STATE.set_selected(cur)
                hover_time = 0
            else:
                hover_time += 0.5
            idx += 1
            time.sleep(0.5)

# -------------------- Tracker thread --------------------
_shutdown_event = threading.Event()
_tracker_thread = None

def _start_tracker_once():
    global _tracker_thread
    if _tracker_thread is not None and _tracker_thread.is_alive():
        return
    _tracker_thread = threading.Thread(target=run_eye_tracking, daemon=True)
    _tracker_thread.start()
    logger.info("Tracker thread started")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_demo_data()
    # Auto-load persisted calibration if available
    if HAS_MEDIAPIPE:
        W = _load_calibration()
        if W is not None:
            CALIB.W = W
            STATE.set_calibrated(True)
    _migrate_unencrypted_sessions()
    _start_tracker_once()
    retention_days = int(os.getenv("DATA_RETENTION_DAYS", "30"))
    result = _purge_expired(retention_days, SESSIONS_FILE, _ENCRYPTION_KEY)
    logger.info(
        "Data retention purge: deleted %d, remaining %d",
        result["deleted_count"], result["remaining_count"],
    )
    log_event(AuditAction.SERVER_START, details={"version": "1.0", "retention_days": retention_days})
    yield
    log_event(AuditAction.SERVER_SHUTDOWN)
    _shutdown_event.set()
    if _tracker_thread is not None:
        _tracker_thread.join(timeout=5)

# -------------------- FastAPI --------------------
app = FastAPI(lifespan=lifespan)

# Allow local dev frontend (Vite default 5173) and others to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def label(idx):
    return None if idx is None else ZONE_LABELS[idx]

@app.get("/eye_tracking")
def read_eye_tracking_status():
    """
    Endpoint to get the current eye-tracking status.
    eye_tracking_status: "calibrated" or "not_calibrated" only process if status is "calibrated"
    hover_zone: "top", "bottom", "left", "right" or None
    selected_zone: "top", "bottom", "left", "right" or None
    last_activation_ts: timestamp of the last activation (zone selected for more than 3.0 seconds)
    """
    snap = STATE.snapshot()
    return {
        "eye_tracking_status": "calibrated" if snap["calibrated"] else "not_calibrated",
        "hover_zone": label(snap["hover_idx"]),  
        "selected_zone": label(snap["selected_idx"]),
        "last_activation_ts": snap["last_activation_ts"],
    }

@app.post("/emergency")
def emergency_alert(request: Request):
    """Called by the frontend when the patient triggers the emergency button."""
    logger.critical("EMERGENCY ALERT TRIGGERED by patient interface")
    log_event(AuditAction.EMERGENCY_TRIGGERED, source_ip=request.client.host)
    return {"status": "emergency_logged", "message": "Emergency alert received"}

class SessionEntry(BaseModel):
    path: list[str]
    summary: str

@app.post("/sessions")
def save_session(entry: SessionEntry):
    """Save a completed communication path + LLM summary to persistent storage."""
    ts = time.time()
    record = {
        "session_id": str(ts),  # stable identifier for deletion / audit
        "timestamp": ts,
        "path": entry.path,
        "summary": entry.summary,
    }
    try:
        _save_session(record)
    except Exception as e:
        logger.error("Failed to save session: %s", e)
        raise HTTPException(status_code=500, detail="Could not save session")
    return {"status": "saved"}

@app.get("/sessions")
def get_sessions():
    """Return all past communication sessions."""
    return {"sessions": _load_sessions()}

@app.get("/sessions/export")
def export_sessions_endpoint():
    """GDPR Article 20 — Right to Data Portability: export all session data as JSON."""
    return _export_sessions(SESSIONS_FILE, _ENCRYPTION_KEY)

@app.post("/sessions/anonymize")
def anonymize_sessions_endpoint():
    """Anonymize all session data for research: replaces summary/path with [ANONYMIZED]."""
    return _anonymize_sessions(SESSIONS_FILE, _ENCRYPTION_KEY)

@app.delete("/sessions")
def delete_all_sessions_endpoint():
    """GDPR Article 17 — Right to Erasure: securely delete all patient session data."""
    return _delete_all_sessions(SESSIONS_FILE, _ENCRYPTION_KEY)

@app.delete("/sessions/{session_id}")
def delete_session_endpoint(session_id: str):
    """GDPR Article 17 — Right to Erasure: securely delete a specific session."""
    try:
        return _delete_session(session_id, SESSIONS_FILE, _ENCRYPTION_KEY)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/sessions/view", response_class=HTMLResponse)
def view_sessions():
    """Human-readable view of all decrypted sessions."""
    sessions = _load_sessions()

    rows = ""
    for i, s in enumerate(sessions, 1):
        timestamp = s.get("timestamp", "N/A")
        if isinstance(timestamp, (int, float)):
            timestamp = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

        path = s.get("path", [])
        if isinstance(path, list):
            path = " → ".join(path)
        summary = s.get("summary", "N/A")

        rows += f"""
        <tr>
            <td style="padding:12px;border-bottom:1px solid #333;color:#888;">{i}</td>
            <td style="padding:12px;border-bottom:1px solid #333;color:#aaa;">{timestamp}</td>
            <td style="padding:12px;border-bottom:1px solid #333;color:#4fc3f7;">{path}</td>
            <td style="padding:12px;border-bottom:1px solid #333;color:#a5d6a7;max-width:400px;">{summary}</td>
        </tr>"""

    html = f"""
    <html>
    <head><title>SpeakWithMe — Sessions (Decrypted)</title></head>
    <body style="background:#111;color:#eee;font-family:system-ui;padding:40px;margin:0;">
        <h1 style="color:#4fc3f7;margin-bottom:5px;">SpeakWithMe — Patient Sessions</h1>
        <p style="color:#888;margin-bottom:30px;">Showing {len(sessions)} decrypted sessions. Data is encrypted at rest with AES-256-GCM.</p>
        <table style="width:100%;border-collapse:collapse;">
            <thead>
                <tr style="border-bottom:2px solid #4fc3f7;">
                    <th style="padding:12px;text-align:left;color:#4fc3f7;">#</th>
                    <th style="padding:12px;text-align:left;color:#4fc3f7;">Timestamp</th>
                    <th style="padding:12px;text-align:left;color:#4fc3f7;">Path</th>
                    <th style="padding:12px;text-align:left;color:#4fc3f7;">Summary</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        <p style="color:#555;margin-top:30px;font-size:12px;">
            Security: Data shown here is decrypted on-the-fly from AES-256-GCM encrypted storage.
            Raw file (data/sessions.json) contains only ciphertext.
        </p>
    </body>
    </html>"""
    return HTMLResponse(content=html)

@app.get("/security/encryption-status")
def encryption_status():
    """Returns current encryption configuration and per-file statistics."""
    sessions_encrypted = 0
    sessions_unencrypted = 0
    if SESSIONS_FILE.exists():
        try:
            raw = json.loads(SESSIONS_FILE.read_text())
            for rec in raw:
                if "_encrypted_fields" in rec:
                    sessions_encrypted += 1
                else:
                    sessions_unencrypted += 1
        except Exception:
            pass

    calibration_encrypted = False
    if CALIBRATION_FILE.exists():
        try:
            data = json.loads(CALIBRATION_FILE.read_text())
            calibration_encrypted = "data" in data
        except Exception:
            pass

    return {
        "encryption_enabled": True,
        "algorithm": "AES-256-GCM",
        "key_size_bits": 256,
        "key_loaded": len(_ENCRYPTION_KEY) == 32,
        "nonce_size_bytes": 12,
        "sessions_encrypted": sessions_encrypted,
        "sessions_unencrypted": sessions_unencrypted,
        "calibration_encrypted": calibration_encrypted,
    }

@app.get("/security/data-retention-status")
def data_retention_status():
    """Returns GDPR data retention configuration and per-session statistics."""
    retention_days = int(os.getenv("DATA_RETENTION_DAYS", "30"))
    sessions = _load_sessions()
    now = time.time()
    cutoff_7d = now - 7 * 86_400

    oldest = newest = None
    expiring_soon = 0
    for s in sessions:
        ts = s.get("timestamp", now)
        if oldest is None or ts < oldest:
            oldest = ts
        if newest is None or ts > newest:
            newest = ts
        if ts < cutoff_7d:
            expiring_soon += 1

    return {
        "retention_days": retention_days,
        "total_sessions": len(sessions),
        "oldest_session": datetime.fromtimestamp(oldest, tz=timezone.utc).isoformat() if oldest else None,
        "newest_session": datetime.fromtimestamp(newest, tz=timezone.utc).isoformat() if newest else None,
        "sessions_expiring_within_7_days": expiring_soon,
        "gdpr_features": {
            "right_to_erasure": True,
            "right_to_portability": True,
            "anonymization": True,
            "secure_deletion": True,
            "auto_purge": True,
        },
    }

@app.get("/security/audit-log")
def audit_log_endpoint(request: Request, last: int = 50):
    """Return recent audit events (without internal hash fields).

    Query param 'last' controls how many events to return (max 500).
    The access itself is logged so the audit trail is self-describing.
    """
    last = min(max(1, last), 500)
    log_event(AuditAction.SUMMARY_VIEWED, details={"requested_count": last}, source_ip=request.client.host)
    return {"events": get_recent_events(last)}

_ACTION_COLORS = {
    "EMERGENCY_TRIGGERED":     "#ef5350",
    "CALIBRATION_START":       "#4fc3f7",
    "CALIBRATION_COMPLETE":    "#4fc3f7",
    "CALIBRATION_FAILED":      "#ff8a65",
    "SUMMARY_GENERATED":       "#a5d6a7",
    "DATA_DELETED":            "#ffb74d",
    "DATA_ANONYMIZED":         "#ffb74d",
    "SECURITY_CHAIN_VERIFIED": "#ce93d8",
    "SERVER_START":            "#80cbc4",
    "SERVER_SHUTDOWN":         "#80cbc4",
}
_ACTION_COLOR_DEFAULT = "#eeeeee"

@app.get("/security/audit-log/view", response_class=HTMLResponse)
def view_audit_log(request: Request, last: int = 50):
    """Human-readable HTML view of the recent audit trail."""
    last = min(max(1, last), 500)
    events = get_recent_events(last)

    rows = ""
    for i, e in enumerate(events, 1):
        ts = html_lib.escape(str(e.get("timestamp", "N/A")))
        action = html_lib.escape(str(e.get("action", "UNKNOWN")))
        details = html_lib.escape(json.dumps(e.get("details", {})))
        source_ip = html_lib.escape(str(e.get("source_ip", "system")))
        color = _ACTION_COLORS.get(action, _ACTION_COLOR_DEFAULT)
        rows += f"""
        <tr>
            <td style="padding:10px 12px;border-bottom:1px solid #222;color:#555;font-size:13px;">{i}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #222;color:#888;font-size:13px;white-space:nowrap;">{ts}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #222;">
                <span style="background:{color}22;color:{color};border:1px solid {color}55;
                             border-radius:4px;padding:2px 8px;font-size:12px;font-weight:600;
                             letter-spacing:0.5px;white-space:nowrap;">{action}</span>
            </td>
            <td style="padding:10px 12px;border-bottom:1px solid #222;color:#aaa;font-size:12px;
                       font-family:monospace;max-width:350px;word-break:break-all;">{details}</td>
            <td style="padding:10px 12px;border-bottom:1px solid #222;color:#666;font-size:13px;">{source_ip}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>SpeakWithMe — Audit Trail</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ background:#111; color:#eee; font-family:system-ui,sans-serif; padding:40px; margin:0; }}
    h1 {{ color:#ce93d8; margin-bottom:4px; }}
    table {{ width:100%; border-collapse:collapse; margin-top:24px; }}
    thead tr {{ border-bottom:2px solid #ce93d8; }}
    th {{ padding:10px 12px; text-align:left; color:#ce93d8; font-size:13px; font-weight:600; }}
    tr:hover td {{ background:#1a1a1a; }}
    .meta {{ color:#555; font-size:12px; margin-top:28px; }}
  </style>
</head>
<body>
  <h1>SpeakWithMe — Audit Trail</h1>
  <p style="color:#888;margin-bottom:0;">Showing last <strong style="color:#eee;">{len(events)}</strong> events
     &nbsp;·&nbsp; <a href="/security/audit-log/view?last=200" style="color:#ce93d8;">Show 200</a>
     &nbsp;·&nbsp; <a href="/security/verify-chain/view" style="color:#ce93d8;">Verify Chain</a>
     &nbsp;·&nbsp; <a href="/security/dashboard/view" style="color:#ce93d8;">Dashboard</a>
  </p>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Timestamp (UTC)</th><th>Action</th><th>Details</th><th>Source IP</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  <p class="meta">
    Hash chain integrity: <a href="/security/verify-chain/view" style="color:#ce93d8;">verify here</a>.
    Raw audit file: <code>data/audit.jsonl</code> (append-only, SHA-256 chained).
  </p>
</body>
</html>"""
    return HTMLResponse(content=html)

@app.get("/security/verify-chain")
def verify_chain_endpoint(request: Request):
    """Verify the integrity of the entire audit hash chain.

    Returns whether the chain is intact and where it breaks if not.
    Logs the verification itself as a SECURITY_CHAIN_VERIFIED event.
    """
    result = verify_chain()
    log_event(
        AuditAction.SECURITY_CHAIN_VERIFIED,
        details={"valid": result["valid"], "total_entries": result["total_entries"]},
        source_ip=request.client.host,
    )
    return result

@app.get("/security/verify-chain/view", response_class=HTMLResponse)
def view_verify_chain(request: Request):
    """Human-readable HTML view of the audit hash chain verification."""
    result = verify_chain()
    log_event(
        AuditAction.SECURITY_CHAIN_VERIFIED,
        details={"valid": result["valid"], "total_entries": result["total_entries"]},
        source_ip=request.client.host,
    )

    valid = result["valid"]
    status_color = "#4caf50" if valid else "#ef5350"
    status_bg    = "#1b3a1e" if valid else "#3a1b1b"
    status_icon  = "✓" if valid else "✗"
    status_text  = "CHAIN INTACT" if valid else "CHAIN COMPROMISED"
    status_sub   = "All entries verified. No tampering detected." if valid else \
                   f"Tampering detected at entry #{result['broken_at_entry']}."

    broken_html = ""
    if not valid and result["broken_at_entry"]:
        broken_html = f"""
        <div style="background:#3a1b1b;border:1px solid #ef5350;border-radius:8px;
                    padding:20px;margin-top:24px;">
          <p style="color:#ef5350;font-size:16px;font-weight:700;margin:0 0 8px;">
            Tampered entry detected
          </p>
          <p style="color:#ffcdd2;margin:0;">
            Entry <strong>#{result['broken_at_entry']}</strong> has a hash mismatch.
            Either this entry or the entry before it was modified after being written.
          </p>
        </div>"""

    actions_rows = ""
    for action, count in sorted(result.get("actions_summary", {}).items(), key=lambda x: -x[1]):
        color = _ACTION_COLORS.get(action, _ACTION_COLOR_DEFAULT)
        bar_width = min(100, max(4, count * 6))
        actions_rows += f"""
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">
          <span style="width:260px;font-size:13px;color:{color};flex-shrink:0;">{html_lib.escape(action)}</span>
          <div style="background:{color}33;height:18px;border-radius:3px;width:{bar_width}px;min-width:4px;"></div>
          <span style="color:#888;font-size:13px;">{count}</span>
        </div>"""

    first_ts = html_lib.escape(str(result.get("first_entry") or "—"))
    last_ts  = html_lib.escape(str(result.get("last_entry")  or "—"))

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>SpeakWithMe — Chain Verification</title>
  <style>
    * {{ box-sizing:border-box; }}
    body {{ background:#111; color:#eee; font-family:system-ui,sans-serif; padding:40px; margin:0; }}
    h1 {{ color:#ce93d8; margin-bottom:4px; }}
    .card {{ background:#1a1a1a; border:1px solid #333; border-radius:8px; padding:24px; margin-top:24px; }}
    .stat-label {{ color:#666; font-size:12px; text-transform:uppercase; letter-spacing:1px; margin-bottom:4px; }}
    .stat-value {{ color:#eee; font-size:20px; font-weight:700; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin-top:24px; }}
  </style>
</head>
<body>
  <h1>SpeakWithMe — Chain Verification</h1>
  <p style="color:#888;margin-bottom:0;">
    <a href="/security/audit-log/view" style="color:#ce93d8;">Audit Log</a>
    &nbsp;·&nbsp;
    <a href="/security/dashboard/view" style="color:#ce93d8;">Dashboard</a>
  </p>

  <div style="background:{status_bg};border:2px solid {status_color};border-radius:12px;
              padding:32px;margin-top:28px;text-align:center;">
    <div style="font-size:64px;color:{status_color};line-height:1;">{status_icon}</div>
    <div style="font-size:32px;font-weight:800;color:{status_color};margin-top:12px;">{status_text}</div>
    <div style="color:{status_color}cc;margin-top:8px;font-size:16px;">{status_sub}</div>
  </div>

  {broken_html}

  <div class="grid">
    <div class="card">
      <div class="stat-label">Total entries</div>
      <div class="stat-value">{result['total_entries']}</div>
    </div>
    <div class="card">
      <div class="stat-label">Verified entries</div>
      <div class="stat-value" style="color:{'#4caf50' if valid else '#ef5350'};">{result['verified_entries']}</div>
    </div>
    <div class="card">
      <div class="stat-label">First entry</div>
      <div style="color:#aaa;font-size:14px;margin-top:6px;">{first_ts}</div>
    </div>
    <div class="card">
      <div class="stat-label">Last entry</div>
      <div style="color:#aaa;font-size:14px;margin-top:6px;">{last_ts}</div>
    </div>
  </div>

  <div class="card" style="margin-top:24px;">
    <p style="color:#ce93d8;font-weight:700;margin:0 0 16px;">Actions breakdown</p>
    {actions_rows if actions_rows else '<p style="color:#555;">No events recorded yet.</p>'}
  </div>

  <p style="color:#555;font-size:12px;margin-top:28px;">
    Algorithm: SHA-256 hash chain · Storage: <code>data/audit.jsonl</code>
    · Verified at: {html_lib.escape(datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))}
  </p>
</body>
</html>"""
    return HTMLResponse(content=html)

@app.get("/security/dashboard/view", response_class=HTMLResponse)
def view_security_dashboard(request: Request):
    """HTML security dashboard showing the three implemented security modules."""
    # --- Module 1: Encryption ---
    enc_sessions_encrypted = enc_sessions_unencrypted = 0
    enc_calibration_encrypted = False
    try:
        if SESSIONS_FILE.exists():
            raw = json.loads(SESSIONS_FILE.read_text())
            for rec in raw:
                if "_encrypted_fields" in rec:
                    enc_sessions_encrypted += 1
                else:
                    enc_sessions_unencrypted += 1
        if CALIBRATION_FILE.exists():
            enc_calibration_encrypted = "data" in json.loads(CALIBRATION_FILE.read_text())
    except Exception:
        pass

    # --- Module 2: Audit chain ---
    chain = verify_chain()

    # --- Module 3: GDPR ---
    retention_days = int(os.getenv("DATA_RETENTION_DAYS", "30"))
    sessions = _load_sessions()
    now = time.time()
    cutoff_7d = now - 7 * 86_400
    expiring_soon = sum(1 for s in sessions if s.get("timestamp", now) < cutoff_7d)

    total_events = chain.get("total_entries", 0)

    # Overall status: key loaded, no unencrypted legacy records remain, chain intact.
    enc_key_ok = len(_ENCRYPTION_KEY) == 32
    chain_ok = chain["valid"]
    enc_ok = enc_key_ok and enc_sessions_unencrypted == 0
    overall_ok = enc_ok and chain_ok

    overall_color = "#4caf50" if overall_ok else "#ef5350"
    overall_bg    = "#162316" if overall_ok else "#2d1515"
    overall_text  = "ALL SYSTEMS SECURE" if overall_ok else "ATTENTION REQUIRED"

    def badge(ok: bool, ok_text: str = "ACTIVE", fail_text: str = "WARNING") -> str:
        color, bg = ("#4caf50", "#1b3a1e") if ok else ("#ef5350", "#3a1b1b")
        text = ok_text if ok else fail_text
        return (f'<span style="background:{bg};color:{color};border:1px solid {color}66;'
                f'border-radius:4px;padding:2px 10px;font-size:12px;font-weight:700;'
                f'letter-spacing:0.5px;">{text}</span>')

    def card(title: str, status_html: str, rows: list[tuple[str, str]]) -> str:
        detail_rows = "".join(
            f'<div style="display:flex;justify-content:space-between;padding:8px 0;'
            f'border-bottom:1px solid #222;">'
            f'<span style="color:#666;font-size:13px;">{html_lib.escape(k)}</span>'
            f'<span style="color:#ccc;font-size:13px;">{v}</span></div>'
            for k, v in rows
        )
        return f"""
        <div style="background:#1a1a1a;border:1px solid #333;border-radius:10px;padding:24px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <span style="color:#eee;font-weight:700;font-size:16px;">{html_lib.escape(title)}</span>
            {status_html}
          </div>
          {detail_rows}
        </div>"""

    card_enc = card(
        "Module 1 — AES-256-GCM Encryption",
        badge(enc_ok),
        [
            ("Algorithm", "AES-256-GCM"),
            ("Key size", "256 bits"),
            ("Sessions encrypted", str(enc_sessions_encrypted)),
            ("Sessions unencrypted (legacy)", str(enc_sessions_unencrypted)),
            ("Calibration encrypted", "Yes" if enc_calibration_encrypted else "No"),
            ("Nonce size", "12 bytes (per-write)"),
        ],
    )

    chain_status = badge(chain_ok, "INTACT", "COMPROMISED")
    card_audit = card(
        "Module 2 — SHA-256 Audit Chain",
        chain_status,
        [
            ("Total log entries", str(chain.get("total_entries", 0))),
            ("Verified entries", str(chain.get("verified_entries", 0))),
            ("Chain status", "Intact" if chain_ok else f'<span style="color:#ef5350;">Broken at entry #{chain.get("broken_at_entry")}</span>'),
            ("First entry", html_lib.escape(str(chain.get("first_entry") or "—"))),
            ("Last entry", html_lib.escape(str(chain.get("last_entry") or "—"))),
            ("Storage", "data/audit.jsonl (append-only)"),
        ],
    )

    card_gdpr = card(
        "Module 3 — GDPR (Retention · Secure Deletion · Export · Anonymization)",
        badge(True),
        [
            ("Retention period", f"{retention_days} days (DATA_RETENTION_DAYS env)"),
            ("Total sessions", str(len(sessions))),
            ("Expiring within 7 days", f'<span style="color:{"#ffb74d" if expiring_soon else "#4caf50"};">{expiring_soon}</span>'),
            ("Auto-purge on startup", "✓ Enabled"),
            ("Secure deletion", "✓ Random-byte overwrite + fsync"),
            ("Right to erasure (Art. 17)", "✓ DELETE /sessions/{id}"),
            ("Right to portability (Art. 20)", "✓ GET /sessions/export"),
            ("Anonymization", "✓ POST /sessions/anonymize"),
        ],
    )

    generated_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>SpeakWithMe — Security Dashboard</title>
  <style>
    * {{ box-sizing:border-box; }}
    body {{ background:#111; color:#eee; font-family:system-ui,sans-serif; padding:40px; margin:0; }}
    h1 {{ color:#4fc3f7; margin-bottom:4px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:20px; margin-top:28px; }}
  </style>
</head>
<body>
  <h1>SpeakWithMe — Security Dashboard</h1>
  <p style="color:#888;margin-bottom:0;">
    <a href="/security/audit-log/view" style="color:#4fc3f7;">Audit Log</a>
    &nbsp;·&nbsp;
    <a href="/security/verify-chain/view" style="color:#4fc3f7;">Verify Chain</a>
    &nbsp;·&nbsp;
    <a href="/sessions/view" style="color:#4fc3f7;">Sessions</a>
  </p>

  <div style="background:{overall_bg};border:2px solid {overall_color};border-radius:10px;
              padding:20px 28px;margin-top:28px;display:flex;align-items:center;gap:16px;">
    <span style="font-size:32px;color:{overall_color};">{'✓' if overall_ok else '✗'}</span>
    <div>
      <div style="font-size:22px;font-weight:800;color:{overall_color};">{overall_text}</div>
      <div style="color:{overall_color}aa;font-size:14px;margin-top:2px;">
        3 modules active · {total_events} audit events · {len(sessions)} sessions · {enc_sessions_encrypted} encrypted
      </div>
    </div>
  </div>

  <div class="grid">
    {card_enc}
    {card_audit}
    {card_gdpr}
  </div>

  <p style="color:#444;font-size:12px;margin-top:32px;border-top:1px solid #222;padding-top:16px;">
    Generated at {html_lib.escape(generated_at)} · SpeakWithMe v1.0 · AES-256-GCM · SHA-256 audit chain · GDPR-compliant
  </p>
</body>
</html>"""
    return HTMLResponse(content=html)

@app.get("/health")
def health_check():
    snap = STATE.snapshot()
    return {"status": "ok", "tracking": _tracker_thread is not None and _tracker_thread.is_alive(), "calibrated": snap["calibrated"]}

@app.get("/test_api_key")
def test_api_key():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"status": "error", "message": "ANTHROPIC_API_KEY not found in environment"}
    return {
        "status": "found",
        "key_prefix": api_key[:15] + "...",
        "key_length": len(api_key),
        "has_whitespace": api_key != api_key.strip(),
        "has_quotes": api_key.startswith('"') or api_key.startswith("'"),
        "has_newline": "\n" in api_key or "\r" in api_key,
    }

@app.get("/test_llm_quick")
def test_llm_quick():
    try:
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=50,
            messages=[{"role": "user", "content": "Say hello in one word"}],
        )
        return {"status": "ok", "response": response.content[0].text}
    except Exception as e:
        return {"status": "error", "error": str(e), "type": type(e).__name__}

class CalibrationTarget(BaseModel):
    target_index: int  # 0..4 corresponding to top,bottom,right,left,center

class CalibrationStatus(BaseModel):
    calibrated: bool
    samples_per_target: dict
    targets_needed: int

@app.post("/calibration/start")
def calibration_start(request: Request, force: bool = False):
    if not force and STATE.snapshot()["calibrated"]:
        return {"message": "Calibration already loaded. Pass force=true to reset.", "skipped": True}
    CALIB.reset()
    STATE.set_calibrated(False)
    log_event(AuditAction.CALIBRATION_START, details={"force": force}, source_ip=request.client.host)
    return {"message": "Calibration reset. Use /calibration/target then /calibration/sample.", "skipped": False}

@app.post("/calibration/target")
def calibration_set_target(t: CalibrationTarget):
    if t.target_index not in (0,1,2,3,4):
        raise HTTPException(400, "target_index must be 0..4")
    CALIB.set_target(t.target_index)
    return {"message": "Target set", "target_index": t.target_index}

@app.post("/calibration/sample")
def calibration_sample():
    # Capture current feature vs known target point — snapshot under lock to avoid TOCTOU race
    with CALIB.lock:
        target_index = CALIB.target_index
        last_feat = CALIB.last_feat
    if target_index is None:
        raise HTTPException(400, "No target set")
    if last_feat is None:
        raise HTTPException(409, "No face/landmarks yet")
    w,h = CALIB.frame_size
    if w == 0:
        raise HTTPException(409, "No frames yet")
    pts = grid_points(w,h)
    if target_index >= len(pts):
        raise HTTPException(400, "Invalid target index for current layout")
    target_xy = np.array(pts[target_index], dtype=np.float32)
    CALIB.add_sample(last_feat, target_xy)
    return {"message": "Sample added", "counts": CALIB.samples_per_target}

@app.post("/calibration/compute")
def calibration_compute(request: Request):
    try:
        W = CALIB.compute()
    except ValueError as e:
        log_event(AuditAction.CALIBRATION_FAILED, details={"error": str(e)}, source_ip=request.client.host)
        raise HTTPException(400, str(e))
    # Compute RMSE over training samples (pixel distance)
    with CALIB.lock:
        X = np.array(CALIB.samples_X, dtype=np.float32)
        Y = np.array(CALIB.samples_Y, dtype=np.float32)
    ones = np.ones((X.shape[0], 1), dtype=np.float32)
    A = np.hstack([X, ones])
    Y_pred = A @ W
    rmse = float(np.sqrt(np.mean(np.sum((Y_pred - Y) ** 2, axis=1))))
    if rmse < 50:
        quality_label = "excellent"
    elif rmse < 100:
        quality_label = "good"
    elif rmse < 150:
        quality_label = "fair"
    else:
        quality_label = "poor"
    log_event(
        AuditAction.CALIBRATION_COMPLETE,
        details={"quality_rmse": round(rmse, 2), "quality_label": quality_label, "samples": len(CALIB.samples_X)},
        source_ip=request.client.host,
    )
    return {"message": "Calibration complete", "weights": W.tolist(),
            "quality_rmse": rmse, "quality_label": quality_label}

@app.get("/calibration/status", response_model=CalibrationStatus)
def calibration_status():
    return CalibrationStatus(
        calibrated=STATE.snapshot()["calibrated"],
        samples_per_target=CALIB.samples_per_target,
        targets_needed=5,
    )



@app.websocket("/ws/eye_tracking")
async def ws_eye_tracking(ws: WebSocket):
    """WebSocket streaming current eye tracking state.

    Client receives JSON messages shaped like the /eye_tracking REST response
    roughly every 100ms, plus immediate push on state change attempts (best-effort).
    """
    await ws.accept()
    last_payload = None
    try:
        while True:
            snap = STATE.snapshot()
            payload = {
                "eye_tracking_status": "calibrated" if snap["calibrated"] else "not_calibrated",
                "hover_zone": label(snap["hover_idx"]),
                "selected_zone": label(snap["selected_idx"]),
                "last_activation_ts": snap["last_activation_ts"],
                "eyes_closed": snap["eyes_closed"],
                "camera_connected": snap["camera_connected"],
            }
            # Only send if changed to reduce traffic
            if payload != last_payload:
                await ws.send_json(payload)
                last_payload = payload
            # Simple ping interval
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await ws.close(code=1011)
        except Exception:
            pass
        logger.error("WebSocket error: %s", e)


if Anthropic is not None:
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
else:
    # Dummy client for local/dev so calls to /get_llm_summary don't crash.
    class _DummyContent:
        text = "[anthropic not installed in dev] Summary unavailable"

    class _DummyMessage:
        content = [_DummyContent()]

    class _DummyMessages:
        @staticmethod
        def create(*args, **kwargs):
            return _DummyMessage()

    class _DummyClient:
        messages = _DummyMessages()

    client = _DummyClient()

# The function will receive a JSON body containing a list of strings and return a summary.
class LLMRequest(BaseModel):
    labels: list[str]
    patient_id: int | None = None


@app.post("/get_llm_summary")
def get_llm_summary(req: LLMRequest, request: Request):
    """
    Receives the patient's communication path and returns a first-person clinical summary.

    Example body:
    {
        "labels": ["Pain", "Abdomen / Stomach", "Urinary / Kidneys", "Mild Pain"],
        "patient_id": 1  (optional — if provided and doctor is authenticated, saves to SQLite)
    }
    """
    patient_path = " → ".join(req.labels)
    system_msg = (
        "You are an AI assistant helping doctors understand nonverbal patient communications. "
        "Summarize the patient's communication path in first person, concisely and clearly. "
        "Do not add opinions or interpretations beyond what the patient selected."
    )
    patient_path_text = textwrap.dedent(f"""
        Patient's communication path: {patient_path}

        Write a brief first-person summary (1-2 sentences) of what the patient is communicating.
        Example input: "Pain → Abdomen / Stomach → Urinary / Kidneys → Mild Pain"
        Example output: "I have mild pain in my abdomen, possibly related to my urinary or kidney function."
    """).strip()
    try:
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=200,
            system=system_msg,
            messages=[{"role": "user", "content": patient_path_text}],
        )
        summary = response.content[0].text
        log_event(
            AuditAction.SUMMARY_GENERATED,
            details={"path_length": len(req.labels)},
            source_ip=request.client.host,
        )
    except Exception as e:
        logger.error("Anthropic API call failed: %s", e)
        summary = None

    # If a patient_id is provided and a doctor is authenticated, persist to SQLite
    if summary and req.patient_id is not None:
        try:
            doctor = get_current_doctor(request)
            from database import save_session as db_save_session
            db_save_session(req.patient_id, doctor["doctor_id"], req.labels, summary)
        except HTTPException:
            pass  # Not authenticated — standalone mode, skip SQLite save
        except Exception as exc:
            logger.error("Failed to save session to SQLite: %s", exc)

    return {"summary": summary}


# ─────────────────────────────────────────────────────────────────────────────
# Auth endpoints
# ─────────────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
async def auth_login(req: LoginRequest, response: HTMLResponse.__class__ = None):
    from fastapi.responses import JSONResponse
    from database import authenticate_doctor
    from auth import TOKEN_TTL

    doctor = authenticate_doctor(req.username, req.password)
    if not doctor:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = generate_token()
    active_tokens[token] = {
        "doctor_id": doctor["id"],
        "username": doctor["username"],
        "full_name": doctor["full_name"],
        "expires": time.time() + TOKEN_TTL,
    }

    resp = JSONResponse({"token": token, "doctor": doctor})
    resp.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        max_age=TOKEN_TTL,
        samesite="lax",
    )
    return resp


@app.post("/auth/logout")
async def auth_logout(request: Request):
    from fastapi.responses import JSONResponse

    token = (
        request.cookies.get("auth_token")
        or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    )
    if token and token in active_tokens:
        del active_tokens[token]

    resp = JSONResponse({"logged_out": True})
    resp.delete_cookie("auth_token")
    return resp


@app.get("/auth/me")
async def auth_me(request: Request):
    doctor = get_current_doctor(request)
    return {
        "doctor_id": doctor["doctor_id"],
        "username": doctor["username"],
        "full_name": doctor["full_name"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Patient management endpoints
# ─────────────────────────────────────────────────────────────────────────────

class PatientCreate(BaseModel):
    first_name: str
    last_name: str
    age: int | None = None
    room_number: str | None = None
    diagnosis: str | None = None
    notes: str | None = None


class PatientUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    age: int | None = None
    room_number: str | None = None
    diagnosis: str | None = None
    notes: str | None = None


@app.get("/api/patients")
async def list_patients(request: Request):
    from database import get_patients
    doctor = get_current_doctor(request)
    return get_patients(doctor["doctor_id"])


@app.post("/api/patients", status_code=201)
async def create_patient_endpoint(req: PatientCreate, request: Request):
    from database import create_patient, get_patient
    doctor = get_current_doctor(request)
    patient_id = create_patient(
        doctor["doctor_id"],
        req.first_name, req.last_name,
        req.age, req.room_number, req.diagnosis, req.notes,
    )
    return get_patient(patient_id)


@app.get("/api/patients/{patient_id}")
async def get_patient_endpoint(patient_id: int, request: Request):
    from database import get_patient, get_sessions
    get_current_doctor(request)
    patient = get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    patient["sessions"] = get_sessions(patient_id)
    return patient


@app.put("/api/patients/{patient_id}")
async def update_patient_endpoint(patient_id: int, req: PatientUpdate, request: Request):
    from database import update_patient, get_patient
    get_current_doctor(request)
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not update_patient(patient_id, **fields):
        raise HTTPException(status_code=404, detail="Patient not found or no valid fields")
    return get_patient(patient_id)


@app.delete("/api/patients/{patient_id}")
async def delete_patient_endpoint(patient_id: int, request: Request):
    from database import delete_patient
    get_current_doctor(request)
    if not delete_patient(patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    return {"deleted": True, "patient_id": patient_id}


@app.post("/api/patients/{patient_id}/start-session")
async def start_patient_session(patient_id: int, request: Request):
    from database import get_patient
    get_current_doctor(request)
    patient = get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return {"session_active": True, "patient_id": patient_id}


@app.get("/api/patients/{patient_id}/sessions")
async def get_patient_sessions(patient_id: int, request: Request):
    from database import get_sessions
    get_current_doctor(request)
    return get_sessions(patient_id)

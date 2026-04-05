from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
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

# Safe import for OpenAI + dotenv — if unavailable, provide a simple fallback client so the
# server can start without installing the OpenAI package during local dev.
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv():
        return None

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
LLM_MODEL        = os.getenv("LLM_MODEL", "gpt-4o-mini")
SESSIONS_FILE      = pathlib.Path(os.getenv("SESSIONS_FILE", "./data/sessions.json"))
CALIBRATION_FILE   = pathlib.Path(os.getenv("CALIBRATION_FILE", "./data/calibration.json"))

# -------------------- Calibration persistence --------------------
def _save_calibration(W):
    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        CALIBRATION_FILE.write_text(json.dumps({"W": W.tolist(), "timestamp": time.time()}))
        logger.info("Calibration saved to %s", CALIBRATION_FILE)
    except Exception as e:
        logger.error("Failed to save calibration: %s", e)

def _load_calibration():
    if not CALIBRATION_FILE.exists():
        return None
    try:
        data = json.loads(CALIBRATION_FILE.read_text())
        W = np.array(data["W"], dtype=np.float32)
        logger.info("Calibration loaded from %s", CALIBRATION_FILE)
        return W
    except Exception as e:
        logger.warning("Could not load calibration file: %s", e)
        return None

# -------------------- Session store --------------------
_sessions_lock = threading.Lock()

def _load_sessions() -> list:
    if SESSIONS_FILE.exists():
        try:
            return json.loads(SESSIONS_FILE.read_text())
        except Exception:
            return []
    return []

def _save_session(entry: dict):
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _sessions_lock:
        sessions = _load_sessions()
        sessions.append(entry)
        SESSIONS_FILE.write_text(json.dumps(sessions, indent=2))

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
        self.dwell_start = None
        self.last_active_idx = None
        self.samples_per_target = {0:0,1:0,2:0,3:0,4:0}

    def reset(self):
        with self.lock:
            self.samples_X.clear(); self.samples_Y.clear()
            self.target_index = None
            self.W = None
            self.ema_gaze = None
            self.dwell_start = None
            self.last_active_idx = None
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
        grid_idx = 0
        calib_X, calib_Y = [], []
        W = None
        ema_gaze = None
        dwell_start = None
        last_active_idx = None
        calibrated_points_counter = 1

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

                            # Dwell detection
                            pts = grid_points(w, h)
                            dists = [np.hypot(gaze_point[0] - x, gaze_point[1] - y) for (x, y) in pts]
                            ci = int(np.argmin(dists))
                            # Skip dwell activation for center (neutral) index 4
                            with CALIB.lock:
                                if ci != 4 and dists[ci] <= ACTIVE_RADIUS_PX:
                                    if CALIB.last_active_idx != ci:
                                        CALIB.last_active_idx = ci
                                        CALIB.dwell_start = time.time()
                                    else:
                                        if CALIB.dwell_start and (time.time() - CALIB.dwell_start) >= DWELL_SECONDS:
                                            do_select = ci
                                            CALIB.dwell_start = None
                                        else:
                                            do_select = None
                                else:
                                    if ci != 4:
                                        CALIB.last_active_idx = None
                                        CALIB.dwell_start = None
                                    do_select = None
                            if do_select is not None:
                                STATE.set_selected(do_select)

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
    # Auto-load persisted calibration if available
    if HAS_MEDIAPIPE:
        W = _load_calibration()
        if W is not None:
            CALIB.W = W
            STATE.set_calibrated(True)
    _start_tracker_once()
    yield
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
def emergency_alert():
    """Called by the frontend when the patient triggers the emergency button."""
    logger.critical("EMERGENCY ALERT TRIGGERED by patient interface")
    return {"status": "emergency_logged", "message": "Emergency alert received"}

class SessionEntry(BaseModel):
    path: list[str]
    summary: str

@app.post("/sessions")
def save_session(entry: SessionEntry):
    """Save a completed communication path + LLM summary to persistent storage."""
    record = {
        "timestamp": time.time(),
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

@app.get("/health")
def health_check():
    snap = STATE.snapshot()
    return {"status": "ok", "tracking": _tracker_thread is not None and _tracker_thread.is_alive(), "calibrated": snap["calibrated"]}

class CalibrationTarget(BaseModel):
    target_index: int  # 0..4 corresponding to top,bottom,right,left,center

class CalibrationStatus(BaseModel):
    calibrated: bool
    samples_per_target: dict
    targets_needed: int

@app.post("/calibration/start")
def calibration_start(force: bool = False):
    if not force and STATE.snapshot()["calibrated"]:
        return {"message": "Calibration already loaded. Pass force=true to reset.", "skipped": True}
    CALIB.reset()
    STATE.set_calibrated(False)
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
def calibration_compute():
    try:
        W = CALIB.compute()
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"message": "Calibration complete", "weights": W.tolist()}

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


load_dotenv()
if OpenAI is not None:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
else:
    # Dummy client for local/dev so calls to /get_llm_summary don't crash.
    class _DummyChoice:
        class message:
            content = "[openai not installed in dev] Summary unavailable"

    class _DummyCompletion:
        choices = [_DummyChoice()]

    class _DummyChatCompletions:
        @staticmethod
        def create(*args, **kwargs):
            return _DummyCompletion()

    class _DummyChat:
        completions = _DummyChatCompletions()

    class _DummyClient:
        chat = _DummyChat()

    client = _DummyClient()

# The function will receive a JSON body containing a list of strings and return a summary.
class LLMRequest(BaseModel):
    labels: list[str]


@app.post("/get_llm_summary")
def get_llm_summary(req: LLMRequest):
    """
    Receives the patient's communication path and returns a first-person clinical summary.

    Example body:
    {
        "labels": ["Pain", "Abdomen / Stomach", "Urinary / Kidneys", "Mild Pain"]
    }
    """
    patient_path = " → ".join(req.labels)
    system_msg = (
        "You are an AI assistant helping doctors understand nonverbal patient communications. "
        "Summarize the patient's communication path in first person, concisely and clearly. "
        "Do not add opinions or interpretations beyond what the patient selected."
    )
    user_msg = textwrap.dedent(f"""
        Patient's communication path: {patient_path}

        Write a brief first-person summary (1-2 sentences) of what the patient is communicating.
        Example input: "Pain → Abdomen / Stomach → Urinary / Kidneys → Mild Pain"
        Example output: "I have mild pain in my abdomen, possibly related to my urinary or kidney function."
    """).strip()
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=150,
        )
    except Exception as e:
        logger.error("OpenAI API call failed: %s", e)
        raise HTTPException(status_code=502, detail="LLM service unavailable")
    return {"summary": response.choices[0].message.content}



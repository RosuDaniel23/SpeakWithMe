# SpeakWithMe — Complete Technical Context

> Paste this document into any Claude conversation to give it full context about the project.
> Generated: 2026-04-25

---

## 1. Project Overview

**SpeakWithMe** is a medical eye-tracking AAC (Augmentative and Alternative Communication) web application built as a bachelor's thesis project. It allows nonverbal hospital patients (e.g., post-stroke, ALS, post-intubation) to communicate with doctors by navigating a structured decision tree using only their eye gaze. When the patient reaches a leaf node, an Anthropic Claude LLM generates a first-person medical summary ("I have severe pain in my head") which the doctor reads.

- **Problem solved:** Nonverbal patients in hospital settings have no reliable way to communicate pain, needs, or urgent requests when they cannot speak or use their hands.
- **Target users:** Nonverbal hospital patients (using the eye-tracking interface) and their attending doctors (using the login dashboard).
- **Type:** Full-stack web application — React SPA frontend + FastAPI Python backend.
- **Status:** MVP / thesis demo — fully functional but not production-hardened (e.g., auth tokens are in-memory only).

---

## 2. Tech Stack

### Backend
- **Language:** Python 3.11.9 (pinned in pyproject.toml)
- **Framework:** FastAPI ≥ 0.116.1
- **ASGI server:** Uvicorn ≥ 0.30.0 (with `[standard]` extras)
- **Eye tracking:** MediaPipe ≥ 0.10.21, OpenCV ≥ 4.11.0.86, NumPy (transitive)
- **LLM:** Anthropic SDK ≥ 0.40.0 (Claude claude-sonnet-4-20250514 by default)
- **Encryption:** cryptography ≥ 44.0.0 (AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`)
- **Database:** SQLite via Python's built-in `sqlite3` — no ORM
- **Config:** python-dotenv ≥ 1.1.1
- **WebSockets:** websockets ≥ 12.0
- **Package manager:** `uv` (ultra-fast, replaces pip/poetry)

### Frontend
- **Language:** TypeScript (strict mode)
- **Framework:** React 19.1.1
- **Build tool:** Vite 7.1.2 with `@vitejs/plugin-react` 5.0.0
- **CSS:** Tailwind CSS v4 (`@tailwindcss/vite` 4.1.13), tw-animate-css
- **UI components:** shadcn/ui (built on Radix UI primitives)
- **HTTP client:** `api.ts` wrapper around `fetch` (no axios in use despite being in package.json)
- **Icons:** Lucide React 0.542.0
- **State management:** React Context + `useReducer` (no Redux/Zustand)
- **Linting:** ESLint 9.33.0 with react-refresh and react-hooks plugins

### External APIs
- **Anthropic Claude API** (`ANTHROPIC_API_KEY`) — LLM summaries via `POST /get_llm_summary`
- No other third-party services

---

## 3. Architecture

### High-Level
Client-server: React SPA (port 5173) ↔ FastAPI backend (port 8000)

```
Browser (React SPA)
  ├── HTTP/REST  ─────────────────→  FastAPI (main.py)
  │                                    ├── Eye tracking logic (mediapipe/cv2)
  │                                    ├── SQLite (database.py)
  │                                    ├── In-memory token store (auth.py)
  │                                    ├── security/encryption.py
  │                                    ├── security/audit.py
  │                                    └── security/data_retention.py
  └── WebSocket  ─────────────────→  /ws/eye_tracking  (push ~100ms updates)
```

### Communication
- REST endpoints for all CRUD operations
- One persistent WebSocket (`/ws/eye_tracking`) streams gaze state to the frontend in real-time
- CORS allows `http://localhost:5173` and `http://localhost:3000`

### Authentication
Simple in-memory token dict in `auth.py`:
- `active_tokens: dict[str, dict]` — does NOT persist across server restarts
- Token lifetime: 24 hours (`TOKEN_TTL = 86_400`)
- Token sent as httpOnly cookie OR `Authorization: Bearer <token>` header
- `get_current_doctor(request)` extracts and validates token, raises HTTP 401 if invalid

### State Management (Frontend)
React Context + `useReducer`:
- `AppStateCtx` — read-only `AppState` (current tree node, progress, selections, etc.)
- `AppDispatchCtx` — dispatch `AppAction` to modify state
- `SessionCallbackCtx` — carries `{ onSessionEnd, patientId, token }` for doctor-mode sessions
- All three are provided by `AppProvider` in `AppContext.tsx`

### Key Design Patterns
- **Dwell-based selection:** Progress increments at 30ms ticks; selection fires at 100% (default 3s)
- **Hash chain audit log:** Each audit entry SHA-256-hashes its own fields + previous hash — tamper-evident
- **AEAD encryption at rest:** AES-256-GCM wraps sensitive fields; nonce prepended to ciphertext
- **Graceful degradation:** MediaPipe/OpenCV imported with `HAS_MEDIAPIPE` fallback to simulated tracker

---

## 4. Project Structure

```
SpeakWithMe/
├── README.md                  (placeholder: "i changed this :D")
├── PROJECT_CONTEXT.md         (this file)
├── .gitignore
├── frontend/
│   ├── src/
│   │   ├── App.tsx            ← Root router (login/dashboard/session pages)
│   │   ├── App.css            ← Tailwind config, CSS vars, theme
│   │   ├── main.tsx           ← React entry point (ReactDOM.createRoot)
│   │   ├── options.tsx        ← DECISION_TREE data + iconMap
│   │   ├── components/
│   │   │   ├── LoginPage.tsx
│   │   │   ├── Dashboard.tsx
│   │   │   ├── CalibrationPage.tsx
│   │   │   ├── TriangleZone.tsx
│   │   │   ├── SelectionTerminalBar.tsx
│   │   │   ├── EmergencyButton.tsx
│   │   │   ├── SummaryModal.tsx
│   │   │   └── ui/            ← shadcn/ui primitives (button, card, input, label, etc.)
│   │   ├── state/
│   │   │   ├── AppContext.tsx  ← Provider, hooks, commitSelection()
│   │   │   ├── appReducer.ts  ← Reducer + initialAppState()
│   │   │   ├── appTypes.ts    ← AppState, AppAction, EyeStatus types
│   │   │   ├── useDwellController.ts  ← Dwell timer hook
│   │   │   └── useGazeOrchestration.ts ← Gaze→zone mapping hook
│   │   └── lib/
│   │       ├── api.ts         ← fetch wrapper (API_BASE, api() function)
│   │       ├── useEyeTracking.ts ← WebSocket hook for gaze state
│   │       └── utils.ts       ← cn() Tailwind class merge utility
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── index.html
└── backend/
    ├── main.py                ← FastAPI app (1475 lines) — all endpoints + eye tracking
    ├── database.py            ← SQLite CRUD (218 lines)
    ├── auth.py                ← Token auth (33 lines)
    ├── security/
    │   ├── encryption.py      ← AES-256-GCM (244 lines)
    │   ├── audit.py           ← SHA-256 hash chain (307 lines)
    │   └── data_retention.py  ← GDPR lifecycle (285 lines)
    ├── data/
    │   ├── speakwithme.db     ← SQLite database
    │   ├── sessions.json      ← Encrypted session records (JSON array)
    │   ├── calibration.json   ← Encrypted calibration weights
    │   └── audit.jsonl        ← Append-only audit trail
    ├── pyproject.toml
    └── .env                   ← ANTHROPIC_API_KEY, ENCRYPTION_KEY
```

---

## 5. Database / Data Model

### SQLite tables (in `speakwithme.db`)

**doctors**
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Autoincrement |
| username | TEXT UNIQUE | Login name |
| password_hash | TEXT | Format: `"salt:sha256hash"` (16-byte hex salt) |
| full_name | TEXT | Display name |
| created_at | TIMESTAMP | Default CURRENT_TIMESTAMP |

**patients**
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Autoincrement |
| doctor_id | INTEGER FK→doctors | Owning doctor |
| first_name | TEXT | |
| last_name | TEXT | |
| age | INTEGER | Nullable |
| room_number | TEXT | Nullable |
| diagnosis | TEXT | Nullable |
| notes | TEXT | Nullable |
| created_at | TIMESTAMP | |

**sessions** (SQLite — distinct from `sessions.json` flat-file store)
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Autoincrement |
| patient_id | INTEGER FK→patients | Cascades on patient delete |
| doctor_id | INTEGER FK→doctors | |
| path | TEXT | JSON-serialized `list[str]` of tree labels |
| summary | TEXT | LLM-generated first-person summary |
| created_at | TIMESTAMP | |

### Flat-file session store (`sessions.json`)
Legacy/parallel storage — JSON array where each element is either:
- **Unencrypted** (legacy): `{ timestamp, path, summary, session_id }`
- **Encrypted**: `{ timestamp, path: "base64...", summary: "base64...", session_id, _encrypted_fields: ["summary", "path"] }`

Foreign keys are enabled via `PRAGMA foreign_keys = ON`.
No ORM — raw `sqlite3` with `row_factory = sqlite3.Row`.

---

## 6. Main Features & Modules

### 6.1 Eye Tracking & Calibration
**Files:** `backend/main.py` (functions: `eye_features()`, `fit_regression()`, `predict_gaze()`, `run_eye_tracking()`, `activate_zone_and_update_state()`, calibration endpoints)
**What it does:** MediaPipe FaceMesh detects iris position → linear regression maps (x,y) to screen zone → hover zone is updated every frame. Falls back to a simulated tracker if MediaPipe is unavailable.
**Calibration flow:** 5 targets (top/bottom/right/left/center), minimum 5 samples each → `POST /calibration/compute` → stores encrypted weights in `calibration.json`.
**Key endpoints:** `POST /calibration/start`, `POST /calibration/target`, `POST /calibration/sample`, `POST /calibration/compute`, `GET /calibration/status`, `WebSocket /ws/eye_tracking`

### 6.2 Decision Tree Navigation
**Files:** `frontend/src/options.tsx`, `frontend/src/state/AppContext.tsx` (`commitSelection()`), `frontend/src/state/appReducer.ts`
**What it does:** Structured tree with 4 top-level categories (Assistance, Needs, Pain, Communication). Pain branch goes 4 levels deep: Body Region → Pain Level → Pain Type → Duration → Persistence. Each leaf sends the path labels to the LLM.
**Key components:** `TriangleZone.tsx` (zones), `SelectionTerminalBar.tsx` (breadcrumb), `SummaryModal.tsx` (result)

### 6.3 Dwell-Based Selection
**Files:** `frontend/src/state/useDwellController.ts`, `frontend/src/state/useGazeOrchestration.ts`
**What it does:** User holds gaze on a zone for 3 seconds (configurable via `confirmDurationMs`). Progress increments at 30ms ticks. Eyes-closed for 3s triggers automatic SELECTION_BACK. Center gaze for 1s cancels current dwell.
**TODO in code:** `useDwellController.ts:50` — "add TTO by chat gpt here or in commitSelection" (Time-To-Open prediction)

### 6.4 LLM Summary Generation
**Files:** `backend/main.py` (`get_llm_summary()`), `frontend/src/state/AppContext.tsx` (`commitSelection()`)
**What it does:** Leaf selection sends path labels to `POST /get_llm_summary`. Backend calls Anthropic Claude (`claude-sonnet-4-20250514`, max_tokens=200) with a system prompt instructing first-person clinical summarization. Summary is spoken aloud via Web Speech API, then displayed for 10 seconds before auto-reset.
**Doctor mode:** If `patient_id` is in the request body and a valid auth token is present, the session is also saved to SQLite via `save_session()`.

### 6.5 Doctor Login & Patient Dashboard
**Files:** `backend/database.py`, `backend/auth.py`, `backend/main.py` (auth + patient endpoints), `frontend/src/components/LoginPage.tsx`, `frontend/src/components/Dashboard.tsx`
**What it does:** Doctor logs in with username/password. Dashboard shows patient cards with session counts. Doctor can add/delete patients and view session history. Clicking "Start Session" enters full-screen eye-tracking mode linked to that patient.

### 6.6 AES-256-GCM Encryption at Rest
**Files:** `backend/security/encryption.py`
**What it does:** Patient sessions (`summary`, `path`) and calibration data are encrypted before writing to disk. Each encryption uses a fresh 12-byte random nonce. Key is loaded from `ENCRYPTION_KEY` env var (64-char hex = 32 bytes); auto-generated to `.env` on first run.
**Backward compat:** Records without `_encrypted_fields` marker are treated as legacy unencrypted and returned as-is.
**Migration:** `_migrate_unencrypted_sessions()` runs at startup to encrypt any legacy records.

### 6.7 SHA-256 Hash Chain Audit Trail
**Files:** `backend/security/audit.py`
**What it does:** Every security-relevant action (calibration, session save, LLM summary, emergency, login, GDPR operations, server start/stop) is appended to `data/audit.jsonl`. Each entry includes: timestamp, action, sanitized details, source IP, previous_hash, and its own hash. Verification checks the chain from genesis.
**Privacy:** `_sanitize_details()` strips fields like `summary`, `path`, `labels` — patient medical content never appears in the audit log.
**Endpoint:** `GET /security/verify-chain` → `GET /security/verify-chain/view` (HTML)

### 6.8 GDPR Data Lifecycle
**Files:** `backend/security/data_retention.py`
**What it does:**
- **Auto-purge:** Sessions older than `DATA_RETENTION_DAYS` (default 30) days are deleted at startup
- **Right to erasure:** `DELETE /sessions` (all) and `DELETE /sessions/{id}` (single)
- **Right to portability:** `GET /sessions/export` — decrypted JSON with GDPR metadata
- **Anonymization:** `POST /sessions/anonymize` — replaces `summary`/`path` with `[ANONYMIZED]`, re-encrypts, preserves structure for analytics
- **Secure deletion:** `secure_overwrite()` writes random bytes to file before new content, then calls `os.fsync()`

### 6.9 Security Dashboard (HTML Views)
**Files:** `backend/main.py` (HTML generation functions)
**What it does:** Browser-accessible dark-themed HTML pages for monitoring security status.
**Endpoints:**
- `GET /security/dashboard/view` — Overview of all 3 security modules
- `GET /security/audit-log/view` — Color-coded audit trail
- `GET /security/verify-chain/view` — Hash chain verification results
- `GET /sessions/view` — Decrypted session list

### 6.10 Emergency Button
**Files:** `frontend/src/components/EmergencyButton.tsx`, `backend/main.py` (`POST /emergency`)
**What it does:** Red button in the corner. On click (or double-Escape), triggers a 880Hz audio alarm, fullscreen red overlay, and logs an emergency event to the audit trail.

---

## 7. API Endpoints

All endpoints are on `http://localhost:8000`. Auth = requires valid token in cookie or `Authorization: Bearer` header.

### Eye Tracking
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/eye_tracking` | No | Current gaze state (hover_zone, selected_zone, calibrated, eyes_closed) |
| WebSocket | `/ws/eye_tracking` | No | Real-time push of `EyeTrackingState` (~100ms interval) |
| GET | `/health` | No | Server health (tracker alive, calibrated) |

### Calibration
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/calibration/start` | No | Begin calibration (`?force=true` to force recalibrate) |
| POST | `/calibration/target` | No | Set active calibration target `{target_index: 0..4}` |
| POST | `/calibration/sample` | No | Capture one sample for current target |
| POST | `/calibration/compute` | No | Compute regression weights; returns quality label + RMSE |
| GET | `/calibration/status` | No | Current calibration progress |

### Sessions (Flat-file JSON store)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/sessions` | No | Save session `{path: string[], summary: string}` to `sessions.json` (encrypted) |
| GET | `/sessions` | No | Retrieve all decrypted sessions |
| GET | `/sessions/export` | No | GDPR Article 20 export with metadata |
| POST | `/sessions/anonymize` | No | Replace content with `[ANONYMIZED]`, re-encrypt |
| DELETE | `/sessions` | No | Delete all sessions (secure overwrite) |
| DELETE | `/sessions/{session_id}` | No | Delete single session by ID |
| GET | `/sessions/view` | No | HTML table of all sessions |

### LLM & Emergency
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/get_llm_summary` | No (token optional) | Generate summary; if token+patient_id, also saves to SQLite |
| POST | `/emergency` | No | Log emergency event to audit |

### Auth
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/auth/login` | No | `{username, password}` → token + doctor info + sets httpOnly cookie |
| POST | `/auth/logout` | No | Invalidate token, clear cookie |
| GET | `/auth/me` | Yes | Current doctor info |

### Patient Management
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/patients` | Yes | List doctor's patients (with session_count, last_session) |
| POST | `/api/patients` | Yes | Create patient (returns 201 + created record) |
| GET | `/api/patients/{id}` | Yes | Patient details + full session list |
| PUT | `/api/patients/{id}` | Yes | Update patient fields (partial) |
| DELETE | `/api/patients/{id}` | Yes | Delete patient + cascade sessions |
| POST | `/api/patients/{id}/start-session` | Yes | Returns `{session_active: true, patient_id}` |
| GET | `/api/patients/{id}/sessions` | Yes | SQLite sessions for this patient |

### Security (HTML + JSON)
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/security/encryption-status` | No | Encryption config + per-file stats |
| GET | `/security/data-retention-status` | No | Retention config + session counts |
| GET | `/security/audit-log` | No | Last N audit events (JSON) |
| GET | `/security/audit-log/view` | No | HTML audit trail view |
| GET | `/security/verify-chain` | No | SHA-256 chain verification (JSON) |
| GET | `/security/verify-chain/view` | No | HTML chain verification view |
| GET | `/security/dashboard/view` | No | HTML security status dashboard |

### Debug
| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/test_api_key` | No | Validate ANTHROPIC_API_KEY format |
| GET | `/test_llm_quick` | No | Quick Anthropic API smoke-test |

---

## 8. Frontend Structure

### Pages (state-based routing in `App.tsx`)
| Page state | Component | Condition |
|-----------|-----------|-----------|
| `"login"` | `LoginPage` | No authToken |
| `"dashboard"` | `Dashboard` | Has token, not in session |
| `"session"` | `AppProvider` + `AppInner` | Has token, started session |

### Key Components
| Component | File | Purpose |
|-----------|------|---------|
| `MedicalCommunicationApp` | `App.tsx` | Root router |
| `AppInner` | `App.tsx` | Full-screen session UI (uses context, gaze, dwell) |
| `LoginPage` | `components/LoginPage.tsx` | Doctor auth form |
| `Dashboard` | `components/Dashboard.tsx` | Patient list + history + add patient |
| `CalibrationPage` | `components/CalibrationPage.tsx` | 5-target calibration UI |
| `TriangleZone` | `components/TriangleZone.tsx` | One cardinal zone (progress ring + icon + label) |
| `SelectionTerminalBar` | `components/SelectionTerminalBar.tsx` | Bottom breadcrumb bar |
| `EmergencyButton` | `components/EmergencyButton.tsx` | Emergency trigger + fullscreen overlay |
| `SummaryModal` | `components/SummaryModal.tsx` | LLM result + 10s countdown |

### State Shape (`AppState` in `appTypes.ts`)
```typescript
{
  currentNode: DecisionTreeNode      // Current position in the tree
  selectedPath: DecisionTreeNode[]   // Breadcrumb of traversed nodes
  activeOptionId: string | null      // Zone user is currently gazing at
  progress: number                   // 0..100 dwell fill
  isSelecting: boolean               // Dwell in progress
  currentQuestion: string            // Center heading text
  showCalibration: boolean           // Show calibration overlay
  confirmDurationMs: number          // Dwell threshold (default 3000ms)
  selectionTriggered: boolean        // Guards against double-commit
  pendingSummary: string | null      // LLM summary to display
  isLocked: boolean                  // Disable all interaction
  summaryCountdown: number | null    // Seconds before auto-reset
}
```

### Routing Approach
No react-router. State variable `page: "login" | "dashboard" | "session"` in `MedicalCommunicationApp`.

---

## 9. Configuration & Environment

### Required Environment Variables
```
ANTHROPIC_API_KEY        Anthropic API key for Claude LLM
ENCRYPTION_KEY           64-char hex string (32 bytes AES-256 key)
```

### Optional Environment Variables
```
SESSIONS_FILE            Path to sessions JSON (default: data/sessions.json)
CALIBRATION_FILE         Path to calibration JSON (default: data/calibration.json)
DB_FILE                  Path to SQLite DB (default: data/speakwithme.db)
AUDIT_FILE               Path to audit JSONL (default: data/audit.jsonl)
DATA_RETENTION_DAYS      Auto-purge threshold in days (default: 30)
ALLOWED_ORIGINS          CORS origins (default: http://localhost:5173,http://localhost:3000)
LLM_MODEL                Anthropic model ID (default: claude-sonnet-4-20250514)
VITE_API_URL             Backend URL for frontend (default: http://localhost:8000)
```

### Configuration Files
| File | Purpose |
|------|---------|
| `backend/.env` | Secrets (ANTHROPIC_API_KEY, ENCRYPTION_KEY) |
| `backend/pyproject.toml` | Python 3.11.9, 8 dependencies, uv-managed |
| `frontend/vite.config.ts` | Vite + React + Tailwind v4 + `@` path alias |
| `frontend/tsconfig.json` | TypeScript strict, ES2022, `@/*` alias |
| `frontend/components.json` | shadcn/ui component config |

### Running Locally
```bash
# Backend (from project root)
cd backend
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (from project root)
cd frontend
npm install
npm run dev
# → http://localhost:5173

# Default login credentials
# Username: admin
# Password: admin123
```

---

## 10. Current Issues, TODOs, and Known Limitations

### TODO Comments in Code
1. **`frontend/src/state/useDwellController.ts:49-53`**
   ```
   // TODO: add TTO by chat gpt here or in commitSelection
   // create path from state.selectedPath + current option label or something like that
   // request to backend to get TTO prediction for this path
   ```
   Placeholder for Time-To-Open (TTO) prediction — intended to predict which option the patient wants before they finish dwelling, reducing selection time.

2. **`frontend/src/App.tsx`** — Commented-out path breadcrumb display under the center heading (lines ~72-75):
   ```tsx
   {/* {state.selectedPath.length > 0 && (
     <p>Path: {state.selectedPath.map(n => n.label).join(" → ")}</p>
   )} */}
   ```

### Known Limitations
- **Auth tokens are in-memory only** — all doctors are logged out when the server restarts. Not suitable for production.
- **Single ENCRYPTION_KEY for all data** — key rotation would make all existing encrypted records unreadable.
- **Duplicate ENCRYPTION_KEY in .env** — the file contains two `ENCRYPTION_KEY=` lines; last one wins.
- **`sessions.json` and SQLite sessions are separate stores** — sessions from the standalone (no-login) flow go to `sessions.json`; sessions from the doctor flow go to both. No unified query.
- **Demo unencrypted session** — one intentionally unencrypted record exists in `sessions.json` at timestamp `1.0` for demo purposes.
- **No HTTPS** — communication between browser and server is plaintext HTTP/WS in local dev.
- **MediaPipe accuracy** — eye tracking accuracy degrades with glasses, poor lighting, or users with certain facial features. The linear regression calibration is intentionally simple.
- **SSD wear-leveling caveat** — secure deletion (`secure_overwrite`) is best-effort at the application level; SSDs may retain data in reallocated sectors.
- **No TypeScript compiler installed in the project** — `tsc` not in devDependencies; type checking relies on Vite's esbuild (which skips type errors).

---

## 11. Code Style & Conventions

- **Language:** English for all identifiers, comments, and docstrings. Romanian names appear only in demo data (Ion Popescu, Maria Ionescu, etc.).
- **Python naming:** `snake_case` for functions/variables; `PascalCase` for classes; `SCREAMING_SNAKE_CASE` for module-level constants. Private helpers prefixed with `_`.
- **TypeScript naming:** `PascalCase` for components/interfaces/types; `camelCase` for variables/functions; `SCREAMING_SNAKE_CASE` for constants.
- **Comments:** Docstrings explain *why* (design rationale), not just *what*. Security modules have module-level docstrings explaining cryptographic choices.
- **No Python formatting tools** (no black, ruff, flake8). Frontend has ESLint but no Prettier.
- **Path anchoring:** All data file paths anchored to `pathlib.Path(__file__).parent` to work regardless of working directory.
- **Error handling:** Audit logging errors are caught and logged — never crash the app. Encryption failures raise descriptive `ValueError` or `RuntimeError`.

---

## 12. Thesis-Specific Context

### Academic Context
- **Thesis title (inferred):** "SpeakWithMe — Eye-Tracking AAC System for Nonverbal Hospital Patients"
- **University:** Unspecified in project files
- **Field:** Computer Science / Human-Computer Interaction / Medical Informatics
- **Git repo name:** `AI-Communication-for-Nonverbal-Patients`

### Technical Contribution
The thesis demonstrates a complete end-to-end prototype combining:
1. **Real-time eye-tracking** using commodity webcams (no specialized hardware) via MediaPipe FaceMesh + linear regression calibration
2. **Structured AAC communication** via a hierarchical decision tree specifically designed for hospital patient needs (pain assessment, urgency levels, body regions)
3. **LLM-generated summaries** converting eye-gaze selection paths into clinically useful first-person statements for doctors
4. **Three-layer security architecture:**
   - Module 1: AES-256-GCM encryption at rest (GDPR Article 5(1)(f) — data integrity & confidentiality)
   - Module 2: SHA-256 hash-chain audit trail (non-repudiation, tamper evidence)
   - Module 3: GDPR data lifecycle (Articles 5(1)(e), 17, 20 — storage limitation, erasure, portability)
5. **Doctor-patient management system** with SQLite persistence and session history

### What Makes It a Thesis Project
- Eye-tracking module implemented from scratch (not a commercial SDK)
- Security modules implemented at the cryptographic primitive level
- Decision tree designed specifically for non-verbal hospital communication
- Works with no specialized hardware — just a standard laptop webcam

### Commit History (7 total commits)
```
6199a8e  Add doctor login, patient dashboard, SQLite database, and session management
d4d3d46  Add security dashboard with visual HTML views for audit log, chain verification, and module status
4c8887a  GDPR data retention - auto-purge, secure deletion, data export, anonymization, right to erasure
aea9f86  AES-256-GCM encryption at rest for patient sessions and calibration data
6046e59  Fix: isolate calibration from gaze activity, lock screen during summary with 10s auto-reset
24fc012  Fix LLM summary fallback, calibration quality score, remove dead code, stabilize keyboard handlers
8e31d2c  Initial commit: SpeakWithMe - eye-tracking communication system
```

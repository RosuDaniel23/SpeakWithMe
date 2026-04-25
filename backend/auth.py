"""
Simple token-based authentication for SpeakWithMe.
Tokens are stored in memory — they do not survive server restarts.
"""
import secrets
import time

from fastapi import HTTPException, Request

# {token: {"doctor_id": int, "username": str, "full_name": str, "expires": float}}
active_tokens: dict[str, dict] = {}

TOKEN_TTL = 86_400  # 24 hours


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def get_current_doctor(request: Request) -> dict:
    """Extract and validate auth token from cookie or Authorization header."""
    token = (
        request.cookies.get("auth_token")
        or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    )
    if not token or token not in active_tokens:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = active_tokens[token]
    if time.time() > session["expires"]:
        del active_tokens[token]
        raise HTTPException(status_code=401, detail="Session expired")
    return session

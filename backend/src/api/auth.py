"""Authentication API routes for TranSafe."""

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from src.db.supabase import get_supabase

router = APIRouter(tags=["auth"])

# ── Schemas ──────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Login request with bank account number and PIN."""
    account_number: str
    pin: str


class LoginResponse(BaseModel):
    """Successful login response with JWT token and user profile."""
    token: str
    token_type: str = "Bearer"
    expires_at: str
    user: dict[str, Any]
    account: dict[str, Any]


class TokenPayload(BaseModel):
    """JWT token payload structure."""
    user_id: str
    account_number: str
    display_name: str
    exp: float
    iat: float


# ── Helpers ──────────────────────────────────────────────────────

def _get_jwt_config() -> tuple[str, str, int]:
    """Return (secret, algorithm, expiry_hours) from environment."""
    secret = os.getenv("JWT_SECRET", "transafe-jwt-secret-2026-hackathon")
    algorithm = os.getenv("JWT_ALGORITHM", "HS256")
    expiry_hours = int(os.getenv("JWT_EXPIRY_HOURS", "24"))
    return secret, algorithm, expiry_hours


def hash_pin(pin: str) -> str:
    """Hash a PIN string using bcrypt."""
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_pin(pin: str, pin_hash: str) -> bool:
    """Verify a PIN against its bcrypt hash."""
    return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))


def create_access_token(user_id: str, account_number: str, display_name: str) -> tuple[str, str]:
    """Create a signed JWT access token.

    Returns:
        Tuple of (token_string, expiry_iso_string).
    """
    secret, algorithm, expiry_hours = _get_jwt_config()
    now = datetime.now(UTC)
    expires = now + timedelta(hours=expiry_hours)

    payload = {
        "user_id": user_id,
        "account_number": account_number,
        "display_name": display_name,
        "iat": now.timestamp(),
        "exp": expires.timestamp(),
    }

    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, expires.isoformat()


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Raises:
        HTTPException 401: If token is expired or invalid.
    """
    secret, algorithm, _ = _get_jwt_config()
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "TOKEN_EXPIRED", "message": "Session expired. Please sign in again."},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Invalid authentication token."},
        )


# ── Routes ───────────────────────────────────────────────────────

@router.post("/auth/login")
async def login(body: LoginRequest) -> dict[str, Any]:
    """Authenticate user by bank account number and PIN.

    Looks up the account in the database, verifies the PIN hash,
    checks account status, and returns a JWT session token.
    """
    client = get_supabase()

    # 1. Look up account by account_number, join with users table
    account_resp = (
        client.table("accounts")
        .select("*, users(id, display_name, risk_profile)")
        .eq("account_number", body.account_number)
        .execute()
    )

    if not account_resp.data or len(account_resp.data) == 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "ACCOUNT_NOT_FOUND",
                "message": "Invalid account number. Please check and try again.",
            },
        )

    account = account_resp.data[0]
    user_data = account.get("users", {})

    # 2. Check account status
    if account.get("status") == "frozen":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCOUNT_FROZEN",
                "message": "This account has been frozen for security. Contact your bank.",
            },
        )

    if account.get("status") == "closed":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ACCOUNT_CLOSED",
                "message": "This account has been closed.",
            },
        )

    # 3. Verify PIN
    stored_hash = account.get("pin_hash")
    if not stored_hash:
        # Account has no PIN set — for demo, allow login if PIN matches default
        # This handles the transition period where accounts don't yet have PINs
        if body.pin != "123456":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_PIN", "message": "Invalid PIN. Please try again."},
            )
    else:
        if not verify_pin(body.pin, stored_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_PIN", "message": "Invalid PIN. Please try again."},
            )

    # 4. Create JWT token
    user_id = str(account.get("user_id", ""))
    display_name = user_data.get("display_name", "User") if isinstance(user_data, dict) else "User"
    token, expires_at = create_access_token(user_id, body.account_number, display_name)

    # 5. Build response
    response_data = {
        "token": token,
        "token_type": "Bearer",
        "expires_at": expires_at,
        "user": {
            "id": user_id,
            "display_name": display_name,
            "risk_profile": user_data.get("risk_profile", "normal") if isinstance(user_data, dict) else "normal",
        },
        "account": {
            "account_number": account.get("account_number"),
            "account_type": account.get("account_type"),
            "balance_myr": float(account.get("balance_myr", 0)),
            "status": account.get("status"),
        },
    }

    return {
        "success": True,
        "data": response_data,
        "error": None,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/auth/me")
async def get_current_user(token: str) -> dict[str, Any]:
    """Get current user profile from JWT token (passed as query param for simplicity)."""
    payload = decode_access_token(token)
    client = get_supabase()

    # Fetch fresh account + user data
    account_resp = (
        client.table("accounts")
        .select("*, users(id, display_name, risk_profile)")
        .eq("account_number", payload["account_number"])
        .execute()
    )

    if not account_resp.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ACCOUNT_NOT_FOUND", "message": "Account no longer exists."},
        )

    account = account_resp.data[0]
    user_data = account.get("users", {})

    return {
        "success": True,
        "data": {
            "user": {
                "id": payload["user_id"],
                "display_name": payload.get("display_name", "User"),
                "risk_profile": user_data.get("risk_profile", "normal") if isinstance(user_data, dict) else "normal",
            },
            "account": {
                "account_number": account.get("account_number"),
                "account_type": account.get("account_type"),
                "balance_myr": float(account.get("balance_myr", 0)),
                "status": account.get("status"),
            },
        },
        "error": None,
        "timestamp": datetime.now(UTC).isoformat(),
    }

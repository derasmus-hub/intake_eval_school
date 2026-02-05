"""
Admin-only endpoints protected by X-Admin-Secret header.
"""

import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr
from app.db.database import get_db
from app.config import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin_secret(request: Request) -> None:
    """Verify the X-Admin-Secret header matches the configured secret."""
    provided = request.headers.get("X-Admin-Secret", "")
    if not provided or provided != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Invalid or missing admin secret")


class CreateInviteRequest(BaseModel):
    email: EmailStr
    expires_days: int = 7
    # For testing only: override with seconds (takes precedence over days if set)
    expires_seconds: int | None = None


class CreateInviteResponse(BaseModel):
    email: str
    token: str
    invite_url: str
    expires_at: str


@router.post("/teacher-invites", response_model=CreateInviteResponse)
async def create_teacher_invite(body: CreateInviteRequest, request: Request):
    """Create a teacher invite token.

    Requires X-Admin-Secret header matching ADMIN_SECRET env var.
    """
    _require_admin_secret(request)

    # Validate expires_days (unless expires_seconds is used for testing)
    if body.expires_seconds is None and (body.expires_days < 1 or body.expires_days > 365):
        raise HTTPException(status_code=400, detail="expires_days must be between 1 and 365")

    db = await get_db()
    try:
        # Check if invite already exists for this email
        cursor = await db.execute(
            "SELECT id, used_at FROM teacher_invites WHERE email = ?",
            (body.email.lower(),),
        )
        existing = await cursor.fetchone()

        if existing:
            if existing["used_at"]:
                raise HTTPException(
                    status_code=409,
                    detail="This email has already been used to register a teacher"
                )
            # Delete old unused invite to allow new one
            await db.execute("DELETE FROM teacher_invites WHERE id = ?", (existing["id"],))
            await db.commit()

        # Generate secure token
        token = secrets.token_urlsafe(32)
        if body.expires_seconds is not None:
            expires_at = datetime.utcnow() + timedelta(seconds=body.expires_seconds)
        else:
            expires_at = datetime.utcnow() + timedelta(days=body.expires_days)

        # Insert invite
        await db.execute(
            """INSERT INTO teacher_invites (email, token, expires_at, created_at)
               VALUES (?, ?, ?, ?)""",
            (body.email.lower(), token, expires_at.isoformat(), datetime.utcnow().isoformat()),
        )
        await db.commit()

        # Build invite URL (relative - frontend will handle)
        invite_url = f"/teacher_register.html?token={token}&email={body.email.lower()}"

        return CreateInviteResponse(
            email=body.email.lower(),
            token=token,
            invite_url=invite_url,
            expires_at=expires_at.isoformat(),
        )
    finally:
        await db.close()


@router.get("/teacher-invites")
async def list_teacher_invites(request: Request):
    """List all teacher invites (for admin review).

    Requires X-Admin-Secret header.
    """
    _require_admin_secret(request)

    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT id, email, token, expires_at, used_at, created_at
               FROM teacher_invites ORDER BY created_at DESC"""
        )
        rows = await cursor.fetchall()

        invites = []
        for row in rows:
            invites.append({
                "id": row["id"],
                "email": row["email"],
                "token": row["token"],
                "expires_at": row["expires_at"],
                "used_at": row["used_at"],
                "created_at": row["created_at"],
                "is_expired": datetime.fromisoformat(row["expires_at"]) < datetime.utcnow(),
                "is_used": row["used_at"] is not None,
            })

        return {"invites": invites}
    finally:
        await db.close()

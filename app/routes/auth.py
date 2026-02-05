import json
import bcrypt
import jwt
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator
from app.db.database import get_db
from app.config import settings
from app.middleware.rate_limit import auth_limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

JWT_SECRET = settings.jwt_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72

# Password policy
MIN_PASSWORD_LENGTH = 8


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request (handles proxies)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(request: Request) -> None:
    """Check rate limit and raise 429 if exceeded."""
    ip = _get_client_ip(request)
    if not auth_limiter.is_allowed(ip):
        retry_after = auth_limiter.get_retry_after(ip)
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)} if retry_after else {},
        )


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    age: int | None = None
    role: str = "student"  # "student" or "teacher"

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_token(student_id: int, email: str, role: str = "student") -> str:
    payload = {
        "sub": str(student_id),
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(request: Request) -> dict:
    """Extract and validate the current user from the JWT token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")

    payload = decode_token(token)
    student_id = int(payload["sub"])

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, name, email, current_level, role FROM students WHERE id = ?",
            (student_id,),
        )
        user = await cursor.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "current_level": user["current_level"],
            "role": user["role"] or "student",
        }
    finally:
        await db.close()


# ── Convenience helpers for route-level auth ────────────────────────

async def require_user(request: Request) -> dict:
    """Alias for get_current_user — returns the authenticated user or raises 401."""
    return await get_current_user(request)


def require_role(*allowed_roles: str):
    """Return a dependency that checks the user has one of the allowed roles.

    Usage in a route:
        user = await require_role("teacher")(request)
    """
    async def _check(request: Request) -> dict:
        user = await get_current_user(request)
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {', '.join(allowed_roles)}",
            )
        return user
    return _check


@router.post("/register")
async def register(body: RegisterRequest, request: Request):
    """Public registration endpoint - STUDENTS ONLY.

    Any role field in the request body is ignored; role is always 'student'.
    Teachers must register via /api/auth/teacher/register with an invite token.
    """
    _check_rate_limit(request)
    db = await get_db()
    try:
        # Check email not already taken
        cursor = await db.execute("SELECT id FROM students WHERE email = ?", (body.email,))
        if await cursor.fetchone():
            raise HTTPException(status_code=409, detail="Email already registered")

        pw_hash = hash_password(body.password)

        # Force role to student - ignore any role field in request
        role = "student"

        cursor = await db.execute(
            """INSERT INTO students (name, email, password_hash, age, filler, role)
               VALUES (?, ?, ?, ?, 'student', ?)""",
            (body.name, body.email, pw_hash, body.age, role),
        )
        await db.commit()
        student_id = cursor.lastrowid

        token = create_token(student_id, body.email, role)

        return {
            "token": token,
            "student_id": student_id,
            "name": body.name,
            "email": body.email,
            "role": role,
        }
    finally:
        await db.close()


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    _check_rate_limit(request)
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, name, email, password_hash, current_level, role FROM students WHERE email = ?",
            (body.email,),
        )
        user = await cursor.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if not user["password_hash"]:
            raise HTTPException(status_code=401, detail="Account has no password. Please register or contact admin.")

        if not verify_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        role = user["role"] or "student"
        token = create_token(user["id"], user["email"], role)

        return {
            "token": token,
            "student_id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "current_level": user["current_level"],
            "role": role,
        }
    finally:
        await db.close()


@router.get("/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    return user


# ── Teacher Registration via Invite ─────────────────────────────────

class TeacherRegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    invite_token: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
        return v


@router.post("/teacher/register")
async def teacher_register(body: TeacherRegisterRequest, request: Request):
    """Register as a teacher using an invite token.

    The invite token must be valid (not expired, not used) and the email
    must match the invited email (case-insensitive).
    """
    _check_rate_limit(request)
    db = await get_db()
    try:
        # Lookup invite by token
        cursor = await db.execute(
            "SELECT id, email, expires_at, used_at FROM teacher_invites WHERE token = ?",
            (body.invite_token,),
        )
        invite = await cursor.fetchone()

        if not invite:
            raise HTTPException(status_code=400, detail="Invalid invite token")

        # Check if already used
        if invite["used_at"]:
            raise HTTPException(status_code=400, detail="Invite token has already been used")

        # Check expiry
        expires_at = datetime.fromisoformat(invite["expires_at"].replace("Z", "+00:00"))
        if datetime.now(expires_at.tzinfo if expires_at.tzinfo else None) > expires_at:
            raise HTTPException(status_code=400, detail="Invite token has expired")

        # Verify email matches (case-insensitive)
        if body.email.lower() != invite["email"].lower():
            raise HTTPException(
                status_code=400,
                detail="Email does not match the invited email address"
            )

        # Check email not already registered
        cursor = await db.execute("SELECT id FROM students WHERE email = ?", (body.email.lower(),))
        if await cursor.fetchone():
            raise HTTPException(status_code=409, detail="Email already registered")

        pw_hash = hash_password(body.password)

        # Create teacher account
        cursor = await db.execute(
            """INSERT INTO students (name, email, password_hash, filler, role)
               VALUES (?, ?, ?, 'teacher', 'teacher')""",
            (body.name, body.email.lower(), pw_hash),
        )
        await db.commit()
        teacher_id = cursor.lastrowid

        # Mark invite as used
        await db.execute(
            "UPDATE teacher_invites SET used_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), invite["id"]),
        )
        await db.commit()

        token = create_token(teacher_id, body.email.lower(), "teacher")

        return {
            "token": token,
            "student_id": teacher_id,
            "name": body.name,
            "email": body.email.lower(),
            "role": "teacher",
        }
    finally:
        await db.close()

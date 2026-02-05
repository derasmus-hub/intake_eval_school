import json
import bcrypt
import jwt
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.db.database import get_db
from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

JWT_SECRET = settings.jwt_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    age: int | None = None
    role: str = "student"  # "student" or "teacher"


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
async def register(body: RegisterRequest):
    db = await get_db()
    try:
        # Check email not already taken
        cursor = await db.execute("SELECT id FROM students WHERE email = ?", (body.email,))
        if await cursor.fetchone():
            raise HTTPException(status_code=409, detail="Email already registered")

        pw_hash = hash_password(body.password)

        # Validate role
        role = body.role if body.role in ("student", "teacher") else "student"

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
async def login(body: LoginRequest):
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

"""Organization management endpoints for multi-tenancy."""

import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from app.db.database import get_db
from app.routes.auth import get_current_user

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


# -- Request / response models -----------------------------------------------

class CreateOrgRequest(BaseModel):
    name: str
    slug: str | None = None
    plan: str = "free"


class InviteToOrgRequest(BaseModel):
    email: EmailStr
    role: str = "student"  # "student" or "teacher"


class UpdateOrgRequest(BaseModel):
    name: str | None = None
    plan: str | None = None
    settings: dict | None = None


# -- Helpers ------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Generate a URL-safe slug from an org name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "org"


async def _get_user_org_id(user: dict, db) -> int | None:
    """Get the org_id for a user."""
    cursor = await db.execute(
        "SELECT org_id FROM users WHERE id = ?", (user["id"],)
    )
    row = await cursor.fetchone()
    return row["org_id"] if row else None


async def _require_org_owner(user: dict, org_id: int, db) -> dict:
    """Verify the user is the org owner or an admin."""
    cursor = await db.execute(
        "SELECT * FROM organizations WHERE id = ?", (org_id,)
    )
    org = await cursor.fetchone()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if user["role"] != "admin" and org["owner_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Only the organization owner can perform this action")

    return org


# -- Endpoints ----------------------------------------------------------------

@router.post("")
async def create_organization(body: CreateOrgRequest, request: Request, db=Depends(get_db)):
    """Create a new organization. The creating user becomes the owner."""
    user = await get_current_user(request, db)

    if user["role"] not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Only teachers or admins can create organizations")

    if not body.name or len(body.name.strip()) < 2:
        raise HTTPException(status_code=422, detail="Organization name must be at least 2 characters")

    slug = body.slug or _slugify(body.name)

    # Check slug uniqueness
    cursor = await db.execute(
        "SELECT id FROM organizations WHERE slug = ?", (slug,)
    )
    if await cursor.fetchone():
        raise HTTPException(status_code=409, detail=f"Organization slug '{slug}' is already taken")

    valid_plans = ("free", "basic", "premium", "enterprise")
    if body.plan not in valid_plans:
        raise HTTPException(status_code=422, detail=f"Plan must be one of: {', '.join(valid_plans)}")

    cursor = await db.execute(
        """INSERT INTO organizations (name, slug, plan, owner_id, settings)
           VALUES (?, ?, ?, ?, '{}')""",
        (body.name.strip(), slug, body.plan, user["id"]),
    )
    await db.commit()
    org_id = cursor.lastrowid

    # Assign the creator to the new org
    await db.execute(
        "UPDATE users SET org_id = ? WHERE id = ?",
        (org_id, user["id"]),
    )
    await db.commit()

    return {
        "id": org_id,
        "name": body.name.strip(),
        "slug": slug,
        "plan": body.plan,
        "owner_id": user["id"],
    }


@router.get("/{org_id}")
async def get_organization(org_id: int, request: Request, db=Depends(get_db)):
    """Get organization details. Must be a member or admin."""
    user = await get_current_user(request, db)

    cursor = await db.execute(
        "SELECT * FROM organizations WHERE id = ?", (org_id,)
    )
    org = await cursor.fetchone()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Check membership: user must belong to this org or be admin
    user_org_id = await _get_user_org_id(user, db)
    if user["role"] != "admin" and user_org_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get member count
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM users WHERE org_id = ?", (org_id,)
    )
    count_row = await cursor.fetchone()
    member_count = count_row["cnt"] if count_row else 0

    # Get member summary by role
    cursor = await db.execute(
        """SELECT role, COUNT(*) as cnt FROM users
           WHERE org_id = ? GROUP BY role""",
        (org_id,),
    )
    role_counts = {row["role"]: row["cnt"] for row in await cursor.fetchall()}

    settings = {}
    if org["settings"]:
        try:
            settings = json.loads(org["settings"])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "id": org["id"],
        "name": org["name"],
        "slug": org["slug"],
        "plan": org["plan"],
        "owner_id": org["owner_id"],
        "settings": settings,
        "created_at": org["created_at"],
        "member_count": member_count,
        "role_counts": role_counts,
    }


@router.put("/{org_id}")
async def update_organization(org_id: int, body: UpdateOrgRequest, request: Request, db=Depends(get_db)):
    """Update organization details. Owner or admin only."""
    user = await get_current_user(request, db)
    await _require_org_owner(user, org_id, db)

    updates = []
    params = []

    if body.name is not None:
        updates.append("name = ?")
        params.append(body.name.strip())

    if body.plan is not None:
        valid_plans = ("free", "basic", "premium", "enterprise")
        if body.plan not in valid_plans:
            raise HTTPException(status_code=422, detail=f"Plan must be one of: {', '.join(valid_plans)}")
        updates.append("plan = ?")
        params.append(body.plan)

    if body.settings is not None:
        updates.append("settings = ?")
        params.append(json.dumps(body.settings))

    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    params.append(org_id)
    await db.execute(
        f"UPDATE organizations SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    await db.commit()

    return {"status": "updated", "org_id": org_id}


@router.get("/{org_id}/members")
async def list_org_members(org_id: int, request: Request, db=Depends(get_db)):
    """List all members of an organization."""
    user = await get_current_user(request, db)

    # Check membership
    user_org_id = await _get_user_org_id(user, db)
    if user["role"] != "admin" and user_org_id != org_id:
        raise HTTPException(status_code=403, detail="Access denied")

    cursor = await db.execute(
        """SELECT id, name, email, role, current_level, created_at
           FROM users WHERE org_id = ?
           ORDER BY role, name""",
        (org_id,),
    )
    members = [dict(row) for row in await cursor.fetchall()]

    return {"org_id": org_id, "members": members}


@router.post("/{org_id}/invite")
async def invite_to_organization(
    org_id: int, body: InviteToOrgRequest, request: Request, db=Depends(get_db)
):
    """Invite a user to an organization by email.

    If the user already exists, they are assigned to the org.
    If not, a pending invite is stored for when they register.
    """
    user = await get_current_user(request, db)
    await _require_org_owner(user, org_id, db)

    if body.role not in ("student", "teacher"):
        raise HTTPException(status_code=422, detail="Role must be 'student' or 'teacher'")

    # Check if user already exists
    cursor = await db.execute(
        "SELECT id, org_id FROM users WHERE email = ?",
        (body.email.lower(),),
    )
    existing_user = await cursor.fetchone()

    if existing_user:
        if existing_user["org_id"] == org_id:
            raise HTTPException(status_code=409, detail="User is already a member of this organization")

        # Move user to this org
        await db.execute(
            "UPDATE users SET org_id = ? WHERE id = ?",
            (org_id, existing_user["id"]),
        )
        await db.commit()
        return {
            "status": "added",
            "user_id": existing_user["id"],
            "email": body.email.lower(),
            "org_id": org_id,
        }
    else:
        # Store a pending org invite for future registration
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

        # Check if invite already exists
        cursor = await db.execute(
            "SELECT id FROM org_invites WHERE email = ? AND org_id = ?",
            (body.email.lower(), org_id),
        )
        if await cursor.fetchone():
            await db.execute(
                "DELETE FROM org_invites WHERE email = ? AND org_id = ?",
                (body.email.lower(), org_id),
            )

        await db.execute(
            """INSERT INTO org_invites (org_id, email, role, token, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (org_id, body.email.lower(), body.role, token, expires_at),
        )
        await db.commit()

        return {
            "status": "invited",
            "email": body.email.lower(),
            "org_id": org_id,
            "token": token,
            "expires_at": expires_at,
        }


@router.delete("/{org_id}/members/{user_id}")
async def remove_org_member(org_id: int, user_id: int, request: Request, db=Depends(get_db)):
    """Remove a user from an organization. Owner or admin only."""
    user = await get_current_user(request, db)
    org = await _require_org_owner(user, org_id, db)

    if org["owner_id"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot remove the organization owner")

    cursor = await db.execute(
        "SELECT id, org_id FROM users WHERE id = ?", (user_id,)
    )
    target = await cursor.fetchone()
    if not target or target["org_id"] != org_id:
        raise HTTPException(status_code=404, detail="User not found in this organization")

    await db.execute(
        "UPDATE users SET org_id = NULL WHERE id = ?", (user_id,)
    )
    await db.commit()

    return {"status": "removed", "user_id": user_id, "org_id": org_id}

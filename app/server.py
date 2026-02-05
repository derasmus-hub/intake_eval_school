import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pathlib import Path
from contextlib import asynccontextmanager
from app.db.database import init_db
from app.middleware.auth import AuthMiddleware
from app.config import settings

# CORS configuration based on environment
# ENV=prod → require explicit CORS_ORIGINS or use restrictive default
# ENV=dev (default) → permissive localhost origins
_env = settings.env.lower()
_cors_origins_setting = settings.cors_origins

if _env == "prod":
    # Production: only allow explicit origins
    if _cors_origins_setting:
        _allowed_origins = [o.strip() for o in _cors_origins_setting.split(",") if o.strip()]
    else:
        # No origins configured in prod = no CORS (same-origin only)
        _allowed_origins = []
else:
    # Development: permissive defaults
    if _cors_origins_setting:
        _allowed_origins = [o.strip() for o in _cors_origins_setting.split(",") if o.strip()]
    else:
        _allowed_origins = [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Intake Eval School", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(AuthMiddleware)

# Import and register routes
from app.routes.auth import router as auth_router
from app.routes.intake import router as intake_router
from app.routes.diagnostic import router as diagnostic_router
from app.routes.lessons import router as lessons_router
from app.routes.progress import router as progress_router
from app.routes.assessment import router as assessment_router
from app.routes.learning_path import router as learning_path_router
from app.routes.analytics import router as analytics_router
from app.routes.vocabulary import router as vocabulary_router
from app.routes.conversation import router as conversation_router
from app.routes.recall import router as recall_router
from app.routes.challenges import router as challenges_router
from app.routes.leaderboard import router as leaderboard_router
from app.routes.games import router as games_router
from app.routes.gamification import router as gamification_router
from app.routes.scheduling import router as scheduling_router

app.include_router(auth_router)
app.include_router(intake_router)
app.include_router(diagnostic_router)
app.include_router(lessons_router)
app.include_router(progress_router)
app.include_router(assessment_router)
app.include_router(learning_path_router)
app.include_router(analytics_router)
app.include_router(vocabulary_router)
app.include_router(conversation_router)
app.include_router(recall_router)
app.include_router(challenges_router)
app.include_router(leaderboard_router)
app.include_router(games_router)
app.include_router(gamification_router)
app.include_router(scheduling_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# Serve frontend — single static mount (must be last to avoid shadowing /api routes)
frontend_path = Path(__file__).parent.parent / "frontend"


@app.get("/")
async def serve_root():
    return FileResponse(frontend_path / "login.html")


@app.get("/dashboard.html")
async def serve_teacher_dashboard(request: Request):
    """Teacher dashboard — server-side role check before serving HTML."""
    from app.routes.auth import get_current_user
    try:
        user = await get_current_user(request)
        if user.get("role") != "teacher":
            return RedirectResponse(url="/student_dashboard.html", status_code=303)
        return FileResponse(frontend_path / "dashboard.html")
    except Exception:
        return RedirectResponse(url="/login.html", status_code=303)


@app.get("/student_dashboard.html")
async def serve_student_dashboard(request: Request):
    """Student dashboard — server-side role check before serving HTML."""
    from app.routes.auth import get_current_user
    try:
        user = await get_current_user(request)
        if user.get("role") != "student":
            return RedirectResponse(url="/dashboard.html", status_code=303)
        return FileResponse(frontend_path / "student_dashboard.html")
    except Exception:
        return RedirectResponse(url="/login.html", status_code=303)


app.mount("/", StaticFiles(directory=frontend_path), name="frontend")

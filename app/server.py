import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pathlib import Path
from contextlib import asynccontextmanager
from app.db.database import init_db, close_db
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
    await close_db()


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
from app.routes.admin import router as admin_router
from app.routes.availability import router as availability_router
from app.routes.quiz import router as quiz_router
from app.routes.learning_plan import router as learning_plan_router
from app.routes.dashboard import router as dashboard_router
from app.routes.writing import router as writing_router
from app.routes.organizations import router as organizations_router
from app.routes.intelligence import router as intelligence_router

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
app.include_router(admin_router)
app.include_router(availability_router)
app.include_router(quiz_router)
app.include_router(learning_plan_router)
app.include_router(dashboard_router)
app.include_router(writing_router)
app.include_router(organizations_router)
app.include_router(intelligence_router)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "served_by": "docker" if settings.in_docker == "1" else "host",
    }


# Serve frontend — single static mount (must be last to avoid shadowing /api routes)
frontend_path = Path(__file__).parent.parent / "frontend"


@app.get("/")
async def serve_root():
    return FileResponse(frontend_path / "login.html")


# Dashboard pages are served as static files.
# Role-based access is enforced client-side (APP.guardRole in each HTML)
# and API endpoints require Bearer token authentication.
# Server-side guards were removed because browser navigation doesn't send
# Authorization headers (tokens are in localStorage, not cookies).

app.mount("/", StaticFiles(directory=frontend_path), name="frontend")

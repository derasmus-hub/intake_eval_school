from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from contextlib import asynccontextmanager
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Intake Eval School", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and register routes
from app.routes.intake import router as intake_router
from app.routes.diagnostic import router as diagnostic_router
from app.routes.lessons import router as lessons_router
from app.routes.progress import router as progress_router

app.include_router(intake_router)
app.include_router(diagnostic_router)
app.include_router(lessons_router)
app.include_router(progress_router)

# Serve frontend static files
frontend_path = Path(__file__).parent.parent / "frontend"
app.mount("/css", StaticFiles(directory=frontend_path / "css"), name="css")
app.mount("/js", StaticFiles(directory=frontend_path / "js"), name="js")


@app.get("/")
async def serve_index():
    return FileResponse(frontend_path / "index.html")


@app.get("/dashboard")
async def serve_dashboard():
    return FileResponse(frontend_path / "dashboard.html")

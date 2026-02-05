from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Paths that don't require authentication
PUBLIC_PATHS = {
    "/api/auth/register",
    "/api/auth/login",
    "/",
    "/index.html",
    "/dashboard",
    "/dashboard.html",
    "/student_dashboard",
    "/student_dashboard.html",
    "/assessment",
    "/assessment.html",
    "/vocab",
    "/vocab.html",
    "/conversation",
    "/conversation.html",
    "/recall",
    "/recall.html",
    "/session",
    "/session.html",
    "/login",
    "/login.html",
    "/register",
    "/register.html",
    "/leaderboard",
    "/leaderboard.html",
    "/games",
    "/games.html",
    "/profile",
    "/profile.html",
}

# Path prefixes that are always public
PUBLIC_PREFIXES = (
    "/css/",
    "/js/",
    "/docs",
    "/openapi",
    "/redoc",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public paths
        if path in PUBLIC_PATHS:
            return await call_next(request)

        # Allow static file prefixes
        if path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        # Allow non-API paths (HTML pages)
        if not path.startswith("/api/"):
            return await call_next(request)

        # For API paths, check for auth token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            # Token present — let the route handler validate it
            return await call_next(request)

        # No token — allow the request through but routes can still reject
        # This keeps backwards compatibility for now — existing routes
        # work without auth, new ones can check via get_current_user()
        return await call_next(request)

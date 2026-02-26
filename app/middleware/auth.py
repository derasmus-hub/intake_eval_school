from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# API paths that don't require authentication
PUBLIC_API_PATHS = {
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/teacher/register",
}

# Non-API prefixes that are always public (static files, docs)
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

        # Allow static file prefixes (css, js, docs)
        if path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        # Allow non-API paths (HTML pages, health check, root)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Allow public API endpoints (login, register)
        if path in PUBLIC_API_PATHS:
            return await call_next(request)

        # All other API paths require a Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            # Token present — let the route handler validate it
            return await call_next(request)

        # No token — reject the request
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

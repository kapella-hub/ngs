"""NGS (NoiseGate Service) - Main FastAPI Application."""
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from app.config import get_settings
from app.database import init_db, close_db
from app.logging_config import setup_logging
from app.routers import incidents, maintenance, admin, auth, quarantine, metrics

# Setup structured logging
setup_logging()
logger = structlog.get_logger()

# Prometheus metrics
REQUEST_COUNT = Counter(
    "ngs_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "ngs_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"]
)


async def seed_admin_user():
    """Ensure default admin user exists."""
    from passlib.context import CryptContext
    from app.database import get_db_pool

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        # Check if admin exists
        existing = await conn.fetchrow(
            "SELECT id FROM users WHERE username = 'admin'"
        )

        if not existing:
            # Create admin user with password "admin123"
            password_hash = pwd_context.hash("admin123")
            await conn.execute(
                """
                INSERT INTO users (username, email, password_hash, display_name, role)
                VALUES ('admin', 'admin@example.com', $1, 'NGS Admin', 'admin')
                ON CONFLICT (username) DO NOTHING
                """,
                password_hash
            )
            logger.info("Created default admin user (admin/admin123)")
        else:
            # Update password hash and fix email if needed
            password_hash = pwd_context.hash("admin123")
            await conn.execute(
                "UPDATE users SET password_hash = $1, email = 'admin@example.com' WHERE username = 'admin'",
                password_hash
            )
            logger.info("Admin user exists, password reset to default")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan handler."""
    logger.info("Starting NGS API server")
    await init_db()
    await seed_admin_user()
    yield
    logger.info("Shutting down NGS API server")
    await close_db()


# Create FastAPI application
app = FastAPI(
    title="NGS - NoiseGate Service",
    description="Enterprise-grade alert noise reduction and incident correlation platform",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Middleware to track request metrics."""
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    # Extract endpoint pattern (simplified)
    endpoint = request.url.path

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        status=response.status_code
    ).inc()

    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=endpoint
    ).observe(duration)

    return response


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Middleware to log requests."""
    request_id = request.headers.get("X-Request-ID", "")

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    logger.info("Request started")

    try:
        response = await call_next(request)
        logger.info("Request completed", status_code=response.status_code)
        return response
    except Exception as e:
        logger.exception("Request failed", error=str(e))
        raise


# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(incidents.router, prefix="/api/incidents", tags=["Incidents"])
app.include_router(maintenance.router, prefix="/api/maintenance", tags=["Maintenance"])
app.include_router(quarantine.router, prefix="/api/quarantine", tags=["Quarantine"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])


@app.get("/healthz", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "ngs-api", "version": "0.1.0"}


@app.get("/readyz", tags=["Health"])
async def readiness_check():
    """Readiness check endpoint."""
    from app.database import get_db_pool
    pool = await get_db_pool()
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "disconnected", "error": str(e)}
        )


@app.get("/metrics", tags=["Metrics"])
async def prometheus_metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.exception("Unhandled exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.audit import configure_logging
from app.audit_middleware import AuditMiddleware
from app.auth.routes import admin, router, student
from app.config import Settings, require_service_credentials
from app.health import readiness
from app.model_gateway.registry import configured_models
from app.uploads.routes import admin_uploads, student_uploads

settings = Settings()
require_service_credentials(settings)
configured_models()
configure_logging()

app = FastAPI(title="TutorBot API", version="0.1.0")


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.get("/health/ready")
def ready() -> JSONResponse:
    report = readiness(Settings())
    return JSONResponse(
        status_code=200 if report.status == "ok" else 503, content=report.model_dump()
    )


app.add_middleware(AuditMiddleware)
app.include_router(router)
app.include_router(admin if settings.service_mode == "admin" else student, prefix="/v1")

app.include_router(admin_uploads if settings.service_mode == "admin" else student_uploads)

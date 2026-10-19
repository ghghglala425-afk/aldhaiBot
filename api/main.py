# -*- coding: utf-8 -*-
"""نقطة إقلاع FastAPI — API المنصّة + فحص الصحة + تهيئة قاعدة البيانات."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import admin, auth, catalog, generate, learn, miniapp, paths, proxy, targets
from core.config import settings
from core.db import close_db, init_db
from core.logging import get_logger, setup_logging

setup_logging()
log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    errors = settings.check_required()
    if errors:
        for e in errors:
            log.error("إعداد ناقص: %s", e)
    for w in settings.check_warnings():
        log.warning("تحذير: %s", w)
    if not errors:
        log.info("كل المفاتيح المطلوبة سليمة.")
    await init_db()
    # زرع البيانات الأساسية إن كانت القاعدة فارغة (قاعدة Railway الجديدة)
    try:
        from pipeline.seed import ensure_seeded

        if await ensure_seeded():
            log.info("تمت زرع البيانات الأساسية.")
    except Exception as e:  # noqa: BLE001
        log.warning("تعذّر زرع البيانات الأساسية: %s", e)
    yield
    await close_db()


app = FastAPI(
    title="Cyber Academy API",
    version="0.1.0",
    description="منصّة تعلّم البرمجة والأمن السيبراني — بوت تلجرام + تطبيق",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_prod else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(admin.router)
app.include_router(generate.router)
app.include_router(learn.router)
app.include_router(targets.router)
app.include_router(proxy.router)
app.include_router(paths.router)
app.include_router(miniapp.router)


@app.get("/health", tags=["system"])
async def health():
    from core.db import _DATABASE_URL

    if _DATABASE_URL.startswith("sqlite"):
        db_kind = "sqlite"
        db_host = _DATABASE_URL.split(":///", 1)[-1] or "memory"
    else:
        db_kind = "postgresql"
        # نُخفي كلمة المرور في التقرير
        db_host = ""
        try:
            db_host = _DATABASE_URL.split("@", 1)[-1].split(":", 1)[0]
        except Exception:  # noqa: BLE001
            pass
    return {
        "status": "ok",
        "env": settings.ENV,
        "bot_configured": bool(settings.BOT_TOKEN),
        "ai_configured": settings.ai_configured,
        "database": db_kind,
        "database_host": db_host,
    }


@app.get("/", tags=["system"])
async def root():
    return {"name": "Cyber Academy", "docs": "/docs", "health": "/health"}


if __name__ == "__main__":
    import os

    import uvicorn

    # Railway يحقن PORT — لازم نسمع عليه وإلا فشل فحص الصحة
    _port = int(os.environ.get("PORT") or os.environ.get("API_PORT") or 8000)
    uvicorn.run("api.main:app", host="0.0.0.0", port=_port)

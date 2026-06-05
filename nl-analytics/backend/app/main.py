from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .api import ask, data_quality, schema, sessions, upload
from .config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="NL Analytics", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(upload.router)
app.include_router(schema.router)
app.include_router(data_quality.router)
app.include_router(ask.router)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "ollama_host": settings.ollama_host,
        "sql_model": settings.ollama_sql_model,
        "narrate_model": settings.ollama_narrate_model,
    }

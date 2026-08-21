from pathlib import Path

from fastapi import FastAPI
from app.api.chat import router as chat_router
from app.api.ingest import router as ingest_router
from app.api.upload import router as upload_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Insurance Claims RAG API"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Allow all origins
    allow_credentials=False,  # Must be False when using "*"
    allow_methods=["*"],      # Allow all HTTP methods
    allow_headers=["*"],      # Allow all headers
)

app.include_router(chat_router)
app.include_router(ingest_router)
app.include_router(upload_router)

@app.get("/")
def home():
    return {
        "message": "Welcome to the Insurance Claims RAG API"
    }

@app.get("/health")
def health():
    return {
        "status": "healthy"
    }

@app.get("/ui", response_class=HTMLResponse)
def ui():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

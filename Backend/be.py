"""Compatibility entrypoint: `python be.py` starts the refactored API."""

import os

import uvicorn

from app.main import app


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        reload=os.getenv("RELOAD", "true").lower() == "true",
    )


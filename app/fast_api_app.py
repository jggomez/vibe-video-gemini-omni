"""Modular FastAPI Application Factory for app package.

Allows the app directory to be served independently by ADK runners or Agent Engine.
"""

import os

from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app


def create_app() -> FastAPI:
    """Create and configure the FastAPI application for the app package."""
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fastapi_app = get_fast_api_app(
        agents_dir=root_dir,
        web=True,
    )
    fastapi_app.title = "Vibe Video Studio App Module"
    return fastapi_app


app: FastAPI = create_app()

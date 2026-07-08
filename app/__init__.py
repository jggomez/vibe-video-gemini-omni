"""ADK App entry point — exports 'app' for agents-cli and fast_api_app."""

from app.agent import app

__all__ = ["app"]

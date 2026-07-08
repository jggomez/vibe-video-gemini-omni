"""Project-wide constants — eliminate magic strings across modules."""

import contextvars

OMNI_MODEL: str = "gemini-omni-flash-preview"
DEFAULT_ASPECT_RATIO: str = "16:9"
MAX_TURNS_BEFORE_DRIFT: int = 4
DEFAULT_USER_ID: str = "anonymous"
VIDEO_MIME_TYPE: str = "video/mp4"
DEFAULT_PORT: int = 8000
DEFAULT_HOST: str = "0.0.0.0"

user_api_key_var = contextvars.ContextVar("user_api_key", default=None)
user_api_client_var = contextvars.ContextVar("user_api_client", default=None)
user_live_client_var = contextvars.ContextVar("user_live_client", default=None)

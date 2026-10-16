"""Process entry point for the API container."""

import uvicorn

from app.core.config import get_settings
from app.core.logging import configure_logging


def main() -> None:
    """Serve the API on the internal network; TLS terminates at the reverse proxy."""
    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104  # nosec B104
        port=8000,
        log_config=None,
        access_log=False,
        server_header=False,
        date_header=False,
        proxy_headers=False,
        timeout_keep_alive=30,
        timeout_graceful_shutdown=20,
    )


if __name__ == "__main__":
    main()

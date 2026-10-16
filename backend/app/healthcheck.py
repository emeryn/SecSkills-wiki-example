"""Container healthcheck: the runtime image has no shell or curl."""

import sys
import urllib.request

HEALTH_URL = "http://127.0.0.1:8000/api/v1/health"


def main() -> int:
    """Exit 0 when the API reports healthy."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as response:  # nosec B310
            return 0 if response.status == 200 else 1  # noqa: PLR2004
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())

import os
import sys

import pytest

from app.core.sandbox import install_exec_filter

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="seccomp is Linux-only")

EXIT_BLOCKED = 0
EXIT_ALLOWED = 1
EXIT_SETUP_FAILED = 2


def test_exec_is_denied_after_filter_installed() -> None:
    # The filter is irreversible, so it is installed in a forked child, never in pytest itself.
    pid = os.fork()
    if pid == 0:
        try:
            install_exec_filter()
        except Exception:
            os._exit(EXIT_SETUP_FAILED)
        try:
            os.execv(sys.executable, [sys.executable, "-c", "pass"])  # noqa: S606
        except PermissionError:
            os._exit(EXIT_BLOCKED)
        os._exit(EXIT_ALLOWED)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == EXIT_BLOCKED


def test_regular_work_still_runs_after_filter() -> None:
    pid = os.fork()
    if pid == 0:
        install_exec_filter()
        total = sum(range(1000))
        with open(os.devnull, "w") as sink:
            sink.write(str(total))
        os._exit(EXIT_BLOCKED)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == EXIT_BLOCKED

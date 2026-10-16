"""In-process seccomp filter denying ``execve``/``execveat``.

Loaded in each worker after startup: a container-level deny would also block the entrypoint.
Applied to every thread of the process (TSYNC) and irreversible for the process lifetime.
"""

import ctypes
import logging
import platform
import sys

logger = logging.getLogger(__name__)

_PR_SET_NO_NEW_PRIVS = 38
_SECCOMP_SET_MODE_FILTER = 1
_SECCOMP_FILTER_FLAG_TSYNC = 1
_SECCOMP_RET_KILL_PROCESS = 0x80000000
_SECCOMP_RET_ERRNO = 0x00050000
_SECCOMP_RET_ALLOW = 0x7FFF0000
_EPERM = 1

_BPF_LD_W_ABS = 0x20
_BPF_JEQ_K = 0x15
_BPF_JGE_K = 0x35
_BPF_RET_K = 0x06
_OFFSET_NR = 0
_OFFSET_ARCH = 4
_X32_SYSCALL_BIT = 0x40000000

# machine -> (AUDIT_ARCH, seccomp syscall number, denied syscall numbers)
_ARCHITECTURES: dict[str, tuple[int, int, tuple[int, ...]]] = {
    "x86_64": (0xC000003E, 317, (59, 322)),
    "aarch64": (0xC00000B7, 277, (221, 281)),
}


class _SockFilter(ctypes.Structure):
    _fields_ = (
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint),
    )


class _SockFprog(ctypes.Structure):
    _fields_ = (("len", ctypes.c_ushort), ("filter", ctypes.POINTER(_SockFilter)))


class SandboxError(RuntimeError):
    """The filter could not be installed."""


def _program(audit_arch: int, denied: tuple[int, ...], deny_x32: bool) -> list[tuple[int, ...]]:
    checks: list[tuple[int, int]] = [(_BPF_JEQ_K, nr) for nr in denied]
    if deny_x32:
        checks.append((_BPF_JGE_K, _X32_SYSCALL_BIT))
    program: list[tuple[int, ...]] = [
        (_BPF_LD_W_ABS, 0, 0, _OFFSET_ARCH),
        (_BPF_JEQ_K, 1, 0, audit_arch),
        (_BPF_RET_K, 0, 0, _SECCOMP_RET_KILL_PROCESS),
        (_BPF_LD_W_ABS, 0, 0, _OFFSET_NR),
    ]
    errno_index = len(program) + len(checks) + 1
    for op, value in checks:
        program.append((op, errno_index - len(program) - 1, 0, value))
    program.append((_BPF_RET_K, 0, 0, _SECCOMP_RET_ALLOW))
    program.append((_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO | _EPERM))
    return program


def install_exec_filter() -> None:
    """Deny process execution for the rest of the process lifetime."""
    if sys.platform != "linux":
        raise SandboxError("seccomp is only available on Linux")
    machine = platform.machine()
    if machine not in _ARCHITECTURES:
        raise SandboxError(f"Unsupported architecture: {machine}")
    audit_arch, seccomp_nr, denied = _ARCHITECTURES[machine]
    program = _program(audit_arch, denied, deny_x32=machine == "x86_64")

    filters = (_SockFilter * len(program))(*(_SockFilter(*ins) for ins in program))
    fprog = _SockFprog(len(program), ctypes.cast(filters, ctypes.POINTER(_SockFilter)))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise SandboxError(f"prctl(NO_NEW_PRIVS) failed: errno {ctypes.get_errno()}")
    result = libc.syscall(
        seccomp_nr, _SECCOMP_SET_MODE_FILTER, _SECCOMP_FILTER_FLAG_TSYNC, ctypes.byref(fprog)
    )
    if result != 0:
        raise SandboxError(f"seccomp() failed: result {result}, errno {ctypes.get_errno()}")
    logger.info("Process execution disabled by seccomp", extra={"arch": machine})

"""Test-only direct syscalls against the exact Rust-generated compiler filter."""

import ctypes
import errno
import os
import struct
import sys


def exact(length):
    result = sys.stdin.buffer.read(length)
    if len(result) != length:
        raise RuntimeError("truncated test policy")
    return result


length = struct.unpack("<I", exact(4))[0]
if length == 0 or length > 8192 or length % 8:
    raise RuntimeError("invalid test policy length")
encoded = exact(length)
if sys.stdin.buffer.read(1):
    raise RuntimeError("trailing test policy")


class Filter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    ]


class Program(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ushort), ("filter", ctypes.POINTER(Filter))]


libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
storage = (Filter * (length // 8))(
    *(Filter(*values) for values in struct.iter_unpack("<HBBI", encoded))
)
program = Program(length // 8, storage)
if libc.prctl(38, 1, 0, 0, 0) != 0:
    raise RuntimeError("no-new-privileges unavailable")
if libc.syscall(317, 1, 0, ctypes.byref(program)) != 0:
    raise RuntimeError("production seccomp policy installation failed")

# Direct mmap(PROT_READ|PROT_EXEC), socket, fork-style clone, fork, and
# execve(NULL,NULL,NULL) must each fail by policy (EPERM), not by argument shape.
# No code is executed from a mapping and no network connection is attempted.
for number, arguments in [
    (9, (0, 4096, 5, 0x22, -1, 0)),
    (41, (2, 1, 0)),
    (56, (17, 0, 0, 0, 0)),
    (57, ()),
    (59, (0, 0, 0)),
]:
    ctypes.set_errno(0)
    result = libc.syscall(number, *arguments)
    if number in (56, 57) and result == 0:
        os._exit(97)
    if result != -1 or ctypes.get_errno() != errno.EPERM:
        os._exit(98)

os.write(1, b"kernel syscall denial passed\n")
os._exit(0)

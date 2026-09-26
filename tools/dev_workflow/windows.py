"""Windows read handles forbid ancestor substitution; private state uses a DACL."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import msvcrt
import os
from pathlib import Path

from .common import require

kernel = ctypes.WinDLL("kernel32", use_last_error=True)
advapi = ctypes.WinDLL("advapi32", use_last_error=True)
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.CloseHandle.restype = wintypes.BOOL
kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
kernel.LocalFree.argtypes = [ctypes.c_void_p]
kernel.LocalFree.restype = ctypes.c_void_p


class AttributeTag(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]


def _handle(path: Path, *, folder: bool):
    name = str(path)
    require(not name.startswith("\\\\"), "network-state-path-unsupported")
    # No FILE_SHARE_DELETE: a path component cannot be replaced while held.
    # Files also omit FILE_SHARE_WRITE for a stable byte read.
    handle = kernel.CreateFileW("\\\\?\\" + name, 0x80 if folder else 0x80000000,
                                3 if folder else 1, None, 3, 0x02200000, None)
    require(handle not in (None, ctypes.c_void_p(-1).value), "windows-protected-open-failed")
    metadata = AttributeTag()
    if (not kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(metadata), ctypes.sizeof(metadata))
            or metadata.attributes & 0x400 or bool(metadata.attributes & 0x10) != folder):
        kernel.CloseHandle(handle)
        require(False, "reparse-or-file-type-rejected")
    return handle


@contextmanager
def anchored_directory(path: Path):
    handles = []
    try:
        current = Path(path.anchor)
        handles.append(_handle(current, folder=True))
        for part in path.parts[1:]:
            current /= part
            handles.append(_handle(current, folder=True))
        yield handles[-1]
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


def open_file(path: Path) -> int:
    handle = _handle(path, folder=False)
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise


def check_private(path: Path) -> None:
    """Accept only the current owner, SYSTEM and Administrators in allow ACEs."""
    advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    descriptor, owner, dacl = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    status = advapi.GetNamedSecurityInfoW(str(path), 1, 5, ctypes.byref(owner), None,
        ctypes.byref(dacl), None, ctypes.byref(descriptor))
    require(status == 0 and dacl.value, "private-windows-dacl-required")
    text = wintypes.LPWSTR()
    try:
        require(advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 5,
                ctypes.byref(text), None), "windows-dacl-inspection-failed")
        sddl = text.value
        import re
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
        def sid_string(sid):
            converted = wintypes.LPWSTR()
            require(advapi.ConvertSidToStringSidW(sid, ctypes.byref(converted)), "windows-token-sid")
            try:
                return converted.value
            finally:
                kernel.LocalFree(converted)
        owner_sid = sid_string(owner)
        # Verify current identity using a process token, not localized whoami text.
        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi.OpenProcessToken.restype = wintypes.BOOL
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        token = wintypes.HANDLE()
        require(advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)), "windows-token-open")
        try:
            advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                  wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
            advapi.GetTokenInformation.restype = wintypes.BOOL
            def token_sid(information_class):
                needed = wintypes.DWORD()
                advapi.GetTokenInformation(token, information_class, None, 0, ctypes.byref(needed))
                require(0 < needed.value <= 65536, "windows-token-size")
                buffer = ctypes.create_string_buffer(needed.value)
                require(advapi.GetTokenInformation(token, information_class, buffer, needed,
                        ctypes.byref(needed)), "windows-token-read")
                return sid_string(ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0])
            user_sid, default_owner = token_sid(1), token_sid(4)
            # Elevated Windows tokens normally create Administrators-owned files.
            # Accept that owner only when it is this token's actual default owner;
            # do not infer ownership from a localized account name or SDDL alias.
            require(owner_sid == user_sid or owner_sid == default_owner == "S-1-5-32-544",
                    "private-state-owner-mismatch")
        finally:
            kernel.CloseHandle(token)
        aces = re.findall(r"\(([^()]+)\)", sddl)
        require(aces, "private-windows-dacl-required")
        for ace in aces:
            fields = ace.split(";")
            require(len(fields) == 6 and fields[0] == "A"
                    and fields[5] in {user_sid, "OW", "SY", "BA"}, "windows-state-acl-too-broad")
    finally:
        if text:
            kernel.LocalFree(text)
        kernel.LocalFree(descriptor)

"""OS-bound host authority resolution shared by runtime and release gates."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import uuid


class HostBoundaryError(RuntimeError):
    pass


def _native_profile_home() -> Path:
    """Resolve the signed-in OS account profile without environment variables."""
    if os.name == "nt":
        import ctypes

        class _Guid(ctypes.Structure):
            _fields_ = (
                ("data1", ctypes.c_ulong),
                ("data2", ctypes.c_ushort),
                ("data3", ctypes.c_ushort),
                ("data4", ctypes.c_ubyte * 8),
            )

        profile = uuid.UUID("5e6c858f-0e22-4760-9afe-ea3317b67173")
        guid = _Guid(
            profile.time_low,
            profile.time_mid,
            profile.time_hi_version,
            (ctypes.c_ubyte * 8)(*profile.bytes[8:]),
        )
        output = ctypes.c_wchar_p()
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        result = shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(output)
        )
        if result != 0 or not output.value:
            raise OSError("native profile is unavailable")
        try:
            return Path(output.value)
        finally:
            ole32.CoTaskMemFree(ctypes.cast(output, ctypes.c_void_p))
    import pwd

    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def is_reparse_point(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        if os.name != "nt":
            return False
        return bool(
            getattr(path.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    except OSError:
        return True


def reject_reparse_ancestors(path: Path, boundary: Path | None = None) -> None:
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise HostBoundaryError("canonical host boundary is invalid")
    stop = boundary.parent if boundary is not None else None
    current = path
    while True:
        if current.exists() and is_reparse_point(current):
            raise HostBoundaryError("canonical host boundary contains a reparse point")
        if current == stop or current.parent == current:
            break
        current = current.parent
    if boundary is not None:
        try:
            path.resolve().relative_to(boundary.resolve())
        except ValueError as error:
            raise HostBoundaryError("canonical host boundary is invalid") from error


def canonical_host_home() -> Path:
    try:
        home = _native_profile_home()
    except (ImportError, KeyError, OSError, ValueError) as error:
        raise HostBoundaryError("canonical host boundary is unavailable") from error
    if not home.is_absolute() or str(home).startswith("\\\\"):
        raise HostBoundaryError("canonical host boundary is unavailable")
    reject_reparse_ancestors(home.absolute())
    return home.resolve()


_WINDOWS_ACL_QUERY = r"""
& {
param([Parameter(Mandatory=$true)][string]$path)
$ErrorActionPreference = 'Stop'
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = if ([System.IO.Directory]::Exists($path)) {
    [System.IO.DirectoryInfo]::new($path).GetAccessControl()
} else {
    [System.IO.FileInfo]::new($path).GetAccessControl()
}
$ownerSid = (New-Object System.Security.Principal.NTAccount($acl.Owner)).Translate(
    [System.Security.Principal.SecurityIdentifier]
).Value
$entries = @($acl.Access | ForEach-Object {
    @{
        sid = $_.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
        type = $_.AccessControlType.ToString()
        inherited = $_.IsInherited
    }
})
@{
    protected = $acl.AreAccessRulesProtected
    owner_sid = $ownerSid
    current_sid = $sid.Value
    access = $entries
} | ConvertTo-Json -Compress -Depth 4
}
""".strip()


def _native_powershell() -> Path:
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if length <= 0 or length >= len(buffer):
        raise HostBoundaryError("owner-private ACL verification is unavailable")
    executable = (
        Path(buffer.value).parent
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not executable.is_file():
        raise HostBoundaryError("owner-private ACL verification is unavailable")
    return executable


def _native_powershell_environment(executable: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PSModulePath"] = str(executable.parent / "Modules")
    return environment


def verify_owner_private(path: Path, *, directory: bool) -> None:
    path = Path(path)
    reject_reparse_ancestors(path)
    if (not path.is_dir()) if directory else (not path.is_file()):
        raise HostBoundaryError("owner-private host path is unavailable")
    if os.name != "nt":
        expected = 0o700 if directory else 0o600
        retained = path.stat()
        if stat.S_IMODE(retained.st_mode) != expected or (
            hasattr(os, "geteuid") and retained.st_uid != os.geteuid()
        ):
            raise HostBoundaryError("host path is not owner-private")
        return
    try:
        executable = _native_powershell()
        result = subprocess.run(
            [
                str(executable),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _WINDOWS_ACL_QUERY,
                str(path),
            ],
            capture_output=True,
            text=True,
            env=_native_powershell_environment(executable),
            timeout=30,
            check=False,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise HostBoundaryError("owner-private ACL verification is unavailable") from error
    access = payload.get("access") if isinstance(payload, dict) else None
    current = payload.get("current_sid") if isinstance(payload, dict) else None
    if (
        result.returncode != 0
        or payload.get("protected") is not True
        or payload.get("owner_sid") != current
        or not isinstance(access, list)
        or not access
        or any(
            not isinstance(item, dict)
            or item.get("sid") not in {current, "S-1-5-18"}
            or item.get("type") != "Allow"
            or item.get("inherited") is not False
            for item in access
        )
        or not any(item.get("sid") == current for item in access)
    ):
        raise HostBoundaryError("host path is not owner-private")

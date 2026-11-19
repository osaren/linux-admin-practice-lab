"""Host capability probes. None creates a VM or changes system settings."""
import ctypes
import os
import pathlib
import platform
import re
import stat
import subprocess
import sys


def host_kind():
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        # Rosetta can report x86_64 on an Apple Silicon host.
        arm = subprocess.run(["sysctl", "-n", "hw.optional.arm64"], capture_output=True,
                             text=True, check=False)
        if arm.returncode == 0 and arm.stdout.strip() == "1":
            machine = "arm64"
    elif system == "Windows":
        # This reports the native CPU even when Python runs under emulation.
        machine = os.environ.get("PROCESSOR_ARCHITEW6432", machine).lower()
    arch = {"arm64": "arm64", "aarch64": "arm64", "amd64": "amd64", "x86_64": "amd64"}.get(machine, machine)
    if system == "Linux":
        try:
            release = pathlib.Path("/proc/sys/kernel/osrelease").read_text().lower()
        except OSError:
            release = ""
        if "microsoft" in release:
            return ("wsl2" if "wsl2" in release or "microsoft-standard" in release else "wsl1"), arch
    return {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(system, "unsupported"), arch


def version_from(output):
    match = re.search(r"\bv?(\d+)\.(\d+)\.(\d+)([-+][\w.-]+)?", output)
    if not match or (match[4] and match[4].startswith("-") and
                     re.match(r"-(?:alpha|beta|rc|dev|pre)", match[4], re.I)):
        return None
    return tuple(map(int, match.groups()[:3]))


def version_label(version):
    return ".".join(map(str, version)) if version else "unknown"


def kvm_access():
    try:
        fd = os.open("/dev/kvm", os.O_RDWR)
    except OSError:
        return False
    os.close(fd)
    return True


def windows_hypervisor():
    try:
        # WHvCapabilityCodeHypervisorPresent returns a Win32 BOOL.
        api = ctypes.WinDLL("WinHvPlatform.dll", winmode=0x800).WHvGetCapability
        present = ctypes.c_int32()
        return api(0, ctypes.byref(present), ctypes.sizeof(present), None) == 0 and bool(present.value)
    except (AttributeError, OSError):
        return False


def windows_local_ntfs(path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDriveTypeW.argtypes = (ctypes.c_wchar_p,)
    if kernel.GetDriveTypeW(path.anchor) != 3:  # DRIVE_FIXED
        return False
    filesystem = ctypes.create_unicode_buffer(32)
    query = kernel.GetVolumeInformationW
    query.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                      ctypes.c_wchar_p, ctypes.c_uint32)
    return bool(query(path.anchor, None, 0, None, None, None, filesystem, len(filesystem))) and filesystem.value == "NTFS"


def host_memory(host):
    if host == "windows":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32),
                        ("total", ctypes.c_uint64), ("available", ctypes.c_uint64),
                        ("remaining_fields", ctypes.c_uint64 * 5)]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.total, status.available
        return 0, None
    if host == "macos":
        result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=False)
        return (int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0), None
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        total = page * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return 0, None
    try:
        match = re.search(r"^MemAvailable:\s+(\d+) kB", pathlib.Path("/proc/meminfo").read_text(), re.M)
    except OSError:
        match = None
    return total, int(match[1]) * 1024 if match else None


def redirected(path):
    """Reject symlinks and Windows junctions at ownership boundaries."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def windows_allocated_kb(path):
    """Count actual NTFS allocation, including sparse virtual disk files."""
    size_of = ctypes.WinDLL("kernel32", use_last_error=True).GetCompressedFileSizeW
    size_of.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32))
    size_of.restype = ctypes.c_uint32
    size = 0
    for parent, dirs, files in os.walk(path):
        dirs[:] = [name for name in dirs if not redirected(pathlib.Path(parent, name))]
        for name in files:
            file = pathlib.Path(parent, name)
            if redirected(file):
                continue
            high = ctypes.c_uint32()
            ctypes.set_last_error(0)
            low = size_of(str(file), ctypes.byref(high))
            if low == 0xffffffff and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
            size += (high.value << 32) | low
    return (size + 1023) // 1024

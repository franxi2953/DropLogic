import os
import platform
from pathlib import Path
import sys
from typing import Optional

_dll_directory_handles = []


def _add_dll_directory(path):
    if platform.system() != "Windows":
        return
    if not hasattr(os, "add_dll_directory"):
        return
    path = str(path)
    if path in os.environ.get("PATH", "").split(os.pathsep):
        return
    _dll_directory_handles.append(os.add_dll_directory(path))


def _package_vendor_candidates():
    """
    Return plausible vendor-binary directories located in or next to an installed library.

    The primary supported layout is droplogic/vendors_bin inside the installed
    package, so users do not need to configure a separate native runtime folder.
    """
    package_dir = Path(__file__).resolve().parents[1]
    candidates = [
        package_dir / "vendors_bin",
        package_dir.parent / "vendors_bin",
    ]
    return [candidate for candidate in candidates if candidate.exists()]


def get_vendor_bin_dir():
    """Resolve the DropLogic vendored native-binary directory."""
    for candidate in _package_vendor_candidates():
        return candidate

    env_dir = os.environ.get("DROPLOGIC_VENDOR_BIN_DIR")
    if env_dir and os.path.exists(env_dir):
        return Path(env_dir)
            
    return None


def get_runtime_dir():
    """Backward-compatible alias for older DropLogic runtime terminology."""
    return get_vendor_bin_dir()


def inject_vendor_python_path(relative_dir: str, local_fallback: str):
    """
    Injects the folder containing vendor Python modules into sys.path
    so they can be imported normally.
    """
    vendor_dir = get_vendor_bin_dir()
    if vendor_dir:
        vendor_path = vendor_dir / relative_dir
        if vendor_path.is_dir() and str(vendor_path) not in sys.path:
            sys.path.insert(0, str(vendor_path))
            _add_dll_directory(vendor_path)
            return
            
    if os.path.isdir(local_fallback) and local_fallback not in sys.path:
        sys.path.insert(0, local_fallback)
        _add_dll_directory(local_fallback)

def resolve_dll(relative_path: str, local_fallback: str) -> str:
    """
    Resolve a native library path.
    1. Vendored DLLs under droplogic/vendors_bin
    2. DROPLOGIC_VENDOR_BIN_DIR for development overrides
    3. Local fallback for backward compatibility during transition
    """
    vendor_dir = get_vendor_bin_dir()
    if vendor_dir:
        dll_path = vendor_dir / relative_path
        if dll_path.exists():
            _add_dll_directory(dll_path.parent)
            return str(dll_path)
            
    # Fallback to local
    if os.path.exists(local_fallback):
        _add_dll_directory(Path(local_fallback).resolve().parent)
        return local_fallback
        
    raise FileNotFoundError(
        f"Required native library '{relative_path}' could not be found. "
        f"Install DropLogic with its vendors_bin assets included."
    )


def resolve_runtime_path(relative_path: str, local_fallback: Optional[str] = None) -> str:
    """Resolve any vendored file or directory, not only dynamic libraries."""
    vendor_dir = get_vendor_bin_dir()
    if vendor_dir:
        path = vendor_dir / relative_path
        if path.exists():
            return str(path)

    if local_fallback and os.path.exists(local_fallback):
        return local_fallback

    raise FileNotFoundError(
        f"Required vendored path '{relative_path}' could not be found. "
        f"Install DropLogic with its vendors_bin assets included."
    )

import os
import platform
import ctypes
from pathlib import Path
import sys

if platform.system() == "Windows":
    try:
        import winreg
    except ImportError:
        winreg = None
else:
    winreg = None


def _package_runtime_candidates():
    """
    Return plausible runtime directories located next to an installed library.

    This supports deployments where the native runtime is installed adjacent to
    the DropLogic package instead of only under ProgramData.
    """
    package_dir = Path(__file__).resolve().parents[1]
    candidates = [
        package_dir / "runtime",
        package_dir.parent / "runtime",
        package_dir.parent / "DropLogicRuntime",
    ]
    return [candidate for candidate in candidates if candidate.exists()]


def _registry_runtime_dir():
    """Read an installer-provided runtime directory from the Windows registry."""
    if winreg is None:
        return None

    key_specs = [
        (winreg.HKEY_LOCAL_MACHINE, r"Software\DropLogic", "RuntimePath"),
        (winreg.HKEY_CURRENT_USER, r"Software\DropLogic", "RuntimePath"),
    ]
    for hive, subkey, value_name in key_specs:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
            if value and os.path.exists(value):
                return Path(value)
        except OSError:
            continue
    return None

def get_runtime_dir():
    """Resolve the DropLogic runtime directory based on environment variable or known install locations."""
    env_dir = os.environ.get("DROPLOGIC_RUNTIME_DIR")
    if env_dir and os.path.exists(env_dir):
        return Path(env_dir)

    for candidate in _package_runtime_candidates():
        return candidate

    if platform.system() == "Windows":
        registry_dir = _registry_runtime_dir()
        if registry_dir is not None:
            return registry_dir

        program_data = os.environ.get("ProgramData", "C:\\ProgramData")
        default_dir = Path(program_data) / "DropLogic" / "runtime"
        if default_dir.exists():
            return default_dir
            
    return None

def inject_vendor_python_path(relative_dir: str, local_fallback: str):
    """
    Injects the folder containing vendor Python modules into sys.path
    so they can be imported normally.
    """
    runtime_dir = get_runtime_dir()
    if runtime_dir:
        vendor_path = runtime_dir / relative_dir
        if vendor_path.is_dir() and str(vendor_path) not in sys.path:
            sys.path.insert(0, str(vendor_path))
            return
            
    if os.path.isdir(local_fallback) and local_fallback not in sys.path:
        sys.path.insert(0, local_fallback)

def resolve_dll(relative_path: str, local_fallback: str) -> str:
    """
    Resolve a native DLL path.
    1. DROPLOGIC_RUNTIME_DIR
    2. Runtime installed next to the DropLogic package
    3. Installer-provided Windows registry path
    4. %ProgramData%/DropLogic/runtime
    5. Local fallback (for backward compatibility during transition)
    """
    runtime_dir = get_runtime_dir()
    if runtime_dir:
        dll_path = runtime_dir / relative_path
        if dll_path.exists():
            return str(dll_path)
            
    # Fallback to local
    if os.path.exists(local_fallback):
        return local_fallback
        
    raise FileNotFoundError(
        f"Required native library '{relative_path}' could not be found. "
        f"Please install the DropLogic Windows Runtime next to the library, use the installer-provided path, or set DROPLOGIC_RUNTIME_DIR."
    )

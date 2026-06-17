import os
import sys
import platform
import ctypes
from droplogic.utils.native_runtime import resolve_dll


try:
    from termcolor import colored
except ImportError:
    def colored(text, color=None):
        return text


def check_dll(name, relative_path, dummy_local):
    print(f"Checking {name}...", end=" ")
    try:
        path = resolve_dll(relative_path, dummy_local)
        
        if platform.system() == "Windows":
            # Test ctypes loading
            ctypes.CDLL(path)
        print(colored("PASS", "green"))
        return True
    except FileNotFoundError as e:
        print(colored("MISSING", "red"))
        print(f"  -> {e}")
        return False
    except OSError as e:
        print(colored("OS ERROR", "red"))
        print(f"  -> Could not load {path}: {e}")
        return False

def run_doctor():
    print("DropLogic Native Vendor Doctor")
    print("========================")
    
    if platform.system() != "Windows":
        print("native_runtime components are primarily used on Windows.")
        sys.exit(0)
    
    # We pass a nonexistent local fallback to ensure it checks packaged vendors_bin assets.
    success = True
    success &= check_dll("DMLite SDK", "electrode_matrix/dmlite/sdk.dll", "dummy_dmlite.dll")
    success &= check_dll("Camera MVS", "camera/mvs_camera/drivers/Runtime/Win64_x64/MvCameraControl.dll", "dummy_mvs.dll")
    success &= check_dll("XY Stage", "xy_stage/nmc/MCDLL_NET.dll", "dummy_xy.dll")
    
    print("\nSummary:")
    if success:
        print(colored("All native components validated successfully.", "green"))
    else:
        print(colored("Some components failed to load.", "red"))
        print("Expected vendor assets:")
        print("  - droplogic/vendors_bin inside the installed package")
        print("Install DropLogic with its bundled vendors_bin files.")
        sys.exit(1)

if __name__ == "__main__":
    run_doctor()

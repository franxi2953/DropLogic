import os
import sys
import platform
import ctypes
from termcolor import colored
from droplogic.utils.native_runtime import resolve_dll

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
    print("DropLogic Runtime Doctor")
    print("========================")
    
    if platform.system() != "Windows":
        print("native_runtime components are primarily used on Windows.")
        sys.exit(0)
    
    # We pass a nonexistent local fallback to ensure it checks the runtime dir
    success = True
    success &= check_dll("DMLite SDK", "electrode_matrix/dmlite/sdk.dll", "dummy_dmlite.dll")
    success &= check_dll("Camera MVS", "camera/mvs/MvCameraControl.dll", "dummy_mvs.dll")
    success &= check_dll("XY Stage", "xy_stage/nmc/MCDLL_NET.dll", "dummy_xy.dll")
    
    print("\nSummary:")
    if success:
        print(colored("All native components validated successfully.", "green"))
    else:
        print(colored("Some components failed to load.", "red"))
        print("Expected runtime locations:")
        print("  - DROPLOGIC_RUNTIME_DIR")
        print("  - a runtime folder next to the DropLogic package")
        print("  - the installer-provided runtime path")
        print("  - %ProgramData%/DropLogic/runtime")
        print("Install the DropLogic runtime or point DROPLOGIC_RUNTIME_DIR to it.")
        sys.exit(1)

if __name__ == "__main__":
    run_doctor()

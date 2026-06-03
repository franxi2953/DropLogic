import platform
import os
import subprocess

def bring_window_to_front(window_name: str):
    """
    Intenta llevar la ventana con el nombre dado al primer plano.
    Soporta Windows a través de pywin32 y macOS mediante AppleScript.
    """
    system = platform.system()
    
    if system == "Windows":
        try:
            import win32gui
            import win32con
            hwnd = win32gui.FindWindow(None, window_name)
            if hwnd:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        except ImportError:
            print("Warning: win32gui no está instalado, no se puede controlar la ventana.")
            pass

    elif system == "Darwin":
        try:
            # En macOS solemos traer el proceso actual de Python (donde corre cv2 o pygame) al frente.
            pid = os.getpid()
            script = f'tell application "System Events" to set frontmost of every process whose unix id is {pid} to true'
            subprocess.run(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

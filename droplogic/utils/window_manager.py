import logging
import os
import platform
import subprocess
import time


logger = logging.getLogger(__name__)


def get_window_status(window_name: str):
    """Return OS-level visibility information for a visualizer window."""
    system = platform.system()

    if system != "Windows":
        return {
            "platform": system,
            "requested_title": window_name,
            "supported": system == "Darwin",
            "found": None,
            "windows": [],
        }

    try:
        import win32gui
        import win32process
    except ImportError:
        return {
            "platform": system,
            "requested_title": window_name,
            "supported": False,
            "found": False,
            "error": "pywin32 is not installed",
            "windows": [],
        }

    requested = (window_name or "").lower()
    windows = []

    def collect(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        if title == window_name or (requested and requested in title.lower()):
            thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
            windows.append(
                {
                    "hwnd": int(hwnd),
                    "title": title,
                    "visible": bool(win32gui.IsWindowVisible(hwnd)),
                    "enabled": bool(win32gui.IsWindowEnabled(hwnd)),
                    "minimized": bool(win32gui.IsIconic(hwnd)),
                    "rect": list(win32gui.GetWindowRect(hwnd)),
                    "thread_id": int(thread_id),
                    "process_id": int(process_id),
                    "foreground": hwnd == win32gui.GetForegroundWindow(),
                }
            )

    win32gui.EnumWindows(collect, None)
    exact = [item for item in windows if item["title"] == window_name]
    primary = exact[0] if exact else (windows[0] if windows else None)
    return {
        "platform": system,
        "requested_title": window_name,
        "supported": True,
        "found": primary is not None,
        "primary": primary,
        "windows": windows,
    }


def bring_window_to_front(window_name: str):
    """Try to bring a visualizer window to the foreground."""
    system = platform.system()

    if system == "Windows":
        try:
            import win32api
            import win32com.client
            import win32con
            import win32gui
            import win32process
        except ImportError:
            logger.warning("pywin32 is not installed; cannot bring the window to front.")
            return {
                "platform": system,
                "requested_title": window_name,
                "supported": False,
                "found": False,
                "brought_to_front": False,
                "error": "pywin32 is not installed",
            }

        status = get_window_status(window_name)
        primary = status.get("primary")
        hwnd = int(primary["hwnd"]) if primary else 0
        if not hwnd:
            return {**status, "brought_to_front": False}

        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWNORMAL)

            # Windows often blocks SetForegroundWindow from background processes.
            # Sending ALT and attaching input improves this without changing app state.
            try:
                shell = win32com.client.Dispatch("WScript.Shell")
                shell.SendKeys("%")
            except Exception:
                pass

            try:
                foreground = win32gui.GetForegroundWindow()
                current_thread = win32api.GetCurrentThreadId()
                target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
                foreground_thread, _ = win32process.GetWindowThreadProcessId(foreground)
                attached = []

                for thread_id in {target_thread, foreground_thread}:
                    if thread_id and thread_id != current_thread:
                        win32process.AttachThreadInput(current_thread, thread_id, True)
                        attached.append(thread_id)
                try:
                    win32gui.BringWindowToTop(hwnd)
                    win32gui.SetForegroundWindow(hwnd)
                finally:
                    for thread_id in attached:
                        win32process.AttachThreadInput(current_thread, thread_id, False)
            except Exception as exc:
                logger.debug("SetForegroundWindow failed for %s: %s", window_name, exc)

            flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
            time.sleep(0.05)
            win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            return {**get_window_status(window_name), "brought_to_front": True}
        except Exception as exc:
            logger.warning("Cannot bring window '%s' to front: %s", window_name, exc)
            return {**get_window_status(window_name), "brought_to_front": False, "error": str(exc)}

    if system == "Darwin":
        try:
            pid = os.getpid()
            script = (
                'tell application "System Events" to set frontmost of every process '
                f"whose unix id is {pid} to true"
            )
            subprocess.run(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return {
                "platform": system,
                "requested_title": window_name,
                "supported": True,
                "found": None,
                "brought_to_front": True,
            }
        except Exception as exc:
            return {
                "platform": system,
                "requested_title": window_name,
                "supported": True,
                "found": None,
                "brought_to_front": False,
                "error": str(exc),
            }

    return {
        "platform": system,
        "requested_title": window_name,
        "supported": False,
        "found": None,
        "brought_to_front": False,
    }


def request_window_close(window_name: str):
    """Ask the OS to close a visualizer window without blocking on OpenCV."""
    system = platform.system()

    if system != "Windows":
        return {
            "platform": system,
            "requested_title": window_name,
            "supported": False,
            "requested_close": False,
        }

    try:
        import win32con
        import win32gui
    except ImportError:
        return {
            "platform": system,
            "requested_title": window_name,
            "supported": False,
            "requested_close": False,
            "error": "pywin32 is not installed",
        }

    status = get_window_status(window_name)
    windows = status.get("windows") or []
    requested = 0
    for window in windows:
        hwnd = int(window["hwnd"])
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            requested += 1
        except Exception as exc:
            logger.debug("Could not post WM_CLOSE to %s: %s", window_name, exc)

    return {
        **status,
        "requested_close": requested > 0,
        "requested_count": requested,
    }

"""Standalone manual control entrypoint for BOXMini using DropLogic.

Running this file initializes real BOXMini hardware, starts the streamer, and
opens the same control loop as the old basic terminal manual control program.
Do not run it unless the machine is physically ready.
"""

import cv2
import os
import sys
import threading
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "hide")

import pygame
from collections import deque
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DROPLOGIC_ROOT = SCRIPT_DIR.parent.resolve()
if str(DROPLOGIC_ROOT) not in sys.path:
    sys.path.insert(0, str(DROPLOGIC_ROOT))


def resolve_config_path():
    configured_path = os.environ.get("DROPLOGIC_CONFIG")
    if configured_path:
        return Path(configured_path).expanduser().resolve()

    cwd_config = Path.cwd() / "config.json"
    if cwd_config.exists():
        return cwd_config.resolve()

    return (DROPLOGIC_ROOT / "config.json").resolve()

from rich.console import Console, Group
from rich.panel import Panel
from rich.live import Live
import asciichartpy
import ctypes
from ctypes import wintypes
import ctypes.wintypes
from droplogic.hardware.box_mini1 import BOXMini
from droplogic.base import Priority
import gc
import win32gui
import win32con
import numpy as np
from droplogic.utils.hardware_utils.utils import electrode_to_stage


# Global Console
console = Console()


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

# Constants and global state
MOVE_STEP = 100  
Z_MOVE_STEP = 50  
TEMP_MIN = 20
TEMP_MAX = 80
POSITION = {"X": 0, "Y": 0, "Z": 0}
LIGHT_STATUS = {"Coaxial": 0, "Ring": 0}
TARGET_TEMPERATURE = None
LIGHT_MODES = {
    "0": (95, 0),  
    "1": (95, 99),  
    "2": (0, 0),  
}

exit_flag = threading.Event()  # Used to signal threads to stop
stop_electrode_animation = threading.Event()  # Used to signal the electrode animation to stop
threads = []  # Store streaming threads for proper cleanup
temperature_history = deque(maxlen=50)  # Store last 50 temperature values

adjusting_light = False           # Tracks if we are adjusting light intensity
adjusting_temperature = False     # Tracks if we are adjusting temperature
light_input = ""                  # Stores user input for light intensity
temperature_input = ""            # Stores user input for temperature value
adjusting_light_type = None       # Either "Coaxial" or "Ring"
show_green_dot = False           # Show position coordinates

adjusting_exposure = False
exposure_input = ""

adjusting_gain = False
gain_input = ""

adjusting_electrode_position = False  # Tracks if we are setting electrode position
electrode_input = ""                  # Stores user input for electrode row,

streamer = None
box = None
close_lock = threading.Lock()
closed = False

# Windows API key codes
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_MINUS = 0xBD  # - key
VK_PLUS = 0xBB   # = key (+ without shift)

# Digit key codes (0-9)
VK_DIGITS = {
    0: 0x30, 1: 0x31, 2: 0x32, 3: 0x33, 4: 0x34,
    5: 0x35, 6: 0x36, 7: 0x37, 8: 0x38, 9: 0x39
}

# Key state tracking for reliable continuous movement
key_states = {
    'left': False,
    'right': False, 
    'up': False,
    'down': False,
    'minus': False,
    'plus': False
}
key_state_lock = threading.Lock()
last_key_activity = time.time()  # Track last key activity for safety timeout
JOG_KEEPALIVE_INTERVAL = 0.08

# Windows API function for checking key state
user32 = ctypes.windll.user32

# Track key states for debouncing
key_pressed_states = {}

# Debug window flag
debug_window_active = False

# No local queue needed - using DropLogic parent queue system


# -----------------------------------------------------------------------------
# UI Panels and Helpers
# -----------------------------------------------------------------------------
def plot_temperature_trend():
    """Generates an ASCII line plot for the temperature trend."""
    if not temperature_history:
        return "No data"
    chart = asciichartpy.plot(list(temperature_history), {"height": 5})
    return f"Trend:\n{chart}"

def get_status_panel():
    global speed
    """Generates the status panel displaying current settings."""
    temperature_plot = plot_temperature_trend()

    if adjusting_light:
        if adjusting_light_type == "Coaxial":
            light_info = (f"[bold green]Coaxial:[/] [bold cyan]{light_input or '█'}[/] "
                        f"[bold green]Ring:[/] {LIGHT_STATUS['Ring']}")
        else:
            light_info = (f"[bold green]Coaxial:[/] {LIGHT_STATUS['Coaxial']} "
                        f"[bold green]Ring:[/] [bold cyan]{light_input or '█'}[/]")
    else:
        light_info = (f"[bold green]Coaxial:[/] {LIGHT_STATUS['Coaxial']} "
                    f"[bold green]Ring:[/] {LIGHT_STATUS['Ring']}")

    if adjusting_temperature:
        temperature_info = f"[bold magenta]Target Temperature:[/] [bold cyan]{temperature_input or '█'}°C[/]"
    else:
        temperature_info = (f"[bold magenta]Target Temperature:[/] "
                            f"{TARGET_TEMPERATURE if TARGET_TEMPERATURE is not None else 'N/A'}°C")

    if adjusting_exposure:
        exposure_info = (f"[bold green]Exposure time:[/] [bold cyan]{exposure_input or '█'}[/] ")
    else:
        exposure_info = (f"[bold magenta]Exposure time:[/] "
                            f"{box.state["camera_settings"]["exposure_time"] if box.state["camera_settings"]["exposure_time"] is not None else 'N/A'}")

    if adjusting_gain:
        gain_info = (f"[bold green]Analog Gain:[/] [bold cyan]{gain_input or '█'}[/] ")
    else:
        gain_info = (f"[bold magenta]Analog Gain:[/] "
                            f"{box.state['microscope_settings']['gain'] if 'gain' in box.state['microscope_settings'] and box.state['microscope_settings']['gain'] is not None else 'N/A'}")

    if adjusting_electrode_position:
        electrode_info = f"[bold cyan]Electrode Position:[/] [bold cyan]{electrode_input or '█'}[/]"
    else:
        electrode_info = ""

    return Panel(
        f"[bold cyan]Status[/bold cyan]\n"
        f"[bold magenta]Position:[/bold magenta] X={POSITION['X']}, Y={POSITION['Y']}, Z={POSITION['Z']}\n"
        f"[bold magenta]Speed:[/bold magenta] {box.state['xy_stage']['motion_params']['dMaxV']} mm/s\n"
        f"{light_info}\n"
        f"[bold green]Channel:[/] {box.state['microscope_settings']['current_channel']}\n"
        f"{exposure_info}\n"
        f"{gain_info}\n"
        f"{electrode_info}\n"
        f"{temperature_info}\n"
        f"[bold yellow]Temperature:[/] {temperature_history[-1] if temperature_history else 'N/A'} °C\n"
        f"{temperature_plot}",
        title="Status",
        expand=False,
        border_style="bold white",
    )

def get_controls_panel():
    """Generates the controls panel."""
    if adjusting_light:
        return Panel(
            f"[bold cyan]Adjusting {adjusting_light_type} Light[/bold cyan]\n"
            "Type a value (0-99) and press [bold green]Enter[/] to confirm.\n"
            "Press [bold red]Backspace[/] to delete, or [bold red]Esc[/] to cancel.",
            title="Controls",
            expand=False,
            border_style="bold yellow",
        )
    if adjusting_temperature:
        return Panel(
            "[bold cyan]Adjusting Target Temperature[/bold cyan]\n"
            f"Type a value ({TEMP_MIN}-{TEMP_MAX}°C) and press [bold green]Enter[/] to confirm.\n"
            "Press [bold red]Backspace[/] to delete, or [bold red]Esc[/] to cancel.",
            title="Controls",
            expand=False,
            border_style="bold magenta",
        )
    if adjusting_exposure:
        return Panel(
            "[bold cyan]Adjusting Exposure Time[/bold cyan]\n"
            "Type a value (°C) and press [bold green]Enter[/] to confirm.\n"
            "Press [bold red]Backspace[/] to delete, or [bold red]Esc[/] to cancel.",
            title="Controls",
            expand=False,
            border_style="bold magenta",
        )
    if adjusting_gain:
        return Panel(
            "[bold cyan]Adjusting Analog Gain[/bold cyan]\n"
            "Type a value (0-100) and press [bold green]Enter[/] to confirm.\n"
            "Press [bold red]Backspace[/] to delete, or [bold red]Esc[/] to cancel.",
            title="Controls",
            expand=False,
            border_style="bold magenta",
        )
    if adjusting_electrode_position:
        return Panel(
            "[bold cyan]Setting Electrode Position[/bold cyan]\n"
            "Type row,col (e.g. 5,10) and press [bold green]Enter[/] to move.\n"
            "Press [bold red]Backspace[/] to delete, or [bold red]Esc[/] to cancel.",
            title="Controls",
            expand=False,
            border_style="bold cyan",
        )
    return Panel(
        "[bold cyan]Manual Control Mode[/bold cyan]\n"
        "[bold yellow]Movement:[/] ← → (X) | ↑ ↓ (Y) | - / + (Z)\n"
        "[bold blue]M : Move to default position[/]\n"
        "[bold blue]D : Show camera coordinates[/]\n"
        "[bold blue]P : Toggle electrode overlay[/]\n\n"
        "[bold blue]1, 2, 3, 4 : Set movement speed[/]\n\n"
        "[bold magenta]Lighting:[/]\n"
        "[bold blue]C : Adjust Coaxial Light[/]\n"
        "[bold blue]R : Adjust Ring Light[/]\n"
        "[bold blue]L : Adjust Tarjet Exposure[/]\n"
        "[bold blue]G : Adjust Analog Gain[/]\n\n"
        "[bold magenta]Temperature:[/]\n"
        "[bold blue]T : Set Target Temperature[/]\n\n"
        "[bold blue]O : Move to Electrode Position[/]\n"
        "[bold blue]E : Animate Electrode Matrix[/]\n"
        "[bold blue]K : Open Key Debug Window[/]\n\n"
        "[bold red]q : Exit[/]",
        title="Controls",
        expand=False,
        border_style="bold white",
    )

def save_chip_to_file(chip, filename="chip.txt"):
    """Saves an ASCII representation of the chip matrix to a file."""
    with open(filename, "w") as f:
        for row in chip:
            # Join each row's digits with a space (or use another format)
            line = " ".join(str(bit) for bit in row)
            f.write(line + "\n")
    # console.print(f"[bold green]Chip state saved to {filename}[/]")

# -----------------------------------------------------------------------------
# Streaming and Electrode Matrix Animation
# -----------------------------------------------------------------------------
def stream_camera(device, window_name, system_camera=False):
    """Captures and streams frames from a given device in a separate thread."""
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)

    time.sleep(0.5)  # Allow time for the window to be created

    hwnd = win32gui.FindWindow(None, window_name)
    
    if hwnd:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
    if window_name == "Microscope Stream":
        time.sleep(0.5)  # Give time to be visible on top
    elif system_camera:
        cap = cv2.VideoCapture(device, cv2.CAP_DSHOW)  # Ensure DirectShow backend on Windows
        if not cap.isOpened():
            # print(f"⚠️ Failed to open system camera {device}")
            return
    else:
        cap = None  # For ACX cameras

    global show_green_dot
    while not exit_flag.is_set():
        if window_name == "Microscope Stream":
            frame = device.visualizers.streamer.get_processed_frame()
            #print the shape
            # print(f"Microscope frame shape: {frame.shape if frame is not None else 'None'}")
        elif system_camera:
            ret, frame = cap.read()
            if not ret or frame is None:
                # print(f"⚠️ System camera {device} returned empty frame")
                continue
        else:
            frame = device.capture_image()

        if frame is not None: 
            orig_height, orig_width = frame.shape[:2]
            if orig_height != 0:
                aspect_ratio = orig_width / orig_height
                prev_width, prev_height = orig_width, orig_height
                if not cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE):
                    exit_flag.set()
                    break

                win_x, win_y, win_width, win_height = cv2.getWindowImageRect(window_name)
                if win_width != 0 and win_height != 0:
                    # Maintain aspect ratio
                    if win_width / win_height > aspect_ratio:
                        new_width = int(win_height * aspect_ratio)
                        new_height = win_height
                    else:
                        new_width = win_width
                        new_height = int(win_width / aspect_ratio)

                    if abs(new_width - prev_width) > 2 or abs(new_height - prev_height) > 2:
                        cv2.resizeWindow(window_name, new_width, new_height)
                        prev_width, prev_height = new_width, new_height

                    resized_frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
                    
                    # Create a copy of the frame for overlays to avoid modifying the original
                    display_frame = resized_frame.copy()
                    
                    # Ensure display_frame is in color format for overlays
                    if len(display_frame.shape) == 2:  # Grayscale
                        display_frame = cv2.cvtColor(display_frame, cv2.COLOR_GRAY2BGR)

                    # Display position coordinates if enabled
                    if show_green_dot:
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        bottomLeftCornerOfText = (10, 30)
                        fontScale = 0.5
                        fontColor = (0, 255, 0)
                        lineType = 2

                        _x=box.state["xy_stage"]["position"]["X"]
                        _y=box.state["xy_stage"]["position"]["Y"]
                        _z=box.state["xy_stage"]["position"]["Z"]

                        cv2.putText(display_frame, f"(X {_x} Y {_y} Z {_z})",
                                    bottomLeftCornerOfText,
                                    font,
                                    fontScale,
                                    fontColor,
                                    lineType)
                    
                    # Display the frame with overlays
                    cv2.imshow(window_name, display_frame)
                        

        # Reduced waitKey time to improve responsiveness during movement
        key = cv2.waitKey(5) & 0xFF  # Increased from 1ms to 5ms to reduce CPU load
        if key == ord("q"):
            exit_flag.set()
            break

    if system_camera:
        cap.release()
    
    cv2.destroyWindow(window_name)

def animate_electrode_columns():
    existing_thread = next((t for t in threads if t.name == 'electrode_animation'), None)

    if existing_thread and existing_thread.is_alive():
        # Signal the thread to stop and wait for it to finish
        stop_electrode_animation.set()
        existing_thread.join()
        threads.remove(existing_thread)
        stop_electrode_animation.clear()
        # print("Stopped existing animation thread.")
    else:
        # No existing thread, create and start a new one
        stop_electrode_animation.clear()
        new_thread = threading.Thread(
            target=electrode_animation_loop,
            name='electrode_animation',
            daemon=True
        )
        threads.append(new_thread)
        new_thread.start()
        # print("Started new animation thread.")     

def electrode_animation_loop():
    pygame.init()
    pygame.font.init()
    
    state = box.state
    total_cols = state["electrode_matrix"]["columns"]
    rows = state["electrode_matrix"]["rows"]
    
    window_size = 600  # Adjust as needed

    screen = pygame.display.set_mode((window_size, window_size))
    pygame.display.set_caption("Electrode Matrix State")
    clock = pygame.time.Clock()
    
    # Bring the window to the top (Windows only)
    try:
        hwnd = pygame.display.get_wm_info()['window']
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        time.sleep(0.5)  # Give time to be visible on top
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
    except Exception as e:
        print("Failed to set window topmost:", e)

    # Get current state in case it updates over time
    total_cols = box.state["electrode_matrix"]["columns"]
    rows = box.state["electrode_matrix"]["rows"]
    
    # Specific electrode positions to activate
    positions = [(58, 56), (58, 60), (58, 64), (58, 68), (62, 56), (62, 60), (62, 64), (62, 68), (62, 72), (58, 72)]

    # Generate the chip matrix with specific electrodes active
    chip = np.zeros((rows, total_cols), dtype=int)
    for r, c in positions:
        if 0 <= r < rows and 0 <= c < total_cols:
            chip[r, c] = 1

    # Update electrode matrix state
    box.update_state("electrode_matrix.matrix", chip.tolist())

    # Draw on screen using your provided function
    draw_chip_visualization(chip, screen, window_size // rows, window_size)

    running = True
    while running and not stop_electrode_animation.is_set():
        # Process Pygame events for window closure
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break
        
        # Keep the window updated
        draw_chip_visualization(chip, screen, window_size // rows, window_size)
        
        # Wait briefly, checking the stop flag periodically
        elapsed = 0
        while elapsed < 100:  # 100ms update
            if stop_electrode_animation.is_set() or not running:
                break
            dt = clock.tick(60)
            elapsed += dt

    pygame.quit()

def draw_chip_visualization(chip, screen, cell_size, window_size, debug_graphics=True):
    """
    Draws the chip matrix onto the Pygame screen.
    
    The chip (a 2D list) is converted to a NumPy array and rotated -90° (i.e. 90° clockwise) 
    before drawing. Active cells (1's) are drawn in cyan on a black background.
    
    A white outline is drawn around the chip area. In addition, if debug_graphics is True,
    the function draws the current mouse coordinates in the bottom right corner.
    """

    # Define colors.
    BLACK = (0, 0, 0)
    CYAN  = (0, 255, 255)
    WHITE = (255, 255, 255)
    
    # Offsets for drawing (so the chip is not drawn flush with the window edges).
    x_offset = 50
    y_offset = 50

    # Convert chip (a 2D list) to a NumPy array and rotate it -90° (clockwise).
    chip_array = np.array(chip)
    rotated_chip = np.rot90(chip_array, k=-1)

    # Clear the screen with black.
    screen.fill(BLACK)

    # Draw active cells from the rotated matrix.
    for r in range(rotated_chip.shape[0]):
        for c in range(rotated_chip.shape[1]):
            if rotated_chip[r, c] == 1:
                rect = pygame.Rect(x_offset + c * cell_size,
                                   y_offset + r * cell_size,
                                   cell_size, cell_size)
                pygame.draw.rect(screen, CYAN, rect)

    # Draw a white outline around the chip area.
    # (Assumes the chip is 128x128.)
    thickness = 1
    chip_width = 128 * cell_size
    chip_height = 128 * cell_size
    outline_rect = pygame.Rect(x_offset - thickness, y_offset - thickness,
                               chip_width + thickness, chip_height + thickness)
    pygame.draw.rect(screen, WHITE, outline_rect, thickness)

    # Prepare to render text.
    font_size = 15
    font = pygame.font.SysFont(None, font_size)
    margin = 10

    # Render fixed text "0" (adjust as needed).
    # Column indicator
    text = "Col. 0"
    text_surface = font.render(text, True, WHITE)
    text_rect = text_surface.get_rect()
    text_rect.bottomleft = (565, 60)
    screen.blit(text_surface, text_rect)

    # Row indicator
    text = "Row 0"
    text_surface_2 = font.render(text, True, WHITE)
    text_surface_2 = pygame.transform.rotate(text_surface_2, 90)
    text_rect.bottomleft = (550, 25)
    screen.blit(text_surface_2, text_rect)

    # If debugging is enabled, display the current mouse coordinates.
    if debug_graphics:
        mouse_x, mouse_y = pygame.mouse.get_pos()
        mouse_text = f"Mouse: ({mouse_x}, {mouse_y})"
        mouse_surface = font.render(mouse_text, True, WHITE)
        mouse_rect = mouse_surface.get_rect()
        # Position above the previously drawn text.
        mouse_rect.bottomright = (window_size - margin, 590)
        screen.blit(mouse_surface, mouse_rect)
    
    # Finally, update the display.
    pygame.display.flip()

def debug_key_window():
    """Debug window to show key states and queue monitoring in real-time"""
    global debug_window_active
    debug_window_active = True
    
    pygame.init()
    screen = pygame.display.set_mode((1200, 800))
    pygame.display.set_caption("Key State & Queue Debug Window")
    font = pygame.font.Font(None, 24)
    small_font = pygame.font.Font(None, 18)
    clock = pygame.time.Clock()
    
    # Colors
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    GREEN = (144, 238, 144)  # Light green
    RED = (255, 182, 193)    # Light pink/red
    BLUE = (173, 216, 230)   # Light blue
    GRAY = (220, 220, 220)   # Light gray
    
    # Keys to monitor
    keys_to_monitor = [
        ('Arrow Up', VK_UP),
        ('Arrow Down', VK_DOWN),
        ('Arrow Left', VK_LEFT),
        ('Arrow Right', VK_RIGHT),
        ('Plus (+)', VK_PLUS),
        ('Minus (-)', VK_MINUS),
        ('F (Channel)', ord('F')),
        ('T (Temp)', ord('T')),
        ('E (Electrode)', ord('E')),
        ('D (Dot)', ord('D')),
        ('P (Pointer)', ord('P')),
        ('M (Move)', ord('M')),
        ('L (Light)', ord('L')),
        ('G (Gain)', ord('G')),
        ('K (Debug)', ord('K')),
        ('1 (Speed)', ord('1')),
        ('2 (Speed)', ord('2')),
        ('3 (Speed)', ord('3')),
    ]
    
    running = True
    while running and not exit_flag.is_set():
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
        
        screen.fill(WHITE)
        
        # Title
        title = font.render("Real-time Key State & Queue Monitor", True, BLACK)
        screen.blit(title, (10, 10))
        
        # Key states section
        key_title = font.render("Key States:", True, BLACK)
        screen.blit(key_title, (10, 40))
        
        y_offset = 70
        for i, (key_name, vk_code) in enumerate(keys_to_monitor):
            is_pressed = ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000
            color = GREEN if is_pressed else RED
            
            # Draw colored rectangle
            pygame.draw.rect(screen, color, (10, y_offset + i * 25, 15, 15))
            
            # Draw key name and status
            status = "PRESSED" if is_pressed else "not pressed"
            text = small_font.render(f"{key_name}: {status}", True, BLACK)
            screen.blit(text, (35, y_offset + i * 25))
        
        # Queue monitoring section
        queue_x = 500
        queue_title = font.render("Hardware Command Queue:", True, BLACK)
        screen.blit(queue_title, (queue_x, 40))
        
        # Current queue size from ACX parent queue system
        queue_status = box.get_queue_status()
        total_queue_size = sum(status['queue_size'] for status in queue_status.values())
        queue_size_text = font.render(f"Total Queue Size: {total_queue_size}", True, BLACK)
        screen.blit(queue_size_text, (queue_x, 70))
        
        # Commands processed from ACX queue system
        processed_text = font.render(f"CRITICAL Queue: {queue_status['CRITICAL']['queue_size']}", True, BLACK)
        executed_text = font.render(f"HIGH Queue: {queue_status['HIGH']['queue_size']}", True, BLACK)
        rate_text = font.render(f"MEDIUM Queue: {queue_status['MEDIUM']['queue_size']}", True, BLACK)
        retry_text = font.render(f"LOW Queue: {queue_status['LOW']['queue_size']}", True, BLACK)
        screen.blit(processed_text, (queue_x, 100))
        screen.blit(executed_text, (queue_x, 130))
        screen.blit(rate_text, (queue_x, 160))
        screen.blit(retry_text, (queue_x, 190))
        
        # Worker thread status
        active_workers = sum(1 for status in queue_status.values() if status['worker_alive'])
        total_workers = len(queue_status)
        status_text = small_font.render(f"Worker Threads: {active_workers}/{total_workers} active", True, BLACK)
        screen.blit(status_text, (queue_x, 220))
        
        # Processing intervals
        intervals_text = small_font.render("Processing Intervals: CRIT(1ms) HIGH(10ms) MED(100ms) LOW(1s)", True, BLACK)
        screen.blit(intervals_text, (queue_x, 240))
        
        # Queue health status
        health_color = GREEN if total_queue_size < 3 else RED if total_queue_size > 10 else BLUE
        health_text = font.render(f"Queue Health: {'GOOD' if total_queue_size < 3 else 'OVERLOADED' if total_queue_size > 10 else 'BUSY'}", True, health_color)
        screen.blit(health_text, (queue_x, 270))
        
        # Queue priority breakdown chart
        chart_title = small_font.render("Queue Priority Breakdown:", True, BLACK)
        screen.blit(chart_title, (queue_x, 300))
        
        chart_x = queue_x
        chart_y = 330
        chart_width = 400
        chart_height = 100
        
        # Draw chart background
        pygame.draw.rect(screen, GRAY, (chart_x, chart_y, chart_width, chart_height))
        
        # Draw priority queue bars
        priorities = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
        colors = [RED, (255, 165, 0), BLUE, GREEN]  # Red, Orange, Blue, Green
        bar_width = chart_width / len(priorities)
        
        for i, priority in enumerate(priorities):
            queue_size = queue_status[priority]['queue_size']
            bar_height = min(queue_size * 10, chart_height)  # Scale appropriately
            bar_x = chart_x + i * bar_width
            bar_y = chart_y + chart_height - bar_height
            
            pygame.draw.rect(screen, colors[i], (bar_x, bar_y, bar_width - 2, bar_height))
            
            # Draw priority label
            label = small_font.render(priority[:4], True, BLACK)
            screen.blit(label, (bar_x + 5, chart_y + chart_height + 5))
        
        # Emergency stop instruction
        emergency_text = small_font.render("Press 'R' to emergency stop all queues", True, BLACK)
        screen.blit(emergency_text, (queue_x, 450))
        
        # Check for emergency stop key
        if ctypes.windll.user32.GetAsyncKeyState(ord('R')) & 0x8000:
            box.emergency_stop()
            time.sleep(0.2)  # Prevent multiple stops
        
        pygame.display.flip()
        clock.tick(30)  # 30 FPS for debug window
    
    pygame.quit()
    debug_window_active = False

# -----------------------------------------------------------------------------
# Key State Monitoring
# -----------------------------------------------------------------------------
def is_key_pressed(vk_code):
    """Check if a key is currently pressed using Windows API."""
    return user32.GetAsyncKeyState(vk_code) & 0x8000 != 0

def queue_hardware_command(cmd_type, args):
    """Queue a hardware command using DropLogic parent queue system."""
    if cmd_type == "update_state":
        path, value = args
        priority = Priority.HIGH if path.startswith("xy_stage.continuous_movement.") else None
        box.update_state(path, value, priority=priority)
    elif cmd_type == "print":
        console.print(args)

def monitor_key_states():
    """Continuously polls actual key states and applies movements accordingly."""
    last_x_movement = 0
    last_y_movement = 0
    last_z_movement = 0
    last_keepalive_by_axis = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    current_key_states = {"left": False, "right": False, "up": False, "down": False, "minus": False, "plus": False}
    
    while not exit_flag.is_set():
        try:
            current_time = time.time()
            
            # Poll actual key states directly from Windows API
            current_key_states = {
                'left': is_key_pressed(VK_LEFT),
                'right': is_key_pressed(VK_RIGHT),
                'up': is_key_pressed(VK_UP),
                'down': is_key_pressed(VK_DOWN),
                'minus': is_key_pressed(VK_MINUS),
                'plus': is_key_pressed(VK_PLUS)
            }
            
            with key_state_lock:
                # Update our tracked states with actual states
                key_states.update(current_key_states)
                
                # Update last activity time if any key is pressed
                if any(current_key_states.values()):
                    last_key_activity = current_time
                
                # Calculate current movement values
                x_movement = 0
                y_movement = 0
                z_movement = 0
                
                if key_states['left']:
                    x_movement = -1
                elif key_states['right']:
                    x_movement = 1
                    
                if key_states['up']:
                    y_movement = 1
                elif key_states['down']:
                    y_movement = -1
                    
                if key_states['minus']:
                    z_movement = -1
                elif key_states['plus']:
                    z_movement = 1
            
            # Start/stop immediately on state changes. While a key stays held,
            # renew the jog lease so the stage can fail-safe if the UI stalls.
            if (
                x_movement != last_x_movement
                or (x_movement != 0 and current_time - last_keepalive_by_axis["X"] >= JOG_KEEPALIVE_INTERVAL)
            ):
                queue_hardware_command("update_state", ("xy_stage.continuous_movement.X", x_movement))
                last_x_movement = x_movement
                last_keepalive_by_axis["X"] = current_time
                
            if (
                y_movement != last_y_movement
                or (y_movement != 0 and current_time - last_keepalive_by_axis["Y"] >= JOG_KEEPALIVE_INTERVAL)
            ):
                queue_hardware_command("update_state", ("xy_stage.continuous_movement.Y", y_movement))
                last_y_movement = y_movement
                last_keepalive_by_axis["Y"] = current_time
                
            if (
                z_movement != last_z_movement
                or (z_movement != 0 and current_time - last_keepalive_by_axis["Z"] >= JOG_KEEPALIVE_INTERVAL)
            ):
                queue_hardware_command("update_state", ("xy_stage.continuous_movement.Z", z_movement))
                last_z_movement = z_movement
                last_keepalive_by_axis["Z"] = current_time
                
        except Exception as e:
            console.print(f"[bold red]Key monitor error: {e}[/]")
            
        # Adaptive delay - longer when no keys pressed to reduce CPU usage
        if any(current_key_states.values()):
            time.sleep(0.001)  # 1ms when keys are active
        else:
            time.sleep(0.01)   # 10ms when idle to reduce CPU load

# -----------------------------------------------------------------------------
# Main Control Stage
# -----------------------------------------------------------------------------
def control_stage():
    """Runs the manual control interface while streaming both the camera and microscope."""

    # Set auto exposure for microscope via centralized update logic
    box.update_state("microscope_settings.auto_exposure", False)
    box.update_state("camera_settings.auto_exposure", False)

    # Start streaming threads for camera and microscope.
    threads.append(threading.Thread(target=stream_camera, args=(box.camera, "Camera Stream"), daemon=True))
    # threads.append(threading.Thread(target=stream_camera, args=(box, "Microscope Stream"), daemon=True))
    threads.append(threading.Thread(target=stream_camera, args=(0, "Device Stream", True), daemon=True))  # System webcam

    for thread in threads:
        thread.start()

    # Start the key state monitoring thread
    key_monitor_thread = threading.Thread(target=monitor_key_states, daemon=True)
    threads.append(key_monitor_thread)
    key_monitor_thread.start()

    def handle_keyboard_input():
        """Handle keyboard input using direct key polling for all keys."""
        global POSITION, LIGHT_STATUS, adjusting_light, light_input, adjusting_light_type, exposure_input, adjusting_exposure
        global adjusting_temperature, temperature_input, TARGET_TEMPERATURE, adjusting_gain, gain_input
        global show_green_dot, last_key_activity, key_pressed_states
        global adjusting_electrode_position, electrode_input
        
        # Check for non-movement key presses using Windows API
        try:
            # Define key codes
            VK_ENTER = 0x0D
            VK_BACKSPACE = 0x08
            VK_ESCAPE = 0x1B
            
            # Helper function for debounced key detection
            def is_key_just_pressed(key_code):
                current_state = is_key_pressed(key_code)
                previous_state = key_pressed_states.get(key_code, False)
                key_pressed_states[key_code] = current_state
                return current_state and not previous_state
            
            # Function keys and special commands (only trigger once per press)
            if is_key_just_pressed(ord('Q')):
                exit_flag.set()
                return False
            
            if is_key_just_pressed(ord('C')) and not adjusting_light and not adjusting_temperature and not adjusting_exposure and not adjusting_gain and not adjusting_electrode_position:
                adjusting_light = True
                light_input = ""
                adjusting_light_type = "Coaxial"
            
            if is_key_just_pressed(ord('R')) and not adjusting_light and not adjusting_temperature and not adjusting_exposure and not adjusting_gain and not adjusting_electrode_position:
                adjusting_light = True
                light_input = ""
                adjusting_light_type = "Ring"
            
            if is_key_just_pressed(ord('F')) and not adjusting_light and not adjusting_temperature and not adjusting_exposure and not adjusting_gain and not adjusting_electrode_position:
                if box.state["microscope_settings"]["current_channel"] == "FAM":
                    queue_hardware_command("update_state", ("microscope_settings.current_channel", "Brightfield"))
                else:
                    queue_hardware_command("update_state", ("microscope_settings.current_channel", "FAM"))
            
            if is_key_just_pressed(ord('T')) and not adjusting_temperature and not adjusting_light and not adjusting_exposure and not adjusting_gain and not adjusting_electrode_position:
                adjusting_temperature = True
                temperature_input = ""
            
            if is_key_just_pressed(ord('E')) and not adjusting_light and not adjusting_temperature and not adjusting_exposure and not adjusting_gain and not adjusting_electrode_position:
                animate_electrode_columns()
            
            if is_key_just_pressed(ord('D')) and not adjusting_light and not adjusting_temperature and not adjusting_exposure and not adjusting_gain and not adjusting_electrode_position:
                show_green_dot = not show_green_dot
            
            if is_key_just_pressed(ord('P')) and not adjusting_light and not adjusting_temperature and not adjusting_exposure and not adjusting_gain and not adjusting_electrode_position:
                # Toggle electrode overlay
                try:
                    if hasattr(box, 'visualizers') and hasattr(box.visualizers, 'streamer') and box.visualizers.streamer:
                        box.visualizers.streamer.electrode_overlay = not getattr(box.visualizers.streamer, 'electrode_overlay', False)
                        console.print(f"[bold green]Electrode overlay {'enabled' if box.visualizers.streamer.electrode_overlay else 'disabled'}[/]")
                    else:
                        console.print("[bold red]No streamer visualizer available[/]")
                except Exception as e:
                    console.print(f"[bold red]Error toggling electrode overlay: {e}[/]")
            
            if is_key_just_pressed(ord('M')) and not adjusting_light and not adjusting_temperature and not adjusting_exposure and not adjusting_gain and not adjusting_electrode_position:
                queue_hardware_command("update_state", ("xy_stage.position", {"X": 95206, "Y": 5120, "Z": 10899}))
            
            if is_key_just_pressed(ord('L')) and not adjusting_exposure and not adjusting_light and not adjusting_temperature and not adjusting_gain and not adjusting_electrode_position:
                adjusting_exposure = True
                exposure_input = ""
            
            if is_key_just_pressed(ord('G')) and not adjusting_gain and not adjusting_light and not adjusting_temperature and not adjusting_exposure and not adjusting_electrode_position:
                adjusting_gain = True
                gain_input = ""
            
            if is_key_just_pressed(ord('O')) and not adjusting_electrode_position and not adjusting_light and not adjusting_temperature and not adjusting_exposure and not adjusting_gain:
                adjusting_electrode_position = True
                electrode_input = ""
            
            if is_key_just_pressed(ord('K')) and not adjusting_light and not adjusting_temperature and not adjusting_exposure and not adjusting_gain and not adjusting_electrode_position:
                # Launch debug key window
                if not debug_window_active:
                    debug_thread = threading.Thread(target=debug_key_window, daemon=True)
                    threads.append(debug_thread)
                    debug_thread.start()
            
            # Speed control (only trigger once per press and NOT during input modes)
            if not adjusting_light and not adjusting_temperature and not adjusting_exposure and not adjusting_gain and not adjusting_electrode_position:
                if is_key_just_pressed(ord('1')):
                    queue_hardware_command("update_state", ("xy_stage.motion_params.dMaxV", 10))
                    queue_hardware_command("update_state", ("xy_stage.motion_params.dMaxA", 100))
                elif is_key_just_pressed(ord('2')):
                    queue_hardware_command("update_state", ("xy_stage.motion_params.dMaxV", 100))
                    queue_hardware_command("update_state", ("xy_stage.motion_params.dMaxA", 1000))
                elif is_key_just_pressed(ord('3')):
                    queue_hardware_command("update_state", ("xy_stage.motion_params.dMaxV", 1000))
                    queue_hardware_command("update_state", ("xy_stage.motion_params.dMaxA", 10000))
                elif is_key_just_pressed(ord('4')):
                    queue_hardware_command("update_state", ("xy_stage.motion_params.dMaxV", 10000))
                    queue_hardware_command("update_state", ("xy_stage.motion_params.dMaxA", 100000))
            
            # Handle input modes
            if adjusting_light:
                if is_key_just_pressed(VK_BACKSPACE) and light_input:
                    light_input = light_input[:-1]
                elif is_key_just_pressed(VK_ENTER):
                    if light_input.isdigit() and 0 <= int(light_input) <= 99:
                        intensity = int(light_input)
                        if adjusting_light_type == "Coaxial":
                            queue_hardware_command("update_state", ("light_settings.coaxial_intensity", intensity))
                            LIGHT_STATUS["Coaxial"] = intensity
                        elif adjusting_light_type == "Ring":
                            queue_hardware_command("update_state", ("light_settings.ring_intensity", intensity))
                            LIGHT_STATUS["Ring"] = intensity
                    else:
                        queue_hardware_command("print", "[bold red]❌ Error: Light intensity must be between 0-99.[/]")
                    adjusting_light = False
                    light_input = ""
                elif is_key_just_pressed(VK_ESCAPE):
                    adjusting_light = False
                    light_input = ""
                else:
                    # Check for digit input using proper VK codes
                    for digit in range(10):
                        if is_key_just_pressed(VK_DIGITS[digit]) and len(light_input) < 2:
                            light_input += str(digit)
                            break
            
            elif adjusting_exposure:
                if is_key_just_pressed(VK_BACKSPACE) and exposure_input:
                    exposure_input = exposure_input[:-1]
                elif is_key_just_pressed(VK_ENTER):
                    if exposure_input.isdigit() and 0 <= int(exposure_input) <= 99999448:
                        exposure_time = int(exposure_input)
                        queue_hardware_command("update_state", ("camera_settings.exposure_time", exposure_time))
                        queue_hardware_command("update_state", ("microscope_settings.exposure_time", exposure_time))
                    adjusting_exposure = False
                    exposure_input = ""
                elif is_key_just_pressed(VK_ESCAPE):
                    adjusting_exposure = False
                    exposure_input = ""
                else:
                    # Check for digit input using proper VK codes
                    for digit in range(10):
                        if is_key_just_pressed(VK_DIGITS[digit]) and len(exposure_input) < 8:
                            exposure_input += str(digit)
                            break
            
            elif adjusting_temperature:
                if is_key_just_pressed(VK_BACKSPACE) and temperature_input:
                    temperature_input = temperature_input[:-1]
                elif is_key_just_pressed(VK_ENTER):
                    if temperature_input.isdigit() and TEMP_MIN <= int(temperature_input) <= TEMP_MAX:
                        temperature = int(temperature_input)
                        queue_hardware_command("update_state", ("temperature.target", temperature))
                        TARGET_TEMPERATURE = temperature
                    else:
                        queue_hardware_command("print", f"[bold red]❌ Error: Temperature must be between {TEMP_MIN}-{TEMP_MAX}.[/]")
                    adjusting_temperature = False
                    temperature_input = ""
                elif is_key_just_pressed(VK_ESCAPE):
                    adjusting_temperature = False
                    temperature_input = ""
                else:
                    # Check for digit input using proper VK codes
                    for digit in range(10):
                        if is_key_just_pressed(VK_DIGITS[digit]) and len(temperature_input) < 2:
                            temperature_input += str(digit)
                            break
            
            elif adjusting_gain:
                if is_key_just_pressed(VK_BACKSPACE) and gain_input:
                    gain_input = gain_input[:-1]
                elif is_key_just_pressed(VK_ENTER):
                    if gain_input.isdigit() and 0 <= int(gain_input) <= 100:
                        gain_value = int(gain_input)
                        queue_hardware_command("update_state", ("microscope_settings.gain", gain_value))
                    else:
                        queue_hardware_command("print", "[bold red]❌ Error: Analog gain must be between 0-100.[/]")
                    adjusting_gain = False
                    gain_input = ""
                elif is_key_just_pressed(VK_ESCAPE):
                    adjusting_gain = False
                    gain_input = ""
                else:
                    # Check for digit input using proper VK codes
                    for digit in range(10):
                        if is_key_just_pressed(VK_DIGITS[digit]) and len(gain_input) < 3:
                            gain_input += str(digit)
                            break
            
            elif adjusting_electrode_position:
                if is_key_just_pressed(VK_BACKSPACE) and electrode_input:
                    electrode_input = electrode_input[:-1]
                elif is_key_just_pressed(VK_ENTER):
                    try:
                        # Parse row,col
                        parts = electrode_input.replace(' ', '').split(',')
                        if len(parts) == 2:
                            row = int(parts[0])
                            col = int(parts[1])
                            # Use electrode_to_stage to get coordinates
                            coords = electrode_to_stage(row, col)
                            queue_hardware_command("update_state", ("xy_stage.position", coords))
                            queue_hardware_command("print", f"[bold green]✅ Moving to electrode ({row}, {col}) at X={coords['X']}, Y={coords['Y']}, Z={coords['Z']}[/]")
                        else:
                            queue_hardware_command("print", "[bold red]❌ Error: Input must be in format 'row,col' (e.g. 5,10)[/]")
                    except ValueError:
                        queue_hardware_command("print", "[bold red]❌ Error: Invalid electrode coordinates. Use format 'row,col' with numbers.[/]")
                    except Exception as e:
                        queue_hardware_command("print", f"[bold red]❌ Error moving to electrode: {e}[/]")
                    adjusting_electrode_position = False
                    electrode_input = ""
                elif is_key_just_pressed(VK_ESCAPE):
                    adjusting_electrode_position = False
                    electrode_input = ""
                else:
                    # Allow digits and comma
                    for digit in range(10):
                        if is_key_just_pressed(VK_DIGITS[digit]) and len(electrode_input) < 10:
                            electrode_input += str(digit)
                            break
                    # Use VK_OEM_COMMA for comma key
                    VK_OEM_COMMA = 0xBC
                    if is_key_just_pressed(VK_OEM_COMMA) and len(electrode_input) < 10:
                        electrode_input += ','
            
            # Position updates moved to separate thread to avoid blocking key input
            
        except Exception as e:
            console.print(f"[bold red]❌ Error: {e}[/]")
            close()

    # Separate temperature reading to its own thread to avoid blocking key input
    def temperature_reader():
        while not exit_flag.is_set():
            try:
                temperature = box.temperature.get_temperature()
                if temperature is not None:
                    temperature_history.append(temperature)
            except Exception:
                pass
            time.sleep(0.1)  # Read temperature every 100ms
    
    # Separate position reading to its own thread to avoid blocking key input
    def position_reader():
        while not exit_flag.is_set():
            try:
                POSITION["X"] = box.xy_stage.get_position("X")
                POSITION["Y"] = box.xy_stage.get_position("Y")
                POSITION["Z"] = box.xy_stage.get_position("Z")
            except Exception:
                pass
            time.sleep(0.05)  # Update position every 50ms
    
    # No hardware command processor needed - DropLogic parent handles queue processing
    
    temp_thread = threading.Thread(target=temperature_reader, daemon=True)
    pos_thread = threading.Thread(target=position_reader, daemon=True)
    threads.extend([temp_thread, pos_thread])
    temp_thread.start()
    pos_thread.start()
    
    with Live(Group(get_controls_panel(), get_status_panel()), refresh_per_second=10) as live:
        last_ui_update = time.time()
        
        while not exit_flag.is_set():
            current_time = time.time()
            
            # Handle keyboard input (highest priority - no blocking operations)
            try:
                handle_keyboard_input()
            except Exception:
                pass
            
            # Update UI only every 100ms to avoid blocking key input
            if current_time - last_ui_update > 0.1:
                live.update(Group(get_controls_panel(), get_status_panel()))
                last_ui_update = current_time
            
            # Quick OpenCV check (reduce from 10ms to 1ms)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                exit_flag.set()
                break
            
            # Minimal delay for maximum responsiveness
            time.sleep(0.001)  # 1ms for maximum key responsiveness

    close()
    console.print("[bold red]Exited Manual Control Mode.[/]")
    time.sleep(1)

def show_controls():

    """Displays the control panel and status panel."""
    console.print(get_controls_panel())
    console.print(get_status_panel())

def stop_all_jogs():
    """Force-stop all jog axes immediately."""
    if 'box' not in globals() or box is None:
        return

    for axis in ("X", "Y", "Z"):
        try:
            box.update_state(f"xy_stage.continuous_movement.{axis}", 0, priority=Priority.HIGH)
        except Exception:
            pass

    xy_stage = getattr(box, "xy_stage", None)
    if xy_stage is None:
        return

    for axis in ("X", "Y", "Z"):
        try:
            xy_stage.stop_continuous_movement(axis)
        except Exception:
            try:
                xy_stage.stop_motion(axis)
            except Exception:
                pass

def close():
    global box, closed  # Declare global so we refer to the global variable
    with close_lock:
        if closed:
            return
        closed = True
        if not exit_flag.is_set():
            exit_flag.set()

        # Reset key states and stop movements first
        stop_all_jogs()
        
        for thread in threads:
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=2)
        cv2.destroyAllWindows()
        exit_flag.clear()
        threads.clear()
        
        if box is not None:
            box.close()
            # Delete the box object and set it to None
            del box
            box = None
        gc.collect()
        console.print("[bold red]Exited Manual Control Mode.[/]")

def run():
    clear_screen()
    try:
        global box, closed
        closed = False
        config_path = resolve_config_path()
        box = BOXMini(config_file=str(config_path))  # Create a new instance each time run() is called
        box.visualizers.streamer.start()
        clear_screen()
        # Main loop!
        control_stage()
    except KeyboardInterrupt:
        close()
    finally:
        close()


def main():
    run()


if __name__ == "__main__":
    main()

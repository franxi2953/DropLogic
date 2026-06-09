import ctypes
import os
import platform
import time
from pathlib import Path

from droplogic.utils.logging_config import setup_droplogic_logger
from droplogic.utils.native_runtime import resolve_dll


logger = setup_droplogic_logger("droplogic.electrode_matrix.dmlite")
_dll_directory_handles = []


class Drop(ctypes.Structure):
    _fields_ = [
        ("height", ctypes.c_int),
        ("width", ctypes.c_int),
        ("row", ctypes.c_int),
        ("col", ctypes.c_int),
    ]


def _platform_sdk_name():
    system = platform.system()
    if system == "Windows":
        return "sdk.dll"
    if system == "Darwin":
        return "sdk.dylib"
    if system == "Linux":
        return "sdk.so"
    raise RuntimeError(
        f"DMLite native hardware control is not supported on {system or 'this OS'}."
    )


def _platform_sdk_subdir():
    if platform.system() != "Linux":
        return None

    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "linux-x86_64"
    if machine in {"aarch64", "arm64"}:
        return "linux-aarch64"
    if machine in {"armv7l", "armv7", "armhf"}:
        return "linux-armv7l"

    raise RuntimeError(
        "DMLite Linux native hardware control is not supported on "
        f"{machine or 'this architecture'}."
    )


def _runtime_relative_sdk_path():
    sdk_name = _platform_sdk_name()
    sdk_subdir = _platform_sdk_subdir()
    if sdk_subdir:
        return f"electrode_matrix/dmlite/{sdk_subdir}/{sdk_name}"
    return f"electrode_matrix/dmlite/{sdk_name}"


def _candidate_local_sdks():
    sdk_name = _platform_sdk_name()
    sdk_subdir = _platform_sdk_subdir()
    current_dir = Path(__file__).resolve().parent
    candidates = [
        current_dir / "sdk" / "bin" / sdk_subdir / sdk_name
        if sdk_subdir
        else current_dir / "sdk" / "bin" / sdk_name,
    ]

    try:
        repo_root = Path(__file__).resolve().parents[5]
        vendor_dir = repo_root / "vendor_bin" / "electrode_matrix" / "dmlite"
        if sdk_subdir:
            candidates.append(vendor_dir / sdk_subdir / sdk_name)
        candidates.append(vendor_dir / sdk_name)
    except IndexError:
        pass

    return candidates


def _resolve_sdk_library():
    last_error = None
    relative_path = _runtime_relative_sdk_path()
    for fallback in _candidate_local_sdks():
        try:
            sdk_path = resolve_dll(relative_path, str(fallback))
            if os.path.exists(sdk_path):
                return sdk_path
        except FileNotFoundError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise FileNotFoundError(f"DMLite SDK library could not be resolved: {relative_path}")


def _load_sdk():
    try:
        sdk_path = _resolve_sdk_library()
        sdk_dir = os.path.dirname(os.path.abspath(sdk_path))
        if platform.system() == "Windows" and hasattr(os, "add_dll_directory"):
            _dll_directory_handles.append(os.add_dll_directory(sdk_dir))
        sdk = ctypes.CDLL(sdk_path)
        _bind_sdk_signatures(sdk)
        return sdk
    except Exception as exc:
        raise RuntimeError(f"Failed to load DMLite SDK for {platform.system()}: {exc}") from exc


def _bind_sdk_signatures(sdk):
    sdk.InitUSB.restype = ctypes.c_int
    sdk.InitUSB.argtypes = []

    sdk.OpenUSB.restype = ctypes.c_int
    sdk.OpenUSB.argtypes = []

    sdk.CloseUSB.restype = ctypes.c_int
    sdk.CloseUSB.argtypes = []

    sdk.SetPower.restype = ctypes.c_int
    sdk.SetPower.argtypes = [ctypes.c_bool]

    sdk.SetVolt.restype = ctypes.c_int
    sdk.SetVolt.argtypes = [ctypes.c_int] * 9

    sdk.InquireVolt.restype = ctypes.c_int
    sdk.InquireVolt.argtypes = [ctypes.POINTER(ctypes.c_int)] * 9

    sdk.ActivateElec.restype = ctypes.c_bool
    sdk.ActivateElec.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(Drop),
    ]


microfluidics = _load_sdk()


class DMLite:
    def __init__(
        self,
        device=None,
        rows=128,
        columns=128,
        initial_voltage=55,
        debug=False,
        port=1,
        baud_rate=9600,
        log_level="INFO",
    ):
        self.device = device
        self.rows = int(rows)
        self.columns = int(columns)
        self.cols = self.columns
        self.port = port
        self.baud_rate = baud_rate
        self.debug = debug
        self.initialized = False
        self.connected = False
        self.electrode_states = [[0] * self.columns for _ in range(self.rows)]
        self.matrix = self.electrode_states
        self.logger = logger

        try:
            startup_voltage = int(initial_voltage)
        except (TypeError, ValueError):
            startup_voltage = 55
        startup_voltage = max(0, min(255, startup_voltage))
        self.voltage = startup_voltage
        self.initialized_voltages = [startup_voltage] * 9

        if microfluidics is None:
            raise RuntimeError(
                "DMLite native SDK could not be loaded. Install the DropLogic runtime "
                "assets for this OS before using DMLite hardware control."
            )

        self.init_board()

    def init_board(self, baud_rate=None, port_number=None):
        if microfluidics is None:
            self.initialized = True
            self.connected = False
            return True

        if self.initialized:
            return True

        if self.debug:
            self.logger.info(
                "Initializing DMLite matrix (rows=%s, columns=%s)",
                self.rows,
                self.columns,
            )

        self._helper_initialize()
        self.initialized = True
        self.connected = True
        return True

    def set_voltage(self, voltage):
        voltage_values = self._normalize_voltage(voltage)
        self.voltage = voltage_values[0]
        self.initialized_voltages = voltage_values

        if microfluidics is None:
            return True

        result = microfluidics.SetVolt(*voltage_values)
        if result != 0:
            raise RuntimeError(f"SetVolt failed with code {result}")
        if self.debug:
            self.logger.info("DMLite voltage set to %s", voltage_values)
        return True

    def set_electrode(self, row, col, state):
        row = int(row)
        col = int(col)
        if row < 0 or row >= self.rows or col < 0 or col >= self.columns:
            raise ValueError("Invalid row or column index")

        self.electrode_states[row][col] = 1 if state else 0
        if state:
            return self.set_droplets(
                [{"row": row, "col": col, "width": 1, "height": 1, "state": 1}]
            )

        return self._update_device_state()

    def set_chip(self, matrix):
        if len(matrix) != self.rows or any(len(row) != self.columns for row in matrix):
            raise ValueError("Matrix dimensions do not match configured grid")

        self.electrode_states = [
            [1 if int(value) else 0 for value in row]
            for row in matrix
        ]
        self.matrix = self.electrode_states
        return self._update_device_state()

    def set_droplet(self, row, col, width=1, height=1, state=1):
        return self.set_droplets(
            [{"row": row, "col": col, "width": width, "height": height, "state": state}]
        )

    def set_droplets(self, droplets):
        active_drops = []

        for droplet in droplets:
            row = int(droplet.get("row", 0))
            col = int(droplet.get("col", 0))
            width = int(droplet.get("width", 1))
            height = int(droplet.get("height", 1))
            state = 1 if droplet.get("state", 1) else 0

            if row < 0 or col < 0 or row + height > self.rows or col + width > self.columns:
                if self.debug:
                    self.logger.warning("Droplet at (%s, %s) out of bounds", row, col)
                continue

            for r in range(row, row + height):
                for c in range(col, col + width):
                    self.electrode_states[r][c] = state

            if state:
                active_drops.append(Drop(height, width, row, col))

        self.matrix = self.electrode_states
        if active_drops:
            return self._activate_drops(active_drops)

        return self._update_device_state()

    def deactivate_all(self):
        self.electrode_states = [[0] * self.columns for _ in range(self.rows)]
        self.matrix = self.electrode_states
        return self._activate_drops([])

    def close(self):
        if not self.initialized and microfluidics is None:
            return True

        if microfluidics is not None and self.initialized:
            try:
                self.deactivate_all()
                microfluidics.SetPower(False)
                microfluidics.CloseUSB()
            finally:
                self.initialized = False
                self.connected = False
        else:
            self.initialized = False
            self.connected = False
        return True

    def send_ascii_command(self, hex_command):
        self.logger.warning("Raw ASCII commands are not supported by the DMLite SDK adapter")
        return None

    def _query_voltage(self):
        if microfluidics is None:
            return tuple(self.initialized_voltages)

        values = [ctypes.c_int(index + 1) for index in range(9)]
        result = microfluidics.InquireVolt(*[ctypes.byref(value) for value in values])
        if result < 0:
            raise RuntimeError(f"InquireVolt failed with code {result}")
        return tuple(value.value for value in values)

    def _helper_initialize(self):
        init_result = microfluidics.InitUSB()
        open_result = microfluidics.OpenUSB()

        while open_result == -255:
            microfluidics.SetPower(False)
            microfluidics.CloseUSB()
            time.sleep(0.5)
            init_result = microfluidics.InitUSB()
            open_result = microfluidics.OpenUSB()

        if init_result != 0 and self.debug:
            self.logger.warning("DMLite InitUSB returned %s", init_result)
        if open_result != 0 and self.debug:
            self.logger.warning("DMLite OpenUSB returned %s", open_result)

        power_result = microfluidics.SetPower(True)
        if power_result != 0 and self.debug:
            self.logger.warning("DMLite SetPower(True) returned %s", power_result)

        self.set_voltage(self.initialized_voltages)
        time.sleep(1)

        try:
            queried = self._query_voltage()
        except Exception as exc:
            raise RuntimeError(f"DMLite voltage query failed after initialization: {exc}") from exc

        if abs(queried[0] - self.initialized_voltages[0]) < 2:
            return

        microfluidics.SetPower(False)
        microfluidics.CloseUSB()
        self._helper_initialize()

    def _activate_drops(self, active_drops):
        if microfluidics is None:
            return True

        if active_drops:
            drops_array = (Drop * len(active_drops))(*active_drops)
        else:
            drops_array = (Drop * 1)()

        result = microfluidics.ActivateElec(
            self.rows,
            self.columns,
            len(active_drops),
            drops_array,
        )
        if active_drops and not result:
            raise RuntimeError("ActivateElec failed")
        return True

    def _update_device_state(self):
        active_drops = []
        for row in range(self.rows):
            for col in range(self.columns):
                if self.electrode_states[row][col]:
                    active_drops.append(Drop(1, 1, row, col))
        return self._activate_drops(active_drops)

    def _normalize_voltage(self, voltage):
        if isinstance(voltage, int):
            values = [voltage] * 9
        elif isinstance(voltage, (list, tuple)) and len(voltage) == 9:
            values = list(voltage)
        else:
            raise ValueError("Voltage must be an int or a list/tuple of 9 values")

        return [max(0, min(255, int(value))) for value in values]

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

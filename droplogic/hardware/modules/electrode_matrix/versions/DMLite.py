import os
import platform
import ctypes
from typing import List
from droplogic.utils.logging_config import setup_droplogic_logger

from droplogic.utils.native_runtime import resolve_dll

logger = setup_droplogic_logger("droplogic.electrode_matrix.dmlite")

# Define the absolute path to the DLL
dll_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sdk', 'bin')
local_dll_path = os.path.join(dll_folder, 'sdk.dll')

# Solo intentar cargar la DLL si estamos en Windows
microfluidics = None
if platform.system() == 'Windows':
    try:
        dll_path = resolve_dll('electrode_matrix/dmlite/sdk.dll', local_dll_path)
        microfluidics = ctypes.CDLL(dll_path)
    except Exception as e:
        logger.error(f"Failed to load DMLite DLL: {e}")
        microfluidics = None
else:
    logger.warning("DMLite hardware is conceptually disabled on non-Windows OS (no DLL support)")

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
        self.port = port
        self.baud_rate = baud_rate
        self.voltage = initial_voltage
        self.debug = debug
        self.status = 1  
        self.error_count = 0  
        self.connected = False  
        self.matrix = [[0 for _ in range(self.columns)] for _ in range(self.rows)]
        
        self.logger = logger
        
        if microfluidics:
            self.logger.info("Initializing communication with DMLite...")
        else:
            self.logger.warning("DMLite runs in mock/simulation mode natively because DLL is missing or OS is not Windows.")

    def close(self):
        if microfluidics:
            microfluidics.close_port()
        self.logger.info("Connection with DMLite closed safely")

    def init_board(self, baud_rate=None, port_number=None):
        if not microfluidics:
            return 1
        baud_rate = baud_rate or self.baud_rate
        port_number = port_number or self.port
        ans = microfluidics.SetParam(baud_rate, port_number - 1, 0, 0, 0)
        return ans

    def update_board(self, flat_matrix: List[int], port_number=None):
        if not microfluidics:
            return True
        port_number = port_number or self.port
        c_matrix = (ctypes.c_int * len(flat_matrix))(*flat_matrix)
        result = microfluidics.send_electrode(c_matrix, port_number - 1)
        if result == 1:
            self.error_count += 1
            if self.error_count > 5:
                self.error_count = 0
                return False
        else:
            self.status = 1
        return True

    def set_voltage(self, voltage):
        self.voltage = voltage
        return True

    def _flatten_matrix(self, matrix):
        return [int(value) for row in matrix for value in row]

    def set_chip(self, matrix):
        self.matrix = [[int(value) for value in row] for row in matrix]
        return self.update_board(self._flatten_matrix(self.matrix))

    def set_electrode(self, row, col, state):
        row = int(row)
        col = int(col)
        if row < 0 or row >= self.rows or col < 0 or col >= self.columns:
            return False
        self.matrix[row][col] = 1 if state else 0
        return self.set_chip(self.matrix)

    def deactivate_all(self):
        self.matrix = [[0 for _ in range(self.columns)] for _ in range(self.rows)]
        return self.set_chip(self.matrix)

    def set_droplet(self, row, col, width=1, height=1, state=1):
        row = int(row)
        col = int(col)
        width = int(width)
        height = int(height)
        value = 1 if state else 0
        for r in range(row, row + height):
            for c in range(col, col + width):
                if 0 <= r < self.rows and 0 <= c < self.columns:
                    self.matrix[r][c] = value
        return self.set_chip(self.matrix)

    def set_droplets(self, droplets):
        for droplet in droplets:
            self.set_droplet(
                droplet.get("row", 0),
                droplet.get("col", 0),
                droplet.get("width", 1),
                droplet.get("height", 1),
                droplet.get("state", 1),
            )
        return self.set_chip(self.matrix)

    def send_ascii_command(self, hex_command):
        self.logger.warning("Raw ASCII commands are not supported by the DMLite SDK adapter")
        return None

    def _query_voltage(self):
        return self.voltage

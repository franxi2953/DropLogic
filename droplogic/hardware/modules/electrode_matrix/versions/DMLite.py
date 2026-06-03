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
    def __init__(self, port, baud_rate, log_level="INFO"):
        self.port = port
        self.baud_rate = baud_rate
        self.status = 1  
        self.error_count = 0  
        self.connected = False  
        
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

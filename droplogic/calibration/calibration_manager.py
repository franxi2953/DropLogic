"""
Calibration Manager for DropLogic hardware systems.

This module provides a central manager for calibration data storage and persistence.
"""

import json
from pathlib import Path

class CalibrationManager:
    """
    Manages calibration data storage and persistence for DropLogic hardware systems.
    
    This class ensures calibration data exists in the system state and provides
    methods to save and load calibration data from files.
    """
    
    def __init__(self, parent):
        """
        Initialize the calibration manager.
        
        Args:
            parent: The parent DropLogic instance that owns this manager.
        """
        self.parent = parent
        self._ensure_calibration_state()
        
    def _ensure_calibration_state(self):
        """Ensure calibration data exists in the system state."""
        if "calibration" not in self.parent.state:
            # Initialize with default calibration values
            self.parent.update_state("calibration", {
                "xy_factor": {"X": 0.001, "Y": 0.001, "Z": 0.001},  # Default: 1 step = 0.001 mm
                "chip_origin": {"X": 0, "Y": 0},
                "electrode_mapping": {
                    "offset_x": 0,
                    "offset_y": 0,
                    "rotation": 0,
                    "scale_x": 0.1,  # Default: 1 electrode = 0.1 mm
                    "scale_y": 0.1
                },
                "field_of_view": {"width": 0, "height": 0}
            })
    
    def save_calibration(self, file_path=None):
        """
        Save calibration data to a file.
        
        Args:
            file_path: Path to save the calibration data. If None, uses default.
        """
        if file_path is None:
            file_path = Path("calibration_data.json")
        
        with open(file_path, 'w') as f:
            json.dump(self.parent.state["calibration"], f, indent=2)
        
        print(f"Calibration data saved to {file_path}")
    
    def load_calibration(self, file_path=None):
        """
        Load calibration data from a file.
        
        Args:
            file_path: Path to load the calibration data from. If None, uses default.
        """
        if file_path is None:
            file_path = Path("calibration_data.json")
        
        try:
            with open(file_path, 'r') as f:
                calibration_data = json.load(f)
                self.parent.update_state("calibration", calibration_data)
            print(f"Calibration data loaded from {file_path}")
        except FileNotFoundError:
            print(f"Calibration file {file_path} not found. Using defaults.")
        except json.JSONDecodeError:
            print(f"Error parsing calibration file {file_path}. Using defaults.")

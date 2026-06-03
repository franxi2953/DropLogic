"""
XY Stage Calibration for DropLogic hardware systems.

This module provides utilities for calibrating the correlation between
XY stage steps and physical distances in millimeters.
"""

class XYCalibration:
    """
    XY calibration functionality for DropLogic hardware systems.
    
    This class provides methods to calibrate the correlation between
    XY stage steps and physical distances in millimeters, as well as
    chip origin calibration.
    """
    
    def __init__(self, parent):
        """
        Initialize the XY calibration module.
        
        Args:
            parent: The parent DropLogic instance that owns this calibrator.
        """
        self.parent = parent
    
    def set_chip_origin(self, x_position, y_position):
        """
        Set the chip origin (0,0) coordinates in the XY stage coordinate system.
        
        This method sets the specified position as the chip origin (0,0) in the
        chip coordinate system. All subsequent chip coordinates will be relative
        to this origin point.
        
        Args:
            x_position: The X position in stage coordinates to set as chip origin
            y_position: The Y position in stage coordinates to set as chip origin
            
        Returns:
            A dictionary with the new chip origin coordinates
        """
        # Update the calibration data in the system state
        self.parent.update_state("calibration.chip_origin.X", x_position)
        self.parent.update_state("calibration.chip_origin.Y", y_position)
        
        # Return the new origin
        return {"X": x_position, "Y": y_position}

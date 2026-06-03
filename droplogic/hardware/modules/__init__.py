# DropSystem Modules Package Initialization

from .temperature import TemperatureModule
from .electrode_matrix import ElectrodeMatrixModule
from .capacitive_feedback import CapacitiveFeedbackModule
from .microscope import MicroscopeModule
from .xy_stage import XYStageModule
from .camera import CameraModule
from .light import LightModule  

# Define what gets imported when using `from droplogic.modules import *`
__all__ = [
    "TemperatureModule",
    "ElectrodeMatrixModule",
    "CapacitiveFeedbackModule",
    "MicroscopeModule",
    "XYStageModule",
    "CameraModule",
    "LightModule",  
]


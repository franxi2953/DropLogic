from .microscope_factory import MicroscopeFactory

class MicroscopeModule:
    """Handles microscope operations with version control."""
    
    SUPPORTED_VERSIONS = {
        "MicroscopeV1": "MicroscopeV1",
        # Future versions can be added here
    }

    def __init__(self, serial, parent=None, version="MicroscopeV1"):
        self.parent = parent

        if version not in self.SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported microscope version: {version}")

        self.microscope = MicroscopeFactory.create_microscope(parent, serial, self.SUPPORTED_VERSIONS[version])

    def open_microscope(self):
        """Opens the microscope, which is essentially a second camera."""
        self.microscope.open_microscope()

    ## ===================== CAMERA-BASED FUNCTIONS ===================== ##
    def enum_devices(self):
        """Enumerates available microscope cameras."""
        return self.microscope.enum_devices()
    
    def close(self):
        """Closes the microscope."""
        self.microscope.close()

    def capture_image(self, save_path="results/microscope.bmp", display=False):
        """Captures an image from the microscope."""
        return self.microscope.capture_image(save_path, display)

    ## ===================== PARAMETER SETTERS ===================== ##
    def set_parameter(self, param_type, node_name, node_value):
        """Sets a microscope parameter."""
        self.microscope.set_parameter(param_type, node_name, node_value)

    def set_exposure(self, exposure_time):
        """Sets the microscope camera exposure time (in µs)."""
        self.microscope.set_exposure(exposure_time)

    def set_exposure_auto(self, enable=True):
        """Enables or disables auto exposure."""
        self.microscope.set_exposure_auto(enable)
    
    def set_channel(self, channel):
        """Sets the microscope channel."""
        self.microscope.set_channel(channel)

    ## ===================== PARAMETER GETTERS ===================== ##
    def get_parameter(self, param_type, node_name):
        """Gets a microscope parameter."""
        return self.microscope.get_parameter(param_type, node_name)

    def get_exposure(self):
        """Gets the microscope camera exposure time (in µs)."""
        return self.microscope.get_exposure()

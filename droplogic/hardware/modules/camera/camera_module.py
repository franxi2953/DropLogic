from .camera_factory import CameraFactory

class CameraModule:
    """Handles camera operations with version control."""

    SUPPORTED_VERSIONS = {
        "CameraV1": "CameraV1",
        # Future versions can be added here
    }

    def __init__(self, parent, version="CameraV1"):
        self.parent = parent

        if version not in self.SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported camera version: {version}")

        self.camera = CameraFactory.create_camera(parent, self.SUPPORTED_VERSIONS[version])

    ## ===================== CORE CAMERA FUNCTIONS ===================== ##
    def enum_devices(self):
        """Enumerates available cameras and returns a list."""
        return self.camera.enum_devices()
    
    def open_camera(self, device_index=0):
        """Opens the camera."""
        self.camera.open_camera(device_index)

    def close(self):
        """Closes the camera."""
        self.camera.close()

    def capture_image(self, save_path="results/0.bmp", display=False, save=False):
        """Captures an image and returns it."""
        return self.camera.capture_image(save_path, display)

    ## ===================== PARAMETER SETTERS ===================== ##

    def set_parameter(self, param_type, node_name, node_value):
        """Sets a camera parameter."""
        self.camera.set_parameter(param_type, node_name, node_value)

    def set_exposure(self, exposure_time):
        """Sets the camera exposure time (in µs)."""
        self.camera.set_exposure(exposure_time)

    def set_exposure_auto(self, enable=True):
        """Enables or disables auto exposure."""
        self.camera.set_exposure_auto(enable)
    ## ===================== PARAMETER GETTERS ===================== ##

    def get_parameter(self, param_type, node_name):
        """Gets a camera parameter."""
        return self.camera.get_parameter(param_type, node_name)

    def get_exposure(self):
        """Gets the camera exposure time (in µs)."""
        return self.camera.get_exposure()

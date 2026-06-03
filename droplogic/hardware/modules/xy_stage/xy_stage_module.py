from .xy_stage_factory import XYStageFactory

class XYStageModule:
    SUPPORTED_VERSIONS = {
        "XYStageV1": "XYStageV1",
        # Future versions can be added here
    }

    def __init__(self, parent=None, version="XYStageV1"):
        """Initialize the XYZ stage module, selecting the appropriate version."""
        self.parent = parent  # Store reference to the parent (e.g., BOXMini)

        if version not in self.SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported XYZ stage version: {version}")

        self.stage = XYStageFactory.create_stage(version, parent=parent)

    def set_params(self, params):
        """Set the parameters of the XYZ stage."""
        self.stage.set_params(params)

    def move_axis_to_position(self, axis, target_position):
        """Move the specified axis by a given distance asynchronously."""
        return self.stage.move_axis_to_position(axis, target_position)

    def start_continuous_movement(self, axis, direction):
        """Start continuous movement of the specified axis."""
        self.stage.start_continuous_movement(axis, direction)

    def stop_continuous_movement(self, axis):
        """Stop continuous movement of the specified axis."""
        self.stage.stop_continuous_movement(axis)
        
    def stop_motion(self, axis, stop_mode=0):
        """Stop the motion of the specified axis."""
        self.stage.stop_motion(axis, stop_mode)

    def is_motion_complete(self, axis):
        """Check if the motion of the specified axis is complete."""
        return self.stage.is_motion_complete(axis)

    def home_axis(self, axis):
        """Home the specified axis synchronously."""
        self.stage.home_axis(axis)

    def is_homing_complete(self, axis):
        """Check if the homing process is complete."""
        return self.stage.is_homing_complete(axis)

    def get_position(self, axis):
        """Retrieve the current position of the specified axis."""
        return self.stage.get_position(axis)

    def get_raw_position(self, axis):
        """Retrieve the current hardware/raw position of the specified axis."""
        return self.stage.get_raw_position(axis)

    def close(self):
        """Close communication with the motion control card."""
        self.stage.close()

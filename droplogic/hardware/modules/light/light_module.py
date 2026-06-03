from .light_factory import LightFactory

class LightModule:
    """Handles light operations with version control."""

    SUPPORTED_VERSIONS = {
        "LightV1": "LightV1",
        "LightV2": "LightV2",
        # Future versions can be added here
    }

    def __init__(self,  parent, ring_serial=None, coaxial_controller=None, version="LightV1"):
        self.parent = parent

        if version not in self.SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported light version: {version}")

        self.light = LightFactory.create_light(ring_serial, coaxial_controller, self.SUPPORTED_VERSIONS[version], parent)

    ## ===================== LIGHT CONTROL FUNCTIONS ===================== ##

    def switch_light(self, on=True):
        """Switches the light source on or off."""
        return self.light.switch_light(on)

    def set_coaxial_light(self, intensity):
        """Sets the coaxial light intensity (0-99)."""
        return self.light.set_coaxial_light(intensity)

    def set_ring_light(self, intensity):
        """Sets the ring light intensity (0-99)."""
        return self.light.set_ring_light(intensity)
    
    def get_state(self):
        """Returns the current state of the light module."""
        return self.light.get_state()

    def close(self):
        """Closes the light module safely."""
        return self.light.close()

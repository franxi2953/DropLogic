class LightFactory:
    """Factory class for creating light controller instances."""

    @staticmethod
    def create_light(ring_serial, coaxial_controller, version, parent=None):
        if version == "LightV1":
            from .versions.light_v1 import LightV1
            return LightV1(ring_serial, parent)
        elif version == "LightV2":
            from .versions.light_v2 import LightV2
            return LightV2(ring_serial, coaxial_controller, parent)
        else:
            raise ValueError(f"Unsupported light version: {version}")

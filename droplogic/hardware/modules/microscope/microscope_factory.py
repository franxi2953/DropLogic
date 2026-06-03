class MicroscopeFactory:
    """Factory class for creating microscope instances based on the requested version."""

    @staticmethod
    def create_microscope(serial, parent, version="MicroscopeV1"):
        """Creates a microscope instance based on the requested version."""
        if version == "MicroscopeV1":
            from .versions.microscope_v1 import MicroscopeV1
            return MicroscopeV1(serial, parent)
        else:
            raise ValueError(f"Unsupported microscope version: {version}")

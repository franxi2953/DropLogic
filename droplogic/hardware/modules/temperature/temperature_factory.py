class TemperatureFactory:
    """Factory class for creating temperature controller instances based on the requested version."""

    @staticmethod
    def create_temperature(serial, version, parent=None):
        """Creates a temperature controller instance based on the requested version."""
        if version == "TemperatureV1":
            from .versions.temperature_v1 import TemperatureV1
            return TemperatureV1(serial)
        elif version == "TemperatureV2":
            from .versions.temperature_v2 import TemperatureV2
            return TemperatureV2(serial, parent)
        else:
            raise ValueError(f"Unsupported temperature controller version: {version}")
    

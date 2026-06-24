from typing import Optional

from .temperature_factory import TemperatureFactory


class TemperatureModule:
    """Handles temperature operations with version control."""

    SUPPORTED_VERSIONS = {
        "TemperatureV1": "TemperatureV1",
        "TemperatureV2": "TemperatureV2",
    }

    def __init__(self, parent, serial, version="TemperatureV1"):
        self.parent = parent

        if version not in self.SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported temperature version: {version}")

        self.temperature_controller = TemperatureFactory.create_temperature(serial, version, parent)

    def send_command(self, command: str) -> str:
        """Sends a command to the temperature controller and returns the response."""
        return self.temperature_controller.send_command(command)

    def set_temperature(self, temp: float):
        """Sets the target temperature in degC."""
        return self.temperature_controller.set_temperature(temp)

    def get_temperature(self) -> Optional[float]:
        """Reads the current temperature."""
        return self.temperature_controller.get_temperature()

    def get_target_temperature(self) -> float:
        """Reads the target temperature."""
        return self.temperature_controller.get_target_temperature()

    def set_default_pid(self):
        """Applies the controller default PID values."""
        return self.temperature_controller.set_default_pid()

    def set_output_limit(self, limit: int):
        """Sets the controller output limit when supported."""
        if not hasattr(self.temperature_controller, "set_output_limit"):
            raise NotImplementedError("This temperature controller does not support output limits")
        return self.temperature_controller.set_output_limit(limit)

    def get_output_limit(self):
        """Reads the controller output limit when supported."""
        if not hasattr(self.temperature_controller, "get_output_limit"):
            raise NotImplementedError("This temperature controller does not support output limits")
        return self.temperature_controller.get_output_limit()

    def set_default_output_limit(self):
        """Applies the calibrated controller output limit when supported."""
        if not hasattr(self.temperature_controller, "set_default_output_limit"):
            raise NotImplementedError("This temperature controller does not support output limits")
        return self.temperature_controller.set_default_output_limit()

    def disable(self):
        """Disables the temperature control loop."""
        return self.temperature_controller.disable()

    def close(self):
        """Closes the temperature controller."""
        self.temperature_controller.close()

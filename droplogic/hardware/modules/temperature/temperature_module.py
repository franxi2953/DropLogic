from .temperature_factory import TemperatureFactory

class TemperatureModule:
    """Handles temperature operations with version control."""
    
    SUPPORTED_VERSIONS = {
        "TemperatureV1": "TemperatureV1",
        "TemperatureV2": "TemperatureV2",
        # Future versions can be added here
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
        """Sets the target temperature (in °C)."""
        return self.temperature_controller.set_temperature(temp)

    def get_temperature(self) -> float:
        """Reads the current temperature."""
        return self.temperature_controller.get_temperature()
    
    def get_target_temperature(self) -> float:
        """Reads the target temperature."""
        return self.temperature_controller.get_target_temperature()
    
    def set_default_pid(self):
        """Applies default PID values (P=50, I=10, D=20)."""
        return self.temperature_controller.set_default_pid()
    
    def close(self):
        """Closes the temperature controller."""
        # Set temperature to 0 to turn off heaters before closing
        try:
            self.set_temperature(0.0)
            self.temperature_controller.logger.info("Set temperature to 0°C before closing")
        except Exception as e:
            self.temperature_controller.logger.warning(f"Failed to set temperature to 0 before closing: {e}")
        self.temperature_controller.close()

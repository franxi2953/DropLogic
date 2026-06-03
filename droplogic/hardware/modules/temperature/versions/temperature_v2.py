import serial
import time
import re
import ast
from droplogic.utils.logging_config import setup_droplogic_logger

class TemperatureV2:
    """Temperature controller implementation for Version 2 (ESP32 firmware v2)."""

    def __init__(self, serial_conn, parent=None):
        # Set up logger from parent if available
        if parent and hasattr(parent, 'logger'):
            self.logger = parent.logger
        else:
            self.logger = setup_droplogic_logger('droplogic.hardware.temperature.v2')

        self.logger.info("Initializing temperature module V2 (ESP32 firmware)...")

        # Get port from config
        self.serial_port = parent.state['temperature']['Port']
        self.target_temp = None

        try:
            # Open serial connection at 115200 baud
            self.ser = serial.Serial(self.serial_port, 115200, timeout=2)
            self.logger.info(f"Serial connection opened on {self.serial_port}")
            
            # Reset ESP32 via DTR/RTS toggle (works with classic USB-Serial, may not with JTAG CDC)
            self.logger.info("Resetting ESP32 via DTR/RTS toggle...")
            self.ser.dtr = False
            self.ser.rts = True
            time.sleep(0.1)
            self.ser.rts = False
            time.sleep(3)  # Wait 3 seconds for ESP32 to boot and stabilize
            
            # Test connection by attempting to read current temperature and wait for it to be > 20°C
            # Retry the reset sequence if needed
            max_reset_attempts = 3
            reset_attempt = 0
            
            while reset_attempt < max_reset_attempts:
                if reset_attempt > 0:
                    self.logger.info(f"Retrying ESP32 reset (attempt {reset_attempt + 1}/{max_reset_attempts})...")
                    # Reset ESP32 via DTR/RTS toggle again
                    self.ser.dtr = False
                    self.ser.rts = True
                    time.sleep(0.1)
                    self.ser.rts = False
                    time.sleep(3)  # Wait 3 seconds for ESP32 to boot and stabilize
                
                self.logger.info("Waiting for device to respond with temperature reading > 20°C...")
                max_temp_attempts = 10  # Try for 10 seconds per reset attempt
                temp_attempt = 0
                temp_received = False
                
                while temp_attempt < max_temp_attempts and not temp_received:
                    temp = self.get_temperature()
                    if temp is not None and temp > 20:
                        self.logger.info(f"Device ready, current temperature: {temp}°C")
                        temp_received = True
                        break
                    elif temp is not None:
                        self.logger.info(f"Temperature reading received but too low: {temp}°C, waiting...")
                    else:
                        self.logger.warning(f"Failed to get temperature reading (attempt {temp_attempt + 1}/{max_temp_attempts})")
                    temp_attempt += 1
                    time.sleep(1)  # Wait 1 second between attempts
                
                if temp_received:
                    break  # Success, exit the reset retry loop
                
                reset_attempt += 1
            
            if not temp_received:
                raise Exception(f"Failed to receive temperature reading > 20°C from device after {max_reset_attempts} reset attempts")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize temperature controller: {e}")
            self.close()
            raise

    def send_command(self, command: str) -> str:
        """Sends a command to the temperature controller and returns the response."""
        try:
            self.ser.reset_input_buffer()
            self.ser.write((command + "\r\n").encode())
            time.sleep(0.1)  # Short delay for response
            response = self.ser.readline().decode().strip()
            return response
        except Exception as e:
            self.logger.error(f"Error sending command '{command}': {e}")
            return ""

    def set_temperature(self, temp: float):
        """Sets the target temperature (in °C) using global target command."""
        for attempt in range(5):
            try:
                response = self.send_command(f"S[{temp:.1f}]")
                if f"Global target set to: {temp:.1f}" in response:
                    self.target_temp = temp
                    # self.logger.info(f"Set global target temperature to {temp}°C")
                    return True
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed to set temperature to {temp}: {e}")
                continue
        # If all attempts failed
        self.logger.warning(f"Failed to set temperature to {temp} after 5 attempts. Last response: {response}")
        return False

    def get_temperature(self) -> float:
        """Reads the current center zone effective temperature."""
        for attempt in range(5):
            try:
                response = self.send_command("A")
                # Parse response: "center_measured=XX.X,center_effective=XX.X"
                match = re.search(r'center_effective=([+-]?\d+\.?\d*)', response)
                if match:
                    temp = float(match.group(1))
                    return temp
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed to get temperature: {e}")
                continue
        # If all attempts failed
        self.logger.warning(f"Could not parse temperature from response after 5 attempts: {response}")
        return None

    def get_target_temperature(self) -> float:
        """Reads the target temperature."""
        # Since it's global, return stored target
        return self.target_temp

    def set_default_pid(self):
        """Applies default PID values."""
        for attempt in range(5):
            try:
                # Default values from API: kp=4.0,ki=0.1,kd=0.2,iclamp=500.0,maxd=100,pwm=50
                response = self.send_command("K[4.0,0.1,0.2,500.0,100,50]")
                if "PID saved" in response:
                    # self.logger.info("Default PID values set")
                    return True
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed to set default PID: {e}")
                continue
        # If all attempts failed
        self.logger.warning(f"Failed to set default PID after 5 attempts. Last response: {response}")
        return False

    def close(self):
        """Closes the serial connection."""
        if hasattr(self, 'ser') and self.ser:
            try:
                self.ser.close()
                self.logger.info("Temperature controller serial connection closed")
            except Exception as e:
                self.logger.error(f"Error closing serial connection: {e}")

    def get_all_temperatures(self) -> list[float]:
        """Gets all 36 sensor temperatures."""
        for attempt in range(5):
            try:
                response = self.send_command("T")
                temps = ast.literal_eval(response)
                if isinstance(temps, list) and len(temps) == 36:
                    return temps
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed to get all temperatures: {e}")
                continue
        # If all attempts failed
        self.logger.warning(f"Unexpected response to get_all_temperatures after 5 attempts: {response}")
        return []

    def get_mapping(self) -> list[int]:
        """Gets the sensor-to-heater mapping."""
        for attempt in range(5):
            try:
                response = self.send_command("M")
                mapping = ast.literal_eval(response)
                if isinstance(mapping, list) and len(mapping) == 36:
                    return mapping
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed to get mapping: {e}")
                continue
        # If all attempts failed
        self.logger.warning(f"Unexpected response to get_mapping after 5 attempts: {response}")
        return []

    def set_mapping(self, mapping: list[int]) -> bool:
        """Saves custom sensor mapping."""
        if len(mapping) != 36:
            self.logger.error("Mapping must have 36 elements")
            return False
        for attempt in range(5):
            try:
                response = self.send_command(f"P{mapping}")
                if "Mapping saved" in response:
                    self.logger.info("Custom sensor mapping saved")
                    return True
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed to set mapping: {e}")
                continue
        # If all attempts failed
        self.logger.warning(f"Failed to set mapping after 5 attempts. Last response: {response}")
        return False

    def calibrate_mapping(self) -> bool:
        """Performs auto-calibration of sensor mapping."""
        for attempt in range(5):
            try:
                self.logger.info("Starting auto-calibration of mapping")
                self.ser.reset_input_buffer()
                self.ser.write(b"C\r\n")
                time.sleep(0.1)
                complete = False
                while True:
                    line = self.ser.readline().decode().strip()
                    if line:
                        self.logger.info(f"Calibration: {line}")
                        if "Mapping saved to flash." in line:
                            complete = True
                            break
                    else:
                        time.sleep(0.5)  # Wait a bit longer
                        # To prevent infinite loop, maybe add timeout
                if complete:
                    return True
            except Exception as e:
                self.logger.error(f"Failed to calibrate mapping: {e}")
                return False
        # If all attempts failed
        self.logger.warning("Failed to calibrate mapping after 5 attempts")
        return False

    def set_per_channel_targets(self, targets: list[float]) -> bool:
        """Sets per-channel temperature targets."""
        if len(targets) != 36:
            self.logger.error("Targets must have 36 elements")
            return False
        for attempt in range(5):
            try:
                response = self.send_command(f"H{targets}")
                if "H targets updated" in response:
                    self.logger.info("Per-channel temperature targets updated")
                    return True
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed to set per-channel targets: {e}")
                continue
        # If all attempts failed
        self.logger.warning(f"Failed to set per-channel targets after 5 attempts. Last response: {response}")
        return False

    def get_targets(self) -> list[float]:
        """Gets current temperature targets."""
        for attempt in range(5):
            try:
                response = self.send_command("G")
                targets = ast.literal_eval(response)
                if isinstance(targets, list) and len(targets) == 36:
                    return targets
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed to get targets: {e}")
                continue
        # If all attempts failed
        self.logger.warning(f"Unexpected response to get_targets after 5 attempts: {response}")
        return []

    def get_pid_and_regression_params(self) -> dict:
        """Reads PID and regression parameters."""
        for attempt in range(5):
            try:
                response = self.send_command("k")
                params = {}
                parts = response.split(',')
                for part in parts:
                    if '=' in part:
                        key, value = part.split('=', 1)
                        params[key.strip()] = float(value.strip())
                return params
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed to get PID and regression params: {e}")
                continue
        # If all attempts failed
        self.logger.warning(f"Failed to get PID and regression params after 5 attempts: {response}")
        return {}

    def set_regression_params(self, z1_m: float, z1_b: float, z2_m: float, z2_b: float, z3_m: float, z3_b: float) -> bool:
        """Writes zone regression parameters."""
        for attempt in range(5):
            try:
                response = self.send_command(f"R[{z1_m},{z1_b},{z2_m},{z2_b},{z3_m},{z3_b}]")
                if "REG saved" in response:
                    self.logger.info("Regression parameters saved")
                    return True
            except Exception as e:
                self.logger.error(f"Attempt {attempt + 1} failed to set regression params: {e}")
                continue
        # If all attempts failed
        self.logger.warning(f"Failed to set regression params after 5 attempts. Last response: {response}")
        return False
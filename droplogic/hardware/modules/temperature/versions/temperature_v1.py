import math
import re
import time
from typing import Optional

from droplogic.utils.logging_config import setup_droplogic_logger


class TemperatureSafetyError(RuntimeError):
    """Raised after the controller has been disabled for a safety fault."""


class TemperatureV1:
    """TCB-NB/TCB-NE UART temperature controller.

    Safety policy for the current BOXMini build:
    - Only command targets in the 20-80 degC range.
    - Treat sensor readings outside 20-80 degC, malformed responses, and
      strong warming while commanded to cool as fatal faults.
    - On every fatal fault, send SEN0 before raising.
    """

    DEFAULT_P = 26
    DEFAULT_I = 1
    DEFAULT_D = 60

    MIN_TARGET_TEMP_C = 20.0
    MAX_TARGET_TEMP_C = 80.0
    MIN_SENSOR_TEMP_C = 20.0
    MAX_SENSOR_TEMP_C = 80.0

    COOLING_MARGIN_C = 0.25
    COOLING_RISE_TOLERANCE_C = 0.35
    READ_ATTEMPTS = 3

    def __init__(
        self,
        serial,
        parent=None,
        set_default_pid_on_init=True,
        disable_on_init=True,
    ):
        if parent and hasattr(parent, "logger"):
            self.logger = parent.logger
        else:
            self.logger = setup_droplogic_logger("droplogic.hardware.temperature.v1")

        self.serial = serial
        self.target_temp = None
        self._last_temperature = None
        self._closed = False

        self.logger.info("Initializing temperature module V1")
        try:
            if disable_on_init:
                self.disable()
            if set_default_pid_on_init:
                self.set_default_pid()
            self.logger.info(
                "Temperature V1 ready with PID P=%s I=%s D=%s",
                self.DEFAULT_P,
                self.DEFAULT_I,
                self.DEFAULT_D,
            )
        except Exception:
            self.close()
            raise

    def _serial_is_open(self) -> bool:
        return self.serial is not None and getattr(self.serial, "is_open", True)

    def send_command(self, command: str) -> str:
        """Send a command to the controller and return the first non-empty line."""
        if not self._serial_is_open():
            raise RuntimeError("Temperature serial port is closed")

        self.serial.reset_input_buffer()
        self.serial.write((command + "\r\n").encode())
        time.sleep(0.3)

        response = ""
        while self.serial.in_waiting > 0:
            line = self.serial.readline().decode(errors="replace").strip()
            if line:
                response = line
                break
        return response

    def disable(self):
        """Disable the TEC loop."""
        return self.send_command("SEN0")

    def emergency_stop(self, reason: str):
        """Disable the TEC loop and raise a fatal safety error."""
        try:
            if self._serial_is_open():
                response = self.disable()
                self.logger.error("Temperature emergency stop: %s; SEN0 -> %s", reason, response)
        except Exception as exc:
            self.logger.error("Temperature emergency stop failed to send SEN0: %s", exc)
        raise TemperatureSafetyError(reason)

    def _ensure_target_in_range(self, temp: float):
        if not math.isfinite(temp):
            self.emergency_stop(f"Unsafe target temperature: {temp!r}")
        if not self.MIN_TARGET_TEMP_C <= temp <= self.MAX_TARGET_TEMP_C:
            self.emergency_stop(
                f"Target {temp:.2f} degC is outside "
                f"{self.MIN_TARGET_TEMP_C:g}-{self.MAX_TARGET_TEMP_C:g} degC"
            )

    def _parse_temperature_response(self, response: str) -> Optional[float]:
        match = re.search(r"P([+-]?\d+(?:\.\d+)?)", response or "")
        if not match:
            return None
        return float(match.group(1))

    def _validate_sensor_temperature(self, temp: float, response: str):
        if not math.isfinite(temp):
            self.emergency_stop(f"Non-finite temperature reading from {response!r}")
        if not self.MIN_SENSOR_TEMP_C <= temp <= self.MAX_SENSOR_TEMP_C:
            self.emergency_stop(
                f"Sensor reading {temp:.2f} degC is outside "
                f"{self.MIN_SENSOR_TEMP_C:g}-{self.MAX_SENSOR_TEMP_C:g} degC"
            )

    def _check_cooling_direction(self, temp: float):
        if self.target_temp is None or self._last_temperature is None:
            return

        cooling = self.target_temp < self._last_temperature - self.COOLING_MARGIN_C
        rising = temp > self._last_temperature + self.COOLING_RISE_TOLERANCE_C
        if cooling and rising:
            self.emergency_stop(
                "Temperature increased while cooling: "
                f"target={self.target_temp:.2f} degC, "
                f"previous={self._last_temperature:.2f} degC, current={temp:.2f} degC"
            )

    def set_temperature(self, temp: float):
        """Set the target temperature in degC."""
        target = float(temp)
        self._ensure_target_in_range(target)

        try:
            current = self.get_temperature()
            if current is not None:
                self._last_temperature = current
        except TemperatureSafetyError:
            raise
        except Exception as exc:
            self.logger.warning("Could not read temperature before setting target: %s", exc)

        self.target_temp = target
        self.send_command("SEN1")
        return self.send_command(f"S1 {target:.2f}")

    def get_temperature(self) -> float:
        """Read the current temperature and enforce safety checks."""
        last_response = ""
        for _ in range(self.READ_ATTEMPTS):
            last_response = self.send_command("RP1")
            temp = self._parse_temperature_response(last_response)
            if temp is None:
                time.sleep(0.1)
                continue

            self._validate_sensor_temperature(temp, last_response)
            self._check_cooling_direction(temp)
            self._last_temperature = temp
            return temp

        self.emergency_stop(f"Invalid temperature response: {last_response!r}")

    def get_target_temperature(self) -> Optional[float]:
        """Read the target temperature."""
        response = self.send_command("RS1")
        match = re.search(r"S([+-]?\d+(?:\.\d+)?)", response or "")
        if match:
            return float(match.group(1))
        return self.target_temp

    def _parse_number_response(self, response: str):
        match = re.search(r"([+-]?\d+(?:\.\d+)?)", response or "")
        if match:
            value = float(match.group(1))
            return int(value) if value.is_integer() else value
        return None

    def set_pid(self, p=None, i=None, d=None):
        """Set one or more PID terms."""
        responses = {}
        if p is not None:
            responses["P"] = self.send_command(f"SP {float(p):g}")
        if i is not None:
            responses["I"] = self.send_command(f"SI {float(i):g}")
        if d is not None:
            responses["D"] = self.send_command(f"SD {float(d):g}")
        return responses

    def get_pid(self):
        """Read PID terms from the controller."""
        return {
            "P": self._parse_number_response(self.send_command("RFP")),
            "I": self._parse_number_response(self.send_command("RFI")),
            "D": self._parse_number_response(self.send_command("RFD")),
        }

    def set_default_pid(self):
        """Apply the calibrated BOXMini PID values."""
        return self.set_pid(p=self.DEFAULT_P, i=self.DEFAULT_I, d=self.DEFAULT_D)

    def close(self):
        """Disable control and close the serial connection."""
        if self._closed:
            return
        self._closed = True

        if self.serial is None:
            return

        try:
            if self._serial_is_open():
                self.disable()
        except Exception as exc:
            self.logger.warning("Failed to send SEN0 while closing TemperatureV1: %s", exc)

        try:
            if self._serial_is_open():
                self.serial.close()
        finally:
            self.serial = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

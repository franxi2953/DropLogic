import crcmod
import time
from droplogic.utils.logging_config import setup_droplogic_logger
from .helpers.UPLEDController import UPLEDController
from ctypes import create_string_buffer

# Initialize the MODBUS CRC function
crc16_modbus = crcmod.predefined.mkPredefinedCrcFun('modbus')

class LightV2:
    """Light control implementation for Version 2 (Modbus for ring, LED for coaxial)."""

    def __init__(self, ring_serial, coaxial_controller, parent=None):
        # Set up logger from parent (BoxMini) if available, otherwise use default
        if parent and hasattr(parent, 'logger'):
            self.logger = parent.logger
        else:
            self.logger = setup_droplogic_logger('droplogic.hardware.light.v2')

        self.logger.info("Initializing light module V2...")

        # Store connections explicitly
        self.ring_serial = ring_serial  # USB serial for ring light (CRC16 commands)
        self.coaxial_controller = coaxial_controller  # UPLED controller for coaxial light
        
        # For backward compatibility, also set self.serial to ring_serial and self.upled to coaxial_controller
        self.serial = ring_serial
        self.upled = coaxial_controller

        # Get LED current limit from parent if available
        self.led_limit = getattr(parent, 'led_limit', 1.2) if parent else 1.2

        # Initialize state tracking
        self.state = {
            "light_on": False,
            "coaxial_intensity": 0,
            "ring_intensity": 0,
        }
        try:
            # Skip initial switch_light and set_ring_light to avoid USB timeout
            # self.switch_light(self.state["light_on"])
            # self.set_coaxial_light(self.state["coaxial_intensity"])
            # self.set_ring_light(self.state["ring_intensity"])
            self.logger.info("Device initialized and powered on.")
            # we need to leave the temperature module with power for it to not crash later, as the "light module" actually is the whole power board. we need something better
            command = bytes.fromhex(f"AAA500000001C6")
            self._send_command(command)
            # command = bytes.fromhex('AAA500000001CA')
            # self._send_command(command)

        except Exception as e:
                self.logger.error(f"Failed to apply initial light settings: {e}")
                self.close()
                raise
            
    def _add_crc16_modbus(self, command_bytes):
        """Adds CRC16-MODBUS checksum to the command."""
        try:
            crc = crc16_modbus(command_bytes)
            crc_bytes = crc.to_bytes(2, byteorder='little')
            return command_bytes + crc_bytes
        except Exception as e:
            self.logger.error(f"Failed to generate CRC16: {e}")
            raise

    def _send_command(self, command):
        """Sends a command and reads the response."""
        if not self.serial:
            self.logger.debug("No serial connection for ring light, skipping command")
            return
        try:
            command_with_crc = self._add_crc16_modbus(command)
            write_result = self.serial.write(1, command_with_crc, timeout=5000)

            # Increased delay for more reliable communication
            time.sleep(0.2)

            response = self.serial.read(0x81, 64, timeout=5000)
            return response
        except Exception as e:
            self.logger.error(f"Communication failed: {e}")
            self.close()
            raise

    def switch_light(self, on=True):
        """Turns the light source ON or OFF while preserving other bits."""

        # Step 1: Start with default XX as 'C2' observed from device (11000010)
        current_value = 0b11000010  # Preserving bits 7, 8, and 2 as '1'

        # Step 2: Modify the 4th bit (bit 3 if counting from 0, right to left)
        if on:
            current_value |= 0b00001000  # Set 4th bit to 1 (turn light ON)
        else:
            current_value &= 0b11110111  # Set 4th bit to 0 (turn light OFF)

        # Step 3: Convert back to hex (two-digit uppercase)
        hex_value = f"{current_value:02X}"

        # Step 4: Construct the command string
        command = bytes.fromhex(f"AAA500000001{hex_value}")

        self.logger.debug(f"Sending switch_light command: {command.hex().upper()}")

        try:
            response = self._send_command(command)
            self.state["light_on"] = on  # Update internal state
            return response
        except Exception as e:
            self.close()
            raise

    def set_coaxial_light(self, intensity):
        """Sets the coaxial light intensity (0-99) using LED."""
        # self.logger.debug(f"set_coaxial_light called with intensity: {intensity}")
        if not (0 <= intensity <= 99):
            raise ValueError("Invalid intensity. Must be between 0 and 99.")

        # Map intensity to current: 0-99 -> 0 to limit
        current = (intensity / 99.0) * self.led_limit
        # print(f"Setting coaxial LED current to {current} A for intensity {intensity}")
        self.upled.set_led_current_setpoint(current)
        measured = self.upled.measure_led_current()
        # print(f"Measured LED current after setting: {measured} A")
        
        # Turn on if intensity > 0, off if 0
        self.upled.set_led_output_state(1 if intensity > 0 else 0)
        
        self.state["coaxial_intensity"] = intensity  # Update state
        # self.logger.debug(f"Coaxial LED set to intensity {intensity}, current {current} A")
        return True  # No response from LED

    def set_ring_light(self, intensity):
        """Sets the ring light intensity (0-99)."""
        if not (0 <= intensity <= 99):
            raise ValueError("Invalid intensity. Must be between 0 and 99.")

        # Convert intensity to hex (two-digit uppercase)
        hex_value = f"{intensity:02X}"

        # Construct the correct command: AA A5 02 01 00 01 XX
        command = bytes.fromhex(f"AA A5 02 01 00 01 {hex_value}")

        try:
            response = self._send_command(command)
            self.state["ring_intensity"] = intensity  # Update state
            return response
        except Exception as e:
            self.logger.error(f"Failed to set ring light intensity to {intensity}: {e}")
            self.close()
            raise

    def get_state(self):
        """Returns the current state of the light module."""
        return self.state

    def close(self):
        """Safely turns off the lights before closing."""
        try:
            self.upled.set_led_output_state(0)  # Turn off LED
        except:
            pass
        if hasattr(self, 'state') and self.state["light_on"]:  # Only try switching off if the light is actually ON
            try:
                self.switch_light(False)
            except Exception as e:
                self.logger.error(f"Failed to turn off light during cleanup: {e}")

        try:
            self.upled.close()
        except:
            pass

        self.serial = None  # Clear serial reference to avoid future operations


    def __del__(self):
        """Ensure proper cleanup when object is deleted."""
        self.close()
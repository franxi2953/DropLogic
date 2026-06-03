from ...camera.versions.camera_v1 import CameraV1
import time
import logging

class MicroscopeV1(CameraV1):
    """Microscope implementation based on CameraV1, with potential future extensions."""

    def __init__(self, serial, parent):
        # Set up logger from parent if available
        if parent and hasattr(parent, 'logger'):
            self.logger = parent.logger
        else:
            self.logger = logging.getLogger('droplogic.hardware.microscope.v1')
        
        self.logger.info("Initializing microscope V1 (wheel channel changer)...")
        
        super().__init__(parent, 1)
        self.serial = serial
        
        # Reset the wheel channel changer via DTR/RTS toggle
        self.logger.info("Resetting wheel channel changer via DTR/RTS toggle...")
        self.serial.dtr = False
        self.serial.rts = True
        time.sleep(0.1)
        self.serial.rts = False
        time.sleep(3)  # Wait 3 seconds for device to boot and stabilize
        
        # Test connection by waiting for any message from the device
        self.logger.info("Waiting for wheel channel changer to send a message...")
        max_attempts = 30  # Wait up to 30 seconds
        attempt = 0
        message_received = False
        
        while attempt < max_attempts and not message_received:
            try:
                if self.serial.in_waiting > 0:
                    message = self.serial.read(self.serial.in_waiting).decode().strip()
                    self.logger.info(f"Received message from device: {message}")
                    message_received = True
                else:
                    time.sleep(1)
                    attempt += 1
            except Exception as e:
                self.logger.warning(f"Error reading from device (attempt {attempt + 1}/{max_attempts}): {e}")
                attempt += 1
                time.sleep(1)
        
        if not message_received:
            self.logger.warning("No message received from wheel channel changer, but continuing initialization")
        else:
            self.logger.info("Wheel channel changer communication established")

    def open_microscope(self):
        """Opens the microscope, which is essentially a second camera."""
        self.open_camera(device_index=1)

    def set_channel(self, channel):
        """Sets the microscope channel."""
        if channel == "FAM":
            # write into the serial D20
            self.serial.write(b"D10\r\n")
        elif channel == "Brightfield":
            # write into the serial D00
            self.serial.write(b"D160\r\n")

    def close_microscope(self):
        """Closes the microscope."""
        self.close()

    def close(self):
        """Close the microscope and serial connection."""
        super().close()
        if hasattr(self, 'serial') and self.serial:
            self.serial.close()

    def __del__(self):
        self.close_microscope()


    # Future methods for controlling filter wheels and fluorescence will go here

import time

class TemperatureV1:
    def __init__(self,  serial):
        """
        Initialize the temperature controller.
        :param port: Serial port (e.g., 'COM3' or '/dev/ttyUSB0')
        :param baudrate: Communication speed (default: 9600)
        :param timeout: Read timeout in seconds
        """

        print("\n[INFO] Initializing temperature module...")
        try:
            self.serial = serial
            self.send_command("SEN0")  # Disable sensor just for safety until sommethings calls set_temperature
            self.set_default_pid()
            print("Device initialized and powered on.")
        except Exception as e:
            print(f"[ERROR] Failed to initialize temperature module: {e}")
            self.close()

    def send_command(self, command: str) -> str:
        """
        Send a command to the TCB-NE module and return the response.
        """
        # Clear any pending data in the buffer
        self.serial.reset_input_buffer()
        
        # Send the command
        self.serial.write((command + "\r\n").encode())
        
        # Wait longer for response to ensure complete data
        time.sleep(0.3)  # Increased from 0.2s to 0.3s
        
        # Read all available data, not just one line
        response = ""
        while self.serial.in_waiting > 0:
            line = self.serial.readline().decode().strip()
            if line:  # Only add non-empty lines
                response += line
                break  # Take the first valid line
        
        return response

    def set_temperature(self, temp: float):
        """
        Set the target temperature (in °C).
        """
        self.send_command("SEN1")
        return self.send_command(f"S1 {temp:.2f}")

    def get_temperature(self) -> float:
        """
        Read the current temperature.
        """
        response = self.send_command("RP1")  # Response format: P+xx.xx
        
        # Handle malformed responses with regex-like pattern matching
        try:
            import re
            
            # Look for pattern: P followed by digits.digits (xx.xx format)
            # This will match P24.45, P-12.34, P100.00, etc.
            pattern = r'P([+-]?\d+\.\d+)'
            match = re.search(pattern, response)
            
            if match:
                temp_str = match.group(1)  # Extract just the number part
                return float(temp_str)
            
            # If no valid P+xx.xx pattern found, ignore the response
            return None
            
        except Exception as e:
            # Silently ignore parsing errors - just return None
            return None

    def get_target_temperature(self) -> float:
        """
        Read the target temperature.
        """
        response = self.send_command("RS1")  # Response format: S+xx.xx
        if response.startswith("S"):
            return float(response[1:])
        return None

    def set_default_pid(self):
        """
        Apply default PID values (P=50, I=10, D=20).
        """
        self.send_command("SP 50")  # Proportional gain
        self.send_command("SI 10")  # Integral gain
        self.send_command("SD 20")  # Derivative gain

    def close(self):
        """
        Close the serial connection.
        """
        if self.serial is not None:
            self.send_command(f"AAA500000001C2")
            self.send_command("SEN0")
            self.serial.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass  # Ignore any exceptions during deletion

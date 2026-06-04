from .electrode_matrix_factory import ElectrodeMatrixFactory

class ElectrodeMatrixModule:
    """
    Handles electrode matrix operations with version control.
    
    This module wraps an underlying electrode matrix interface (e.g. DMLite)
    that is created by the ElectrodeMatrixFactory. It delegates all operations
    (such as setting a single electrode, setting the entire chip, or cleaning up)
    to the underlying instance. Additional logic will be implemented later.
    """

    SUPPORTED_VERSIONS = {
        "DMLite": "DMLite",
        # Future versions can be added here.
    }

    def __init__(self, parent, device, rows, columns, version="DMLite", initial_voltage=55, debug=False):
        """
        :param parent: A reference to a higher-level system or controller.
        :param device: Optional backend-specific device/configuration object.
        :param rows: Number of rows in the electrode matrix.
        :param columns: Number of columns in the electrode matrix.
        :param version: The electrode matrix version to use.
        :param debug: Enable debug logging.
        """
        self.parent = parent

        if version not in self.SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported electrode matrix version: {version}")

        # Pass device, rows, columns, version, and debug to the factory
        self.matrix = ElectrodeMatrixFactory.create_matrix(
            device, rows, columns, self.SUPPORTED_VERSIONS[version], initial_voltage, debug
        )


    def set_electrode(self, row, col, state):
        """
        Activates or deactivates a single electrode.
        
        :param row: Row index.
        :param col: Column index.
        :param state: 1 (activate) or 0 (deactivate).
        :return: The result from the underlying implementation.
        """
        return self.matrix.set_electrode(row, col, state)

    def set_chip(self, matrix):
        """
        Sets the entire electrode state matrix.
        
        :param matrix: 2D list representing the full electrode state.
                       It should be a square matrix matching the configured dimensions.
        :return: The result from the underlying implementation.
        """
        return self.matrix.set_chip(matrix)

    def set_voltage(self, voltage):
        """
        Sends a command to set voltages for electrodes.
        
        :param voltages: A list of 9 voltage values (each 1 byte, 0-255 range).
        :return: The result from the underlying implementation.
        """
        return self.matrix.set_voltage(voltage)

    def deactivate_all(self):
        """
        Deactivates all electrodes.
        
        :return: The result from the underlying implementation.
        """
        return self.matrix.deactivate_all()
        
    def set_droplet(self, row, col, width=1, height=1, state=1):
        """
        Sets a single droplet of specified width and height at the given position.
        
        :param row: Row index of the top-left corner of the droplet.
        :param col: Column index of the top-left corner of the droplet.
        :param width: Width of the droplet in electrodes (default: 1).
        :param height: Height of the droplet in electrodes (default: 1).
        :param state: 1 to activate, 0 to deactivate (default: 1).
        :return: True if successful, False otherwise.
        """
        return self.matrix.set_droplet(row, col, width, height, state)
        
    def set_droplets(self, droplets):
        """
        Sets multiple droplets at once.
        
        :param droplets: List of droplet dictionaries, each containing:
                        - row: Row index of the top-left corner
                        - col: Column index of the top-left corner
                        - width: Width of the droplet (optional, default 1)
                        - height: Height of the droplet (optional, default 1)
                        - state: 1 to activate, 0 to deactivate (optional, default 1)
        :return: True if successful, False otherwise.
        """
        return self.matrix.set_droplets(droplets)

    def send_ascii_command(self, hex_command):
        """
        Sends a raw hex command (given as an ASCII string) to the electrode matrix.
        
        :param hex_command: A string of hex digits (e.g., "aafd01000100").
        :return: The raw response from the underlying device.
        """
        return self.matrix.send_ascii_command(hex_command)

    def close(self):
        """
        Cleans up the electrode matrix device (deactivates electrodes, powers off,
        and releases device resources).
        
        :return: The result from the underlying implementation.
        """
        return self.matrix.close()
    
    def _query_voltage(self):
        """
        Queries the current voltage from the electrode matrix device.
        
        :return: The current voltage value.
        """
        return self.matrix._query_voltage()

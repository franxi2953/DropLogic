class ElectrodeMatrixFactory:
    """Factory class for creating electrode matrix controller instances."""

    @staticmethod
    def create_matrix(device, rows, columns, version, initial_voltage=55, debug=False):
        """
        Create an electrode matrix controller instance.
        
        :param device: For serial-based versions, a serial device. For DLL-based versions, this parameter is ignored.
        :param rows: Number of rows in the electrode matrix.
        :param columns: Number of columns in the electrode matrix.
        :param version: The version of the electrode matrix controller to create.
        :param initial_voltage: Initial startup voltage to apply.
        :param debug: Enable debug logging.
        :return: An electrode matrix controller instance.
        """
        if version == "DMLite":
            from .versions.DMLite import DMLite
            return DMLite(device, rows, columns, initial_voltage, debug)
        else:
            raise ValueError(f"Unsupported electrode matrix version: {version}")

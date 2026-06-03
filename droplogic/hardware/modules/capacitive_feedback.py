class CapacitiveFeedbackModule:
    """Reads capacitive feedback from electrodes with version support."""
    def __init__(self, parent, version="CapacitiveFeedbackV1"):
        self.parent = parent
        self.version = version

        if version == "CapacitiveFeedbackV1":
            self.grid_size = (10, 10)  # Default grid size for V1
        else:
            raise ValueError(f"Unsupported capacitive feedback version: {version}. Future versions should be added.")

        # Initialize capacitive feedback state
        # self.parent.update_state("capacitive_feedback", [[False] * self.grid_size[1] for _ in range(self.grid_size[0])])

    def read_feedback(self, x, y):
        """Reads feedback from an electrode, ensuring it's within the grid."""
        if 0 <= x < self.grid_size[0] and 0 <= y < self.grid_size[1]:
            return self.parent.state["capacitive_feedback"][x][y]
        else:
            raise ValueError(f"Error: ({x}, {y}) is out of bounds for {self.version} grid size {self.grid_size}")

class CameraFactory:
    """Factory class for creating camera instances based on version."""

    @staticmethod
    def create_camera(parent, version):
        """Creates and returns a camera instance based on the specified version."""
        if version == "CameraV1":
            from .versions.camera_v1 import CameraV1
            return CameraV1(parent)
        else:
            raise ValueError(f"Unsupported camera version: {version}")

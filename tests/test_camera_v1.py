import unittest
from unittest.mock import Mock

from droplogic.hardware.modules.camera.versions.camera_v1 import CameraV1


class CameraV1CloseTests(unittest.TestCase):
    def test_close_is_idempotent_and_releases_the_handle_reference(self):
        camera = object.__new__(CameraV1)
        handle = Mock()
        camera.cam = handle
        camera._is_grabbing = True
        camera._closed = False
        camera.logger = Mock()

        camera.close()
        camera.close()

        handle.MV_CC_StopGrabbing.assert_called_once()
        handle.MV_CC_CloseDevice.assert_called_once()
        handle.MV_CC_DestroyHandle.assert_called_once()
        self.assertIsNone(camera.cam)
        self.assertFalse(camera._is_grabbing)


if __name__ == "__main__":
    unittest.main()

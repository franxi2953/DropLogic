import os
import sys
from ctypes import *
import numpy as np
import cv2
import time
import threading

# Dynamically inject the runtime vendor directory for mvs_camera Python wrappers
from droplogic.utils.native_runtime import inject_vendor_python_path
_local_fallback = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "vendor_bin", "camera"))
inject_vendor_python_path("camera", _local_fallback)

# Now we can import the MVS Python SDK (mvs_camera folder must have __init__.py)
from mvs_camera import *

class CameraV1:
    """Implementation for Camera Version 1 (Hikvision Camera) with error handling."""

    def __init__(self, parent, device_index=0):
        self.capture_lock = threading.Lock()
        if device_index == 0:
            print("\n[INFO] Initializing camera module...")
        elif device_index == 1:
            print("\n[INFO] Initializing microscope camera module...")
        self.device_index = device_index
        self.parent = parent
        self.cam = None
        self._is_grabbing = False

        try:
            self.device_list = self.enum_devices()
            self.open_camera(device_index)
            print("Camera initialized and powered on.")
        except Exception as e:
            print(f"[ERROR] Failed to enumerate devices: {e}")
            self.close()
            raise  

    def enum_devices(self):
        """Enumerates available cameras."""
        try:
            tlayerType = MV_GIGE_DEVICE | MV_USB_DEVICE | MV_UNKNOW_DEVICE
            device_list = MV_CC_DEVICE_INFO_LIST()
            ret = MvCamera.MV_CC_EnumDevices(tlayerType, device_list)

            if ret != 0:
                raise RuntimeError(f"Failed to enumerate devices: {parse_mvs_error(ret)}")

            if device_list.nDeviceNum == 0:
                return None  # No cameras found

            return device_list
        except Exception as e:
            print(f"[ERROR] Camera enumeration failed: {e}")
            self.close()
            raise  

    def open_camera(self, device_index=0):
        """Opens the selected camera."""
        print(f"initializing camera {device_index}")
        try:
            if self.device_list is None:
                raise RuntimeError("No devices found!")

            self.cam = MvCamera()
            st_device_list = cast(self.device_list.pDeviceInfo[device_index], POINTER(MV_CC_DEVICE_INFO)).contents
            ret = self.cam.MV_CC_CreateHandle(st_device_list)
            if ret != 0:
                raise RuntimeError(f"Failed to create camera handle: {parse_mvs_error(ret)}")

            ret = self.cam.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
            if ret != 0:
                raise RuntimeError(f"Failed to open camera: {parse_mvs_error(ret)}")

            # Ensure manual exposure mode is enabled
            self.set_exposure_auto(False)

            # Start grabbing
            ret = self.cam.MV_CC_StartGrabbing()
            if ret != 0:
                raise RuntimeError(f"Failed to start grabbing: {parse_mvs_error(ret)}")
            self._is_grabbing = True
            print(f"[INFO] Started grabbing on camera {device_index}")

        except Exception as e:
            print(f"[ERROR] Failed to open camera {device_index}: {e}")
            time.sleep(1)
            self.close()
            raise  

    def set_exposure_auto(self, enable=False):
        """Enables or disables auto exposure mode."""
        try:
            # print(f"[INFO] Setting auto exposure to {'ON' if enable else 'OFF'}")
            mode = 2 if enable else 0  # 2 = Auto, 1 = Manual
            ret = self.cam.MV_CC_SetEnumValue("ExposureAuto", mode)
            # print(f"[INFO] Auto exposure set to {'ON' if enable else 'OFF'}")
            if ret != 0:
                pass
                # raise RuntimeError(f"Failed to set auto exposure to {'ON' if enable else 'OFF'}: {parse_mvs_error(ret)}")
        except Exception as e:
            # print(f"[ERROR] Failed to set auto exposure: {e}")
            pass  

    def set_parameter(self, param_type, node_name, node_value):
        """Sets camera parameters like exposure time, gain, resolution, frame rate."""
        try:
            if param_type == "float_value":
                ret = self.cam.MV_CC_SetFloatValue(node_name, float(node_value))
            elif param_type == "int_value":
                ret = self.cam.MV_CC_SetIntValue(node_name, int(node_value))
            elif param_type == "enum_value":
                ret = self.cam.MV_CC_SetEnumValue(node_name, node_value)
            else:
                pass

            if ret != 0:
                # raise RuntimeError(f"Failed to set {node_name}: {parse_mvs_error(ret)}")
                pass

        except Exception as e:
            pass  

    def get_parameter(self, param_type, node_name):
        """Gets a camera parameter value."""
        try:
            if param_type == "float_value":
                st_param = MVCC_FLOATVALUE()
                ret = self.cam.MV_CC_GetFloatValue(node_name, st_param)
                if ret != 0:
                    raise RuntimeError(f"Failed to get {node_name}: {parse_mvs_error(ret)}")
                return st_param.fCurValue

            elif param_type == "int_value":
                st_param = MVCC_INTVALUE()
                ret = self.cam.MV_CC_GetIntValue(node_name, st_param)
                if ret != 0:
                    raise RuntimeError(f"Failed to get {node_name}: {parse_mvs_error(ret)}")
                return st_param.nCurValue

            elif param_type == "enum_value":
                st_param = MVCC_ENUMVALUE()
                ret = self.cam.MV_CC_GetEnumValue(node_name, st_param)
                if ret != 0:
                    raise RuntimeError(f"Failed to get {node_name}: {parse_mvs_error(ret)}")
                return st_param.nCurValue

        except Exception as e:
            # print(f"[ERROR] Failed to retrieve parameter {node_name}: {e}")
            # self.close()
            return None

    def capture_image(self, save_path="results/0.bmp", display=False, save=False):
        """Fetches the latest frame from the already‐running grab loop.

        Parameters:
            save_path (str): Path where the image should be saved (if `save=True`).
            display (bool): Whether to display the captured image.
            save (bool): Whether to save the image to a file.

        Returns:
            np.ndarray: The captured image as a NumPy array, or None on timeout/format error.
        """
        with self.capture_lock:
            try:
                # Ensure the path is absolute if saving
                if save and not os.path.isabs(save_path):
                    save_path = os.path.join(os.getcwd(), save_path.lstrip("/\\"))

                # Prepare output directory
                if save:
                    output_dir = os.path.dirname(save_path)
                    os.makedirs(output_dir, exist_ok=True)

                # Allocate and zero the frame info struct
                stFrameInfo = MV_FRAME_OUT_INFO_EX()
                memset(byref(stFrameInfo), 0, sizeof(stFrameInfo))

                # Allocate the image buffer
                nDataSize = self.get_parameter("int_value", "PayloadSize")
                if nDataSize is None:
                    # Camera is likely closed/disconnected, return None silently
                    return None
                pData = (c_ubyte * nDataSize)()

                # Grab one frame from the ongoing acquisition
                ret = self.cam.MV_CC_GetOneFrameTimeout(pData, nDataSize, stFrameInfo, 30000)
                if ret != 0:
                    # print(f"[WARN] Frame timeout or error: {parse_mvs_error(ret)}")
                    return None

                # Extract dimensions and pixel format
                width, height, pixel_type = (
                    stFrameInfo.nWidth,
                    stFrameInfo.nHeight,
                    stFrameInfo.enPixelType,
                )

                # Handle different pixel formats
                if pixel_type == 17301513:  # BayerRG8 (color camera)
                    # Convert raw buffer to RGB image
                    raw = np.frombuffer(pData, dtype=np.uint8).reshape(height, width)
                    image = cv2.cvtColor(raw, cv2.COLOR_BAYER_RG2RGB)
                elif pixel_type == 17301505:  # Mono8 (monochrome camera)
                    # Monochrome image, no conversion needed
                    image = np.frombuffer(pData, dtype=np.uint8).reshape(height, width)
                else:
                    print(f"[WARN] Unsupported pixel format {pixel_type}. Supported: BayerRG8 (17301513) or Mono8 (17301505).")
                    return None

                # Save to disk if requested
                if save:
                    cv2.imwrite(save_path, image)

                # Display if requested
                if display:
                    cv2.imshow("Captured Image", image)
                    cv2.waitKey(1)

                return image

            except Exception as e:
                print(f"[ERROR] Image capture failed: {e}")
                self.close()
                raise

    def close(self):
        """Closes the camera safely."""
        try:
            if self.cam:
                if getattr(self, "_is_grabbing", False):
                    self.cam.MV_CC_StopGrabbing()
                    self._is_grabbing = False
                    print("[INFO] Stopped grabbing")
                self.cam.MV_CC_CloseDevice()
                self.cam.MV_CC_DestroyHandle()
                print("[INFO] Camera closed and handle destroyed")
        except Exception as e:
            print(f"[ERROR] Error while closing camera: {e}")

    def __del__(self):
        """Ensure the camera is closed when the object is deleted."""
        self.close()

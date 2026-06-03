

from ctypes import *
import time



class UPLEDController:
    def __init__(self, dllPath=r"C:\Program Files\IVI Foundation\VISA\Win64\Bin\TLUP_64.dll"):
        self.lib = cdll.LoadLibrary(dllPath)
        self.device_count = c_uint32()
        self.upHandle = c_int(0)
        self.model_name = None
        print("nepe")

    def find_devices(self):
        self.lib.TLUP_findRsrc(0, byref(self.device_count))
        if self.device_count.value > 0:
            print("Number of upSeries devices found: " + str(self.device_count.value))
            return self.device_count.value
        else:
            print("No upSeries devices found.")
            return None

    def get_device_info(self, index):
        modelName = create_string_buffer(256)
        serialNumber = create_string_buffer(256)
        self.lib.TLUP_getRsrcInfo(0, index, modelName, serialNumber, 0, 0)
        return (modelName.value).decode(), (serialNumber.value).decode()

    def connect_device(self, index):
        upName = create_string_buffer(256)
        self.lib.TLUP_getRsrcName(0, index, upName)
        res = self.lib.TLUP_init(upName.value, 0, 0, byref(self.upHandle))
        self.model_name, _ = self.get_device_info(index)
        return res

    def get_led_current_limit_user(self, attribute):
        LEDUserCurrentLimit = c_double()
        status = self.lib.TLUP_getLedCurrentLimitUser(self.upHandle, c_int16(attribute), byref(LEDUserCurrentLimit))
        return LEDUserCurrentLimit.value

    def set_led_current_setpoint(self, LEDCurrentSetpoint):
        status = self.lib.TLUP_setLedCurrentSetpoint(self.upHandle, c_double(LEDCurrentSetpoint))
        return status

    def set_led_output_state(self, enableLEDOutput):
        status = self.lib.TLUP_switchLedOutput(self.upHandle, enableLEDOutput)
        return status


# Quick sketch to check LEDs and control one
if __name__ == "__main__":
    controller = UPLEDController()
    device_count = controller.find_devices()
    if device_count:
        for i in range(device_count):
            model, serial = controller.get_device_info(i)
            print(f"Device {i}: Model={model}, Serial={serial}")
        
        # Connect to first device (index 0)
        upName = create_string_buffer(256)
        controller.lib.TLUP_getRsrcName(0, 0, upName)
        resource_name = upName.value.decode()
        print(f"LED resource name: {resource_name}")
        res = controller.connect_device(0)
        print(f"Connect result: {res}")
        if res == 0:  # Assuming 0 is success
            print("Connected to device.")
            
            # Get current limit (attribute 0 assumed)
            limit = controller.get_led_current_limit_user(0)
            print(f"Current limit: {limit} A")
            
            # Set to 30% power
            setpoint = 0.3 * limit
            controller.set_led_current_setpoint(setpoint)
            print(f"Set current setpoint to {setpoint} A (30% of limit)")
            
            # Toggle on/off every second for 10 seconds
            for _ in range(10):
                controller.set_led_output_state(1)  # On
                print("LED ON")
                time.sleep(1)
                controller.set_led_output_state(0)  # Off
                print("LED OFF")
                time.sleep(1)
        else:
            print("Failed to connect to device.")
    else:
        print("No LED devices found.")

    controller.close()

import ctypes
import time
import threading
from ..versions.nmc_controller import MCDLL_NET


class XYStageV1:
    """Motion controller for the XYZ stage, handling movement, limits, and state debugging."""

    AXIS_MAPPING = {"X": 0, "Z": 1, "Y": 2}
    AXIS_ID_TO_NAME = {0: "X", 1: "Z", 2: "Y"}
    SAFE_LIMITS = {"X": 108000, "Z": 30000, "Y": 50000}
    MOTION_PARAMS = {
        "dV_ini": 0.0,
        "dMaxV": 10000.0,
        "dMaxA": 1e6,
        "dJerk": 1e7,
        "dV_end": 0.0,
        "profile": 0,
        "position_mode": 0,
    }
    HOME_OFFSET = 0
    BACKLASH_WAIT_TIMEOUT_SECONDS = 30.0
    BACKLASH_DIRECTIONS = (
        "left_to_right",
        "right_to_left",
        "up_to_down",
        "down_to_up",
    )
    AXIS_DIRECTION_MAP = {
        ("X", -1): "left_to_right",
        ("X", 1): "right_to_left",
        ("Y", 1): "up_to_down",
        ("Y", -1): "down_to_up",
    }

    _instance = None  # Ensure only one instance is managing the connection

    def __new__(cls, *args, **kwargs):
        """Ensure only one instance is created to avoid multiple connections to the board."""
        if cls._instance is None:
            cls._instance = super(XYStageV1, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, parent=None):
        """Initialize the motion controller and home all axes."""
        self._set_parent_context(parent)
        if self._initialized:
            self._reload_backlash_steps_from_parent()
            return  # Prevent re-initialization if already set up

        self.logger.info("Initializing motion controller...")
        self._initialized = True
        self.dll = MCDLL_NET
        self.connection_number = ctypes.c_ushort(1)
        self.station_number = (ctypes.c_ushort * 1)(0)
        self.station_type = (ctypes.c_ushort * 1)(2)
        self.connected = False
        self._motion_command_lock = threading.RLock()
        self._last_direction_by_axis = {axis_name: None for axis_name in self.AXIS_MAPPING}
        self._backlash_steps = {direction: None for direction in self.BACKLASH_DIRECTIONS}
        self._raw_position_by_axis = {axis_name: None for axis_name in self.AXIS_MAPPING}
        self._corrected_position_by_axis = {axis_name: None for axis_name in self.AXIS_MAPPING}
        self._corrected_offset_by_axis = {axis_name: 0 for axis_name in self.AXIS_MAPPING}
        self._jog_active_by_axis = {axis_name: False for axis_name in self.AXIS_MAPPING}
        self._jog_direction_by_axis = {axis_name: None for axis_name in self.AXIS_MAPPING}
        self._jog_threads_by_axis = {}
        self._reload_backlash_steps_from_parent()

        try:
            result = self.dll.MCF_Open_Net(
                self.connection_number,
                ctypes.byref(self.station_number),
                ctypes.byref(self.station_type),
            )
            if result != 0:
                self.logger.error(f"Failed to open motion control card. Error code: {result}")

            self.connected = True

            self.logger.info("Homing axes...")
            for axis in self.AXIS_MAPPING.keys():
                self.home_axis(axis)

            while not all(self.is_homing_complete(axis) == 0 for axis in self.AXIS_MAPPING.keys()):
                time.sleep(0.1)

            self._last_direction_by_axis = {axis_name: None for axis_name in self.AXIS_MAPPING}
            self._corrected_offset_by_axis = {axis_name: 0 for axis_name in self.AXIS_MAPPING}
            self._jog_active_by_axis = {axis_name: False for axis_name in self.AXIS_MAPPING}
            self._jog_direction_by_axis = {axis_name: None for axis_name in self.AXIS_MAPPING}
            self._initialize_axis_positions()
            self.logger.info("Motion initialization complete and axes homed.")

        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            self.close()
            raise

    def _set_parent_context(self, parent):
        """Update parent/logger references without reinitializing the hardware card."""
        if parent is not None:
            self.parent = parent

        current_parent = getattr(self, "parent", None)
        if current_parent and hasattr(current_parent, "logger"):
            self.logger = current_parent.logger
        elif not hasattr(self, "logger"):
            from droplogic.utils.logging_config import setup_droplogic_logger

            self.logger = setup_droplogic_logger("droplogic.hardware.xy_stage.v1")

    def _reload_backlash_steps_from_parent(self):
        """Load optional backlash compensation values from the parent state."""
        backlash_steps = {}
        parent_state = getattr(getattr(self, "parent", None), "state", {})
        if isinstance(parent_state, dict):
            calibration_state = parent_state.get("calibration", {})
            backlash_steps = (
                calibration_state.get("backlash_steps", {})
                if isinstance(calibration_state, dict)
                else {}
            )

        normalized_backlash = {}
        for direction in self.BACKLASH_DIRECTIONS:
            normalized_backlash[direction] = self._normalize_backlash_value(backlash_steps.get(direction))

        self._backlash_steps = normalized_backlash

    def _normalize_backlash_value(self, value):
        if value is None:
            return None
        try:
            normalized = int(round(float(value)))
        except (TypeError, ValueError):
            return None
        return None if normalized <= 0 else normalized

    def _normalize_axis_name(self, axis):
        if isinstance(axis, str):
            axis_name = axis.upper()
            if axis_name in self.AXIS_MAPPING:
                return axis_name
        return self.AXIS_ID_TO_NAME.get(axis)

    def _direction_for_axis_delta(self, axis_name, delta_steps):
        if axis_name not in {"X", "Y"}:
            return None
        if delta_steps == 0:
            return None
        direction_sign = 1 if delta_steps > 0 else -1
        return self.AXIS_DIRECTION_MAP.get((axis_name, direction_sign))

    def _direction_for_continuous_movement(self, axis_name, direction):
        if axis_name not in {"X", "Y"} or direction == 0:
            return None
        direction_sign = 1 if direction > 0 else -1
        return self.AXIS_DIRECTION_MAP.get((axis_name, direction_sign))

    def _raw_sign_for_direction(self, direction_name):
        for (_, axis_sign), mapped_direction in self.AXIS_DIRECTION_MAP.items():
            if mapped_direction == direction_name:
                return axis_sign
        return 0

    def _get_backlash_steps(self, direction_name):
        self._reload_backlash_steps_from_parent()
        return self._backlash_steps.get(direction_name)

    def _get_target_offset_for_direction(self, axis_name, direction_name):
        """Return the signed raw-corrected offset that should be active for a direction."""
        if axis_name not in {"X", "Y"} or direction_name is None:
            return 0

        backlash_steps = int(self._get_backlash_steps(direction_name) or 0)
        if backlash_steps <= 0:
            return 0

        return int(self._raw_sign_for_direction(direction_name) * backlash_steps)

    def _is_target_within_safe_limits(self, axis_name, target_position):
        safe_limit = self.SAFE_LIMITS[axis_name]
        return 0 <= int(target_position) <= safe_limit

    def _wait_for_axis_motion_complete(self, axis_name, timeout_seconds=None):
        timeout_seconds = self.BACKLASH_WAIT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            if self.is_motion_complete(axis_name):
                return True
            time.sleep(0.05)
        return False

    def _read_raw_position(self, axis_name):
        """Read the hardware position directly, without logical backlash correction."""
        axis = self.AXIS_MAPPING.get(axis_name)
        if axis is None:
            self.logger.error(f"Invalid axis for raw position read: {axis_name}")
            return None

        position = ctypes.c_long(0)
        try:
            result = self.dll.MCF_Get_Position_Net(
                ctypes.c_ushort(axis), ctypes.byref(position), ctypes.c_ushort(0)
            )
            if result != 0:
                self.logger.error(f"Failed to get raw position of axis {axis_name}. Error code: {result}")
                self.stop_motion(axis_name)
                return None
        except Exception as e:
            self.logger.error(f"Failed to retrieve raw position for axis {axis_name}: {e}")
            self.close()
            raise

        return int(position.value)

    def _initialize_axis_positions(self):
        """Seed raw and corrected positions from the current hardware positions."""
        for axis_name in self.AXIS_MAPPING:
            raw_position = self._read_raw_position(axis_name)
            if raw_position is None:
                continue
            self._raw_position_by_axis[axis_name] = raw_position
            self._corrected_position_by_axis[axis_name] = raw_position
            self._corrected_offset_by_axis[axis_name] = 0

    def _refresh_axis_position_from_hardware(self, axis_name):
        """
        Update cached raw and corrected positions from the hardware.

        ``raw`` tracks the true motor/controller steps. ``corrected`` is the
        backlash-compensated logical position that upstream code should see.
        """
        raw_position = self._read_raw_position(axis_name)
        if raw_position is None:
            return None

        current_offset = int(self._corrected_offset_by_axis.get(axis_name, 0) or 0)
        if (
            self._raw_position_by_axis.get(axis_name) is None
            or self._corrected_position_by_axis.get(axis_name) is None
        ):
            self._raw_position_by_axis[axis_name] = raw_position
            self._corrected_position_by_axis[axis_name] = int(raw_position) - current_offset
            return self._corrected_position_by_axis[axis_name]

        self._raw_position_by_axis[axis_name] = raw_position
        self._corrected_position_by_axis[axis_name] = int(raw_position) - current_offset
        return self._corrected_position_by_axis[axis_name]

    def _update_axis_tracking_state(self, axis_name, raw_position, corrected_position, offset_steps):
        self._raw_position_by_axis[axis_name] = int(raw_position)
        self._corrected_position_by_axis[axis_name] = int(corrected_position)
        self._corrected_offset_by_axis[axis_name] = int(offset_steps)

    def _preload_axis_backlash(self, axis_name, target_offset, current_corrected_position):
        """Shift the raw axis position to the new backlash offset without moving corrected space."""
        current_raw_position = self._raw_position_by_axis.get(axis_name)
        if current_raw_position is None:
            return False

        preload_target = int(current_corrected_position) + int(target_offset)
        if preload_target == int(current_raw_position):
            self._update_axis_tracking_state(
                axis_name,
                current_raw_position,
                current_corrected_position,
                target_offset,
            )
            return True

        if not self._is_target_within_safe_limits(axis_name, preload_target):
            self.logger.warning(
                "Skipping backlash preload on axis %s because raw target %s exceeds limits.",
                axis_name,
                preload_target,
            )
            return False

        self.logger.debug(
            "Preloading backlash on axis %s: raw %s -> %s, corrected stays %s",
            axis_name,
            current_raw_position,
            preload_target,
            current_corrected_position,
        )
        if not self._execute_absolute_move(axis_name, preload_target):
            return False
        if not self._wait_for_axis_motion_complete(axis_name):
            self.logger.error(f"Timeout waiting for backlash preload on axis {axis_name}")
            return False

        confirmed_raw_position = self._read_raw_position(axis_name)
        if confirmed_raw_position is None:
            return False

        self._update_axis_tracking_state(
            axis_name,
            confirmed_raw_position,
            current_corrected_position,
            target_offset,
        )
        return True

    def _is_jog_active(self, axis_name):
        return bool(self._jog_active_by_axis.get(axis_name, False))

    def _stop_active_jog(self, axis_name, clear_motion=True):
        """Stop and optionally join the jog thread for one axis."""
        self._jog_active_by_axis[axis_name] = False
        self._jog_direction_by_axis[axis_name] = None

        if clear_motion:
            self.stop_and_clear_axis(axis_name)

        jog_thread = self._jog_threads_by_axis.get(axis_name)
        if jog_thread and jog_thread.is_alive() and threading.current_thread() is not jog_thread:
            jog_thread.join(timeout=2.0)

        if jog_thread and not jog_thread.is_alive():
            self._jog_threads_by_axis.pop(axis_name, None)

    def _execute_absolute_move(self, axis_name, target_position):
        """Execute a raw absolute move with no backlash compensation logic."""
        axis = self.AXIS_MAPPING.get(axis_name)
        if axis is None:
            self.logger.error(f"Invalid axis: {axis_name}")
            return False

        if not self.is_motion_complete(axis_name):
            try:
                result = self.dll.MCF_Set_Axis_Stop_Profile_Net(
                    ctypes.c_ushort(axis),
                    ctypes.c_double(self.MOTION_PARAMS["dMaxA"]),
                    ctypes.c_double(self.MOTION_PARAMS["dJerk"]),
                    ctypes.c_ushort(1),
                    ctypes.c_ushort(0),
                )
                if result != 0:
                    self.logger.warning(f"Failed to set stop profile for axis {axis} (code {result})")
            except Exception as e:
                self.logger.warning(f"Exception setting stop profile for axis {axis}: {e}")

            try:
                result = self.dll.MCF_Axis_Stop_Net(
                    ctypes.c_ushort(axis),
                    ctypes.c_ushort(1),
                    ctypes.c_ushort(0),
                )
                if result != 0:
                    self.logger.error(f"Failed to stop axis {axis} (code {result})")
                    return False
            except Exception as e:
                self.logger.error(f"Exception stopping axis {axis}: {e}")
                return False

            timeout = 10
            start_time = time.time()
            while True:
                reason = ctypes.c_ushort(0)
                ret = self.dll.MCF_Get_Axis_State_Net(
                    ctypes.c_ushort(axis),
                    ctypes.byref(reason),
                    ctypes.c_ushort(0),
                )
                if ret != 0:
                    self.logger.error(f"Get_Axis_State({axis}) failed, err={ret}")
                    return False
                if reason.value != 1:
                    break
                if time.time() - start_time > timeout:
                    self.logger.error(f"Timeout waiting for axis {axis_name} to stop")
                    return False
                time.sleep(0.1)

            self.clear_axis_error(axis_name)

        safe_limit = self.SAFE_LIMITS[axis_name]
        max_velocity = self.MOTION_PARAMS["dMaxV"]
        acceleration = self.MOTION_PARAMS["dMaxA"]

        if target_position < 0 or target_position > safe_limit:
            self.logger.warning(f"Target position {target_position} is out of bounds for axis {axis}. Stopping.")
            return False

        try:
            result = self.dll.MCF_Set_Axis_Profile_Net(
                ctypes.c_ushort(axis),
                ctypes.c_double(self.MOTION_PARAMS["dV_ini"]),
                ctypes.c_double(max_velocity),
                ctypes.c_double(acceleration),
                ctypes.c_double(self.MOTION_PARAMS["dJerk"]),
                ctypes.c_double(self.MOTION_PARAMS["dV_end"]),
                ctypes.c_ushort(self.MOTION_PARAMS["profile"]),
                ctypes.c_ushort(0),
            )
            if result != 0:
                self.logger.error(f"Failed to set motion profile for axis {axis}. Error code: {result}")
                return False

            result = self.dll.MCF_Uniaxial_Net(
                ctypes.c_ushort(axis), ctypes.c_long(int(target_position)), ctypes.c_ushort(0)
            )
            if result != 0:
                self.logger.error(f"Failed to move axis {axis} to {target_position}. Error code: {result}")
                self.clear_axis_error(axis_name)
                return False

            return True

        except Exception as e:
            self.logger.error(f"Movement failed for axis {axis}: {e}")
            self.close()
            return False

    def set_params(self, params):
        """Set motion parameters for the specified axis."""
        for param, value in params.items():
            self.MOTION_PARAMS[param] = value

    def home_axis(self, axis):
        """Home the specified axis using a negative limit switch."""
        axis_name = self._normalize_axis_name(axis)
        axis = self.AXIS_MAPPING.get(axis_name, axis)
        homing_mode, limit_logic, home_logic, index_logic = 17, 0, 0, 0
        high_speed, low_speed, offset_position, trigger_source = 10000, 1000, 100, 0

        try:
            result = self.dll.MCF_Search_Home_Set_Net(
                ctypes.c_ushort(axis),
                ctypes.c_ushort(homing_mode),
                ctypes.c_ushort(limit_logic),
                ctypes.c_ushort(home_logic),
                ctypes.c_ushort(index_logic),
                ctypes.c_double(high_speed),
                ctypes.c_double(low_speed),
                ctypes.c_long(offset_position),
                ctypes.c_ushort(trigger_source),
                ctypes.c_ushort(0),
            )
            if result != 0:
                raise RuntimeError(f"Failed to set homing parameters for ==-----axis {axis}. Error: {result}")

            result = self.dll.MCF_Search_Home_Start_Net(
                ctypes.c_ushort(axis), ctypes.c_ushort(0)
            )
            if result != 0:
                raise RuntimeError(f"Failed to start homing for axis {axis}. Error: {result}")
            if axis_name in self._last_direction_by_axis:
                self._last_direction_by_axis[axis_name] = None
                self._corrected_offset_by_axis[axis_name] = 0
                self._raw_position_by_axis[axis_name] = None
                self._corrected_position_by_axis[axis_name] = None

        except Exception as e:
            self.logger.error(f"Homing failed for axis {axis}: {e}")
            self.close()
            raise

    def is_homing_complete(self, axis):
        """Check if the homing process is complete."""
        if axis == -1:
            return all(self.is_homing_complete(ax) == 0 for ax in self.AXIS_MAPPING.keys())

        axis = self.AXIS_MAPPING.get(axis.upper(), axis)
        home_state = ctypes.c_ushort(0)
        try:
            self.dll.MCF_Search_Home_Get_State_Net(
                ctypes.c_ushort(axis), ctypes.byref(home_state), ctypes.c_ushort(0)
            )
        except Exception as e:
            self.logger.error(f"Failed to check homing status for axis {axis}: {e}")
            self.close()
            raise
        return home_state.value

    def is_motion_complete(self, axis):
        """
        Return True when:
        - axis finished a commanded move normally (Reason == 0), or
        - axis == -1 and all axes finished.
        Return False while busy (Reason == 1); any other code means stopped by cause.
        """

        def _axis_reason(aid):
            reason = ctypes.c_ushort(0)
            ret = self.dll.MCF_Get_Axis_State_Net(
                ctypes.c_ushort(aid), ctypes.byref(reason), ctypes.c_ushort(0)
            )
            if ret != 0:
                self.logger.error(f"Get_Axis_State({aid}) failed, err={ret}")
                return 1
            return reason.value

        if axis == -1:
            return all(_axis_reason(aid) == 0 for aid in self.AXIS_MAPPING.values())

        axis_id = self.AXIS_MAPPING.get(axis.upper(), axis)
        return _axis_reason(axis_id) == 0

    def move_axis_to_position(self, axis, target_position):
        """Move the specified axis to an absolute position while respecting safe limits."""
        axis_name = self._normalize_axis_name(axis)
        if axis_name is None:
            self.logger.error(f"Invalid axis: {axis}")
            return False

        target_position = int(target_position)
        with self._motion_command_lock:
            if self._is_jog_active(axis_name):
                self._stop_active_jog(axis_name, clear_motion=True)
                self._refresh_axis_position_from_hardware(axis_name)

            current_corrected_position = self._refresh_axis_position_from_hardware(axis_name)
            current_raw_position = self._raw_position_by_axis.get(axis_name)
            if current_corrected_position is None or current_raw_position is None:
                self.logger.error(f"Failed to refresh positions for axis {axis_name}.")
                return False

            logical_delta = int(target_position) - int(current_corrected_position)
            current_direction = self._direction_for_axis_delta(axis_name, logical_delta)

            if logical_delta == 0:
                return True

            current_offset = int(self._corrected_offset_by_axis.get(axis_name, 0) or 0)
            target_offset = self._get_target_offset_for_direction(axis_name, current_direction)

            if current_offset != target_offset:
                if not self._preload_axis_backlash(axis_name, target_offset, current_corrected_position):
                    return False
                current_raw_position = self._raw_position_by_axis.get(axis_name)
            else:
                self._update_axis_tracking_state(
                    axis_name,
                    current_raw_position,
                    current_corrected_position,
                    target_offset,
                )

            raw_target_position = int(target_position) + int(target_offset)

            if not self._is_target_within_safe_limits(axis_name, raw_target_position):
                self.logger.warning(
                    "Corrected target %s maps to raw target %s, which exceeds safe limits for axis %s.",
                    target_position,
                    raw_target_position,
                    axis_name,
                )
                return False

            result = self._execute_absolute_move(axis_name, raw_target_position)
            if result:
                self._last_direction_by_axis[axis_name] = current_direction
            return result

    def get_axis_error_reason(self, axis):
        axis_name = self._normalize_axis_name(axis)
        axis_id = self.AXIS_MAPPING.get(axis_name, axis)
        reason = ctypes.c_ushort(0)
        ret = self.dll.MCF_Get_Axis_State_Net(
            ctypes.c_ushort(axis_id),
            ctypes.byref(reason),
            ctypes.c_ushort(0),
        )
        if ret != 0:
            self.logger.error(f"Failed to get axis state for {axis} (code {ret})")
            return None
        return reason.value

    def clear_axis_error(self, axis):
        reason = self.get_axis_error_reason(axis)
        if reason is None:
            return False

        safe_to_clear = {1, 22}
        if reason in safe_to_clear:
            self.logger.info(f"Axis {axis} has reason {reason}, attempting to clear.")
            axis_name = self._normalize_axis_name(axis)
            result = self.dll.MCF_Clear_Axis_State_Net(
                ctypes.c_ushort(self.AXIS_MAPPING[axis_name]), ctypes.c_ushort(0)
            )
            if result != 0:
                return False
            self.logger.info(f"Cleared error state for axis {axis}")
            return True
        return False

    def stop_and_clear_axis(self, axis):
        """Stop the axis and clear its latched state, ensuring clean transition for next movement."""
        axis_name = self._normalize_axis_name(axis)
        axis_id = self.AXIS_MAPPING.get(axis_name, axis)

        try:
            result = self.dll.MCF_Set_Axis_Stop_Profile_Net(
                ctypes.c_ushort(axis_id),
                ctypes.c_double(self.MOTION_PARAMS["dMaxA"]),
                ctypes.c_double(self.MOTION_PARAMS["dJerk"]),
                ctypes.c_ushort(0),
                ctypes.c_ushort(0),
            )
            if result != 0:
                self.logger.warning(f"Failed to set stop profile for axis {axis} (code {result})")
        except Exception as e:
            self.logger.warning(f"Exception setting stop profile for axis {axis}: {e}")

        try:
            result = self.dll.MCF_Axis_Stop_Net(
                ctypes.c_ushort(axis_id),
                ctypes.c_int(0),
                ctypes.c_ushort(0),
            )
            if result != 0:
                self.logger.error(f"Failed to stop axis {axis} (code {result})")
                return False
        except Exception as e:
            self.logger.error(f"Exception stopping axis {axis}: {e}")
            return False

        timeout = 10
        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                self.logger.error(f"Timeout waiting for axis {axis} to stop")
                return False

            reason = ctypes.c_ushort(0)
            ret = self.dll.MCF_Get_Axis_State_Net(
                ctypes.c_ushort(axis_id),
                ctypes.byref(reason),
                ctypes.c_ushort(0),
            )
            if ret != 0:
                self.logger.error(f"Get_Axis_State({axis_id}) failed, err={ret}")
                return False
            if reason.value != 1:
                break
            time.sleep(0.01)

        try:
            result = self.dll.MCF_Clear_Axis_State_Net(
                ctypes.c_ushort(axis_id), ctypes.c_ushort(0)
            )
            if result != 0:
                return False
        except Exception:
            return False

        return True

    def start_continuous_movement(self, axis, direction):
        """Start continuous jog movement in a given direction while checking limits."""
        axis_name = self._normalize_axis_name(axis)
        axis = self.AXIS_MAPPING.get(axis_name)
        if axis is None:
            raise ValueError(f"Invalid axis: {axis}")

        safe_limit = self.SAFE_LIMITS[axis_name]
        max_velocity = self.MOTION_PARAMS["dMaxV"] * direction
        acceleration = self.MOTION_PARAMS["dMaxA"]
        continuous_direction = self._direction_for_continuous_movement(axis_name, direction)

        def jog_loop():
            while self._jog_active_by_axis.get(axis_name, False):
                current_position = ctypes.c_long()
                result = self.dll.MCF_Get_Position_Net(
                    ctypes.c_ushort(axis), ctypes.byref(current_position), ctypes.c_ushort(0)
                )
                if result != 0:
                    self.logger.error(f"Failed to get position for axis {axis}. Error: {result}")
                    self._jog_active_by_axis[axis_name] = False
                    self._jog_direction_by_axis[axis_name] = None
                    self.stop_and_clear_axis(axis_name)
                    break

                new_position = current_position.value + (direction * 100)

                if new_position < 0 or new_position > safe_limit:
                    self._jog_active_by_axis[axis_name] = False
                    self._jog_direction_by_axis[axis_name] = None
                    self.stop_and_clear_axis(axis_name)
                    break

                if self._jog_active_by_axis.get(axis_name, False):
                    result = self.dll.MCF_JOG_Net(
                        ctypes.c_ushort(axis),
                        ctypes.c_double(max_velocity),
                        ctypes.c_double(acceleration),
                        ctypes.c_ushort(0),
                    )
                    if result not in {0, 1}:
                        self.logger.error(f"Failed to jog axis {axis}. Error: {result}")
                        self._jog_active_by_axis[axis_name] = False
                        self._jog_direction_by_axis[axis_name] = None
                        self.stop_and_clear_axis(axis_name)
                        break
                else:
                    break

            self._jog_active_by_axis[axis_name] = False
            self._jog_direction_by_axis[axis_name] = None

        with self._motion_command_lock:
            if self._is_jog_active(axis_name):
                active_direction = self._jog_direction_by_axis.get(axis_name)
                if active_direction == continuous_direction:
                    return
                self._stop_active_jog(axis_name, clear_motion=True)
                self._refresh_axis_position_from_hardware(axis_name)

            current_corrected_position = self._refresh_axis_position_from_hardware(axis_name)
            current_raw_position = self._raw_position_by_axis.get(axis_name)
            if current_corrected_position is None or current_raw_position is None:
                self.logger.error(f"Failed to read axis state for jog startup on axis {axis_name}.")
                return

            current_offset = int(self._corrected_offset_by_axis.get(axis_name, 0) or 0)
            target_offset = self._get_target_offset_for_direction(axis_name, continuous_direction)

            if current_offset != target_offset:
                if not self._preload_axis_backlash(axis_name, target_offset, current_corrected_position):
                    return
            else:
                self._update_axis_tracking_state(
                    axis_name,
                    current_raw_position,
                    current_corrected_position,
                    target_offset,
                )

            self._last_direction_by_axis[axis_name] = continuous_direction
            self._jog_active_by_axis[axis_name] = True
            self._jog_direction_by_axis[axis_name] = continuous_direction
            jog_thread = threading.Thread(
                target=jog_loop,
                name=f"XYJog-{axis_name}",
                daemon=True,
            )
            self._jog_threads_by_axis[axis_name] = jog_thread
            jog_thread.start()

    def stop_continuous_movement(self, axis):
        """Stop continuous jog movement when the joystick is released."""
        axis_name = self._normalize_axis_name(axis)
        axis_id = self.AXIS_MAPPING.get(axis_name)

        if axis_id is None:
            self.stop_motion(axis_name)
            raise ValueError(f"Invalid axis: {axis}")

        with self._motion_command_lock:
            self._stop_active_jog(axis_name, clear_motion=True)
            self._refresh_axis_position_from_hardware(axis_name)

    def get_raw_position(self, axis):
        """Retrieve the current hardware/raw position of the specified axis."""
        axis_name = self._normalize_axis_name(axis)
        if axis_name is None:
            self.logger.error(f"Invalid axis: {axis}")
            return None

        with self._motion_command_lock:
            raw_position = self._read_raw_position(axis_name)
            if raw_position is None:
                return None
            self._raw_position_by_axis[axis_name] = raw_position
            current_offset = int(self._corrected_offset_by_axis.get(axis_name, 0) or 0)
            self._corrected_position_by_axis[axis_name] = int(raw_position) - current_offset
            return raw_position

    def get_position(self, axis):
        """Retrieve the current backlash-corrected logical position of the specified axis."""
        axis_name = self._normalize_axis_name(axis)
        if axis_name is None:
            self.logger.error(f"Invalid axis: {axis}")
            return None

        with self._motion_command_lock:
            corrected_position = self._refresh_axis_position_from_hardware(axis_name)
            if corrected_position is None:
                return None
            return int(corrected_position)

    def stop_motion(self, axis, stop_mode=0):
        """Stop the motion of the specified axis immediately for safety."""
        axis_name = self._normalize_axis_name(axis)
        axis = self.AXIS_MAPPING.get(axis_name, axis)
        try:
            result = self.dll.MCF_Axis_Stop_Net(
                ctypes.c_ushort(axis), ctypes.c_int(stop_mode), ctypes.c_ushort(0)
            )
            if result != 0:
                self.logger.debug(f"Failed to stop axis {axis} (code {result})")
        except Exception as e:
            self.logger.debug(f"Failed to stop axis {axis}: {e}")

    def close(self):
        """Close the connection and reset the singleton state."""
        if self.connected:
            try:
                self.stop_motion("X")
            except Exception:
                pass
            try:
                self.stop_motion("Y")
            except Exception:
                pass
            try:
                self.stop_motion("Z")
            except Exception:
                pass

            try:
                result = self.dll.MCF_Close_Net()
                if result != 0:
                    self.logger.debug(f"Failed to close motion control card (code {result})")
            except Exception as e:
                self.logger.debug(f"Error while closing motion control card: {e}")
            finally:
                self.connected = False

        self._initialized = False
        type(self)._instance = None

    def get_home_switch(self, axis):
        """Get the state of the home switch for the specified axis."""
        axis_name = self._normalize_axis_name(axis)
        axis_id = self.AXIS_MAPPING.get(axis_name, axis)
        state = ctypes.c_ushort(0)
        try:
            result = self.dll.MCF_Get_Home_Net(
                ctypes.c_ushort(axis_id), ctypes.byref(state), ctypes.c_ushort(0)
            )
            if result != 0:
                self.logger.error(f"Failed to get home switch state for axis {axis}. Error code: {result}")
                return None
            return state.value
        except Exception as e:
            self.logger.error(f"Exception getting home switch for axis {axis}: {e}")
            return None

    def get_positive_limit(self, axis):
        """Get the state of the positive limit switch for the specified axis."""
        axis_name = self._normalize_axis_name(axis)
        axis_id = self.AXIS_MAPPING.get(axis_name, axis)
        state = ctypes.c_ushort(0)
        try:
            result = self.dll.MCF_Get_Positive_Limit_Net(
                ctypes.c_ushort(axis_id), ctypes.byref(state), ctypes.c_ushort(0)
            )
            if result != 0:
                self.logger.error(f"Failed to get positive limit state for axis {axis}. Error code: {result}")
                return None
            return state.value
        except Exception as e:
            self.logger.error(f"Exception getting positive limit for axis {axis}: {e}")
            return None

    def get_negative_limit(self, axis):
        """Get the state of the negative limit switch for the specified axis."""
        axis_name = self._normalize_axis_name(axis)
        axis_id = self.AXIS_MAPPING.get(axis_name, axis)
        state = ctypes.c_ushort(0)
        try:
            result = self.dll.MCF_Get_Negative_Limit_Net(
                ctypes.c_ushort(axis_id), ctypes.byref(state), ctypes.c_ushort(0)
            )
            if result != 0:
                self.logger.error(f"Failed to get negative limit state for axis {axis}. Error code: {result}")
                return None
            return state.value
        except Exception as e:
            self.logger.error(f"Exception getting negative limit for axis {axis}: {e}")
            return None

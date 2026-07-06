"""DropLogic MCP server entrypoint."""

import argparse
import builtins
import ctypes
import contextlib
import inspect
import json
import os
import sys
from io import TextIOWrapper
from typing import Any, Callable, Dict, List, Optional, TypeVar


_T = TypeVar("_T")

def _redirect_prints_to_stderr() -> None:
    """Keep MCP stdout reserved for protocol messages."""
    original_print = builtins.print

    def print_to_stderr(*args, **kwargs):
        file = kwargs.get("file")
        if file is None or file is sys.stdout:
            kwargs["file"] = sys.stderr
        return original_print(*args, **kwargs)

    builtins.print = print_to_stderr


_redirect_prints_to_stderr()

from .runtime import DropLogicMCPRuntime


@contextlib.contextmanager
def _isolate_stdio_protocol_stdout():
    """Keep MCP protocol writes on the original stdout while fd 1 is noisy-safe."""
    if not hasattr(os, "dup") or not hasattr(os, "dup2"):
        yield
        return

    stdout_fd = 1
    stderr_fd = 2
    protocol_stdout = None
    old_stdout = sys.stdout
    old___stdout__ = sys.__stdout__
    saved_stdout_fd = None
    saved_stdout_handle = None
    kernel32 = None

    try:
        sys.stdout.flush()
        sys.stderr.flush()

        saved_stdout_fd = os.dup(stdout_fd)
        protocol_stdout_fd = os.dup(stdout_fd)
        protocol_stdout = TextIOWrapper(
            os.fdopen(protocol_stdout_fd, "wb", buffering=0),
            encoding="utf-8",
            write_through=True,
        )
        sys.stdout = protocol_stdout
        sys.__stdout__ = protocol_stdout

        if os.name == "nt":
            try:
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                saved_stdout_handle = kernel32.GetStdHandle(-11)
            except Exception:
                kernel32 = None

        os.dup2(stderr_fd, stdout_fd)
        if kernel32 is not None:
            try:
                kernel32.SetStdHandle(-11, kernel32.GetStdHandle(-12))
            except Exception:
                pass

        yield
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass

        if saved_stdout_fd is not None:
            os.dup2(saved_stdout_fd, stdout_fd)
            os.close(saved_stdout_fd)

        if kernel32 is not None and saved_stdout_handle is not None:
            try:
                kernel32.SetStdHandle(-11, saved_stdout_handle)
            except Exception:
                pass

        sys.stdout = old_stdout
        sys.__stdout__ = old___stdout__

        if protocol_stdout is not None:
            try:
                protocol_stdout.close()
            except Exception:
                pass


@contextlib.contextmanager
def _redirect_native_stdout_to_stderr():
    """Redirect C/vendor writes to stdout while preserving MCP's stdio stream."""
    if not hasattr(os, "dup") or not hasattr(os, "dup2"):
        yield
        return

    stdout_fd = 1
    stderr_fd = 2
    saved_stdout_fd = None
    saved_stdout_handle = None
    kernel32 = None

    try:
        saved_stdout_fd = os.dup(stdout_fd)

        if os.name == "nt":
            try:
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                saved_stdout_handle = kernel32.GetStdHandle(-11)
            except Exception:
                kernel32 = None

        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(stderr_fd, stdout_fd)
        if kernel32 is not None:
            try:
                kernel32.SetStdHandle(-11, kernel32.GetStdHandle(-12))
            except Exception:
                pass

        yield
    finally:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        if saved_stdout_fd is not None:
            os.dup2(saved_stdout_fd, stdout_fd)
            os.close(saved_stdout_fd)
        if kernel32 is not None and saved_stdout_handle is not None:
            try:
                kernel32.SetStdHandle(-11, saved_stdout_handle)
            except Exception:
                pass


def _runtime_call(fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """Run DropLogic code without letting hardware/library stdout corrupt stdio MCP."""
    with contextlib.redirect_stdout(sys.stderr), _redirect_native_stdout_to_stderr():
        result = fn(*args, **kwargs)
        runtime = getattr(fn, "__self__", None)
        writer = getattr(runtime, "write_dashboard_scene_snapshot", None)
        if writer is not None:
            try:
                writer()
            except Exception:
                pass
        return result


def _import_fastmcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:
        raise RuntimeError(
            "The DropLogic MCP server requires the optional MCP dependency. "
            "Install it with: pip install 'droplogic[agent]'"
        ) from exc
    return FastMCP


def _build_fastmcp(name: str, host: str, port: int):
    """Create FastMCP while tolerating minor SDK constructor differences."""
    FastMCP = _import_fastmcp()
    signature = inspect.signature(FastMCP)
    kwargs = {}
    if "host" in signature.parameters:
        kwargs["host"] = host
    if "port" in signature.parameters:
        kwargs["port"] = port
    server = FastMCP(name, **kwargs)

    settings = getattr(server, "settings", None)
    if settings is not None:
        for key, value in (("host", host), ("port", port)):
            if hasattr(settings, key):
                try:
                    setattr(settings, key, value)
                except Exception:
                    pass
    return server


def build_server(runtime: DropLogicMCPRuntime, host: str = "127.0.0.1", port: int = 8765):
    """Build a FastMCP server bound to a DropLogic runtime."""
    mcp = _build_fastmcp("DropLogic", host=host, port=port)

    @mcp.tool()
    def load_system(
        system: str = "simulator",
        config_file: Optional[str] = None,
        log_level: Optional[str] = None,
        reset_matrix: bool = False,
    ) -> Dict[str, Any]:
        """Load simulator, dmlite, or boxmini into the MCP runtime."""
        return _runtime_call(
            runtime.load_system,
            system,
            config_file=config_file,
            log_level=log_level,
            reset_matrix=reset_matrix,
        )

    @mcp.tool()
    def close_system() -> Dict[str, Any]:
        """Close the currently loaded DropLogic system."""
        return _runtime_call(runtime.close_system)

    @mcp.tool()
    def restart_system(
        system: Optional[str] = None,
        config_file: Optional[str] = None,
        log_level: Optional[str] = None,
        reset_matrix: bool = False,
    ) -> Dict[str, Any]:
        """Close and reload the current or requested DropLogic system."""
        return _runtime_call(
            runtime.restart_system,
            system=system,
            config_file=config_file,
            log_level=log_level,
            reset_matrix=reset_matrix,
        )

    @mcp.tool()
    def runtime_status(detail: str = "compact") -> Dict[str, Any]:
        """Return server, system, executor, plan and droplet status."""
        return _runtime_call(runtime.status, detail=detail)

    @mcp.tool()
    def health_check() -> Dict[str, Any]:
        """Return MCP runtime, worker, executor and module health information."""
        return _runtime_call(runtime.health_check)

    @mcp.tool()
    def capabilities() -> Dict[str, Any]:
        """Return the DropLogic functions and observability surfaces available to agents."""
        return _runtime_call(runtime.capabilities)

    @mcp.tool()
    def read_state(
        path: Optional[str] = None,
        include_large_values: bool = False,
    ) -> Dict[str, Any]:
        """Read DropSystem state safely; large raw values are guarded unless explicitly enabled."""
        return _runtime_call(
            runtime.read_state,
            path,
            include_large_values=include_large_values,
        )

    @mcp.tool()
    def state_summary(path: Optional[str] = None) -> Dict[str, Any]:
        """Read a summarized DropSystem state or a dotted path; numeric path parts index lists."""
        return _runtime_call(runtime.state_summary, path)

    @mcp.tool()
    def matrix_summary(
        source: str = "state",
        include_ranges: bool = True,
        include_active_cells: bool = False,
        active_cells_limit: int = 512,
        include_hash: bool = True,
    ) -> Dict[str, Any]:
        """Return exact compact active ranges for the latest electrode matrix."""
        return _runtime_call(
            runtime.matrix_summary,
            source=source,
            include_ranges=include_ranges,
            include_active_cells=include_active_cells,
            active_cells_limit=active_cells_limit,
            include_hash=include_hash,
        )

    @mcp.tool()
    def matrix_voltage_status() -> Dict[str, Any]:
        """Query the active electrode matrix voltage channels."""
        return _runtime_call(runtime.matrix_voltage_status)

    @mcp.tool()
    def set_matrix_voltage(values: List[int]) -> Dict[str, Any]:
        """Set the active electrode matrix voltage profile. Pass 1, 4, or 9 values."""
        return _runtime_call(runtime.set_matrix_voltage, values)

    @mcp.tool()
    def set_matrix_cells(
        value: int,
        cells: Optional[List[List[int]]] = None,
        rectangles: Optional[List[Dict[str, int]]] = None,
        row_min: Optional[int] = None,
        row_max: Optional[int] = None,
        col_min: Optional[int] = None,
        col_max: Optional[int] = None,
        wait_for_queue: bool = False,
        queue_timeout_seconds: float = 5.0,
    ) -> Dict[str, Any]:
        """Set logical matrix cells: -1 forbidden, 0 clean/off, 1 permanent ON."""
        return _runtime_call(
            runtime.set_matrix_cells,
            value=value,
            cells=cells,
            rectangles=rectangles,
            row_min=row_min,
            row_max=row_max,
            col_min=col_min,
            col_max=col_max,
            wait_for_queue=wait_for_queue,
            queue_timeout_seconds=queue_timeout_seconds,
        )

    @mcp.tool()
    def set_calibration(calibration: Dict[str, Any]) -> Dict[str, Any]:
        """Update the loaded system calibration mapping after operator calibration."""
        return _runtime_call(runtime.set_calibration, calibration)

    @mcp.tool()
    def execution_status_summary(
        include_matrix: bool = True,
        include_plan: bool = True,
        include_droplets: bool = True,
        include_visualizers: bool = False,
        include_planning_job: bool = True,
        include_execution_wait: bool = True,
    ) -> Dict[str, Any]:
        """Return one compact runtime/executor/plan/droplet/matrix status snapshot."""
        return _runtime_call(
            runtime.execution_status_summary,
            include_matrix=include_matrix,
            include_plan=include_plan,
            include_droplets=include_droplets,
            include_visualizers=include_visualizers,
            include_planning_job=include_planning_job,
            include_execution_wait=include_execution_wait,
        )

    @mcp.tool()
    def execution_scene(
        max_path_points: int = 64,
        include_paths: bool = True,
        include_droplet_cells: bool = False,
        max_droplet_cells: int = 0,
    ) -> Dict[str, Any]:
        """Return compact plan/executor scene state for reasoning or external rendering."""
        return _runtime_call(
            runtime.execution_scene,
            max_path_points=max_path_points,
            include_paths=include_paths,
            include_droplet_cells=include_droplet_cells,
            max_droplet_cells=max_droplet_cells,
        )

    @mcp.tool()
    def dashboard_scene(
        max_path_points: int = 256,
        max_droplet_cells: int = 1024,
    ) -> Dict[str, Any]:
        """Dashboard internal: return the freshest full dashboard scene; hidden from agents."""
        return _runtime_call(
            runtime.dashboard_scene,
            max_path_points=max_path_points,
            max_droplet_cells=max_droplet_cells,
        )

    if getattr(runtime, "allow_large_state_tools", False):
        @mcp.tool()
        def read_large_state(path: str) -> Dict[str, Any]:
            """Debug only: read a guarded large raw state value."""
            return _runtime_call(runtime.read_large_state, path)

    @mcp.tool()
    def context_status() -> Dict[str, Any]:
        """Return the active agent context summary."""
        return _runtime_call(runtime.context_status)

    @mcp.tool()
    def list_context_files() -> Dict[str, Any]:
        """Return the merged list of agent context files."""
        return _runtime_call(runtime.list_context_files)

    @mcp.tool()
    def read_context_file(path: str) -> Dict[str, Any]:
        """Read one agent context file."""
        return _runtime_call(runtime.read_context_file, path)

    if getattr(runtime, "allow_unsafe_tools", False):
        @mcp.tool()
        def set_system_state(path: str, value: Any) -> Dict[str, Any]:
            """Unsafe debug only: set a raw DropSystem state path."""
            return _runtime_call(runtime.set_system_state, path, value)

    @mcp.tool()
    def emergency_stop(deactivate_electrodes: bool = True) -> Dict[str, Any]:
        """Stop plan execution, clear queues and optionally turn electrodes off."""
        return _runtime_call(
            runtime.emergency_stop,
            deactivate_electrodes=deactivate_electrodes,
        )

    @mcp.tool()
    def visualizer_frame(
        visualizer: str = "matrix",
        frame_source: str = "snapshot",
        image_format: str = "png",
        include_base64: bool = True,
        output_path: Optional[str] = None,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        image_quality: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return a matrix or streamer frame as base64 and/or a saved image path.

        Relative output_path values are saved under the managed DropLogic capture
        directory, not the current working directory.
        """
        return _runtime_call(
            runtime.visualizer_frame,
            visualizer=visualizer,
            frame_source=frame_source,
            image_format=image_format,
            include_base64=include_base64,
            output_path=output_path,
            max_width=max_width,
            max_height=max_height,
            image_quality=image_quality,
        )

    @mcp.tool()
    def visualizer_status() -> Dict[str, Any]:
        """Return matrix and streamer visualizer status."""
        return _runtime_call(runtime.visualizer_status)

    @mcp.tool()
    def start_visualizer(visualizer: str = "matrix") -> Dict[str, Any]:
        """Start a visualizer window when supported by the host OS."""
        return _runtime_call(runtime.start_visualizer, visualizer)

    @mcp.tool()
    def stop_visualizer(visualizer: str = "matrix") -> Dict[str, Any]:
        """Stop a visualizer window."""
        return _runtime_call(runtime.stop_visualizer, visualizer)

    @mcp.tool()
    def bring_visualizer_to_front(visualizer: str = "streamer") -> Dict[str, Any]:
        """Bring a matrix or streamer visualizer window to the foreground."""
        return _runtime_call(runtime.bring_visualizer_to_front, visualizer)

    @mcp.tool()
    def prepare_visualizers(
        start_matrix: bool = True,
        start_streamer: bool = True,
        streamer_source: str = "microscope",
        streamer_coordinates: bool = False,
        streamer_electrode_overlay: bool = True,
        bring_to_front: bool = True,
        warmup_seconds: float = 1.0,
    ) -> Dict[str, Any]:
        """Configure/start BoxMini run visualizers using the microscope live stream."""
        return _runtime_call(
            runtime.prepare_visualizers,
            start_matrix=start_matrix,
            start_streamer=start_streamer,
            streamer_source=streamer_source,
            streamer_coordinates=streamer_coordinates,
            streamer_electrode_overlay=streamer_electrode_overlay,
            bring_to_front=bring_to_front,
            warmup_seconds=warmup_seconds,
        )

    @mcp.tool()
    def set_streamer_source(
        source: str = "microscope",
        electrode_overlay: Optional[bool] = None,
        coordinates: Optional[bool] = None,
        bring_to_front: bool = False,
    ) -> Dict[str, Any]:
        """Switch only streamer source; use set_execution_view_mode for whole-chip positioning."""
        return _runtime_call(
            runtime.set_streamer_source,
            source=source,
            electrode_overlay=electrode_overlay,
            coordinates=coordinates,
            bring_to_front=bring_to_front,
        )

    @mcp.tool()
    def set_light_state(
        light_on: Optional[bool] = None,
        coaxial_intensity: Optional[int] = None,
        ring_intensity: Optional[int] = None,
        wait_for_queue: bool = True,
        queue_timeout_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """Set BoxMini light master/coaxial/ring safely; use light_off for all-off."""
        return _runtime_call(
            runtime.set_light_state,
            light_on=light_on,
            coaxial_intensity=coaxial_intensity,
            ring_intensity=ring_intensity,
            wait_for_queue=wait_for_queue,
            queue_timeout_seconds=queue_timeout_seconds,
        )

    @mcp.tool()
    def light_off(
        wait_for_queue: bool = True,
        queue_timeout_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """Turn all BoxMini illumination off: coaxial=0, ring=0, master=false."""
        return _runtime_call(
            runtime.light_off,
            wait_for_queue=wait_for_queue,
            queue_timeout_seconds=queue_timeout_seconds,
        )

    @mcp.tool()
    def configure_microscope_imaging(
        channel: str = "Brightfield",
        exposure_time: Optional[int] = None,
        gain: Optional[int] = None,
        coaxial_intensity: Optional[int] = None,
        ring_intensity: Optional[int] = None,
        auto_exposure: Optional[bool] = None,
        restart_streamer: bool = True,
        bring_to_front: bool = False,
        stabilization_wait: float = 0.5,
        queue_timeout_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """Configure microscope imaging safely; pass only channel/preset to use current saved presets."""
        return _runtime_call(
            runtime.configure_microscope_imaging,
            channel=channel,
            exposure_time=exposure_time,
            gain=gain,
            coaxial_intensity=coaxial_intensity,
            ring_intensity=ring_intensity,
            auto_exposure=auto_exposure,
            restart_streamer=restart_streamer,
            bring_to_front=bring_to_front,
            stabilization_wait=stabilization_wait,
            queue_timeout_seconds=queue_timeout_seconds,
        )

    @mcp.tool()
    def configure_camera_imaging(
        exposure_time: int = 72000,
        gain: int = 0,
        auto_exposure: bool = False,
        queue_timeout_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """Configure the primary camera exposure/gain safely."""
        return _runtime_call(
            runtime.configure_camera_imaging,
            exposure_time=exposure_time,
            gain=gain,
            auto_exposure=auto_exposure,
            queue_timeout_seconds=queue_timeout_seconds,
        )

    @mcp.tool()
    def capture_droplet_images(
        droplet_ids: Optional[List[int]] = None,
        channels: Optional[List[Any]] = None,
        output_dir: Optional[str] = None,
        temperature_label: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        capture_source: str = "streamer",
        restart_streamer: bool = True,
        restore_low_light: bool = True,
        image_format: str = "png",
        wait_before_check: float = 0.5,
        wait_after_check: float = 0.5,
    ) -> Dict[str, Any]:
        """Move to droplets and save images; channel strings like FAM resolve current saved imaging presets.

        If output_dir is omitted or relative, images are saved under the managed
        DropLogic capture directory instead of the repository root.
        """
        return _runtime_call(
            runtime.capture_droplet_images,
            droplet_ids=droplet_ids,
            channels=channels,
            output_dir=output_dir,
            temperature_label=temperature_label,
            metadata=metadata,
            capture_source=capture_source,
            restart_streamer=restart_streamer,
            restore_low_light=restore_low_light,
            image_format=image_format,
            wait_before_check=wait_before_check,
            wait_after_check=wait_after_check,
        )

    @mcp.tool()
    def temperature_hold(
        target_c: float,
        hold_seconds: float,
        tolerance_c: float = 0.2,
        settle_timeout_seconds: float = 600.0,
        sample_interval_seconds: float = 5.0,
        require_settle: bool = False,
        max_samples: int = 20,
    ) -> Dict[str, Any]:
        """Set temperature and hold/wait with compact sampled feedback."""
        return _runtime_call(
            runtime.temperature_hold,
            target_c=target_c,
            hold_seconds=hold_seconds,
            tolerance_c=tolerance_c,
            settle_timeout_seconds=settle_timeout_seconds,
            sample_interval_seconds=sample_interval_seconds,
            require_settle=require_settle,
            max_samples=max_samples,
        )

    @mcp.tool()
    def start_temperature_routine(
        steps: List[Dict[str, Any]],
        tolerance_c: float = 0.2,
        settle_timeout_seconds: float = 600.0,
        sample_interval_seconds: float = 5.0,
        require_settle: bool = True,
        max_samples_per_step: int = 20,
        stop_on_error: bool = True,
    ) -> Dict[str, Any]:
        """Start a background temperature routine; poll status separately."""
        return _runtime_call(
            runtime.start_temperature_routine,
            steps=steps,
            tolerance_c=tolerance_c,
            settle_timeout_seconds=settle_timeout_seconds,
            sample_interval_seconds=sample_interval_seconds,
            require_settle=require_settle,
            max_samples_per_step=max_samples_per_step,
            stop_on_error=stop_on_error,
        )

    @mcp.tool()
    def temperature_routine_status() -> Dict[str, Any]:
        """Return compact status for the active or last temperature routine."""
        return _runtime_call(runtime.temperature_routine_status)

    @mcp.tool()
    def cancel_temperature_routine() -> Dict[str, Any]:
        """Cancel the active background temperature routine."""
        return _runtime_call(runtime.cancel_temperature_routine)

    @mcp.tool()
    def start_melting_curve_capture(
        start_c: Optional[float] = None,
        end_c: Optional[float] = None,
        step_c: float = 0.5,
        temperature_steps: Optional[List[Dict[str, Any]]] = None,
        hold_seconds: float = 300.0,
        droplet_ids: Optional[List[int]] = None,
        channels: Optional[List[Any]] = None,
        output_dir: Optional[str] = None,
        capture_mode: str = "droplets",
        visualizer: str = "streamer",
        frame_source: str = "device_raw",
        tolerance_c: float = 0.2,
        settle_timeout_seconds: float = 600.0,
        sample_interval_seconds: float = 5.0,
        require_settle: bool = True,
        max_samples_per_step: int = 20,
        stop_on_error: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        capture_source: str = "streamer",
        restart_streamer: bool = True,
        restore_low_light: bool = True,
        image_format: str = "png",
        wait_before_check: float = 0.5,
        wait_after_check: float = 0.5,
    ) -> Dict[str, Any]:
        """Run a background melting curve and capture an image after every temperature step.

        Use capture_mode='droplets' with channels like ['FAM'] for per-droplet
        fluorescence from saved presets, or capture_mode='whole_chip_camera' for
        fixed whole-cartridge overview photos.
        """
        return _runtime_call(
            runtime.start_melting_curve_capture,
            start_c=start_c,
            end_c=end_c,
            step_c=step_c,
            temperature_steps=temperature_steps,
            hold_seconds=hold_seconds,
            droplet_ids=droplet_ids,
            channels=channels,
            output_dir=output_dir,
            capture_mode=capture_mode,
            visualizer=visualizer,
            frame_source=frame_source,
            tolerance_c=tolerance_c,
            settle_timeout_seconds=settle_timeout_seconds,
            sample_interval_seconds=sample_interval_seconds,
            require_settle=require_settle,
            max_samples_per_step=max_samples_per_step,
            stop_on_error=stop_on_error,
            metadata=metadata,
            capture_source=capture_source,
            restart_streamer=restart_streamer,
            restore_low_light=restore_low_light,
            image_format=image_format,
            wait_before_check=wait_before_check,
            wait_after_check=wait_after_check,
        )

    @mcp.tool()
    def melting_curve_capture_status() -> Dict[str, Any]:
        """Return compact status for the active or last melting-curve capture."""
        return _runtime_call(runtime.melting_curve_capture_status)

    @mcp.tool()
    def cancel_melting_curve_capture() -> Dict[str, Any]:
        """Cancel the active melting-curve capture."""
        return _runtime_call(runtime.cancel_melting_curve_capture)

    @mcp.tool()
    def create_droplet(
        droplet_id: int,
        origin: List[int],
        target: Optional[List[int]] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        shape: Optional[List[List[int]]] = None,
        priority: int = 0,
        vital_space: int = 1,
    ) -> Dict[str, Any]:
        """Create one logical droplet. Use origin=[row,col]; target defaults to origin."""
        return _runtime_call(
            runtime.create_droplet,
            droplet_id=droplet_id,
            origin=origin,
            target=target,
            width=width,
            height=height,
            shape=shape,
            priority=priority,
            vital_space=vital_space,
        )

    @mcp.tool()
    def add_droplets(droplets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create multiple logical droplets. Each entry needs id/droplet_id, origin=[row,col], and normally target=[row,col]."""
        return _runtime_call(runtime.add_droplets, droplets)

    @mcp.tool()
    def clear_droplet_state(reset_executor: bool = True) -> Dict[str, Any]:
        """Clear all logical droplets and plan frames; reset executor cursor by default."""
        return _runtime_call(
            runtime.clear_droplet_state,
            reset_executor=reset_executor,
        )

    @mcp.tool()
    def delete_droplet(
        droplet_id: int,
        persist_electrodes: bool = False,
    ) -> Dict[str, Any]:
        """Delete a droplet by id; by default clears its electrodes in the next plan frame."""
        return _runtime_call(
            runtime.delete_droplet,
            droplet_id,
            persist_electrodes=persist_electrodes,
        )

    @mcp.tool()
    def update_droplet_target(droplet_id: int, target: List[int]) -> Dict[str, Any]:
        """Set one droplet target=[row,col] after validating the active layout."""
        return _runtime_call(runtime.update_droplet_target, droplet_id, target)

    @mcp.tool()
    def update_droplet_targets(
        targets: Any,
        include_summary: bool = False,
    ) -> Dict[str, Any]:
        """Set many validated targets. Accepts [{"id":1,"target":[r,c]}] or {"1":[r,c]}."""
        return _runtime_call(
            runtime.update_droplet_targets,
            targets=targets,
            include_summary=include_summary,
        )

    @mcp.tool()
    def update_droplet_position(droplet_id: int, position: List[int]) -> Dict[str, Any]:
        """Update a droplet current logical coordinate."""
        return _runtime_call(runtime.update_droplet_position, droplet_id, position)

    @mcp.tool()
    def trim_plan_tail(keep_frames: int) -> Dict[str, Any]:
        """Delete planned tail frames, preserving already executed/applied frames."""
        return _runtime_call(runtime.trim_plan_tail, keep_frames)

    @mcp.tool()
    def droplets_summary() -> Dict[str, Any]:
        """Return all droplets and their current targets."""
        return _runtime_call(runtime.droplets_summary)

    @mcp.tool()
    def plan_activation_frame(
        event_type: str = "activation",
        event_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Plan one activation frame for current droplets; does not execute hardware."""
        return _runtime_call(
            runtime.plan_activation_frame,
            event_type=event_type,
            event_data=event_data,
        )

    @mcp.tool()
    def plan_move(
        mode: str = "sipp",
        remove_duplicate_frames: bool = False,
        planning_timeout: Optional[float] = None,
        background: bool = False,
        allow_long_sync: bool = False,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Plan movement for current droplet targets; real hardware rejects oversized active batches."""
        return _runtime_call(
            runtime.plan_move,
            mode=mode,
            remove_duplicate_frames=remove_duplicate_frames,
            planning_timeout=planning_timeout,
            background=background,
            allow_long_sync=allow_long_sync,
            options=options,
        )

    @mcp.tool()
    def plan_reservoir_extraction(
        reservoir_droplet_id: int,
        split_mode: str = "linear",
        steps: Optional[List[int]] = None,
        split_size: Optional[Any] = None,
        new_droplet_id: Optional[int] = None,
        halo_size: int = 0,
        separation_steps: int = 3,
        linear_drops_number: Optional[int] = None,
        linear_offset: Optional[int] = None,
        linear_space_per_col: Optional[int] = None,
        linear_space_per_row: Optional[int] = None,
        linear_drop_shape: Optional[Any] = None,
        linear_direction: Optional[List[int]] = None,
        linear_vital_space: Optional[int] = None,
        linear_post_separation_steps: Optional[int] = 3,
        remove_duplicate_frames: bool = False,
        background: bool = False,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Plan extraction from a reservoir; does not execute hardware."""
        return _runtime_call(
            runtime.plan_reservoir_extraction,
            reservoir_droplet_id=reservoir_droplet_id,
            split_mode=split_mode,
            steps=steps,
            split_size=split_size,
            new_droplet_id=new_droplet_id,
            halo_size=halo_size,
            separation_steps=separation_steps,
            linear_drops_number=linear_drops_number,
            linear_offset=linear_offset,
            linear_space_per_col=linear_space_per_col,
            linear_space_per_row=linear_space_per_row,
            linear_drop_shape=linear_drop_shape,
            linear_direction=linear_direction,
            linear_vital_space=linear_vital_space,
            linear_post_separation_steps=linear_post_separation_steps,
            remove_duplicate_frames=remove_duplicate_frames,
            background=background,
            **(options or {}),
        )

    @mcp.tool()
    def plan_isometric_split(
        droplet_id: int,
        steps: List[List[int]],
        simultaneous: bool = True,
        new_droplet_id: Optional[int] = None,
        event_id: Optional[str] = None,
        remove_duplicate_frames: bool = False,
        background: bool = False,
    ) -> Dict[str, Any]:
        """Plan an isometric split; does not execute hardware."""
        return _runtime_call(
            runtime.plan_isometric_split,
            droplet_id=droplet_id,
            steps=steps,
            simultaneous=simultaneous,
            new_droplet_id=new_droplet_id,
            event_id=event_id,
            remove_duplicate_frames=remove_duplicate_frames,
            background=background,
        )

    @mcp.tool()
    def plan_mix(
        droplet_id: int,
        mode: str = "split_recombine",
        split_area: Optional[List[List[int]]] = None,
        mixing_area_size: Optional[int] = None,
        cycles: int = 5,
        event_id: Optional[str] = None,
        remove_duplicate_frames: bool = False,
        background: bool = False,
    ) -> Dict[str, Any]:
        """Plan droplet mixing; does not execute hardware."""
        return _runtime_call(
            runtime.plan_mix,
            droplet_id=droplet_id,
            mode=mode,
            split_area=split_area,
            mixing_area_size=mixing_area_size,
            cycles=cycles,
            event_id=event_id,
            remove_duplicate_frames=remove_duplicate_frames,
            background=background,
        )

    @mcp.tool()
    def plan_merge(
        droplet_ids: Any,
        target: Any,
        forced_width: Optional[int] = None,
        forced_height: Optional[int] = None,
        hold_final_position: bool = False,
        event_id: Optional[str] = None,
        remove_duplicate_frames: bool = False,
        background: bool = False,
    ) -> Dict[str, Any]:
        """Plan merging droplets into one validated target; does not execute hardware."""
        return _runtime_call(
            runtime.plan_merge,
            droplet_ids=droplet_ids,
            target=target,
            forced_width=forced_width,
            forced_height=forced_height,
            hold_final_position=hold_final_position,
            event_id=event_id,
            remove_duplicate_frames=remove_duplicate_frames,
            background=background,
        )

    @mcp.tool()
    def planning_job_status() -> Dict[str, Any]:
        """Return compact status for the active or last background planning job."""
        return _runtime_call(runtime.advanced_drop_job_status)

    @mcp.tool()
    def cancel_planning_job() -> Dict[str, Any]:
        """Request cancellation of the active background planning job."""
        return _runtime_call(runtime.cancel_advanced_drop_job)

    if getattr(runtime, "allow_unsafe_tools", False):
        @mcp.tool()
        def list_advanced_drop_methods() -> Dict[str, Any]:
            """Debug only: list AdvancedDrop methods behind the generic planner."""
            return _runtime_call(runtime.list_advanced_drop_methods)

        @mcp.tool()
        def advanced_drop_call(
            method: str,
            arguments: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Debug only: call a whitelisted AdvancedDrop method by name."""
            return _runtime_call(runtime.advanced_drop_call, method, arguments or {})

        @mcp.tool()
        def start_advanced_drop_call(
            method: str,
            arguments: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Debug only: start a generic AdvancedDrop call in the background."""
            return _runtime_call(runtime.start_advanced_drop_call, method, arguments or {})

        @mcp.tool()
        def advanced_drop_job_status() -> Dict[str, Any]:
            """Debug only: status alias for generic AdvancedDrop background jobs."""
            return _runtime_call(runtime.advanced_drop_job_status)

        @mcp.tool()
        def cancel_advanced_drop_job() -> Dict[str, Any]:
            """Debug only: cancel alias for generic AdvancedDrop background jobs."""
            return _runtime_call(runtime.cancel_advanced_drop_job)

    @mcp.tool()
    def verify_droplets(
        frame_idx: int,
        droplet_ids: Optional[List[int]] = None,
        save_frames_path: Optional[str] = None,
        debug: bool = False,
    ) -> Dict[str, Any]:
        """Verify droplet positions for a plan frame.

        Pass save_frames_path to save one brightfield debug image per checked
        droplet; failed checks without saved frames should be treated as
        inconclusive during real BoxMini operation. Relative save_frames_path
        values are saved under the managed DropLogic capture directory.
        """
        return _runtime_call(
            runtime.verify_droplets,
            frame_idx=frame_idx,
            droplet_ids=droplet_ids,
            save_frames_path=save_frames_path,
            debug=debug,
        )

    @mcp.tool()
    def detect_condensates(
        crop_droplet: bool = True,
        crop_padding: int = 50,
        confidence_threshold: float = 0.25,
        return_annotated: bool = False,
        save_image_path: Optional[str] = None,
        save_debug_images: bool = False,
        debug_output_dir: Optional[str] = None,
        debug_prefix: Optional[str] = None,
        debug: bool = False,
        fluo_exposure: int = 2000000,
        fluo_light: int = 99,
        brightfield_exposure: int = 3600,
        brightfield_light: int = 30,
    ) -> Dict[str, Any]:
        """Detect condensates using AdvancedDrop vision support.

        Relative save/debug image paths are saved under the managed DropLogic
        capture directory.
        """
        return _runtime_call(
            runtime.detect_condensates,
            crop_droplet=crop_droplet,
            crop_padding=crop_padding,
            confidence_threshold=confidence_threshold,
            return_annotated=return_annotated,
            save_image_path=save_image_path,
            save_debug_images=save_debug_images,
            debug_output_dir=debug_output_dir,
            debug_prefix=debug_prefix,
            debug=debug,
            fluo_exposure=fluo_exposure,
            fluo_light=fluo_light,
            brightfield_exposure=brightfield_exposure,
            brightfield_light=brightfield_light,
        )

    if getattr(runtime, "allow_unsafe_tools", False):
        @mcp.tool()
        def system_call(
            method: str,
            arguments: Optional[Dict[str, Any]] = None,
            wait_if_busy: bool = False,
            timeout_seconds: float = 30.0,
            poll_interval: float = 0.1,
        ) -> Dict[str, Any]:
            """Debug only: call a whitelisted loaded-system method."""
            return _runtime_call(
                runtime.system_call,
                method,
                arguments or {},
                wait_if_busy=wait_if_busy,
                timeout_seconds=timeout_seconds,
                poll_interval=poll_interval,
            )

    @mcp.tool()
    def list_system_modules() -> Dict[str, Any]:
        """List loaded hardware modules and whitelisted callable methods."""
        return _runtime_call(runtime.list_system_modules)

    @mcp.tool()
    def module_busy_status(module: Optional[str] = None) -> Dict[str, Any]:
        """Return busy/free status for one module or all known modules."""
        return _runtime_call(runtime.module_busy_status, module)

    @mcp.tool()
    def module_call(
        module: str,
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
        wait_if_busy: bool = False,
        timeout_seconds: float = 30.0,
        poll_interval: float = 0.1,
    ) -> Dict[str, Any]:
        """Low-level hardware module call. Prefer dedicated MCP tools for planning, execution, imaging, state, and temperature.

        For camera/microscope capture_image, relative save paths are resolved
        under the managed DropLogic capture directory.
        """
        return _runtime_call(
            runtime.module_call,
            module,
            method,
            arguments or {},
            wait_if_busy=wait_if_busy,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval,
        )

    @mcp.tool()
    def plan_summary() -> Dict[str, Any]:
        """Return a compact summary of the current AdvancedDrop plan."""
        return _runtime_call(runtime.plan_summary)

    @mcp.tool()
    def save_protocol(output_path: str) -> Dict[str, Any]:
        """Save current plan and droplets to a pickle protocol file."""
        return _runtime_call(runtime.save_protocol, output_path)

    @mcp.tool()
    def start_plan(
        frame_delay: float = 1.0,
        verify_positions: bool = False,
        enable_visualizers: bool = False,
        save_to_file: Optional[Any] = None,
        record_matrix: bool = False,
        record_streamer: bool = False,
        matrix_filename: Optional[str] = None,
        streamer_filename: Optional[str] = None,
        execution_view_mode: Optional[str] = None,
        fixed_stage_position: Optional[Any] = None,
        prepare_execution_view: bool = True,
        execution_view_timeout_seconds: float = 60.0,
        restart_from_beginning: bool = False,
        allow_failed_plan: bool = False,
    ) -> Dict[str, Any]:
        """Start PlanExecutor from frame 0; omit execution_view_mode to preserve current view."""
        return _runtime_call(
            runtime.start_plan,
            frame_delay=frame_delay,
            verify_positions=verify_positions,
            enable_visualizers=enable_visualizers,
            save_to_file=save_to_file,
            record_matrix=record_matrix,
            record_streamer=record_streamer,
            matrix_filename=matrix_filename,
            streamer_filename=streamer_filename,
            execution_view_mode=execution_view_mode,
            fixed_stage_position=fixed_stage_position,
            prepare_execution_view=prepare_execution_view,
            execution_view_timeout_seconds=execution_view_timeout_seconds,
            restart_from_beginning=restart_from_beginning,
            allow_failed_plan=allow_failed_plan,
        )

    @mcp.tool()
    def set_execution_view_mode(
        mode: str = "follow_droplets",
        fixed_stage_position: Optional[Any] = None,
        move_now: bool = True,
        bring_to_front: bool = False,
        wait_timeout_seconds: float = 20.0,
    ) -> Dict[str, Any]:
        """Switch PlanExecutor viewing between droplet-follow and fixed whole-chip camera."""
        return _runtime_call(
            runtime.set_execution_view_mode,
            mode=mode,
            fixed_stage_position=fixed_stage_position,
            move_now=move_now,
            bring_to_front=bring_to_front,
            wait_timeout_seconds=wait_timeout_seconds,
        )

    @mcp.tool()
    def move_stage(
        position: Optional[Any] = None,
        preset: Optional[str] = None,
        wait_timeout_seconds: float = 20.0,
        poll_interval: float = 0.1,
        wait_for_queue: bool = True,
        wait_for_completion: bool = True,
    ) -> Dict[str, Any]:
        """Move the XY stage using a named preset or explicit X/Y/Z axis values."""
        return _runtime_call(
            runtime.move_stage,
            position=position,
            preset=preset,
            wait_timeout_seconds=wait_timeout_seconds,
            poll_interval=poll_interval,
            wait_for_queue=wait_for_queue,
            wait_for_completion=wait_for_completion,
        )

    @mcp.tool()
    def calibration_stage_set_speed(speed_key: str = "2") -> Dict[str, Any]:
        """Apply the same manual jog speed used by the standalone calibration tool."""
        return _runtime_call(runtime.calibration_stage_set_speed, speed_key=speed_key)

    @mcp.tool()
    def calibration_stage_position() -> Dict[str, Any]:
        """Read the current hardware stage position for calibration recording."""
        return _runtime_call(runtime.calibration_stage_position)

    @mcp.tool()
    def set_stage_motion_speed(speed_key: str = "fast") -> Dict[str, Any]:
        """Apply an XY stage motion speed preset: slow, medium, or fast."""
        return _runtime_call(runtime.set_stage_motion_speed, speed_key=speed_key)

    @mcp.tool()
    def stage_motion_params() -> Dict[str, Any]:
        """Read the current XY stage velocity and acceleration parameters."""
        return _runtime_call(runtime.stage_motion_params)

    @mcp.tool()
    def set_stage_motion_params(velocity: float, acceleration: float) -> Dict[str, Any]:
        """Apply explicit XY stage velocity and acceleration parameters."""
        return _runtime_call(
            runtime.set_stage_motion_params,
            velocity=velocity,
            acceleration=acceleration,
        )

    @mcp.tool()
    def calibration_stage_jog(
        axis: Optional[str] = None,
        direction: int = 0,
        stop_all: bool = False,
    ) -> Dict[str, Any]:
        """Start/refresh/stop continuous calibration jogging on X/Y/Z."""
        return _runtime_call(
            runtime.calibration_stage_jog,
            axis=axis,
            direction=direction,
            stop_all=stop_all,
        )

    @mcp.tool()
    def calibration_stage_move_to_target(
        position: Any,
        speed_key: str = "2",
        wait_timeout_seconds: float = 20.0,
        poll_interval: float = 0.05,
    ) -> Dict[str, Any]:
        """Move to a guided calibration target using calibration travel speed."""
        return _runtime_call(
            runtime.calibration_stage_move_to_target,
            position=position,
            speed_key=speed_key,
            wait_timeout_seconds=wait_timeout_seconds,
            poll_interval=poll_interval,
        )

    @mcp.tool()
    def pause_plan() -> Dict[str, Any]:
        """Pause PlanExecutor."""
        return _runtime_call(runtime.pause_plan)

    @mcp.tool()
    def resume_plan(allow_failed_plan: bool = False) -> Dict[str, Any]:
        """Resume PlanExecutor."""
        return _runtime_call(runtime.resume_plan, allow_failed_plan)

    @mcp.tool()
    def stop_plan() -> Dict[str, Any]:
        """Stop PlanExecutor."""
        return _runtime_call(runtime.stop_plan)

    @mcp.tool()
    def executor_status() -> Dict[str, Any]:
        """Return PlanExecutor status."""
        return _runtime_call(runtime.executor_status)

    @mcp.tool()
    def timeline_status() -> Dict[str, Any]:
        """Return logical timeline pause/resume status and stopped intervals."""
        return _runtime_call(runtime.timeline_status)

    @mcp.tool()
    def pause_timeline(reason: str = "") -> Dict[str, Any]:
        """Stop logical timeline accumulation without pausing hardware execution."""
        return _runtime_call(runtime.pause_timeline, reason=reason, source="agent")

    @mcp.tool()
    def resume_timeline(reason: str = "") -> Dict[str, Any]:
        """Resume logical timeline accumulation and record the stopped duration."""
        return _runtime_call(runtime.resume_timeline, reason=reason, source="agent")

    @mcp.tool()
    def add_breakpoint(frame_number: int) -> Dict[str, Any]:
        """Add a frame breakpoint."""
        return _runtime_call(runtime.add_breakpoint, frame_number)

    @mcp.tool()
    def remove_breakpoint(frame_number: int) -> Dict[str, Any]:
        """Remove a frame breakpoint."""
        return _runtime_call(runtime.remove_breakpoint, frame_number)

    @mcp.tool()
    def clear_breakpoints() -> Dict[str, Any]:
        """Clear all PlanExecutor breakpoints."""
        return _runtime_call(runtime.clear_breakpoints)

    @mcp.tool()
    def executor_frame_history(limit: int = 1000) -> Dict[str, Any]:
        """Return compact per-frame PlanExecutor timing diagnostics."""
        return _runtime_call(runtime.executor_frame_history, limit=limit)

    @mcp.tool()
    def execute_segment_to_breakpoint(
        frame_number: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        poll_interval_seconds: float = 0.25,
        resume_if_paused: bool = True,
        clear_existing_breakpoints: bool = True,
        allow_failed_plan: bool = False,
        frame_delay: float = 1.0,
        verify_positions: bool = False,
        enable_visualizers: bool = False,
        execution_view_mode: Optional[str] = None,
        fixed_stage_position: Optional[Any] = None,
        prepare_execution_view: bool = True,
        execution_view_timeout_seconds: float = 60.0,
        wait_mode: str = "auto",
        inline_wait_max_seconds: Optional[float] = None,
        inline_wait_margin_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Add a breakpoint and execute; omit execution_view_mode to preserve current view."""
        return _runtime_call(
            runtime.execute_segment_to_breakpoint,
            frame_number=frame_number,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            resume_if_paused=resume_if_paused,
            clear_existing_breakpoints=clear_existing_breakpoints,
            allow_failed_plan=allow_failed_plan,
            frame_delay=frame_delay,
            verify_positions=verify_positions,
            enable_visualizers=enable_visualizers,
            execution_view_mode=execution_view_mode,
            fixed_stage_position=fixed_stage_position,
            prepare_execution_view=prepare_execution_view,
            execution_view_timeout_seconds=execution_view_timeout_seconds,
            wait_mode=wait_mode,
            inline_wait_max_seconds=inline_wait_max_seconds,
            inline_wait_margin_seconds=inline_wait_margin_seconds,
        )

    @mcp.tool()
    def start_execute_until_breakpoint(
        timeout_seconds: Optional[float] = None,
        resume_if_paused: bool = True,
        poll_interval_seconds: float = 0.25,
    ) -> Dict[str, Any]:
        """Start a background wait for breakpoint/plan completion."""
        return _runtime_call(
            runtime.start_execute_until_breakpoint,
            timeout_seconds=timeout_seconds,
            resume_if_paused=resume_if_paused,
            poll_interval_seconds=poll_interval_seconds,
        )

    @mcp.tool()
    def execution_wait_status(
        wait_seconds: float = 0.0,
        poll_interval_seconds: float = 0.25,
    ) -> Dict[str, Any]:
        """Return compact execution wait status, optionally waiting up to wait_seconds first."""
        return _runtime_call(
            runtime.execution_wait_status,
            wait_seconds=wait_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    @mcp.tool()
    def cancel_execution_wait() -> Dict[str, Any]:
        """Cancel only the background wait job, not physical execution."""
        return _runtime_call(runtime.cancel_execution_wait)

    @mcp.resource("droplogic://status")
    def status_resource() -> str:
        """Live DropLogic runtime status as JSON."""
        return json.dumps(_runtime_call(runtime.status), indent=2)

    @mcp.resource("droplogic://plan")
    def plan_resource() -> str:
        """Current AdvancedDrop plan summary as JSON."""
        return json.dumps(_runtime_call(runtime.plan_summary), indent=2)

    @mcp.resource("droplogic://droplets")
    def droplets_resource() -> str:
        """Current AdvancedDrop droplets summary as JSON."""
        return json.dumps(_runtime_call(runtime.droplets_summary), indent=2)

    @mcp.resource("droplogic://capabilities")
    def capabilities_resource() -> str:
        """Current DropLogic MCP capabilities as JSON."""
        return json.dumps(_runtime_call(runtime.capabilities), indent=2)

    @mcp.resource("droplogic://context")
    def context_resource() -> str:
        """Current agent context summary as JSON."""
        return json.dumps(_runtime_call(runtime.context_status), indent=2)

    @mcp.resource("droplogic://context/files")
    def context_files_resource() -> str:
        """Merged agent context file list as JSON."""
        return json.dumps(_runtime_call(runtime.list_context_files), indent=2)

    return mcp


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the DropLogic MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default=os.environ.get("DROPLOGIC_MCP_TRANSPORT", "stdio"),
        help="MCP transport to use. stdio is best for local desktop clients.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("DROPLOGIC_MCP_HOST", "127.0.0.1"),
        help="Host for HTTP transports.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("DROPLOGIC_MCP_PORT", "8765")),
        help="Port for HTTP transports.",
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("DROPLOGIC_CONFIG", "config.json"),
        help="Path to config.json.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("DROPLOGIC_LOG_LEVEL", "INFO"),
        help="DropLogic log level.",
    )
    parser.add_argument(
        "--allow-real-hardware",
        action="store_true",
        default=os.environ.get("DROPLOGIC_MCP_ALLOW_REAL_HARDWARE", "").lower()
        in {"1", "true", "yes"},
        help="Allow loading DMLite or BOXMini hardware when requested.",
    )
    parser.add_argument(
        "--allow-unsafe-tools",
        action="store_true",
        default=os.environ.get("DROPLOGIC_MCP_ALLOW_UNSAFE_TOOLS", "").lower()
        in {"1", "true", "yes"},
        help="Allow raw set_system_state writes.",
    )
    parser.add_argument(
        "--allow-large-state-tools",
        action="store_true",
        default=os.environ.get("DROPLOGIC_MCP_ALLOW_LARGE_STATE_TOOLS", "").lower()
        in {"1", "true", "yes"},
        help="Allow raw reads of large state values such as the full electrode matrix.",
    )
    parser.add_argument(
        "--snapshots-dir",
        default=os.environ.get("DROPLOGIC_MCP_SNAPSHOTS_DIR"),
        help="Directory for visualizer snapshot files.",
    )
    parser.add_argument(
        "--context-dir",
        default=os.environ.get("DROPLOGIC_MCP_CONTEXT_DIR"),
        help="Directory with agent context overrides for the active system.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    runtime = DropLogicMCPRuntime(
        config_file=args.config,
        log_level=args.log_level,
        allow_real_hardware=args.allow_real_hardware,
        allow_unsafe_tools=args.allow_unsafe_tools,
        allow_large_state_tools=args.allow_large_state_tools,
        snapshots_dir=args.snapshots_dir,
        context_dir=args.context_dir,
    )
    try:
        server = build_server(runtime, host=args.host, port=args.port)
    except RuntimeError as exc:
        raise SystemExit(str(exc))

    try:
        if args.transport == "stdio":
            with _isolate_stdio_protocol_stdout():
                server.run(transport=args.transport)
        else:
            server.run(transport=args.transport)
    finally:
        _runtime_call(runtime.close_system)


if __name__ == "__main__":
    main()

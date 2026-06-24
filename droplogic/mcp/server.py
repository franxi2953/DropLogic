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
        return fn(*args, **kwargs)


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
    def runtime_status() -> Dict[str, Any]:
        """Return server, system, executor, plan and droplet status."""
        return _runtime_call(runtime.status)

    @mcp.tool()
    def health_check() -> Dict[str, Any]:
        """Return MCP runtime, worker, executor and module health information."""
        return _runtime_call(runtime.health_check)

    @mcp.tool()
    def capabilities() -> Dict[str, Any]:
        """Return the DropLogic functions and observability surfaces available to agents."""
        return _runtime_call(runtime.capabilities)

    @mcp.tool()
    def read_state(path: Optional[str] = None) -> Dict[str, Any]:
        """Read the full DropSystem state or a dotted path."""
        return _runtime_call(runtime.read_state, path)

    @mcp.tool()
    def state_summary(path: Optional[str] = None) -> Dict[str, Any]:
        """Read a summarized DropSystem state or a dotted path."""
        return _runtime_call(runtime.state_summary, path)

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

    @mcp.tool()
    def set_system_state(path: str, value: Any) -> Dict[str, Any]:
        """Set a raw DropSystem state path when unsafe tools are enabled."""
        return _runtime_call(runtime.set_system_state, path, value)

    @mcp.tool()
    def emergency_stop(deactivate_electrodes: bool = True) -> Dict[str, Any]:
        """Stop plan execution, clear queues and optionally turn electrodes off."""
        return _runtime_call(
            runtime.emergency_stop,
            deactivate_electrodes=deactivate_electrodes,
        )

    @mcp.tool()
    def visualizer_snapshot(
        visualizer: str = "matrix",
        output_path: Optional[str] = None,
        image_format: str = "png",
        include_base64: bool = False,
    ) -> Dict[str, Any]:
        """Save a matrix or streamer visualizer snapshot and optionally return base64."""
        return _runtime_call(
            runtime.visualizer_snapshot,
            visualizer=visualizer,
            output_path=output_path,
            image_format=image_format,
            include_base64=include_base64,
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
    ) -> Dict[str, Any]:
        """Return a matrix or streamer frame as base64 and/or a saved image path."""
        return _runtime_call(
            runtime.visualizer_frame,
            visualizer=visualizer,
            frame_source=frame_source,
            image_format=image_format,
            include_base64=include_base64,
            output_path=output_path,
            max_width=max_width,
            max_height=max_height,
        )

    @mcp.tool()
    def visualizer_status() -> Dict[str, Any]:
        """Return matrix and streamer visualizer status."""
        return _runtime_call(runtime.visualizer_status)

    @mcp.tool()
    def visualizer_call(
        visualizer: str,
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call a whitelisted visualizer method."""
        return _runtime_call(runtime.visualizer_call, visualizer, method, arguments or {})

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
        """Switch the BoxMini live streamer between microscope and camera."""
        return _runtime_call(
            runtime.set_streamer_source,
            source=source,
            electrode_overlay=electrode_overlay,
            coordinates=coordinates,
            bring_to_front=bring_to_front,
        )

    @mcp.tool()
    def configure_microscope_imaging(
        channel: str = "Brightfield",
        exposure_time: int = 60000,
        gain: int = 12,
        coaxial_intensity: int = 4,
        ring_intensity: int = 0,
        auto_exposure: bool = False,
        restart_streamer: bool = True,
        bring_to_front: bool = False,
        stabilization_wait: float = 0.5,
        queue_timeout_seconds: float = 10.0,
    ) -> Dict[str, Any]:
        """Configure microscope imaging safely, restarting streamer if needed."""
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
    def temperature_hold(
        target_c: float,
        hold_seconds: float,
        tolerance_c: float = 0.5,
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
    def temperature_sweep(
        steps: List[Dict[str, Any]],
        tolerance_c: float = 0.5,
        settle_timeout_seconds: float = 600.0,
        sample_interval_seconds: float = 5.0,
        require_settle: bool = False,
        max_samples_per_step: int = 20,
        stop_on_error: bool = True,
    ) -> Dict[str, Any]:
        """Run multiple temperature hold steps in one compact call."""
        return _runtime_call(
            runtime.temperature_sweep,
            steps=steps,
            tolerance_c=tolerance_c,
            settle_timeout_seconds=settle_timeout_seconds,
            sample_interval_seconds=sample_interval_seconds,
            require_settle=require_settle,
            max_samples_per_step=max_samples_per_step,
            stop_on_error=stop_on_error,
        )

    @mcp.tool()
    def start_temperature_routine(
        steps: List[Dict[str, Any]],
        tolerance_c: float = 0.5,
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
        """Create one droplet in AdvancedDrop."""
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
        """Create multiple droplets in AdvancedDrop."""
        return _runtime_call(runtime.add_droplets, droplets)

    @mcp.tool()
    def delete_droplet(droplet_id: int) -> Dict[str, Any]:
        """Delete a droplet by id."""
        return _runtime_call(runtime.delete_droplet, droplet_id)

    @mcp.tool()
    def update_droplet_target(droplet_id: int, target: List[int]) -> Dict[str, Any]:
        """Update a droplet target coordinate."""
        return _runtime_call(runtime.update_droplet_target, droplet_id, target)

    @mcp.tool()
    def update_droplet_targets(
        targets: Any,
        include_summary: bool = False,
    ) -> Dict[str, Any]:
        """Update many droplet targets in one compact call."""
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
    def droplets_summary() -> Dict[str, Any]:
        """Return all droplets and their current targets."""
        return _runtime_call(runtime.droplets_summary)

    @mcp.tool()
    def list_advanced_drop_methods() -> Dict[str, Any]:
        """List AdvancedDrop methods exposed through advanced_drop_call."""
        return _runtime_call(runtime.list_advanced_drop_methods)

    @mcp.tool()
    def advanced_drop_call(
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call only whitelisted AdvancedDrop planning methods, not MCP/runtime tools."""
        return _runtime_call(runtime.advanced_drop_call, method, arguments or {})

    @mcp.tool()
    def start_advanced_drop_call(
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Start a long AdvancedDrop call in the background; poll job status."""
        return _runtime_call(runtime.start_advanced_drop_call, method, arguments or {})

    @mcp.tool()
    def advanced_drop_job_status() -> Dict[str, Any]:
        """Return compact status for the active or last AdvancedDrop background job."""
        return _runtime_call(runtime.advanced_drop_job_status)

    @mcp.tool()
    def cancel_advanced_drop_job() -> Dict[str, Any]:
        """Request cancellation of the active AdvancedDrop background job."""
        return _runtime_call(runtime.cancel_advanced_drop_job)

    @mcp.tool()
    def verify_droplets(
        frame_idx: int,
        droplet_ids: Optional[List[int]] = None,
        save_frames_path: Optional[str] = None,
        debug: bool = False,
    ) -> Dict[str, Any]:
        """Verify droplet positions for a plan frame."""
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
        brightfield_exposure: int = 3000,
        brightfield_light: int = 30,
    ) -> Dict[str, Any]:
        """Detect condensates using AdvancedDrop vision support."""
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

    @mcp.tool()
    def system_call(
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
        wait_if_busy: bool = False,
        timeout_seconds: float = 30.0,
        poll_interval: float = 0.1,
    ) -> Dict[str, Any]:
        """Call a whitelisted loaded-system method."""
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
    def wait_for_module_free(
        module: str,
        timeout_seconds: float = 30.0,
        poll_interval: float = 0.1,
    ) -> Dict[str, Any]:
        """Wait until a hardware module appears free, or return timeout status."""
        return _runtime_call(
            runtime.wait_for_module_free,
            module,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval,
        )

    @mcp.tool()
    def module_call(
        module: str,
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
        wait_if_busy: bool = False,
        timeout_seconds: float = 30.0,
        poll_interval: float = 0.1,
    ) -> Dict[str, Any]:
        """Call a whitelisted method on a loaded hardware module."""
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
        execution_view_mode: str = "follow_droplets",
        fixed_stage_position: Optional[Any] = None,
        prepare_execution_view: bool = True,
        execution_view_timeout_seconds: float = 60.0,
        restart_from_beginning: bool = False,
    ) -> Dict[str, Any]:
        """Start PlanExecutor from frame 0 unless a partial run needs resume_plan."""
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
    def pause_plan() -> Dict[str, Any]:
        """Pause PlanExecutor."""
        return _runtime_call(runtime.pause_plan)

    @mcp.tool()
    def resume_plan() -> Dict[str, Any]:
        """Resume PlanExecutor."""
        return _runtime_call(runtime.resume_plan)

    @mcp.tool()
    def stop_plan() -> Dict[str, Any]:
        """Stop PlanExecutor."""
        return _runtime_call(runtime.stop_plan)

    @mcp.tool()
    def executor_status() -> Dict[str, Any]:
        """Return PlanExecutor status."""
        return _runtime_call(runtime.executor_status)

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
    def execute_until_breakpoint(
        timeout_seconds: Optional[float] = None,
        resume_if_paused: bool = True,
    ) -> Dict[str, Any]:
        """Block until the next breakpoint or plan completion; prefer background wait for long runs."""
        return _runtime_call(
            runtime.execute_until_breakpoint,
            timeout_seconds=timeout_seconds,
            resume_if_paused=resume_if_paused,
        )

    @mcp.tool()
    def start_execute_until_breakpoint(
        timeout_seconds: Optional[float] = None,
        resume_if_paused: bool = True,
        poll_interval_seconds: float = 0.25,
    ) -> Dict[str, Any]:
        """Start a background wait for breakpoint/plan completion; poll execution_wait_status."""
        return _runtime_call(
            runtime.start_execute_until_breakpoint,
            timeout_seconds=timeout_seconds,
            resume_if_paused=resume_if_paused,
            poll_interval_seconds=poll_interval_seconds,
        )

    @mcp.tool()
    def execution_wait_status() -> Dict[str, Any]:
        """Return compact status for the active or last execution wait job."""
        return _runtime_call(runtime.execution_wait_status)

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

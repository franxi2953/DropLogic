"""DropLogic MCP server entrypoint."""

import argparse
import inspect
import json
import os
from typing import Any, Dict, List, Optional

from .runtime import DropLogicMCPRuntime


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
    ) -> Dict[str, Any]:
        """Load simulator, dmlite, or boxmini into the MCP runtime."""
        return runtime.load_system(system, config_file=config_file, log_level=log_level)

    @mcp.tool()
    def close_system() -> Dict[str, Any]:
        """Close the currently loaded DropLogic system."""
        return runtime.close_system()

    @mcp.tool()
    def runtime_status() -> Dict[str, Any]:
        """Return server, system, executor, plan and droplet status."""
        return runtime.status()

    @mcp.tool()
    def capabilities() -> Dict[str, Any]:
        """Return the DropLogic functions and observability surfaces available to agents."""
        return runtime.capabilities()

    @mcp.tool()
    def read_state(path: Optional[str] = None) -> Dict[str, Any]:
        """Read the full DropSystem state or a dotted path."""
        return runtime.read_state(path)

    @mcp.tool()
    def set_system_state(path: str, value: Any) -> Dict[str, Any]:
        """Set a raw DropSystem state path when unsafe tools are enabled."""
        return runtime.set_system_state(path, value)

    @mcp.tool()
    def emergency_stop(deactivate_electrodes: bool = True) -> Dict[str, Any]:
        """Stop plan execution, clear queues and optionally turn electrodes off."""
        return runtime.emergency_stop(deactivate_electrodes=deactivate_electrodes)

    @mcp.tool()
    def visualizer_snapshot(
        visualizer: str = "matrix",
        output_path: Optional[str] = None,
        image_format: str = "png",
        include_base64: bool = False,
    ) -> Dict[str, Any]:
        """Save a matrix or streamer visualizer snapshot and optionally return base64."""
        return runtime.visualizer_snapshot(
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
        return runtime.visualizer_frame(
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
        return runtime.visualizer_status()

    @mcp.tool()
    def visualizer_call(
        visualizer: str,
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call a whitelisted visualizer method."""
        return runtime.visualizer_call(visualizer, method, arguments or {})

    @mcp.tool()
    def start_visualizer(visualizer: str = "matrix") -> Dict[str, Any]:
        """Start a visualizer window when supported by the host OS."""
        return runtime.start_visualizer(visualizer)

    @mcp.tool()
    def stop_visualizer(visualizer: str = "matrix") -> Dict[str, Any]:
        """Stop a visualizer window."""
        return runtime.stop_visualizer(visualizer)

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
        return runtime.create_droplet(
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
        return runtime.add_droplets(droplets)

    @mcp.tool()
    def delete_droplet(droplet_id: int) -> Dict[str, Any]:
        """Delete a droplet by id."""
        return runtime.delete_droplet(droplet_id)

    @mcp.tool()
    def update_droplet_target(droplet_id: int, target: List[int]) -> Dict[str, Any]:
        """Update a droplet target coordinate."""
        return runtime.update_droplet_target(droplet_id, target)

    @mcp.tool()
    def update_droplet_position(droplet_id: int, position: List[int]) -> Dict[str, Any]:
        """Update a droplet current logical coordinate."""
        return runtime.update_droplet_position(droplet_id, position)

    @mcp.tool()
    def droplets_summary() -> Dict[str, Any]:
        """Return all droplets and their current targets."""
        return runtime.droplets_summary()

    @mcp.tool()
    def list_advanced_drop_methods() -> Dict[str, Any]:
        """List AdvancedDrop methods exposed through advanced_drop_call."""
        return runtime.list_advanced_drop_methods()

    @mcp.tool()
    def advanced_drop_call(
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call a whitelisted AdvancedDrop method with JSON keyword arguments."""
        return runtime.advanced_drop_call(method, arguments or {})

    @mcp.tool()
    def verify_droplets(
        frame_idx: int,
        droplet_ids: Optional[List[int]] = None,
        save_frames_path: Optional[str] = None,
        debug: bool = False,
    ) -> Dict[str, Any]:
        """Verify droplet positions for a plan frame."""
        return runtime.verify_droplets(
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
        return runtime.detect_condensates(
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
    ) -> Dict[str, Any]:
        """Call a whitelisted loaded-system method."""
        return runtime.system_call(method, arguments or {})

    @mcp.tool()
    def list_system_modules() -> Dict[str, Any]:
        """List loaded hardware modules and whitelisted callable methods."""
        return runtime.list_system_modules()

    @mcp.tool()
    def module_call(
        module: str,
        method: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call a whitelisted method on a loaded hardware module."""
        return runtime.module_call(module, method, arguments or {})

    @mcp.tool()
    def plan_summary() -> Dict[str, Any]:
        """Return a compact summary of the current AdvancedDrop plan."""
        return runtime.plan_summary()

    @mcp.tool()
    def save_protocol(output_path: str) -> Dict[str, Any]:
        """Save current plan and droplets to a pickle protocol file."""
        return runtime.save_protocol(output_path)

    @mcp.tool()
    def start_plan(
        frame_delay: float = 1.0,
        verify_positions: bool = True,
        enable_visualizers: bool = False,
        save_to_file: Optional[Any] = None,
        record_matrix: bool = False,
        record_streamer: bool = False,
        matrix_filename: Optional[str] = None,
        streamer_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start PlanExecutor on the current plan."""
        return runtime.start_plan(
            frame_delay=frame_delay,
            verify_positions=verify_positions,
            enable_visualizers=enable_visualizers,
            save_to_file=save_to_file,
            record_matrix=record_matrix,
            record_streamer=record_streamer,
            matrix_filename=matrix_filename,
            streamer_filename=streamer_filename,
        )

    @mcp.tool()
    def pause_plan() -> Dict[str, Any]:
        """Pause PlanExecutor."""
        return runtime.pause_plan()

    @mcp.tool()
    def resume_plan() -> Dict[str, Any]:
        """Resume PlanExecutor."""
        return runtime.resume_plan()

    @mcp.tool()
    def stop_plan() -> Dict[str, Any]:
        """Stop PlanExecutor."""
        return runtime.stop_plan()

    @mcp.tool()
    def executor_status() -> Dict[str, Any]:
        """Return PlanExecutor status."""
        return runtime.executor_status()

    @mcp.tool()
    def add_breakpoint(frame_number: int) -> Dict[str, Any]:
        """Add a frame breakpoint."""
        return runtime.add_breakpoint(frame_number)

    @mcp.tool()
    def remove_breakpoint(frame_number: int) -> Dict[str, Any]:
        """Remove a frame breakpoint."""
        return runtime.remove_breakpoint(frame_number)

    @mcp.tool()
    def clear_breakpoints() -> Dict[str, Any]:
        """Clear all PlanExecutor breakpoints."""
        return runtime.clear_breakpoints()

    @mcp.tool()
    def execute_until_breakpoint(
        timeout_seconds: Optional[float] = None,
        resume_if_paused: bool = True,
    ) -> Dict[str, Any]:
        """Block until the next breakpoint or plan completion."""
        return runtime.execute_until_breakpoint(
            timeout_seconds=timeout_seconds,
            resume_if_paused=resume_if_paused,
        )

    @mcp.resource("droplogic://status")
    def status_resource() -> str:
        """Live DropLogic runtime status as JSON."""
        return json.dumps(runtime.status(), indent=2)

    @mcp.resource("droplogic://plan")
    def plan_resource() -> str:
        """Current AdvancedDrop plan summary as JSON."""
        return json.dumps(runtime.plan_summary(), indent=2)

    @mcp.resource("droplogic://droplets")
    def droplets_resource() -> str:
        """Current AdvancedDrop droplets summary as JSON."""
        return json.dumps(runtime.droplets_summary(), indent=2)

    @mcp.resource("droplogic://capabilities")
    def capabilities_resource() -> str:
        """Current DropLogic MCP capabilities as JSON."""
        return json.dumps(runtime.capabilities(), indent=2)

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
        help="Allow loading DMLite or BOXMini hardware.",
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
        "--load-system",
        choices=("simulator", "dmlite", "boxmini"),
        default=os.environ.get("DROPLOGIC_MCP_LOAD_SYSTEM"),
        help="Optionally load a system as soon as the server starts.",
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
    )
    try:
        server = build_server(runtime, host=args.host, port=args.port)
    except RuntimeError as exc:
        raise SystemExit(str(exc))

    if args.load_system:
        runtime.load_system(args.load_system)

    try:
        server.run(transport=args.transport)
    finally:
        runtime.close_system()


if __name__ == "__main__":
    main()

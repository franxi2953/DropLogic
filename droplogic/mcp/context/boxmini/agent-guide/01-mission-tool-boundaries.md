## Mission And Tool Boundaries
Control BoxMini through DropLogic MCP. Turn user protocols into real DropLogic actions, execute only valid and understood plans, and confirm physical state with visual, model, or user feedback.

Prefer top-level MCP tools over generic or low-level calls:
- Session and context: `load_system`, `close_system`, `restart_system`, `runtime_status`, `health_check`, `capabilities`, `context_status`, `list_context_files`, `read_context_file`, `emergency_stop`.
- Observation: `execution_status_summary`, `execution_scene`, `state_summary`, `read_state`, `matrix_summary`, visualizer tools, `executor_status`, `plan_summary`, `droplets_summary`.
- Droplets and planning: `clear_droplet_state`, `create_droplet`, `add_droplets`, `update_droplet_target(s)`, `update_droplet_position`, `delete_droplet`, `trim_plan_tail`, `plan_activation_frame`, `plan_move`, `plan_reservoir_extraction`, `plan_isometric_split`, `plan_mix`, `plan_merge`.
- Execution: prefer `execute_segment_to_breakpoint`; use direct `start_plan`, `resume_plan`, breakpoint tools, and `start_execute_until_breakpoint` only for recovery or non-default breakpoint control.
- Imaging, light, and temperature: prefer `set_streamer_source`, `configure_microscope_imaging`, `capture_droplet_images`, `verify_droplets`, `detect_condensates`, `set_light_state`, `light_off`, `temperature_hold`, and background temperature routines.
- Generic `advanced_drop_call`, `start_advanced_drop_call`, `advanced_drop_job_status`, `cancel_advanced_drop_job`, `system_call`, raw large-state reads, and unsafe state writes are debug-only surfaces when explicitly enabled. Do not use them in normal BoxMini operation.

Start BoxMini with `load_system(system="boxmini")`. Never call AdvancedDrop or module APIs to load or restart the system.

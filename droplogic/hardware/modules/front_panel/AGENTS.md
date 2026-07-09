# Front Panel Agent Notes

This folder drives the EQ2013-derived front panel used by DroptiBot / BoxMini.

## Current Architecture

- Source of truth for panel animation is the BMP asset library plus JSON manifests.
- Do not treat the procedural eye renderer as the primary path for normal animation.
- The active production path is:
  - `runs/eq2013_sdk_probe/test_sdk_clean/front_panel_state_library/`
  - one subfolder per state: `idle`, `happy`, `thinking`, `working`, `sad`, `sleep`
  - each state has a `manifest.json`
  - each frame is a prebuilt monochrome `.bmp`
- `droplogic/hardware/modules/front_panel/versions/droptibot_v1.py`
  loads that asset library, maps expressions to states, and sends the BMP files
  directly through the EQ realtime DLL.

## Ownership Model

- The MCP server can own the panel without loading `BOXMini`.
- When MCP is running and `BOXMini` is not loaded, MCP should keep the panel alive.
  Default behavior is sleep / idle-style ambient animation.
- When `BOXMini` loads, it receives the shared front-panel handler and claims control.
- When `BOXMini` closes, control returns to MCP.
- When MCP shuts down, the panel should be blanked to black.

Relevant files:

- `droplogic/mcp/runtime.py`
- `droplogic/mcp/server.py`
- `droplogic/hardware/box_mini1.py`
- `droplogic/hardware/modules/front_panel/front_panel_module.py`

## Animation Model

There are 2 layers:

1. High-level expression names:
   - `idle`
   - `happy`
   - `thinking`
   - `working`
   - `sad`
   - `sleep`
   - plus aliases like `done`, `moving`, `looking`, `heating`

2. Asset-library states:
   - also `idle`, `happy`, `thinking`, `working`, `sad`, `sleep`
   - resolved in `DroptiBotV1.ASSET_STATE_ALIASES`

Within one state:

- `manifest.json` defines:
  - `entry_frame`
  - `allowed_state_transitions`
  - `frames`
- `frames[frame_name]["next"]` is the transition graph.
- The runtime picks the next frame from this graph.

Important:

- For deliberate micro-animations such as sleep eye openings, use linear chains.
- Transition frames should usually have a single predecessor and a single successor.
- Keep the graph simple and explicit. The hardware is unforgiving.

## Where To Edit Frames

Do not hand-edit the generated BMPs unless you have a very specific reason.

Instead edit:

- `runs/eq2013_sdk_probe/test_sdk_clean/generate_front_panel_state_library.py`

Then regenerate:

```bash
/mnt/c/Users/FranQuero/AppData/Local/Programs/Python/Python313/python.exe \
  C:\\Users\\FranQuero\\Documents\\GitHub\\DropLogic\\runs\\eq2013_sdk_probe\\test_sdk_clean\\generate_front_panel_state_library.py
```

That overwrites:

- `runs/eq2013_sdk_probe/test_sdk_clean/front_panel_state_library/`

## Sleep State Conventions

Sleep is special:

- closed eyes should feel sleepy, not happy
- the `Z` glyphs must not overlap the eyes
- ambient sleep frames should move slowly
- rare events may open one eye briefly
- eye-opening transitions should be faster than the base sleep cadence
- one-eye-open sequences should be linear:
  - open step 1
  - open step 2
  - open step 3
  - close step 1
  - close step 2
  - back to base sleep

## Hardware Constraints

- Panel size is `48x16`.
- Transport is the EQ DLL realtime bitmap path.
- BMPs that look good in software can still look bad on the physical panel.
- Simpler shapes usually survive better than detailed ones.
- If a frame causes garbage or unreliable render, simplify it rather than adding detail.

## Testing Workflow

For direct manual testing, use:

- `runs/eq2013_sdk_probe/test_sdk_clean/send_realtime_hbitmap_sequence.ps1`

This path is trusted for visible panel testing.

Typical workflow:

1. Edit the generator.
2. Regenerate the library.
3. Send a short sequence from one state folder.
4. Check the real panel visually.
5. Only then integrate behavior changes into MCP / BoxMini.

## What Not To Regress

- Do not switch normal animation back to the procedural renderer.
- Do not assume a successful DLL call means the panel looked correct.
- Do not introduce complicated frame graphs when a linear sequence will do.
- Do not let front-panel transport errors crash MCP startup.
- MCP should keep retrying panel animation if the panel is temporarily disconnected.

## If You Need New Expressions

Preferred order:

1. Reuse an existing state if the mood is close enough.
2. Extend an existing state folder with more frames.
3. Only add a new state folder if the behavior is genuinely distinct.

If you add a new state:

1. Add frames and a `manifest.json` entry in the generator.
2. Regenerate the library.
3. Add an alias in `DroptiBotV1.ASSET_STATE_ALIASES` if needed.
4. Update MCP / BoxMini state mapping only after visual validation.

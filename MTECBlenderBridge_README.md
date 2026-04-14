# MTEC Blender Bridge

This project connects Codex or any MCP client to Blender in two steps:

1. `MTECBlenderBridge.py`
   Runs inside Blender as an addon and exposes a local HTTP bridge.
2. `mtec_codex_mcp_server.py`
   Runs outside Blender in a normal Python environment and exposes MCP over `stdio`.

The split keeps Blender-side dependencies small while still giving Codex access to Blender tools.

## How It Works

Codex / VS Code MCP client
-> `mtec_codex_mcp_server.py`
-> HTTP requests
-> `MTECBlenderBridge.py` inside Blender
-> `bpy`

## Prerequisites

- Blender 3.6 or newer
- Python 3.10+ recommended for the external MCP server
- A local MCP client such as Codex in VS Code

## 1. Install The Blender Addon

In Blender:

1. Open `Edit -> Preferences -> Add-ons`
2. Click `Install...`
3. Select `MTECBlenderBridge.py`
4. Enable the addon

After enabling it:

1. Open the `3D Viewport`
2. Open the right sidebar with `N` if needed
3. Go to the `MTEC MCP` tab
4. Click `Start MTEC Bridge`

The bridge starts a local HTTP server at:

`http://127.0.0.1:8765`

Useful health checks:

- `http://127.0.0.1:8765/health`
- `http://127.0.0.1:8765/tools`
- `http://127.0.0.1:8765/invoke`

## 2. Create The External Python Environment

From a normal terminal outside Blender:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. Start The MCP Server

Run the external server from this project folder:

```powershell
.venv\Scripts\python.exe .\mtec_codex_mcp_server.py
```

By default it connects to:

`http://127.0.0.1:8765`

If your Blender bridge uses a different address or port, set the environment variable before starting:

```powershell
$env:MTEC_BLENDER_BRIDGE_URL = "http://127.0.0.1:8765"
.venv\Scripts\python.exe .\mtec_codex_mcp_server.py
```

Optional timeout override:

```powershell
$env:MTEC_BLENDER_BRIDGE_TIMEOUT = "120"
```

## 4. Configure Codex / VS Code

Add the MCP server to your Codex MCP configuration so Codex starts the external Python process.

Use the template `mtec-blender.example.json` as a starting point (copy it to `mtec-blender.json`, which is git-ignored so each machine can keep its own paths).

Typical values (adjust paths for your install):

- Name: `mtec-blender`
- Command: `.venv\Scripts\python.exe`
- Args: `mtec_codex_mcp_server.py`

If your MCP client supports environment variables, you can also pass `MTEC_BLENDER_BRIDGE_URL` there.

## 5. Recommended Startup Order

Each time you want to use the bridge:

1. Open Blender
2. Enable the addon if it is not already enabled
3. In the `MTEC MCP` panel, click `Start MTEC Bridge`
4. Start `mtec_codex_mcp_server.py`
5. Start or reconnect your MCP client
6. Ask Codex to inspect or edit the Blender scene

## 6. First Test Prompts

Good first prompts for Codex:

- `Check whether the Blender bridge is healthy.`
- `List the available Blender tools.`
- `List all objects in the current Blender scene.`
- `Create a cube named TestCube at the origin.`
- `Move TestCube to x=2, y=0, z=1.`
- `Create a red material named RedPaint and assign it to TestCube.`
- `Add a bevel modifier to TestCube with width 0.05 and 2 segments.`
- `Render an image to D:\temp\test.png`

## What This Bridge Can Do

The current bridge exposes tools for:

- Scene inspection
- Object creation and transforms
- Collections and selection
- Materials
- Lights and cameras
- Modifiers and booleans
- Import and export
- Render settings and still renders
- Viewport automation
- Rigid body setup and demo scenes
- Generic `bpy.ops` calls
- Raw Python execution inside Blender

To see the exact tool list at runtime, open:

`http://127.0.0.1:8765/tools`

Or ask the MCP tool:

- `blender_list_tools`

## Viewport Features

The Blender panel also includes runtime viewport controls under `MTEC MCP -> Viewport`.

You can switch between:

- `Manual`
- `Cinematic`

And control options such as:

- Auto-focus edited objects
- Auto-orbit edited objects
- Smooth camera motion
- View animation duration
- Cinematic sweep and distance settings

These can also be changed through the MCP tool `set_bridge_options`.

## Troubleshooting

If Codex cannot reach Blender:

- Make sure the addon is enabled
- Make sure `Start MTEC Bridge` has been clicked in Blender
- Open `http://127.0.0.1:8765/health` in a browser
- Make sure the MCP server is using the same URL as the Blender bridge

If the MCP server fails to start:

- Activate the correct virtual environment
- Verify `fastmcp` and `httpx` are installed
- Run the script directly in a terminal first to inspect any import errors

If tool calls time out:

- Increase `MTEC_BLENDER_BRIDGE_TIMEOUT`
- Check whether Blender is busy with a long operation

## Security Note

`run_python_snippet` is intentionally powerful and executes Python inside Blender.

That is useful for development and advanced workflows, but it should only be exposed in trusted local environments.

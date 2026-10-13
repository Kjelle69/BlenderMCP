# MTEC Blender MCP Bridge

A local bridge between Blender and MCP clients. The add-on exposes HTTP on
`http://127.0.0.1:8765`; the external Python server exposes MCP over stdio.

![Blender rig example](doc/rig-demo.png)

## Install

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe package_addon.py
```

Install `dist/MTECBlenderBridge.zip` in Blender through **Install from Disk**.
Enable the add-on and start it from **N -> MTEC MCP**. See the
[installation guide](MTECBlenderBridge_README.md) for configuration and troubleshooting.
`mtec-blender.example.json` is a template; personal configuration belongs in the
ignored `mtec-blender.json`.

## Repository and distribution

| Files | Purpose |
| --- | --- |
| `MTECBlenderBridge.py` | Blender add-on and HTTP tools |
| `mtec_codex_mcp_server.py` | External MCP server |
| `mtec_geometry_tools.py` | Reusable mesh checks, geometry replacement and profile members |
| `setup_codex.py`, `requirements.txt` | Runtime installation |
| `package_addon.py` | ZIP packaging with an explicit file allowlist |
| `test_*.py` | Bridge/setup development checks |
| `doc/` | Bridge documentation and illustrations |
| `_local_builds/` | Local model scripts, drawings, scenes and previews; ignored by Git |

The ZIP contains only the add-on, geometry helper, MCP server, setup helper and dependencies list.
It never scans the workspace for files. Model scripts and their artifacts are
archived together under `_local_builds/rv4/` and `_local_builds/bsa/`; the example
Blender scene lives in `_local_builds/examples/`.
Keep future builds in `_local_builds/<project>/`, using paths relative to their
script directory. This folder is absent from a clone; back it up separately.
Environments, `dist/` and generated outputs are also ignored.

## Development

```powershell
.venv\Scripts\python.exe -m unittest test_setup_codex.py
.venv\Scripts\python.exe package_addon.py
```

`test_blender_setup.py` is a Blender integration check for the installer; it needs
an external Python installation and internet access to install dependencies.
See the [modelling shortcuts proposal](doc/MODELLING_SHORTCUTS.md) and
[development plan](doc/DEVELOPMENT_PLAN.md).

Version 0.3.0 adds `validate_meshes`, `replace_mesh_geometry` and
`create_profile_member` (L/U/solid or hollow rectangular sections), with explicit
meter/mm/inch units. Run `test_geometry_tools.py` using Blender in background
mode for the geometry checks. See the [2D drawing import plan](doc/DRAWING_IMPORT_PLAN.md)
for calibrated PDF crops and traces.

## Diagnostics

- `/health`: bridge health; `/tools`: available Blender tools.
- `MTEC_BLENDER_BRIDGE_URL`: external server's bridge URL.
- `MTEC_BLENDER_BRIDGE_TIMEOUT`: tool-call timeout in seconds.

The bridge executes Python inside Blender. Use a trusted local environment and
keep its HTTP endpoint on localhost.

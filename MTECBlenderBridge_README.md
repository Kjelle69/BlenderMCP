# MTEC Blender Bridge + MTECCodexMCP

Det här upplägget delar upp systemet i två delar:

1. **MTECBlenderBridge.py**  
   Körs **inne i Blender** som addon och exponerar ett enkelt lokalt HTTP-API.

2. **mtec_codex_mcp_server.py**  
   Körs **utanför Blender** i en vanlig Python-miljö och exponerar en riktig MCP-server för Codex/VS Code.

Det gör att Blender slipper bära hela MCP/Windows-beroendekedjan.

---

## Arkitektur

VS Code + Codex  
→ `mtec_codex_mcp_server.py` (MCP server, stdio)  
→ HTTP  
→ `MTECBlenderBridge.py` i Blender  
→ `bpy`

---

## 1. Installera Blender-addonen

I Blender:

- Edit → Preferences → Add-ons
- Install from Disk
- välj `MTECBlenderBridge.py`
- aktivera addonen

I 3D Viewport → Sidebar → **MTEC MCP**:

- klicka **Start MTEC Bridge**

Standardadress:
- `http://127.0.0.1:8765`

Snabbtest i webbläsare:
- `http://127.0.0.1:8765/health`
- `http://127.0.0.1:8765/tools`

---

## 2. Skapa Python-miljö för MCP-servern

I vanlig terminal, utanför Blender:

```bash
python -m venv .venv
```

Aktivera miljön.

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Installera paket:

```bash
pip install fastmcp httpx
```

---

## 3. Starta extern MCP-server

```bash
python mtec_codex_mcp_server.py
```

Detta kör MCP-servern över stdio, vilket passar Codex bra.

Om Blender-bridgen kör på annan adress än standard:

```powershell
$env:MTEC_BLENDER_BRIDGE_URL="http://127.0.0.1:8765"
python mtec_codex_mcp_server.py
```

---

## 4. Koppla till Codex i VS Code

Lägg till den som MCP-server i Codex-konfig med kommando som startar den externa Python-processen.

Exempelidé:

- namn: `mtec-blender`
- kommando: python
- argument: `mtec_codex_mcp_server.py`

Om du kör venv, peka gärna direkt på rätt `python.exe` i `.venv`.

---

## 5. Första tester i Codex

Exempelprompter:

- `List the current Blender scene objects.`
- `Create a cube named TestCube at the origin.`
- `Move TestCube to x=2, y=0, z=1.`
- `Create a material called RedPaint and assign it to TestCube.`
- `Add a bevel modifier to TestCube with width 0.05 and 2 segments.`
- `Render an image to C:\temp\test.png`

---

## Verktyg i v0.1

Blender bridge:

- `get_scene_info`
- `list_objects`
- `create_mesh_object`
- `create_curve_object`
- `create_text_object`
- `transform_object`
- `duplicate_object`
- `delete_objects`
- `create_material`
- `assign_material`
- `create_light`
- `create_camera`
- `add_modifier`
- `apply_modifier`
- `boolean_operation`
- `configure_render_settings`
- `render_image`
- `import_file`
- `export_file`
- `save_blend_file`
- `clear_scene`
- `call_operator`
- `run_python_snippet`

---

## Viktigt

`run_python_snippet` är mycket kraftfullt.  
Bra för intern utveckling, men bör låsas ned senare om ni vill ha hårdare kontroll.

---

## Nästa steg

Bra kandidater för v0.2:

- geometry nodes
- particle systems
- rigid body / cloth / fluids
- bättre typed schemas per tool
- bildfångst från viewport
- sessions/loggning
- whitelistad operator-policy

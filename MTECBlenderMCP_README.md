# MTECBlenderMCP

Egen Blender-addon för att exponera Blender som en lokal MCP-server så att Codex i VS Code kan styra Blender.

## Vad den här första versionen gör

Den här versionen kör **utan PolyMCP** och använder i stället det officiella Python-MCP-SDK:t (`mcp[cli]`) med `FastMCP` och en lokal **streamable HTTP**-endpoint. MCP Python SDK stöder FastMCP och streamable HTTP, och streamable HTTP mountas normalt på `/mcp`. citeturn222661view0turn222661view2

Codex IDE extension finns för VS Code-kompatibla editorer, och Windows-stöd beskrivs som experimentellt. citeturn222661view1

## Medföljande verktyg

- `ping`
- `get_scene_info`
- `list_objects`
- `get_object_info`
- `create_primitive`
- `transform_object`
- `duplicate_object`
- `delete_objects`
- `set_parent`
- `add_modifier`
- `apply_modifier`
- `create_material`
- `assign_material`
- `create_light`
- `create_camera`
- `save_blend_file`
- `import_file`
- `export_file`
- `render_image`
- `select_objects`
- `call_operator`
- `run_python_snippet`
- `capture_viewport_png`

## Viktigt om scope

Det här är en **egen MTEC-grundplatta**, inte en 1:1-kopia av den stora `blender_mcp.py`.

I stället för att mappa exakt varje specialfunktion från originalfilen har den här versionen:

- de viktigaste kategorierna färdiga som egna tools
- `call_operator()` för att anropa nästan valfri Blender-operator
- `run_python_snippet()` som sista escape hatch

Det gör att ni kan komma väldigt långt direkt, samtidigt som addon-koden hålls betydligt renare och lättare att underhålla.

## Installera i Blender

1. Öppna **Edit → Preferences → Add-ons**
2. Klicka **Install...**
3. Välj `MTECBlenderMCP.py`
4. Aktivera addonet
5. Öppna **3D View → Sidebar → MTEC MCP**
6. Tryck **Start MTEC Blender MCP**

Första starten kan installera Python-paket i Blenders Python-miljö:

- `fastapi`
- `uvicorn[standard]`
- `mcp[cli]`

## Lokal MCP-URL

När servern är uppe:

`http://127.0.0.1:8765/mcp`

## Tänkta Codex-flödet

VS Code → Codex → `http://127.0.0.1:8765/mcp` → Blender

## Rekommenderat nästa steg

Bygg ut den här filen kategori för kategori från originalet:

1. geometry nodes
2. particle systems
3. rigid body / cloth / fluids
4. advanced materials / procedural materials
5. batch operations
6. templates / presets

Det är mycket bättre än att försöka bära över hela monsterfilen i ett enda hopp.

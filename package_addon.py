"""Build a Blender-installable legacy add-on ZIP, without local environments."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
output = root / "dist" / "MTECBlenderBridge.zip"
output.parent.mkdir(exist_ok=True)
with ZipFile(output, "w", ZIP_DEFLATED) as archive:
    archive.write(root / "MTECBlenderBridge.py", "mtec_blender_bridge/__init__.py")
    for name in ("mtec_geometry_tools.py", "mtec_codex_mcp_server.py", "setup_codex.py", "requirements.txt"):
        archive.write(root / name, f"mtec_blender_bridge/{name}")
print(output)

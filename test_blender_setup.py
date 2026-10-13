"""Run with Blender --background --python test_blender_setup.py."""
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import bpy

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mtec_test", root / "MTECBlenderBridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
with tempfile.TemporaryDirectory(prefix="MTEC Blender test ") as directory:
    os.environ["CODEX_HOME"] = str(Path(directory) / "codex")
    os.environ["LOCALAPPDATA"] = directory
    bridge.register()
    try:
        assert bpy.ops.mtecbridge.connect_codex() == {'FINISHED'}
        deadline = time.monotonic() + 180
        while bridge.codex_setup_process is not None and time.monotonic() < deadline:
            bridge.poll_codex_setup()
            time.sleep(0.5)
        assert bridge.codex_setup_status == "Codex: Configured - restart Codex", bridge.codex_setup_status
        config = Path(directory) / "codex" / "config.toml"
        assert config.exists()
        assert "mcp_servers.mtec-blender" in config.read_text()
        print("PASS: Blender operator installed runtime and configured isolated Codex home")
    finally:
        bridge.unregister()

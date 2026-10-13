"""Install the local MCP runtime and preserve the user's Codex settings."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def install(source, target, config, endpoint):
    source, target, config = map(Path, (source, target, config))
    target.mkdir(parents=True, exist_ok=True)
    python = target / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python")
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(target / "venv")], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(source / "requirements.txt"), "tomlkit==0.13.3"], check=True)
    # Run the config writer in the environment where tomlkit was installed.
    subprocess.run([str(python), str(Path(__file__).resolve()), "--write-config",
                    "--source", str(source), "--target", str(target),
                    "--config", str(config), "--endpoint", endpoint], check=True)


def write_config(source, target, config, endpoint):
    import tomlkit
    source, target, config = map(Path, (source, target, config))
    original = config.read_bytes() if config.exists() else None
    document = tomlkit.parse(original.decode("utf-8-sig") if original else "")
    servers = document.setdefault("mcp_servers", tomlkit.table())
    server = servers.setdefault("mtec-blender", tomlkit.table())
    python = target / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python")
    script = target / "mtec_codex_mcp_server.py"
    server["command"] = str(python)
    server["args"] = [str(script)]
    server["enabled"] = True
    server.setdefault("env", tomlkit.table())["MTEC_BLENDER_BRIDGE_URL"] = endpoint
    shutil.copy2(source / script.name, script)
    config.parent.mkdir(parents=True, exist_ok=True)
    if original is not None:
        backup = config.with_name(config.name + f".mtec-backup-{time.time_ns()}")
        backup.write_bytes(original)
    descriptor, temporary = tempfile.mkstemp(dir=config.parent, prefix=".mtec-", suffix=".toml")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            output.write(tomlkit.dumps(document))
        if (config.read_bytes() if config.exists() else None) != original:
            raise RuntimeError("Codex settings changed during setup; try again.")
        os.replace(temporary, config)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("Codex configured. Restart Codex to load the Blender tools.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8765")
    parser.add_argument("--write-config", action="store_true")
    args = parser.parse_args()
    (write_config if args.write_config else install)(args.source, args.target, args.config, args.endpoint)

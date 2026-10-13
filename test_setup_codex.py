import tempfile
import unittest
from pathlib import Path
import tomlkit
from setup_codex import write_config


class ConfigTests(unittest.TestCase):
    def test_preserves_settings_and_supports_repeat_install(self):
        with tempfile.TemporaryDirectory(prefix="MTEC test ") as directory:
            root = Path(directory)
            source, target = root / "source", root / "runtime"
            source.mkdir()
            target.mkdir()
            (source / "mtec_codex_mcp_server.py").write_text("# server")
            config = root / "config.toml"
            original = '# keep this comment\nmodel = "example"\n[mcp_servers.other]\nurl = "http://localhost/other"\n'
            config.write_text(original)
            for _ in range(2):
                write_config(source, target, config, "http://127.0.0.1:8765")
            result = tomlkit.parse(config.read_text())
            self.assertEqual(result["model"], "example")
            self.assertEqual(result["mcp_servers"]["other"]["url"], "http://localhost/other")
            self.assertEqual(result["mcp_servers"]["mtec-blender"]["args"], [str(target / "mtec_codex_mcp_server.py")])
            self.assertIn("# keep this comment", config.read_text())
            self.assertTrue(any(p.read_text() == original for p in root.glob("*.mtec-backup-*")))
            config.write_text("invalid = [")
            with self.assertRaises(Exception):
                write_config(source, target, config, "http://127.0.0.1:8765")
            self.assertEqual(config.read_text(), "invalid = [")


if __name__ == "__main__":
    unittest.main()

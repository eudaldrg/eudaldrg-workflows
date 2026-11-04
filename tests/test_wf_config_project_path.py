import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins/core/scripts"))
import wf_config  # noqa: E402


class ProjectConfigPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        wf_config._warned_legacy.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    def resolve(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            path = wf_config.project_config_path(self.root)
        return path, err.getvalue()

    def test_defaults_to_config_dir(self):
        path, err = self.resolve()
        self.assertEqual(path, self.root / ".config/workflows.json")
        self.assertEqual(err, "")

    def test_legacy_only_is_read_with_warning(self):
        self.write(".claude/workflows.json")
        path, err = self.resolve()
        self.assertEqual(path, self.root / ".claude/workflows.json")
        self.assertIn("git mv", err)
        self.assertEqual(self.resolve()[1], "")  # warned once

    def test_new_location_wins_over_legacy(self):
        self.write(".claude/workflows.json")
        self.write(".config/workflows.json")
        path, err = self.resolve()
        self.assertEqual(path, self.root / ".config/workflows.json")
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()

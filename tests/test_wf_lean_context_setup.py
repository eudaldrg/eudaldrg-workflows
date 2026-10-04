import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/core/scripts"))
import wf_lean_context_setup as lc  # noqa: E402

LEAN = {
    "permissions": {"deny": ["Artifact"]},
    "env": {"ENABLE_TOOL_SEARCH": "true"},
    "promptSuggestionEnabled": False,
}


class LeanContextSetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lc.main(["--settings-path", str(self.path), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_apply_on_missing_file(self):
        code, _, _ = self.run_cli("apply")
        self.assertEqual(code, lc.OK)
        self.assertEqual(self.read(), LEAN)

    def test_apply_merges_and_keeps_other_settings(self):
        self.write({"theme": "dark", "permissions": {"deny": ["WebFetch"], "allow": ["Bash(ls)"]},
                    "env": {"FOO": "1"}})
        self.assertEqual(self.run_cli("apply")[0], lc.OK)
        data = self.read()
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(data["permissions"], {"deny": ["WebFetch", "Artifact"],
                                               "allow": ["Bash(ls)"]})
        self.assertEqual(data["env"], {"FOO": "1", "ENABLE_TOOL_SEARCH": "true"})
        self.assertIs(data["promptSuggestionEnabled"], False)

    def test_apply_is_idempotent_and_does_not_rewrite(self):
        self.write({"permissions": {"deny": ["Artifact"]}, "env": {"ENABLE_TOOL_SEARCH": "true"},
                    "promptSuggestionEnabled": False})
        before = self.path.read_text(encoding="utf-8")
        code, out, _ = self.run_cli("apply")
        self.assertEqual(code, lc.OK)
        self.assertIn("nothing to do", out)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_apply_refuses_explicit_values_without_force(self):
        self.write({"env": {"ENABLE_TOOL_SEARCH": "auto:5"}, "promptSuggestionEnabled": True})
        code, _, err = self.run_cli("apply")
        self.assertEqual(code, lc.ERR_CONFLICT)
        self.assertIn("auto:5", err)
        self.assertIn("promptSuggestionEnabled", err)
        self.assertEqual(self.read()["env"]["ENABLE_TOOL_SEARCH"], "auto:5")
        self.assertEqual(self.run_cli("apply", "--force")[0], lc.OK)
        self.assertEqual(self.read(), LEAN)

    def test_dry_runs_write_nothing(self):
        self.write({"theme": "dark"})
        code, out, _ = self.run_cli("apply", "--dry-run")
        self.assertEqual(code, lc.OK)
        self.assertIn("would change", out)
        self.assertEqual(self.read(), {"theme": "dark"})
        self.write(LEAN)
        self.assertEqual(self.run_cli("revert", "--dry-run")[0], lc.OK)
        self.assertEqual(self.read(), LEAN)

    def test_status_reports_pending_changes_without_writing(self):
        self.write({"env": {"ENABLE_TOOL_SEARCH": "auto"}})
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, lc.OK)
        self.assertIn("Artifact denied:          no", out)
        self.assertIn("apply would change", out)
        self.assertIn("--force", out)
        self.assertEqual(self.read(), {"env": {"ENABLE_TOOL_SEARCH": "auto"}})
        self.write(LEAN)
        self.assertIn("fully applied", self.run_cli("status")[1])

    def test_revert_removes_only_our_values(self):
        self.write({"theme": "dark", "permissions": {"deny": ["WebFetch", "Artifact"]},
                    "env": {"FOO": "1", "ENABLE_TOOL_SEARCH": "true"},
                    "promptSuggestionEnabled": False})
        self.assertEqual(self.run_cli("revert")[0], lc.OK)
        self.assertEqual(self.read(), {"theme": "dark", "permissions": {"deny": ["WebFetch"]},
                                       "env": {"FOO": "1"}})

    def test_revert_drops_emptied_containers(self):
        self.write(LEAN)
        self.run_cli("apply")
        self.assertEqual(self.run_cli("revert")[0], lc.OK)
        self.assertEqual(self.read(), {})

    def test_revert_keeps_values_it_did_not_set(self):
        self.write({"env": {"ENABLE_TOOL_SEARCH": "auto:5"}, "promptSuggestionEnabled": True})
        code, out, _ = self.run_cli("revert")
        self.assertEqual(code, lc.OK)
        self.assertIn("kept", out)
        self.assertIn("nothing to revert", out)
        self.assertEqual(self.read(), {"env": {"ENABLE_TOOL_SEARCH": "auto:5"},
                                       "promptSuggestionEnabled": True})

    def test_bad_json_and_bad_shapes_are_refused(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.run_cli("apply")[0], lc.ERR_BAD_JSON)
        self.write({"permissions": {"deny": "Artifact"}})
        self.assertEqual(self.run_cli("apply")[0], lc.ERR_BAD_JSON)
        self.write({"env": ["ENABLE_TOOL_SEARCH"]})
        self.assertEqual(self.run_cli("revert")[0], lc.ERR_BAD_JSON)
        self.assertEqual(self.read(), {"env": ["ENABLE_TOOL_SEARCH"]})


if __name__ == "__main__":
    unittest.main()

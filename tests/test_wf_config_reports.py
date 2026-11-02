import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/core/scripts"))
import wf_config  # noqa: E402

DEFAULTS = Path(__file__).resolve().parents[1] / "plugins/core/defaults/workflows.defaults.json"


def problems(project_layer: dict) -> list[str]:
    defaults = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    loaded = [("defaults", defaults), ("project", project_layer)]
    merged, _ = wf_config.merge_layers(loaded)
    with contextlib.redirect_stderr(io.StringIO()):
        return wf_config.validate(merged, loaded, strict=True)


class ReportsConfigTest(unittest.TestCase):
    def test_default_is_null_and_valid(self):
        defaults = json.loads(DEFAULTS.read_text(encoding="utf-8"))
        self.assertIsNone(defaults["reports"]["publishCmd"])
        self.assertEqual(problems({}), [])

    def test_command_with_file_placeholder_is_valid(self):
        layer = {"reports": {"publishCmd": "publish {file} --title {title} --kind {kind}"}}
        self.assertEqual(problems(layer), [])

    def test_explicit_null_is_valid(self):
        self.assertEqual(problems({"reports": {"publishCmd": None}}), [])

    def test_command_without_file_placeholder_rejected(self):
        found = problems({"reports": {"publishCmd": "publish --title {title}"}})
        self.assertTrue(any("reports.publishCmd" in p for p in found), found)

    def test_non_string_rejected(self):
        found = problems({"reports": {"publishCmd": ["publish", "{file}"]}})
        self.assertTrue(any("reports.publishCmd" in p for p in found), found)

    def test_get_prints_empty_for_null(self):
        self.assertEqual(wf_config.render(None, as_json=False), "")


if __name__ == "__main__":
    unittest.main()

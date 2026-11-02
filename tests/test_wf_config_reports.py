import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wf_test_util import load_defaults, problems, wf_config  # noqa: E402


class ReportsConfigTest(unittest.TestCase):
    def test_default_is_null_and_valid(self):
        self.assertIsNone(load_defaults()["reports"]["publishCmd"])
        self.assertEqual(problems({}, strict=True), [])

    def test_command_with_file_placeholder_is_valid(self):
        layer = {"reports": {"publishCmd": "publish {file} --title {title} --kind {kind}"}}
        self.assertEqual(problems(layer, strict=True), [])

    def test_command_without_file_placeholder_rejected(self):
        found = problems({"reports": {"publishCmd": "publish --title {title}"}})
        self.assertTrue(any("reports.publishCmd" in p for p in found), found)

    def test_non_string_rejected(self):
        found = problems({"reports": {"publishCmd": ["publish", "{file}"]}})
        self.assertTrue(any("reports.publishCmd" in p for p in found), found)


class ExpandTest(unittest.TestCase):
    def test_values_are_quoted_and_substituted_once(self):
        out = wf_config.expand_template(
            "pub {file} --title {title} --kind {kind} {other}",
            {"file": "/tmp/a {title}.html", "title": "it's \"x\"", "kind": "plan"},
        )
        self.assertEqual(
            out,
            "pub '/tmp/a {title}.html' --title 'it'\"'\"'s \"x\"' --kind plan {other}",
        )

    def run_expand(self, layer: dict | None, *values: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home.json"
            home.write_text(json.dumps(layer or {}), encoding="utf-8")
            env = {"WF_HOME_CONFIG": str(home), "WF_PROJECT_DIR": tmp}
            old = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            try:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = wf_config.main(["expand", "reports.publishCmd", *values])
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_null_setting_prints_nothing(self):
        self.assertEqual(self.run_expand(None, "file=/x.html"), "")

    def test_set_setting_prints_command(self):
        layer = {"reports": {"publishCmd": "pub {file} --kind {kind}"}}
        self.assertEqual(self.run_expand(layer, "file=/x y.html", "kind=summary"), "pub '/x y.html' --kind summary\n")


if __name__ == "__main__":
    unittest.main()

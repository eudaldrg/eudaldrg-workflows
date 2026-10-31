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
        return wf_config.validate(merged, loaded, strict=False)


class CppRepoConfigTest(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual(problems({}), [])

    def test_defaults_have_agreed_values(self):
        defaults = json.loads(DEFAULTS.read_text(encoding="utf-8"))
        checks = defaults["cpp"]["repo"]["checks"]
        self.assertTrue(checks["cppcheck"])
        self.assertFalse(checks["sanitizers"]["tsan"])
        self.assertFalse(checks["memoryCap"])
        policy = defaults["git"]["protection"]["default"]
        self.assertEqual(policy["approvals"], 0)
        self.assertFalse(policy["linearHistory"])
        self.assertEqual(defaults["git"]["protection"]["branches"], {})
        self.assertTrue(defaults["implement"]["simplifyBeforePush"])

    def test_bad_forge_rejected(self):
        self.assertTrue(any("git.forge" in p for p in problems({"git": {"forge": "gitlab"}})))

    def test_required_checks_shape(self):
        self.assertEqual(problems({"git": {"protection": {"requiredChecks": ["lint"]}}}), [])
        self.assertTrue(problems({"git": {"protection": {"requiredChecks": "all"}}}))

    def test_matrix_cells_validated(self):
        bad = {"cpp": {"repo": {"ci": {"matrix": [{"os": "ubuntu-24.04", "compiler": "gcc"}]}}}}
        self.assertTrue(any("need a 'version'" in p for p in problems(bad)))
        bad = {"cpp": {"repo": {"ci": {"matrix": [{"os": "x", "compiler": "icc", "version": "1"}]}}}}
        self.assertTrue(any("icc" in p for p in problems(bad)))

    def test_tsan_type_checked(self):
        bad = {"cpp": {"repo": {"checks": {"sanitizers": {"tsan": "yes"}}}}}
        self.assertTrue(any("tsan" in p for p in problems(bad)))


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wf_test_util import load_defaults, problems  # noqa: E402


class CppRepoConfigTest(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual(problems({}), [])

    def test_defaults_have_agreed_values(self):
        defaults = load_defaults()
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

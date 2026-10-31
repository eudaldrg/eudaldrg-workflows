import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/core/scripts"))
import wf_cpp_repo as cr  # noqa: E402
from test_wf_cpp_repo import RepoCase  # noqa: E402

SLUG = "example/demo"
JOBS = ["lint", "sanitizers", "test (clang-18)", "test (gcc-14)", "test (msvc)"]


class FakeGh:
    """Records calls; answers like `gh api` for one repo."""

    def __init__(self, branches=("main", "dev"), protection=None, ran=JOBS, authed=True,
                 put_ok=True):
        self.branches = set(branches)
        self.protection = dict(protection or {})
        self.ran = list(ran)
        self.authed = authed
        self.put_ok = put_ok
        self.calls = []

    def __call__(self, args, payload=None):
        self.calls.append((args, payload))
        if args[0] == "user":
            return (0, "me\n", "") if self.authed else (4, "", "not logged in")
        if args[0] == "-X" and args[1] == "PUT":
            if not self.put_ok:
                return 1, "", "HTTP 422"
            branch = args[2].split("/")[-2]
            self.protection[branch] = to_response(payload)
            return 0, "{}", ""
        path = args[0]
        if path.endswith("/protection"):
            branch = path.split("/")[-2]
            if branch in self.protection:
                return 0, json.dumps(self.protection[branch]), ""
            return 1, "", "gh: Branch not protected (HTTP 404)"
        if "/check-runs" in path:
            return 0, json.dumps(self.ran), ""
        if "/branches/" in path:
            branch = path.split("/")[-1]
            return (0, "{}", "") if branch in self.branches else (1, "", "Not Found (HTTP 404)")
        raise AssertionError(f"unexpected gh call {args}")

    def puts(self):
        return [call for call in self.calls if call[0][:2] == ["-X", "PUT"]]


def to_response(payload):
    """What GitHub's GET returns after a PUT with this payload."""
    response = {
        "enforce_admins": {"enabled": payload["enforce_admins"]},
        "allow_force_pushes": {"enabled": payload["allow_force_pushes"]},
        "allow_deletions": {"enabled": payload["allow_deletions"]},
        "required_linear_history": {"enabled": payload["required_linear_history"]},
    }
    if payload["required_status_checks"]:
        response["required_status_checks"] = payload["required_status_checks"]
    if payload["required_pull_request_reviews"]:
        response["required_pull_request_reviews"] = payload["required_pull_request_reviews"]
    return response


class PolicyTest(RepoCase):
    def test_payload_defaults(self):
        settings = self.settings()
        forge = cr.detect_forge(settings)
        payload = cr.github_payload(cr.policy_for(settings, "main", forge))
        self.assertEqual(set(payload), {"required_status_checks", "enforce_admins",
                                        "required_pull_request_reviews", "restrictions",
                                        "allow_force_pushes", "allow_deletions",
                                        "required_linear_history"})
        self.assertEqual(payload["required_pull_request_reviews"]["required_approving_review_count"], 0)
        self.assertFalse(payload["required_linear_history"])
        self.assertFalse(payload["allow_force_pushes"])
        self.assertFalse(payload["allow_deletions"])
        self.assertTrue(payload["enforce_admins"])
        self.assertEqual(payload["required_status_checks"]["contexts"], JOBS)

    def test_explicit_required_checks(self):
        self.config({"git": {"protection": {"requiredChecks": ["lint"]}}})
        settings = self.settings()
        policy = cr.policy_for(settings, "dev", cr.detect_forge(settings))
        self.assertEqual(policy["requiredChecks"], ["lint"])

    def test_current_roundtrip(self):
        settings = self.settings()
        policy = cr.policy_for(settings, "main", cr.detect_forge(settings))
        current = cr.github_current(to_response(cr.github_payload(policy)))
        self.assertEqual(cr.policy_diff(current, policy), [])


class ProtectCliTest(RepoCase):
    def gh(self, fake):
        patcher = mock.patch.object(cr, "gh_api", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_show_never_writes(self):
        fake = self.gh(FakeGh())
        code, out, _ = self.run_cli("protect")
        self.assertEqual(code, cr.OK)
        self.assertIn(f"== {SLUG} main", out)
        self.assertIn(f"== {SLUG} dev", out)
        self.assertIn("(unprotected)", out)
        self.assertEqual(fake.puts(), [])

    def test_apply_needs_exactly_one_branch(self):
        fake = self.gh(FakeGh())
        code, _, err = self.run_cli("protect", "--apply")
        self.assertEqual(code, cr.ERROR)
        self.assertIn("one --branch", err)
        self.assertEqual(fake.puts(), [])

    def test_apply_one_branch_and_read_back(self):
        fake = self.gh(FakeGh())
        code, out, _ = self.run_cli("protect", "--apply", "--branch", "dev")
        self.assertEqual(code, cr.OK, out)
        self.assertEqual(len(fake.puts()), 1)
        self.assertIn("branches/dev/protection", fake.puts()[0][0][2])
        self.assertNotIn("main", fake.protection)
        code, out, _ = self.run_cli("protect", "--branch", "dev")
        self.assertIn("(already matches the policy)", out)

    def test_linear_history_bug_shows_in_diff(self):
        settings = self.settings()
        policy = cr.policy_for(settings, "main", cr.detect_forge(settings))
        wrong = cr.github_payload({**policy, "linearHistory": True})
        self.gh(FakeGh(protection={"main": to_response(wrong)}))
        _, out, _ = self.run_cli("protect", "--branch", "main")
        self.assertIn("linearHistory: true -> false", out)

    def test_missing_branch_and_unreported_checks(self):
        self.gh(FakeGh(branches=("main",), ran=["lint"]))
        _, out, _ = self.run_cli("protect")
        self.assertIn("branch dev not found", out)
        self.assertIn("never reported on main", out)

    def test_failed_write_is_an_error(self):
        self.gh(FakeGh(put_ok=False))
        code, _, err = self.run_cli("protect", "--apply", "--branch", "main")
        self.assertEqual(code, cr.ERROR)
        self.assertIn("HTTP 422", err)

    def test_unauthenticated_gh_prints_checklist(self):
        fake = self.gh(FakeGh(authed=False))
        code, out, err = self.run_cli("protect")
        self.assertEqual(code, cr.ERROR)
        self.assertIn("gh auth login", err)
        self.assertIn("linear history required: False", out)
        self.assertEqual(fake.puts(), [])


class UnsupportedForgeProtectTest(RepoCase):
    origin = "https://bitbucket.org/example/demo.git"

    def test_checklist_and_no_gh_calls(self):
        with mock.patch.object(cr, "gh_api", side_effect=AssertionError("no gh calls")):
            code, out, _ = self.run_cli("protect")
        self.assertEqual(code, cr.OK)
        self.assertIn("No forge adapter here", out)
        self.assertIn("- main:", out)
        self.assertIn("- dev:", out)


if __name__ == "__main__":
    unittest.main()

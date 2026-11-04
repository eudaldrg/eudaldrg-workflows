import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/core/scripts"))
import wf_cpp_repo as cr  # noqa: E402
import wf_protect as wp  # noqa: E402
from test_wf_cpp_repo import RepoCase  # noqa: E402

SLUG = "example/demo"
JOBS = ["lint", "sanitizers", "test (clang-19)", "test (gcc-14)", "test (msvc)"]
LIVE_REPO = {"allow_merge_commit": False, "allow_rebase_merge": False, "allow_squash_merge": True,
             "squash_merge_commit_title": "COMMIT_OR_PR_TITLE",
             "squash_merge_commit_message": "COMMIT_MESSAGES",
             "merge_commit_title": "MERGE_MESSAGE", "merge_commit_message": "PR_TITLE"}


class FakeGh:
    """Records calls; answers like `gh api` for one repo with rulesets and classic protection."""

    def __init__(self, branches=("main", "dev"), rulesets=None, classic=None, ran=JOBS,
                 authed=True, write_ok=True, repo=None):
        self.repo = dict(repo or LIVE_REPO)
        self.branches = set(branches)
        self.rulesets = {i + 1: {**body, "id": i + 1} for i, body in enumerate(rulesets or [])}
        self.classic = dict(classic or {})
        self.ran = list(ran)
        self.authed = authed
        self.write_ok = write_ok
        self.calls = []

    def __call__(self, args, payload=None):
        self.calls.append((args, payload))
        if args[0] == "user":
            return (0, "me\n", "") if self.authed else (4, "", "not logged in")
        if args[0] == "-X":
            if not self.write_ok:
                return 1, "", "HTTP 422"
            verb, path = args[1], args[2]
            if verb == "POST" and path.endswith("/rulesets"):
                new_id = max(self.rulesets, default=0) + 1
                self.rulesets[new_id] = {**payload, "id": new_id}
            elif verb == "PUT" and "/rulesets/" in path:
                ruleset_id = int(path.split("/")[-1])
                self.rulesets[ruleset_id] = {**payload, "id": ruleset_id}
            elif verb == "DELETE" and path.endswith("/protection"):
                self.classic.pop(path.split("/")[-2], None)
            elif verb == "PATCH" and path == f"repos/{SLUG}":
                self.repo.update(payload)
            else:
                raise AssertionError(f"unexpected write {args}")
            return 0, "{}", ""
        path = args[0]
        if path == f"repos/{SLUG}":
            return 0, json.dumps(self.repo), ""
        if path == f"repos/{SLUG}/rulesets":
            return 0, json.dumps([{"id": r["id"], "name": r["name"]} for r in self.rulesets.values()]), ""
        if path.startswith(f"repos/{SLUG}/rulesets/"):
            return 0, json.dumps(self.rulesets[int(path.split("/")[-1])]), ""
        if path.startswith(f"repos/{SLUG}/rules/branches/"):
            branch = path.split("/")[-1]
            rules = [{**rule, "ruleset_id": r["id"]} for r in self.rulesets.values()
                     if f"refs/heads/{branch}" in r["conditions"]["ref_name"]["include"]
                     for rule in r["rules"]]
            return 0, json.dumps(rules), ""
        if path.endswith("/protection"):
            branch = path.split("/")[-2]
            if branch in self.classic:
                return 0, json.dumps(self.classic[branch]), ""
            return 1, "", "gh: Branch not protected (HTTP 404)"
        if "/check-runs" in path:
            return 0, json.dumps(self.ran), ""
        if "/branches/" in path:
            branch = path.split("/")[-1]
            return (0, "{}", "") if branch in self.branches else (1, "", "Not Found (HTTP 404)")
        raise AssertionError(f"unexpected gh call {args}")

    def writes(self, verb=None):
        return [call for call in self.calls
                if call[0][0] == "-X" and (verb is None or call[0][1] == verb)]

    def ruleset_for(self, branch):
        return next(r for r in self.rulesets.values() if r["name"] == wp.ruleset_name(branch))


class ProtectCase(RepoCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wp.main(["--project", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def settings(self):
        return wp.load(str(self.root))

    def gh(self, fake):
        patcher = mock.patch.object(wp, "gh_api", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake


class PolicyTest(ProtectCase):
    def test_roles_split_merge_methods_and_linear_history(self):
        settings = self.settings()
        main = wp.policy_for(settings, "main", JOBS)
        dev = wp.policy_for(settings, "dev", JOBS)
        self.assertEqual(main["mergeMethods"], ["merge"])
        self.assertFalse(main["linearHistory"])
        self.assertEqual(dev["mergeMethods"], ["rebase", "squash"])
        self.assertTrue(dev["linearHistory"])
        for policy in (main, dev):
            self.assertTrue(policy["requirePR"])
            self.assertEqual(policy["approvals"], 0)
            self.assertTrue(policy["enforceAdmins"])
            self.assertEqual(policy["requiredChecks"], JOBS)

    def test_ruleset_body(self):
        body = wp.github_ruleset("main", wp.policy_for(self.settings(), "main", JOBS))
        self.assertEqual(body["name"], "workflows: main")
        self.assertEqual(body["conditions"]["ref_name"]["include"], ["refs/heads/main"])
        self.assertEqual(body["bypass_actors"], [])
        types = [rule["type"] for rule in body["rules"]]
        self.assertEqual(types, ["deletion", "non_fast_forward", "pull_request",
                                 "required_status_checks"])
        pull = body["rules"][2]["parameters"]
        self.assertEqual(pull["allowed_merge_methods"], ["merge"])
        self.assertEqual(pull["required_approving_review_count"], 0)

    def test_admin_bypass_when_not_enforced(self):
        self.config({"git": {"protection": {"default": {"enforceAdmins": False}}}})
        body = wp.github_ruleset("main", wp.policy_for(self.settings(), "main", JOBS))
        self.assertEqual(body["bypass_actors"][0]["actor_type"], "RepositoryRole")

    def test_branches_follow_configured_names(self):
        self.config({"git": {"releaseBranch": "master", "integrationBranch": "develop",
                             "protection": {"branches": {"develop": {"approvals": 1},
                                                         "staging": {}}}}})
        settings = self.settings()
        self.assertEqual(wp.protected_branches(settings), ["master", "develop", "staging"])
        self.assertEqual(wp.policy_for(settings, "develop", JOBS)["approvals"], 1)
        self.assertEqual(wp.policy_for(settings, "develop", JOBS)["mergeMethods"],
                         ["rebase", "squash"])
        self.assertEqual(wp.policy_for(settings, "master", JOBS)["mergeMethods"], ["merge"])
        self.assertEqual(wp.policy_for(settings, "staging", JOBS)["mergeMethods"],
                         ["merge", "rebase", "squash"])

    def test_trunk_based_branch_takes_feature_merges(self):
        self.config({"git": {"integrationBranch": "main"}})
        settings = self.settings()
        self.assertEqual(wp.protected_branches(settings), ["main"])
        self.assertEqual(wp.policy_for(settings, "main", JOBS)["mergeMethods"], ["rebase", "squash"])

    def test_explicit_required_checks(self):
        self.config({"git": {"protection": {"requiredChecks": ["lint"]}}})
        self.assertEqual(wp.policy_for(self.settings(), "dev", JOBS)["requiredChecks"], ["lint"])

    def test_current_roundtrip(self):
        for branch in ("main", "dev"):
            policy = wp.policy_for(self.settings(), branch, JOBS)
            current = wp.github_current(wp.github_ruleset(branch, policy))
            self.assertEqual(wp.policy_diff(current, policy), [], branch)

    def test_repo_methods_are_the_union(self):
        proposed = wp.github_repo_proposed(self.settings())
        self.assertTrue(proposed["allow_merge_commit"])
        self.assertTrue(proposed["allow_rebase_merge"])
        self.assertTrue(proposed["allow_squash_merge"])
        self.assertEqual(proposed["squash_merge_commit_message"], "PR_BODY")
        self.assertEqual(proposed["merge_commit_message"], "PR_BODY")


class ProtectCliTest(ProtectCase):
    def test_show_never_writes(self):
        fake = self.gh(FakeGh())
        code, out, _ = self.run_cli("protect")
        self.assertEqual(code, wp.OK)
        self.assertIn(f"== {SLUG} main", out)
        self.assertIn(f"== {SLUG} dev", out)
        self.assertIn("(no ruleset)", out)
        self.assertEqual(fake.writes(), [])

    def test_apply_needs_exactly_one_branch(self):
        fake = self.gh(FakeGh())
        code, _, err = self.run_cli("protect", "--apply")
        self.assertEqual(code, wp.ERROR)
        self.assertIn("one --branch", err)
        self.assertEqual(fake.writes(), [])

    def test_apply_creates_one_ruleset_and_reads_back(self):
        fake = self.gh(FakeGh())
        code, out, err = self.run_cli("protect", "--apply", "--branch", "dev")
        self.assertEqual(code, wp.OK, out + err)
        self.assertEqual(len(fake.writes("POST")), 1)
        self.assertEqual(len(fake.rulesets), 1)
        self.assertIn("required_linear_history",
                      [rule["type"] for rule in fake.ruleset_for("dev")["rules"]])
        _, out, _ = self.run_cli("protect", "--branch", "dev")
        self.assertIn("(already matches the policy)", out)

    def test_apply_updates_existing_ruleset(self):
        settings = self.settings()
        stale = wp.github_ruleset("main", {**wp.policy_for(settings, "main", JOBS),
                                           "mergeMethods": ["squash"]})
        fake = self.gh(FakeGh(rulesets=[stale]))
        _, out, _ = self.run_cli("protect", "--branch", "main")
        self.assertIn('mergeMethods: ["squash"] -> ["merge"]', out)
        code, _, _ = self.run_cli("protect", "--apply", "--branch", "main")
        self.assertEqual(code, wp.OK)
        self.assertEqual(len(fake.writes("PUT")), 1)
        self.assertEqual(len(fake.rulesets), 1)

    def test_classic_protection_is_replaced(self):
        classic = {"required_linear_history": {"enabled": True}}
        fake = self.gh(FakeGh(classic={"main": classic}))
        _, out, _ = self.run_cli("protect", "--branch", "main")
        self.assertIn("classic branch protection: present -> removed", out)
        code, _, err = self.run_cli("protect", "--apply", "--branch", "main")
        self.assertEqual(code, wp.OK, err)
        verbs = [call[0][1] for call in fake.writes()]
        self.assertEqual(verbs, ["POST", "DELETE"])
        self.assertNotIn("main", fake.classic)

    def test_missing_branch_and_unreported_checks(self):
        self.config({"git": {"protection": {"requiredChecks": ["lint", "sanitizers"]}}})
        self.gh(FakeGh(branches=("main",), ran=["lint"]))
        _, out, _ = self.run_cli("protect")
        self.assertIn("branch dev not found", out)
        self.assertIn("never reported on main: sanitizers", out)

    def test_auto_checks_are_the_jobs_that_ran(self):
        fake = self.gh(FakeGh(ran=["lint", "test (msvc)"]))
        self.run_cli("protect", "--apply", "--branch", "main")
        rules = {rule["type"]: rule.get("parameters") for rule in fake.ruleset_for("main")["rules"]}
        self.assertEqual([c["context"] for c in rules["required_status_checks"]["required_status_checks"]],
                         ["lint", "test (msvc)"])

    def test_auto_checks_need_a_ci_run(self):
        fake = self.gh(FakeGh(ran=[]))
        code, out, _ = self.run_cli("protect", "--apply", "--branch", "main")
        self.assertEqual(code, wp.ERROR)
        self.assertIn("no CI checks have reported on main", out)
        self.assertEqual(fake.writes(), [])

    def test_no_ci_repo_uses_an_empty_list(self):
        self.config({"git": {"protection": {"requiredChecks": []}}})
        fake = self.gh(FakeGh(ran=[]))
        code, _, err = self.run_cli("protect", "--apply", "--branch", "main")
        self.assertEqual(code, wp.OK, err)
        self.assertNotIn("required_status_checks",
                         [rule["type"] for rule in fake.ruleset_for("main")["rules"]])

    def test_failed_write_is_an_error(self):
        self.gh(FakeGh(write_ok=False))
        code, _, err = self.run_cli("protect", "--apply", "--branch", "main")
        self.assertEqual(code, wp.ERROR)
        self.assertIn("HTTP 422", err)

    def test_unauthenticated_gh_prints_checklist(self):
        fake = self.gh(FakeGh(authed=False))
        code, out, err = self.run_cli("protect")
        self.assertEqual(code, wp.ERROR)
        self.assertIn("gh auth login", err)
        self.assertIn("allowed merge methods: merge\n", out)
        self.assertIn("linear history required: True", out)
        self.assertEqual(fake.writes(), [])

    def test_cpp_repo_protect_is_the_same_command(self):
        fake = self.gh(FakeGh())
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cr.main(["--project", str(self.root), "protect", "--branch", "main"])
        self.assertEqual(code, cr.OK, err.getvalue())
        self.assertIn(f"== {SLUG} main", out.getvalue())
        self.assertEqual(fake.writes(), [])


class RepoMergeSettingsTest(ProtectCase):
    def test_show_lists_repo_settings_and_writes_nothing(self):
        fake = self.gh(FakeGh())
        code, out, _ = self.run_cli("protect")
        self.assertEqual(code, wp.OK)
        self.assertIn(f"== {SLUG} (repo merge settings)", out)
        self.assertIn("allow_merge_commit: false -> true", out)
        self.assertIn('squash_merge_commit_message: "COMMIT_MESSAGES" -> "PR_BODY"', out)
        self.assertIn('merge_commit_message: "PR_TITLE" -> "PR_BODY"', out)
        self.assertEqual(fake.writes(), [])

    def test_branch_show_leaves_repo_settings_out(self):
        self.gh(FakeGh())
        _, out, _ = self.run_cli("protect", "--branch", "main")
        self.assertNotIn("repo merge settings", out)

    def test_apply_repo_writes_only_repo_settings(self):
        fake = self.gh(FakeGh())
        code, out, _ = self.run_cli("protect", "--apply", "--repo")
        self.assertEqual(code, wp.OK, out)
        self.assertEqual([call[0][1] for call in fake.writes()], ["PATCH"])
        _, out, _ = self.run_cli("protect", "--repo")
        self.assertIn("(already matches the policy)", out)

    def test_apply_repo_and_branch_together_is_an_error(self):
        fake = self.gh(FakeGh())
        code, _, err = self.run_cli("protect", "--apply", "--repo", "--branch", "main")
        self.assertEqual(code, wp.ERROR)
        self.assertIn("one target at a time", err)
        self.assertEqual(fake.calls[1:], [])

    def test_null_messages_leave_them_alone(self):
        self.config({"git": {"protection": {"squashMessage": None, "mergeMessage": None}}})
        proposed = wp.github_repo_proposed(self.settings())
        self.assertNotIn("squash_merge_commit_message", proposed)
        self.assertNotIn("merge_commit_message", proposed)

    def test_checklist_names_messages(self):
        self.gh(FakeGh(authed=False))
        _, out, _ = self.run_cli("protect")
        self.assertIn("squash merge's default message is the PR title and description", out)
        self.assertIn("merge commit's default message is the PR title and description", out)


class MethodsTest(ProtectCase):
    def test_squash_only_repo(self):
        self.gh(FakeGh())
        code, out, _ = self.run_cli("methods", "--base", "main")
        self.assertEqual(code, wp.OK)
        self.assertIn("allowed into main: squash", out)
        self.assertIn("commit messages concatenated", out)

    def test_rulesets_narrow_the_repo_switches(self):
        settings = self.settings()
        rulesets = [wp.github_ruleset(b, wp.policy_for(settings, b, JOBS)) for b in ("main", "dev")]
        repo = {**LIVE_REPO, **wp.github_repo_proposed(settings)}
        self.gh(FakeGh(rulesets=rulesets, repo=repo))
        _, out, _ = self.run_cli("methods", "--base", "main", "--json")
        main = json.loads(out)
        self.assertEqual(main["allowed"], ["merge"])
        self.assertEqual(main["squashMessage"], "pr")
        self.assertEqual(main["mergeMessage"], "pr")
        _, out, _ = self.run_cli("methods", "--base", "dev", "--json")
        self.assertEqual(json.loads(out)["allowed"], ["rebase", "squash"])

    def test_classic_linear_history_rules_out_merge(self):
        repo = {**LIVE_REPO, "allow_merge_commit": True}
        self.gh(FakeGh(repo=repo, classic={"main": {"required_linear_history": {"enabled": True}}}))
        _, out, _ = self.run_cli("methods", "--base", "main", "--json")
        self.assertEqual(json.loads(out)["allowed"], ["squash"])


class UnsupportedForgeProtectTest(ProtectCase):
    origin = "https://bitbucket.org/example/demo.git"

    def test_checklist_and_no_gh_calls(self):
        with mock.patch.object(wp, "gh_api", side_effect=AssertionError("no gh calls")):
            code, out, _ = self.run_cli("protect")
            self.assertEqual(code, wp.OK)
            self.assertIn("No forge adapter here", out)
            self.assertIn("- main:", out)
            self.assertIn("- dev:", out)
            code, out, _ = self.run_cli("methods", "--base", "main")
        self.assertEqual(code, wp.OK)
        self.assertIn("unknown: no adapter for bitbucket.org", out)


if __name__ == "__main__":
    unittest.main()

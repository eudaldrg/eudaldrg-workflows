#!/usr/bin/env python3
"""Show or apply a repo's branch protection, and report which merge methods a base branch accepts.

The policy (`git.protection`) is forge-neutral and follows the branch model in
references/branch-model.md: the integration branch takes squash or rebase merges and stays linear,
the release branch takes merge commits only. An adapter turns it into one forge's API calls. Only
GitHub has one; any other forge gets the policy printed as a checklist.

On GitHub the policy is written as one repository ruleset per branch, because only rulesets can
restrict the allowed merge methods per branch (the repo-wide `allow_*_merge` settings cannot tell
`main` from `dev`). A classic branch protection rule on the same branch is removed once its ruleset
is in place; both would otherwise apply, and the stricter one wins.

Every write goes through `protect --apply --branch B` (one branch) or `protect --apply --repo`
(the repo-wide merge settings), so a caller can show the diff and ask before each.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf_config  # noqa: E402

OK = 0
ERROR = 2

METHODS = ("merge", "rebase", "squash")
RULESET_PREFIX = "workflows: "
ADMIN_ROLE_ID = 5  # GitHub's built-in "Repository admin" role, for bypass_actors.


@dataclass
class Settings:
    root: Path
    git: dict

    @property
    def integration(self) -> str:
        return str(self.git["integrationBranch"])

    @property
    def release(self) -> str:
        return str(self.git["releaseBranch"])

    @property
    def protection(self) -> dict:
        return self.git["protection"]


def load(project: str | None) -> Settings:
    merged, _, _ = wf_config.load_all(project)
    git = merged.get("git") if isinstance(merged.get("git"), dict) else {}
    return Settings(root=wf_config.project_root(project), git=git)


# --------------------------------------------------------------------------- forge


def origin_url(root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def parse_remote(url: str | None) -> tuple[str | None, str | None]:
    """(host, owner/repo) from an ssh or https remote URL."""
    if not url:
        return None, None
    match = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^:/]+)(?::\d+)?[:/](.+?)(?:\.git)?/?$", url)
    if not match:
        return None, None
    return match.group(1).lower(), match.group(2)


def detect_forge(git: dict, root: Path, url: str | None = None) -> dict:
    """{'forge': 'github'|'none'|'unsupported', 'host', 'slug', 'reason'}."""
    configured = git.get("forge", "auto")
    host, slug = parse_remote(url if url is not None else origin_url(root))
    if configured == "none":
        return {"forge": "none", "host": host, "slug": slug, "reason": "git.forge is none"}
    if configured == "github" or (host and (host == "github.com" or host.endswith(".github.com"))):
        return {"forge": "github", "host": host, "slug": slug, "reason": "origin is GitHub"
                if configured == "auto" else "git.forge is github"}
    if host:
        return {"forge": "unsupported", "host": host, "slug": slug,
                "reason": f"no adapter for {host}; only GitHub has one"}
    return {"forge": "none", "host": None, "slug": None, "reason": "no origin remote"}


def gh_api(args: list[str], payload: dict | None = None) -> tuple[int, str, str]:
    """Run `gh api`. Tests replace this function."""
    cmd = ["gh", "api", *args]
    try:
        out = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None,
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return out.returncode, out.stdout, out.stderr


def not_found(err: str) -> bool:
    return "404" in err or "not found" in err.lower() or "not protected" in err.lower()


# --------------------------------------------------------------------------- policy


def role(settings: Settings, branch: str) -> str | None:
    """A branch that is both (trunk-based: features merge straight into it) is the integration role."""
    if branch == settings.integration:
        return "integration"
    if branch == settings.release:
        return "release"
    return None


def policy_for(settings: Settings, branch: str, ran: list[str] | None = None) -> dict:
    """default <- the branch's role (release / integration) <- branches.<name>.

    `requiredChecks: "auto"` means the CI checks that actually reported on the branch (`ran`):
    the repo owns its CI file, so its job names are only known from a run."""
    protection = settings.protection
    branch_role = role(settings, branch)
    policy = {**protection["default"],
              **((protection.get(branch_role) or {}) if branch_role else {}),
              **(protection["branches"].get(branch) or {})}
    policy["mergeMethods"] = sorted(policy.get("mergeMethods") or METHODS)
    required = protection["requiredChecks"]
    policy["requiredChecks"] = sorted(ran or []) if required == "auto" else sorted(required)
    return policy


def protected_branches(settings: Settings) -> list[str]:
    """The release and integration branches, plus any other branch with its own policy entry."""
    branches = [settings.release, settings.integration, *settings.protection["branches"]]
    return list(dict.fromkeys(branches))


def comparable(policy: dict) -> dict:
    """Merge methods are only enforceable through the PR rule; without one they are not compared."""
    return policy if policy["requirePR"] else {k: v for k, v in policy.items() if k != "mergeMethods"}


def policy_diff(current: dict | None, proposed: dict) -> list[str]:
    proposed = comparable(proposed)
    if current is None:
        return [f"{key}: (no ruleset) -> {json.dumps(value)}" for key, value in proposed.items()]
    return [f"{key}: {json.dumps(current.get(key))} -> {json.dumps(value)}"
            for key, value in proposed.items() if current.get(key) != value]


# --------------------------------------------------------------------------- GitHub rulesets


def ruleset_name(branch: str) -> str:
    return f"{RULESET_PREFIX}{branch}"


def github_ruleset(branch: str, policy: dict) -> dict:
    """POST/PUT /repos/{o}/{r}/rulesets body for one branch."""
    rules: list[dict] = []
    if not policy["allowDeletion"]:
        rules.append({"type": "deletion"})
    if not policy["allowForcePush"]:
        rules.append({"type": "non_fast_forward"})
    if policy["linearHistory"]:
        rules.append({"type": "required_linear_history"})
    if policy["requirePR"]:
        rules.append({"type": "pull_request", "parameters": {
            "required_approving_review_count": int(policy["approvals"]),
            "dismiss_stale_reviews_on_push": False,
            "require_code_owner_review": False,
            "require_last_push_approval": False,
            "required_review_thread_resolution": False,
            "allowed_merge_methods": list(policy["mergeMethods"]),
        }})
    if policy["requiredChecks"]:
        rules.append({"type": "required_status_checks", "parameters": {
            "strict_required_status_checks_policy": False,
            "required_status_checks": [{"context": name} for name in policy["requiredChecks"]],
        }})
    bypass = [] if policy["enforceAdmins"] else [
        {"actor_id": ADMIN_ROLE_ID, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
    return {
        "name": ruleset_name(branch),
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": bypass,
        "conditions": {"ref_name": {"include": [f"refs/heads/{branch}"], "exclude": []}},
        "rules": rules,
    }


def github_current(ruleset: dict | None) -> dict | None:
    """GET .../rulesets/{id} response -> the policy shape, or None when there is no ruleset."""
    if ruleset is None:
        return None
    rules = {rule["type"]: rule.get("parameters") or {} for rule in ruleset.get("rules") or []}
    pull = rules.get("pull_request")
    checks = rules.get("required_status_checks") or {}
    return {
        "requirePR": pull is not None,
        "approvals": int((pull or {}).get("required_approving_review_count", 0)),
        "allowForcePush": "non_fast_forward" not in rules,
        "allowDeletion": "deletion" not in rules,
        "linearHistory": "required_linear_history" in rules,
        "enforceAdmins": not ruleset.get("bypass_actors"),
        "mergeMethods": sorted((pull or {}).get("allowed_merge_methods") or METHODS),
        "requiredChecks": sorted(item["context"] for item in checks.get("required_status_checks") or []),
    }


def github_find_ruleset(slug: str, branch: str) -> tuple[dict | None, str | None]:
    """(ruleset, error). The ruleset this tool owns for `branch`, found by name."""
    code, out, err = gh_api([f"repos/{slug}/rulesets", "--paginate"])
    if code != 0:
        return None, err.strip()
    for item in json.loads(out or "[]"):
        if item.get("name") == ruleset_name(branch):
            code, out, err = gh_api([f"repos/{slug}/rulesets/{item['id']}"])
            if code != 0:
                return None, err.strip()
            return json.loads(out), None
    return None, None


def github_classic(slug: str, branch: str) -> tuple[bool | None, str | None]:
    """(has a classic protection rule, error)."""
    code, _, err = gh_api([f"repos/{slug}/branches/{branch}/protection"])
    if code == 0:
        return True, None
    if not_found(err):
        return False, None
    return None, err.strip()


def github_branch_state(slug: str, branch: str, settings: Settings) -> dict:
    state: dict = {"branch": branch}
    code, _, err = gh_api([f"repos/{slug}/branches/{branch}"])
    if code != 0:
        state["error"] = (f"branch {branch} not found on {slug}; push it first"
                          if not_found(err) else err.strip())
        return state
    code, out, _ = gh_api([f"repos/{slug}/commits/{branch}/check-runs", "--jq",
                           '[.check_runs[] | select(.app.slug == "github-actions") | .name]'])
    ran = sorted(set(json.loads(out))) if code == 0 and out.strip() else []
    state["proposed"] = policy_for(settings, branch, ran)
    if settings.protection["requiredChecks"] == "auto" and not ran:
        state["error"] = (f"no CI checks have reported on {branch}; run CI on it first, so the "
                          "required checks are the job names the repo's CI really uses. Or set "
                          "git.protection.requiredChecks to [] for a repo with no CI.")
        return state
    ruleset, error = github_find_ruleset(slug, branch)
    if error:
        state["error"] = error
        return state
    state["rulesetId"] = ruleset["id"] if ruleset else None
    state["current"] = github_current(ruleset)
    classic, error = github_classic(slug, branch)
    if error:
        state["error"] = error
        return state
    state["classic"] = classic
    state["diff"] = policy_diff(state["current"], state["proposed"])
    if classic:
        state["diff"].append("classic branch protection: present -> removed (the ruleset replaces it)")
    # An explicitly required check that never reported on this branch blocks every PR into it.
    state["neverRan"] = [name for name in state["proposed"]["requiredChecks"] if name not in ran]
    return state


def github_apply_branch(slug: str, state: dict) -> int:
    branch = state["branch"]
    body = github_ruleset(branch, state["proposed"])
    if state["rulesetId"] is None:
        code, _, err = gh_api(["-X", "POST", f"repos/{slug}/rulesets", "--input", "-"], body)
    else:
        code, _, err = gh_api(["-X", "PUT", f"repos/{slug}/rulesets/{state['rulesetId']}",
                               "--input", "-"], body)
    if code != 0:
        print(f"error: ruleset write failed: {err.strip()}", file=sys.stderr)
        return ERROR
    ruleset, error = github_find_ruleset(slug, branch)
    after = policy_diff(github_current(ruleset), state["proposed"]) if not error else [error]
    if after:
        print("error: ruleset written but read back differently:", file=sys.stderr)
        for line in after:
            print(f"   {line}", file=sys.stderr)
        return ERROR
    if state["classic"]:
        code, _, err = gh_api(["-X", "DELETE", f"repos/{slug}/branches/{branch}/protection"])
        if code != 0 and not not_found(err):
            print(f"error: ruleset applied, but removing the classic protection failed: "
                  f"{err.strip()}", file=sys.stderr)
            return ERROR
    print(f"applied protection to {branch}")
    return OK


# --------------------------------------------------------------------------- repo merge settings
# Repo-wide, so they gate every branch: a method must be enabled here before any ruleset can allow
# it. They are the union of the protected branches' methods. `squashMessage: "pr"` makes a squash
# default to the PR title and body, so a branch's commit messages and their trailers (Plan-Id,
# Task-Id) never reach the base; `mergeMessage: "pr"` does the same for a merge commit, so a release
# merge reads as the release PR. "commits" / "default" are the forge's defaults; null leaves it.

GITHUB_SQUASH = {
    "pr": {"squash_merge_commit_title": "PR_TITLE", "squash_merge_commit_message": "PR_BODY"},
    "commits": {"squash_merge_commit_title": "COMMIT_OR_PR_TITLE",
                "squash_merge_commit_message": "COMMIT_MESSAGES"},
}
GITHUB_MERGE = {
    "pr": {"merge_commit_title": "PR_TITLE", "merge_commit_message": "PR_BODY"},
    "default": {"merge_commit_title": "MERGE_MESSAGE", "merge_commit_message": "PR_TITLE"},
}
GITHUB_ALLOW = {"merge": "allow_merge_commit", "rebase": "allow_rebase_merge",
                "squash": "allow_squash_merge"}


def repo_methods(settings: Settings) -> list[str]:
    used: set[str] = set()
    for branch in protected_branches(settings):
        used.update(policy_for(settings, branch)["mergeMethods"])
    return sorted(used)


def github_repo_proposed(settings: Settings) -> dict:
    methods = repo_methods(settings)
    proposed = {GITHUB_ALLOW[m]: m in methods for m in METHODS}
    squash = settings.protection.get("squashMessage")
    merge = settings.protection.get("mergeMessage")
    if squash:
        proposed.update(GITHUB_SQUASH[squash])
    if merge:
        proposed.update(GITHUB_MERGE[merge])
    return proposed


def github_repo_state(slug: str, settings: Settings) -> dict:
    """The repo's merge settings against the policy."""
    state: dict = {"branch": "(repo merge settings)"}
    code, out, err = gh_api([f"repos/{slug}"])
    if code != 0:
        state["error"] = err.strip()
        return state
    live = json.loads(out)
    state["proposed"] = github_repo_proposed(settings)
    state["diff"] = [f"{key}: {json.dumps(live.get(key))} -> {json.dumps(value)}"
                     for key, value in state["proposed"].items() if live.get(key) != value]
    return state


def github_apply_repo(slug: str, settings: Settings) -> int:
    state = github_repo_state(slug, settings)
    print(f"== {slug} {state['branch']}")
    if "error" in state:
        print(f"   error: {state['error']}")
        return ERROR
    for line in state["diff"] or ["(already matches the policy)"]:
        print(f"   {line}")
    if not state["diff"]:
        return OK
    code, _, err = gh_api(["-X", "PATCH", f"repos/{slug}", "--input", "-"], state["proposed"])
    if code != 0:
        print(f"error: repo settings write failed: {err.strip()}", file=sys.stderr)
        return ERROR
    after = github_repo_state(slug, settings)
    if after.get("diff") or "error" in after:
        print("error: repo settings written but read back differently:", file=sys.stderr)
        for line in after.get("diff") or [after.get("error", "")]:
            print(f"   {line}", file=sys.stderr)
        return ERROR
    print("applied repo merge settings")
    return OK


def checklist(settings: Settings, forge: dict) -> str:
    lines = [f"No forge adapter here ({forge['reason']}). Set these by hand in the forge's settings:"]
    for branch in protected_branches(settings):
        policy = policy_for(settings, branch)
        lines.append(f"- {branch}:")
        lines.append(f"    merge only through a pull/merge request: {policy['requirePR']}")
        lines.append(f"    allowed merge methods: {', '.join(policy['mergeMethods'])}")
        lines.append(f"    required approvals: {policy['approvals']}")
        lines.append(f"    required CI checks: {', '.join(policy['requiredChecks']) or 'every CI job, by the names it reports'}")
        lines.append(f"    force push allowed: {policy['allowForcePush']}")
        lines.append(f"    deletion allowed: {policy['allowDeletion']}")
        lines.append(f"    linear history required: {policy['linearHistory']}")
        lines.append(f"    rules apply to admins too: {policy['enforceAdmins']}")
    squash = settings.protection.get("squashMessage")
    if squash == "pr":
        lines.append("- repo: a squash merge's default message is the PR title and description")
    elif squash == "commits":
        lines.append("- repo: a squash merge's default message is the branch's commit messages")
    if settings.protection.get("mergeMessage") == "pr":
        lines.append("- repo: a merge commit's default message is the PR title and description")
    return "\n".join(lines)


# --------------------------------------------------------------------------- methods


def github_methods(slug: str, base: str) -> dict:
    """What the forge will actually offer for a PR into `base`: the repo-wide switches, narrowed by
    every ruleset that applies to the branch (ours or not) and any classic linear-history rule."""
    code, out, err = gh_api([f"repos/{slug}"])
    if code != 0:
        return {"error": err.strip()}
    repo = json.loads(out)
    allowed = {m for m in METHODS if repo.get(GITHUB_ALLOW[m])}
    sources = ["repo merge settings"]
    code, out, err = gh_api([f"repos/{slug}/rules/branches/{base}"])
    if code == 0:
        for rule in json.loads(out or "[]"):
            params = rule.get("parameters") or {}
            if rule.get("type") == "pull_request" and params.get("allowed_merge_methods"):
                allowed &= set(params["allowed_merge_methods"])
                sources.append(f"ruleset {rule.get('ruleset_id')}: pull_request")
            if rule.get("type") == "required_linear_history":
                allowed.discard("merge")
                sources.append(f"ruleset {rule.get('ruleset_id')}: required_linear_history")
    code, out, _ = gh_api([f"repos/{slug}/branches/{base}/protection"])
    if code == 0 and (json.loads(out).get("required_linear_history") or {}).get("enabled"):
        allowed.discard("merge")
        sources.append("classic protection: required_linear_history")
    squash = "pr" if repo.get("squash_merge_commit_message") == "PR_BODY" else (
        "commits" if repo.get("squash_merge_commit_message") == "COMMIT_MESSAGES" else
        repo.get("squash_merge_commit_message"))
    return {"base": base, "allowed": sorted(allowed), "squashMessage": squash,
            "mergeMessage": "pr" if repo.get("merge_commit_message") == "PR_BODY" else "default",
            "sources": sources}


def describe_methods(info: dict) -> str:
    if "error" in info:
        return f"unknown: {info['error']}"
    lines = [f"allowed into {info['base']}: {', '.join(info['allowed']) or 'none'}"]
    lines.append({"pr": "squash message: PR title and description",
                  "commits": "squash message: the branch's commit messages concatenated "
                             "(trailers and intermediate states included)"}
                 .get(info["squashMessage"], f"squash message: {info['squashMessage']}"))
    lines.append("merge commit message: PR title and description" if info["mergeMessage"] == "pr"
                 else "merge commit message: forge default (Merge pull request #n ...)")
    lines.append(f"from: {'; '.join(info['sources'])}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- commands


def github_ready(forge: dict, settings: Settings) -> bool:
    code, _, err = gh_api(["user", "--jq", ".login"])
    if code == 0:
        return True
    print(f"gh is not usable ({err.strip() or 'not installed'}); run `gh auth login`, or set "
          "protection by hand:", file=sys.stderr)
    print(checklist(settings, {**forge, "reason": "gh unavailable"}))
    return False


def cmd_protect(args: argparse.Namespace) -> int:
    settings = load(args.project)
    forge = detect_forge(settings.git, settings.root)
    if forge["forge"] != "github":
        print(checklist(settings, forge))
        return OK
    if not github_ready(forge, settings):
        return ERROR
    slug = forge["slug"]

    if args.apply and args.repo:
        if args.branch:
            print("error: --apply writes one target at a time; pass --repo or one --branch",
                  file=sys.stderr)
            return ERROR
        return github_apply_repo(slug, settings)

    branches = args.branch or protected_branches(settings)
    if args.apply and len(branches) != 1:
        print("error: --apply writes one branch at a time; pass exactly one --branch", file=sys.stderr)
        return ERROR

    states = [github_branch_state(slug, branch, settings) for branch in branches]
    if not args.apply and (args.repo or not args.branch):
        states.append(github_repo_state(slug, settings))
    if args.json and not args.apply:
        print(json.dumps({"forge": forge, "branches": states}, indent=2))
        return OK
    for state in states:
        print(f"== {slug} {state['branch']}")
        if "error" in state:
            print(f"   error: {state['error']}")
            continue
        for line in state["diff"] or ["(already matches the policy)"]:
            print(f"   {line}")
        if state.get("neverRan"):
            print(f"   warning: required checks never reported on {state['branch']}: "
                  f"{', '.join(state['neverRan'])}. Every PR into it would wait on them; run CI "
                  "on it first.")
    if not args.apply:
        return OK

    state = states[0]
    if "error" in state:
        return ERROR
    if not state["diff"]:
        return OK
    return github_apply_branch(slug, state)


def cmd_methods(args: argparse.Namespace) -> int:
    settings = load(args.project)
    forge = detect_forge(settings.git, settings.root)
    if forge["forge"] != "github":
        info = {"base": args.base, "error": forge["reason"]}
    else:
        info = {"base": args.base, **github_methods(forge["slug"], args.base)}
    print(json.dumps(info, indent=2) if args.json else describe_methods(info))
    return OK


def add_protect_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--branch", action="append", help="branch to show or apply; repeatable")
    parser.add_argument("--repo", action="store_true",
                        help="show or apply the repo-wide merge settings")
    parser.add_argument("--apply", action="store_true",
                        help="write one --branch's protection, or with --repo the repo settings")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=cmd_protect)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", help="repo root (default: the current git repo)")
    sub = parser.add_subparsers(dest="command", required=True)
    add_protect_arguments(sub.add_parser(
        "protect", help="show (default) or apply branch protection and repo merge settings"))
    methods = sub.add_parser("methods", help="the merge methods the forge offers for a PR into a base")
    methods.add_argument("--base", required=True)
    methods.add_argument("--json", action="store_true")
    methods.set_defaults(func=cmd_methods)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except wf_config.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return ERROR


if __name__ == "__main__":
    sys.exit(main())

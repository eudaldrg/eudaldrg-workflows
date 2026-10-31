import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugins/core/scripts"))
import wf_cpp_repo as cr  # noqa: E402

GITHUB = "git@github.com:example/demo.git"


class RepoCase(unittest.TestCase):
    """A scratch git repo with an isolated home layer and a chosen origin."""

    origin = GITHUB

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "demo-repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        if self.origin:
            subprocess.run(["git", "-C", str(self.root), "remote", "add", "origin", self.origin],
                           check=True)
        home = Path(self.tmp.name) / "home.json"
        home.write_text("{}", encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {"WF_HOME_CONFIG": str(home),
                                               "WF_PLUGIN_ROOT": str(REPO / "plugins/core")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, data):
        path = self.root / ".claude" / "workflows.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cr.main(["--project", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def settings(self):
        return cr.load(str(self.root))


class ForgeTest(unittest.TestCase):
    def test_parse_remote_forms(self):
        self.assertEqual(cr.parse_remote("git@github.com:a/b.git"), ("github.com", "a/b"))
        self.assertEqual(cr.parse_remote("https://github.com/a/b"), ("github.com", "a/b"))
        self.assertEqual(cr.parse_remote("ssh://git@gitlab.example.org:2222/g/s/p.git"),
                         ("gitlab.example.org", "g/s/p"))
        self.assertEqual(cr.parse_remote(None), (None, None))

    def test_detect(self):
        settings = mock.Mock(git={"forge": "auto"}, root=Path("."))
        self.assertEqual(cr.detect_forge(settings, GITHUB)["forge"], "github")
        self.assertEqual(cr.detect_forge(settings, "git@gitlab.com:a/b.git")["forge"], "unsupported")
        self.assertEqual(cr.detect_forge(settings, "")["forge"], "none")
        settings.git = {"forge": "none"}
        self.assertEqual(cr.detect_forge(settings, GITHUB)["forge"], "none")

    def test_msvc_version(self):
        self.assertEqual(cr.msvc_version("17.8"), 1938)
        self.assertEqual(cr.msvc_version("17.10"), 1940)
        self.assertEqual(cr.msvc_version("16.11"), 1931)


class ScaffoldTest(RepoCase):
    def test_dry_run_writes_nothing(self):
        code, out, _ = self.run_cli("scaffold")
        self.assertEqual(code, cr.OK)
        self.assertIn("write   cmake/ProjectSettings.cmake", out)
        self.assertFalse((self.root / "CMakeLists.txt").exists())

    def test_apply_renders_every_marker(self):
        self.assertEqual(self.run_cli("scaffold", "--apply")[0], cr.OK)
        for path in self.root.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"(?<!\$)\{\{", str(path))
        cmake = (self.root / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("project(demo_repo LANGUAGES CXX)", cmake)
        settings = (self.root / "cmake/ProjectSettings.cmake").read_text(encoding="utf-8")
        self.assertIn("set(PROJECT_MSVC_FLOOR_VERSION 1938)", settings)
        self.assertIn('option(ENABLE_TEST_MEMORY_CAP "Run tests under a memory cap" OFF)', settings)

    def test_never_overwrites(self):
        (self.root / "CMakeLists.txt").write_text("mine\n", encoding="utf-8")
        code, out, _ = self.run_cli("scaffold", "--apply")
        self.assertEqual(code, cr.OK)
        self.assertIn("keep    CMakeLists.txt", out)
        self.assertEqual((self.root / "CMakeLists.txt").read_text(encoding="utf-8"), "mine\n")

    def test_agents_md_section_appended_once(self):
        (self.root / "AGENTS.md").write_text("# demo\n\nExisting rules.\n", encoding="utf-8")
        self.run_cli("scaffold", "--apply")
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# demo\n\nExisting rules.\n\n## Lint"))
        self.assertIn("Public history is for any reader", text)
        self.run_cli("scaffold", "--apply")
        self.assertEqual((self.root / "AGENTS.md").read_text(encoding="utf-8"), text)

    def test_project_config_gets_missing_keys_only(self):
        self.config({"cpp": {"enabled": True}, "implement": {"checkTimeoutSeconds": 60}})
        self.run_cli("scaffold", "--apply")
        data = json.loads((self.root / ".claude/workflows.json").read_text(encoding="utf-8"))
        self.assertEqual(data["implement"], {"checkTimeoutSeconds": 60})
        self.assertEqual(data["git"], {"protectedBranches+": ["dev"]})

    def test_memory_cap_toggle(self):
        self.config({"cpp": {"repo": {"checks": {"memoryCap": True}}}})
        self.run_cli("scaffold", "--apply")
        settings = (self.root / "cmake/ProjectSettings.cmake").read_text(encoding="utf-8")
        self.assertIn('"Run tests under a memory cap" ON)', settings)


class GenerateTest(RepoCase):
    def test_precommit_defaults(self):
        body = cr.precommit_body(self.settings())
        self.assertIn("default_stages: [pre-commit]", body)
        self.assertIn("rev: v21.1.8", body)
        self.assertIn("clang-tidy==21.1.6", body)
        self.assertIn("id: cppcheck", body)
        self.assertIn("run_sanitizers.py --variant asan-ubsan\n", body)
        self.assertNotIn("tsan", body)
        self.assertFalse(body.startswith("#"))

    def test_precommit_toggles(self):
        self.config({"cpp": {"repo": {"checks": {"cppcheck": False,
                                                 "sanitizers": {"tsan": True}}}}})
        body = cr.precommit_body(self.settings())
        self.assertNotIn("id: cppcheck", body)
        self.assertIn("--variant asan-ubsan --variant tsan", body)
        self.config({"cpp": {"repo": {"checks": {"sanitizers": {"asanUbsan": False}}}}})
        self.assertNotIn("sanitizers", cr.precommit_body(self.settings()).split("repos:")[1])

    def test_ci_matrix_and_jobs(self):
        settings = self.settings()
        body = cr.github_ci_body(settings)
        self.assertIn("branches: [main, dev]", body)
        self.assertIn("libstdc++-14-dev", body)
        self.assertIn("ilammy/msvc-dev-cmd@v1", body)
        self.assertIn("apt-get install -y cppcheck", body)
        self.assertEqual(cr.ci_job_names(settings),
                         ["lint", "test (gcc-14)", "test (clang-18)", "test (msvc)", "sanitizers"])

    def test_ci_extras(self):
        self.config({"cpp": {"repo": {"ci": {
            "aptPackages": ["libx11-dev", "xvfb"], "pipPackages": ["jinja2"],
            "env": {"LIBGL_ALWAYS_SOFTWARE": 1}, "testWrapper": "xvfb-run -a"}}}})
        body = cr.github_ci_body(self.settings())
        self.assertIn("apt-get install -y cppcheck libx11-dev xvfb", body)       # lint
        self.assertIn("run: sudo apt-get install -y libx11-dev xvfb", body)     # test, Linux only
        self.assertEqual(body.count("pip install ninja pre-commit jinja2"), 2)  # lint, sanitizers
        self.assertIn("pip install ninja jinja2", body)                         # test, all OSes
        self.assertEqual(body.count('LIBGL_ALWAYS_SOFTWARE: "1"'), 3)
        self.assertIn("run: xvfb-run -a ctest --preset debug", body)
        self.assertIn("if: runner.os != 'Linux'\n        run: ctest --preset debug", body)
        self.assertIn("run: xvfb-run -a pre-commit run --all-files --hook-stage pre-push", body)
        self.assertNotIn("xvfb-run -a cmake", body)
        try:
            import yaml  # noqa: PLC0415  (optional; the repo is stdlib-only)
        except ImportError:
            return
        self.assertIn("jobs", yaml.safe_load(body))

    def test_ci_extras_empty_changes_nothing(self):
        body = cr.github_ci_body(self.settings())
        self.assertNotIn("Install packages", body)
        self.assertEqual(body.count("run: ctest --preset debug"), 1)

    def test_ci_rejects_below_floor(self):
        self.config({"cpp": {"repo": {"ci": {"matrix": [
            {"os": "ubuntu-24.04", "compiler": "gcc", "version": "13"}]}}}})
        code, _, err = self.run_cli("generate")
        self.assertEqual(code, cr.ERROR)
        self.assertIn("below the floor", err)

    def test_ci_needs_a_linux_cell(self):
        self.config({"cpp": {"repo": {"ci": {"matrix": [{"os": "windows-2022", "compiler": "msvc"}]}}}})
        self.assertEqual(self.run_cli("generate")[0], cr.ERROR)

    def test_generate_is_idempotent_and_check_clean(self):
        self.assertEqual(self.run_cli("generate", "--apply")[0], cr.OK)
        self.assertTrue((self.root / ".github/workflows/ci.yml").exists())
        code, out, _ = self.run_cli("generate", "--apply")
        self.assertIn("unchanged .pre-commit-config.yaml", out)
        self.assertEqual(self.run_cli("check")[0], cr.OK)

    def test_drift_kinds(self):
        self.run_cli("generate", "--apply")
        path = self.root / cr.PRECOMMIT
        path.write_text(path.read_text(encoding="utf-8") + "# local tweak\n", encoding="utf-8")
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, cr.DRIFT)
        self.assertIn("hand-edited since generation", out)
        code, _, err = self.run_cli("generate", "--apply")
        self.assertEqual(code, cr.DRIFT)
        self.assertIn("refusing", err)
        self.assertIn("# local tweak", path.read_text(encoding="utf-8"))

        self.run_cli("generate", "--apply", "--force")
        self.config({"cpp": {"repo": {"checks": {"cppcheck": False}}}})
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, cr.DRIFT)
        self.assertIn("config changed, never regenerated", out)

    def test_hand_written_file_needs_force(self):
        path = self.root / cr.PRECOMMIT
        path.write_text("repos: []\n", encoding="utf-8")
        code, _, err = self.run_cli("generate", "--apply")
        self.assertEqual(code, cr.DRIFT)
        self.assertIn("not generated", err)
        self.assertEqual(path.read_text(encoding="utf-8"), "repos: []\n")
        self.assertEqual(self.run_cli("generate", "--apply", "--force")[0], cr.OK)
        self.assertEqual(self.run_cli("check")[0], cr.OK)

    def test_template_version_drift(self):
        self.run_cli("generate", "--apply")
        path = self.root / cr.PRECOMMIT
        version = self.settings().template_version
        text = path.read_text(encoding="utf-8").replace(f"cpp-repo/{version}", "cpp-repo/0")
        path.write_text(text, encoding="utf-8")
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, cr.DRIFT)
        self.assertIn("template moved on", out)


class NonGithubTest(RepoCase):
    origin = "git@gitlab.com:example/demo.git"

    def test_no_ci_file_for_unsupported_forge(self):
        code, out, _ = self.run_cli("generate", "--apply")
        self.assertEqual(code, cr.OK)
        self.assertIn("forge: unsupported", out)
        self.assertTrue((self.root / cr.PRECOMMIT).exists())
        self.assertFalse((self.root / ".github").exists())


if __name__ == "__main__":
    unittest.main()

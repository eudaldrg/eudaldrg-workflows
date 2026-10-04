import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/core/scripts"))
import wf_statusline as sl  # noqa: E402

NOW = 1_000_000.0
OPUS55 = ("claude-opus-5-5", "Opus 5.5")


def seg(cache, tokens=358_000, model=OPUS55):
    return sl.ANSI_RE.sub("", sl.cache_segment(cache, 300, NOW, tokens, *model))


class CacheSegmentTest(unittest.TestCase):
    def test_warm_shows_remaining_and_read_cost(self):
        cache = {"caching_observed": True, "warm": True, "expires_at": NOW + 42 * 60, "ttl": "1h"}
        self.assertEqual(seg(cache, 358_000), "cache 42m/1h ($0.07r)")

    def test_cold_shows_write_cost_for_ttl(self):
        cache = {"caching_observed": True, "warm": False, "expires_at": NOW - 5, "ttl": "1h"}
        self.assertEqual(seg(cache), "cache cold ($2.86w)")
        cache["ttl"] = "5m"
        self.assertEqual(seg(cache), "cache cold ($1.79w)")

    def test_none_when_missing_or_unobserved(self):
        self.assertEqual(seg(None), "cache none ($2.86w)")
        self.assertEqual(seg({"caching_observed": False, "warm": True}), "cache none ($2.86w)")

    def test_none_and_cold_are_red_warm_is_not(self):
        self.assertIn(sl.RED, sl.cache_segment(None, 300, NOW, 1000, *OPUS55))
        warm = {"caching_observed": True, "warm": True, "expires_at": NOW + 3000, "ttl": "1h"}
        self.assertNotIn(sl.RED, sl.cache_segment(warm, 300, NOW, 1000, *OPUS55))

    def test_unknown_model_keeps_state_drops_amount(self):
        self.assertEqual(seg(None, model=("claude-fable-5", "Fable 5")), "cache none")
        self.assertEqual(seg(None, model=("", "")), "cache none")

    def test_no_context_drops_amount(self):
        self.assertEqual(seg(None, tokens=None), "cache none")

    def test_model_prices(self):
        self.assertEqual(sl.model_price("claude-fable-5-1", "Fable 5.1"), (10.0, 0.025))
        self.assertEqual(sl.model_price("claude-opus-5-5", "Opus 5.5"), (4.0, 0.05))
        self.assertEqual(sl.model_price("claude-opus-5", "Opus 5"), (5.0, 0.1))
        self.assertEqual(sl.model_price("claude-sonnet-5-5", ""), (2.0, 0.1))
        self.assertEqual(sl.model_price("claude-haiku-4-5-20251001", ""), (1.0, 0.1))

    def test_build_line_always_has_cache(self):
        line = sl.build_line({"model": {"id": "claude-sonnet-5-5", "display_name": "Sonnet 5.5"},
                              "context_window": {"total_input_tokens": 100_000}}, {})
        self.assertIn("cache none ($0.40w)", sl.ANSI_RE.sub("", line))


SID = "c3bdb720-43a2-4d33-b283-347d32130803"


class CavemanSegmentTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / ".caveman-sessions").mkdir()

    def write_session(self, content, sid=SID):
        (self.dir / ".caveman-sessions" / f"{sid}.mode").write_bytes(content)

    def mode(self, sid=SID):
        return sl.caveman_mode(sid, self.dir)

    def test_session_file_mode(self):
        self.write_session(b"full")
        self.assertEqual(self.mode(), "full")
        self.write_session(b"Wenyan-Lite\n")
        self.assertEqual(self.mode(), "wenyan-lite")

    def test_session_file_wins_over_global_mirror(self):
        (self.dir / ".caveman-active").write_bytes(b"full")
        self.write_session(b"lite")
        self.assertEqual(self.mode(), "lite")
        self.write_session(b"off")
        self.assertIsNone(self.mode())

    def test_global_mirror_only_without_session_id(self):
        (self.dir / ".caveman-active").write_bytes(b"ultra")
        self.assertEqual(self.mode(None), "ultra")
        self.assertEqual(self.mode("../escape"), "ultra")
        self.assertEqual(self.mode(123), "ultra")
        # A window with its own id but no session file is a window without caveman.
        self.assertIsNone(self.mode())

    def test_absent_malformed_or_unknown_renders_nothing(self):
        self.assertIsNone(sl.caveman_mode(SID, self.dir / "missing"))
        self.assertIsNone(self.mode())
        for content in (b"", b"off", b"bogus", b"\x1b[31mfull", b"\xff\xfe", b"f" * 200):
            self.write_session(content)
            self.assertIsNone(self.mode(), content)

    def test_symlink_refused(self):
        target = self.dir / "target"
        target.write_bytes(b"full")
        (self.dir / ".caveman-sessions" / f"{SID}.mode").symlink_to(target)
        self.assertIsNone(self.mode())

    def test_directory_in_place_of_file(self):
        (self.dir / ".caveman-sessions" / f"{SID}.mode").mkdir()
        self.assertIsNone(self.mode())

    def build(self, merged=None):
        payload = {"session_id": SID, "model": {"display_name": "Opus 5.5"}, "effort": {"level": "high"}}
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.dir)}):
            return sl.build_line(payload, merged or {})

    def test_build_line_badge_after_model(self):
        self.write_session(b"full")
        line = self.build()
        self.assertIn(f"{sl.ORANGE}[CAVEMAN:full]{sl.RESET}", line)
        self.assertIn("Opus 5.5 [high] [CAVEMAN:full]", sl.ANSI_RE.sub("", line))

    def test_build_line_without_caveman_or_when_disabled(self):
        self.assertNotIn("CAVEMAN", self.build())
        self.write_session(b"full")
        self.assertNotIn("CAVEMAN", self.build({"statusLine": {"showCaveman": False}}))


if __name__ == "__main__":
    unittest.main()

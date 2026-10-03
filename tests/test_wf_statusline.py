import sys
import unittest
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
        self.assertEqual(seg(cache, 358_000), "cache 42m/1h $0.07r")

    def test_cold_shows_write_cost_for_ttl(self):
        cache = {"caching_observed": True, "warm": False, "expires_at": NOW - 5, "ttl": "1h"}
        self.assertEqual(seg(cache), "cache cold $2.86w")
        cache["ttl"] = "5m"
        self.assertEqual(seg(cache), "cache cold $1.79w")

    def test_none_when_missing_or_unobserved(self):
        self.assertEqual(seg(None), "cache none $2.86w")
        self.assertEqual(seg({"caching_observed": False, "warm": True}), "cache none $2.86w")

    def test_none_and_cold_are_red_warm_is_not(self):
        self.assertIn(sl.RED, sl.cache_segment(None, 300, NOW, 1000, *OPUS55))
        warm = {"caching_observed": True, "warm": True, "expires_at": NOW + 3000, "ttl": "1h"}
        self.assertNotIn(sl.RED, sl.cache_segment(warm, 300, NOW, 1000, *OPUS55))

    def test_unknown_model_keeps_state_drops_amount(self):
        self.assertEqual(seg(None, model=("claude-fable-5-1", "Fable 5.1")), "cache none")
        self.assertEqual(seg(None, model=("", "")), "cache none")

    def test_no_context_drops_amount(self):
        self.assertEqual(seg(None, tokens=None), "cache none")

    def test_model_prices(self):
        self.assertEqual(sl.model_price("claude-opus-5", "Opus 5"), (5.0, 0.1))
        self.assertEqual(sl.model_price("claude-sonnet-5-5", ""), (2.0, 0.1))
        self.assertEqual(sl.model_price("claude-haiku-4-5-20251001", ""), (1.0, 0.1))

    def test_build_line_always_has_cache(self):
        line = sl.build_line({"model": {"id": "claude-sonnet-5-5", "display_name": "Sonnet 5.5"},
                              "context_window": {"total_input_tokens": 100_000}}, {})
        self.assertIn("cache none $0.40w", sl.ANSI_RE.sub("", line))


if __name__ == "__main__":
    unittest.main()

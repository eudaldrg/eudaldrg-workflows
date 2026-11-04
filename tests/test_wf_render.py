import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/core/scripts"))
import wf_render  # noqa: E402

DIAGRAM = (
    '<svg viewBox="0 0 120 40" xmlns="http://www.w3.org/2000/svg" version="1.1">\n'
    '  <rect x="1" y="1" width="118" height="38" fill="none" stroke="currentColor"/>\n'
    '  <text x="60" y="25" text-anchor="middle" fill="currentColor">A &amp; B</text>\n'
    "</svg>"
)


def fence(body: str, language: str = "svg") -> str:
    return wf_render.to_html(f"```{language}\n{body}\n```")


class SvgFenceTest(unittest.TestCase):
    def test_static_svg_passes_through_raw(self):
        out = fence(DIAGRAM)
        self.assertEqual(out, f"<figure>{DIAGRAM}</figure>")
        self.assertNotIn("&lt;svg", out)

    def assert_escaped(self, body: str) -> None:
        out = fence(body)
        self.assertTrue(out.startswith('<pre><code class="language-svg">'), out)
        self.assertNotIn("<svg", out)

    def test_script_element_is_escaped(self):
        self.assert_escaped('<svg><script>alert(1)</script></svg>')

    def test_event_handler_is_escaped(self):
        self.assert_escaped('<svg onload="alert(1)"></svg>')
        self.assert_escaped('<svg><rect ONCLICK = "x()"/></svg>')
        self.assert_escaped('<svg/onload=alert(1)></svg>')

    def test_javascript_url_is_escaped(self):
        self.assert_escaped('<svg><a href="javascript:alert(1)"><text>x</text></a></svg>')
        self.assert_escaped('<svg><a href="&#106;ava&#x73;cript:alert(1)"><text>x</text></a></svg>')
        self.assert_escaped('<svg><a href="java\tscript:alert(1)"><text>x</text></a></svg>')

    def test_embedded_documents_are_escaped(self):
        self.assert_escaped('<svg><foreignObject><div>x</div></foreignObject></svg>')
        self.assert_escaped('<svg><iframe src="x"></iframe></svg>')

    def test_not_a_single_svg_element_is_escaped(self):
        self.assert_escaped("<p>hi</p>")
        self.assert_escaped(f"{DIAGRAM}<p>trailing</p>")
        self.assert_escaped(f"<div>{DIAGRAM}</div>")

    def test_other_fences_unchanged(self):
        self.assertEqual(
            fence("<svg></svg>", "html"),
            '<pre><code class="language-html">&lt;svg&gt;&lt;/svg&gt;</code></pre>',
        )
        self.assertEqual(fence("<svg></svg>", ""), "<pre><code>&lt;svg&gt;&lt;/svg&gt;</code></pre>")

    def test_supported_lists_svg(self):
        self.assertIn("svg", wf_render.SUPPORTED)


if __name__ == "__main__":
    unittest.main()

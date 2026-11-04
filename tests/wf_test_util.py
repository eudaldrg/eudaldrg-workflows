"""Shared helpers for tests that validate the layered config."""

import contextlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/core/scripts"))
import wf_config  # noqa: E402

DEFAULTS = ROOT / "plugins/core/defaults/workflows.defaults.json"


def load_defaults() -> dict:
    return json.loads(DEFAULTS.read_text(encoding="utf-8"))


def problems(project_layer: dict, strict: bool = False) -> list[str]:
    """Validate defaults + one project layer, as `wf_config.py validate` would."""
    loaded = [("defaults", load_defaults()), ("project", project_layer)]
    merged, _ = wf_config.merge_layers(loaded)
    with contextlib.redirect_stderr(io.StringIO()):
        return wf_config.validate(merged, loaded, strict=strict)

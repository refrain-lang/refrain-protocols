"""Round-trip the whole reference library through the protocol-editor shared core.

For every protocol: `describe_protocol` must not crash. If it is in-subset, the
`describe -> render -> resolve` loop must reproduce the *exact* IR. This is the
"completeness critic" over the real corpus — distinct from the SDK's handful of
inline fixtures: it catches editor regressions, and it flags which protocols
still fall outside catalog v1 (the catalog-growth TODO, in KNOWN_GAPS below).

Requires a `refrain` build that includes the `refrain.editor` module (unreleased
as of refrain 0.9.x). Skips cleanly where the editor is absent, so it does not
break this library's own CI until the `refrain` dependency pin is bumped to a
release that ships the editor.
"""
from __future__ import annotations

from pathlib import Path

import pytest

refrain = pytest.importorskip("refrain")
editor = pytest.importorskip("refrain.editor")
from refrain.ir_json import ir_to_json_obj  # noqa: E402
from refrain.resolver import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ALL = sorted((ROOT / "protocols").glob("*.refrain")) + sorted((ROOT / "drafts").glob("*.refrain"))

# Protocols not yet covered by catalog v1 — each is a catalog-growth TODO.
# When the catalog grows to cover one, `test_known_gaps_stay_flagged` fails and
# reminds us to move it out of this set (it will then be gated as in-subset).
KNOWN_GAPS = {
    "scp_cz.refrain",  # draft: not resolvable yet (needs engine SCP primitives)
}
# Closed by refrain-lang/refrain#39: composite_smr_theta_cz (weighted composite) and
# hrv_resonance (passthrough / lf_envelope / auto_range / bare-ref reward) are now
# in-subset and gated by the round-trip test below. Coverage: 37/38.

_IN_SUBSET = [p for p in ALL if p.name not in KNOWN_GAPS]
_GAPS = [p for p in ALL if p.name in KNOWN_GAPS]


def _ir(src: str) -> dict:
    return ir_to_json_obj(resolve(refrain.parse(src)))


def test_corpus_is_non_empty():
    assert ALL, "no .refrain files found — wrong ROOT?"


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_describe_never_crashes(path: Path):
    editor.describe_protocol(path.read_text())  # must return, never raise


@pytest.mark.parametrize("path", _IN_SUBSET, ids=lambda p: p.name)
def test_in_subset_round_trips_to_equal_ir(path: Path):
    src = path.read_text()
    d = editor.describe_protocol(src)
    assert d["in_subset"] is True, f"{path.name} unexpectedly fell out of catalog subset"
    assert _ir(src) == _ir(editor.render_protocol(d["model"])), f"{path.name} round-trip IR differs"


@pytest.mark.parametrize("path", _GAPS, ids=lambda p: p.name)
def test_known_gaps_stay_flagged(path: Path):
    # A documented catalog gap must degrade gracefully (no crash) and NOT claim
    # in-subset. If this fails, the catalog now covers it — move it out of
    # KNOWN_GAPS so it gets gated by the round-trip test above.
    d = editor.describe_protocol(path.read_text())
    assert d["in_subset"] is False

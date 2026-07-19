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
ALL = sorted((ROOT / "protocols").rglob("*.refrain")) + sorted((ROOT / "drafts").rglob("*.refrain"))

# Protocols not yet covered by catalog v1 — each is a catalog-growth TODO.
# When the catalog grows to cover one, `test_known_gaps_stay_flagged` fails and
# reminds us to move it out of this set (it will then be gated as in-subset).
KNOWN_GAPS = {
    "critical_fluctuation.refrain",    # bands{} fan-out + autocorr — a non-operant early-warning cue, outside catalog v1
    "scp_cz.refrain",                  # draft: not resolvable yet (needs engine SCP primitives)
    # The 16 generated seed cores (tools/gen_seed_protocols.py) collapsed their
    # adaptive/baseline variants into one mode-based core per refrain 0.12.0:
    # `threshold "env_t" { type = threshold_style == "baseline" ? absolute(...) : percentile(...) }`.
    # The engine resolves this ternary (folds on the `mode` control) fine, but the
    # installed 0.12.0 `refrain.editor` catalog-v1 matcher (`_match_threshold`)
    # only recognizes a bare `percentile(...)`/`absolute(...)` call as a `type`,
    # not a mode-folded conditional — so these fall out of subset until the
    # editor's catalog grows mode-threshold support (engine-side, not this repo).
    "smr_theta_cz.refrain",
    "theta_beta_cz.refrain",
    "theta_beta_fz.refrain",
    "theta_down_cz.refrain",
    "theta_down_fz.refrain",
    "slow_down_cz.refrain",
    "slow_down_fz.refrain",
    "smr_up_c4.refrain",
    "beta_up_c3.refrain",
    "beta_up_fz.refrain",
    "alpha_up_pz.refrain",
    "hibeta_down_cz.refrain",
    "peak_alpha_up_pz.refrain",
    "fm_theta_up_fz.refrain",
    "alpha_down_pz.refrain",
    "theta_up_pz.refrain",
    # BrainBit mode-folded-threshold cores — same catalog-v1 gap as the generic
    # cores above (editor's _match_threshold doesn't recognise the mode-folded
    # conditional). Surfaced when rglob brought protocols/brainbit/ into the test.
    "beta_focus_staged_fz_brainbit.refrain",
    "smr_classic_cz_brainbit.refrain",
    "smr_graded_cz_brainbit.refrain",
    "smr_up_c4_brainbit.refrain",
}
# Closed by refrain-lang/refrain#39: composite_smr_theta_cz (weighted composite) and
# hrv_resonance (passthrough / lf_envelope / auto_range / bare-ref reward) are now
# in-subset and gated by the round-trip test below. critical_fluctuation
# (multi-band bands{} fan-out + autocorr) is a new non-operant gap added here.

# NOTE: in-subset protocols are resolved at amp=None below. A protocol that
# reads `amp.*` (amp-neutral) will ResolveError here (fail-closed by design) if
# it is ever in-subset. All 16 amp-reading operant cores are currently KNOWN_GAPS,
# so none reach this path. When the sweep moves an amp-reader into subset, teach
# this test to skip amp-readers (or resolve them against a default amp) first.
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

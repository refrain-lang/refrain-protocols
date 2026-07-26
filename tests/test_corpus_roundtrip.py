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
    # draft: resolves fine (no engine gap) — out of subset because its near-DC
    # derive pipeline (`bandpass(...), smooth(...)`, no hilbert/magnitude/rectify
    # envelope detector) isn't one of catalog v1's recognized derive shapes
    # (`_match_derive` only knows envelope/envelope_band/lf_envelope/rectify/
    # auto_range pipelines). Not the "needs engine SCP primitives" reason this
    # entry used to carry — that description predates this check and no longer
    # matches what `describe_protocol` actually reports.
    "scp_cz.refrain",
    # refrain v0.21.0 (this repo's CI pin, bumped from v0.18.0 — see
    # .github/workflows/ci.yml) taught the editor's catalog-v1 `_match_threshold`
    # matcher to recognize a mode-folded ternary threshold —
    # `threshold "env_t" { type = threshold_style == "baseline" ? absolute(...) : percentile(...) }`
    # — which is the gap that originally put the 16 generated seed cores
    # (tools/gen_seed_protocols.py) below, and the 3 BrainBit-origin cores after
    # them, in this set. That matcher gap is now closed: `smr_up_c4_brainbit`,
    # the one member of this whole family whose montage still uses a literal
    # reference instead of `amp.reference`, round-trips exactly and has moved
    # out of KNOWN_GAPS as a result.
    #
    # Every protocol below stays a gap anyway, for an UNRELATED reason: the
    # 2026-07 amp-portability sweep (docs/fork-audit-2026-07.md) switched their
    # `montage.referential` reference to `amp.reference`, so
    # `describe_protocol`'s `resolve(amp=None)` call fails closed (see the
    # amp-neutral NOTE below) before the now-fixed threshold matcher is ever
    # reached. Resolving them against a real amp profile (verified here against
    # refrain's bundled `amp_profiles/q21.json`) shows they describe in-subset
    # and round-trip exactly — the amp-neutral gate is their only blocker.
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
    # BrainBit-origin mode-folded-threshold cores — same amp-neutral gap as the
    # generic cores above (the threshold-matcher gap they used to share is
    # fixed; see above). 2026-07: these three dropped their "_brainbit" filename
    # suffix when protocols/brainbit/ was dissolved (relocated to protocols/eeg/,
    # made amp-portable, i.e. switched to `amp.reference`). The fourth member of
    # this original foursome, smr_up_c4_brainbit, was already retired to
    # protocols/eeg/legacy/ under its original name and kept a literal
    # reference — which is why it alone closed and is no longer in this set.
    "beta_focus_staged_fz.refrain",
    "smr_classic_cz.refrain",
    "smr_graded_cz.refrain",
    # Amp-neutral coherence consolidation (2026-07): now reads `amp.reference`
    # on both of its inputs, per the general amp-reader exclusion documented
    # below — resolve(amp=None) fails closed here exactly as predicted, same
    # bucket as the 16 amp-reading operant cores above (unrelated mode-folded-
    # threshold reason; this file has no threshold_style control at all, it's
    # simply an amp-reader like they are).
    "alpha_coherence.refrain",
    # Library amp-portability sweep (2026-07, docs/fork-audit-2026-07.md):
    # each of these was reverted from a hardcoded "device"/"linked_ears"
    # reference to `amp.reference` (either merged from/replacing a retired
    # BrainBit fork, or relocated from protocols/brainbit/ with no top-level
    # counterpart). Same amp-neutral resolve(amp=None) fail-closed gap as
    # alpha_coherence.refrain above, unrelated to the mode-folded-threshold
    # reason for the cores earlier in this set.
    "alpha_theta_pz.refrain",
    "beta_up_cz.refrain",
    "faa_f3f4.refrain",
    "placement_smr_active.refrain",
    "placement_smr_set.refrain",
    "smr_classic_baseline_staged_cz.refrain",
    "smr_cz_modulating.refrain",
    # Configurable SMR template (2026-07, replaces the whole SMR family): reads
    # `amp.reference`, same amp-neutral resolve(amp=None) fail-closed gap as
    # the group above. Also combines a `placement` site control, paired
    # `frequency` band-edge controls in a `band: (...)` tuple, and an
    # artifact-guard `mode` folded one level inside a call argument (not at
    # threshold.type) — none of which catalog v1's matcher covers yet, so
    # this would stay a gap even once amp-neutral resolution is handled.
    "smr.refrain",
    # The four remaining configurable goal templates (2026-07): each copies
    # smr.refrain's shape verbatim (placement site, paired frequency
    # band-edge controls, mode-folded artifact guard, amp.reference) — same
    # catalog-v1 gap as smr.refrain above, for the same reasons.
    "beta_attention.refrain",
    "high_beta_down.refrain",
    "alpha_up.refrain",
    "alpha_theta.refrain",
}
# Closed by refrain-lang/refrain#39: composite_smr_theta_cz (weighted composite) and
# hrv_resonance (passthrough / lf_envelope / auto_range / bare-ref reward) are now
# in-subset and gated by the round-trip test below. critical_fluctuation
# (multi-band bands{} fan-out + autocorr) is a new non-operant gap added here.
#
# Closed by refrain v0.21.0 (2026-07, CI pin bumped from v0.18.0): the
# catalog-v1 mode-folded-threshold matcher gap. Measured upstream: the
# round-trippable subset went from 16/38 to 36/38 with this fix, with zero
# round-trip mismatches. Only `smr_up_c4_brainbit.refrain` actually moved out
# of this set as a direct result (it's the only mode-folded-threshold core
# with a literal montage reference); its 19 amp-portable siblings above stay
# gapped for the unrelated amp-neutral reason documented next to them.

# NOTE: in-subset protocols are resolved at amp=None below. A protocol that
# reads `amp.*` (amp-neutral) will ResolveError here (fail-closed by design) if
# it is ever in-subset. 33 of the 34 protocols in this set are amp-readers (all
# but scp_cz.refrain, whose gap is unrelated to amp), so none reach this path.
# When the sweep moves an amp-reader into subset, teach this test to skip
# amp-readers (or resolve them against a default amp) first.
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

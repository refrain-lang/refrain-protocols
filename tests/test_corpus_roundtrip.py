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
from refrain.amp_profile import load_amp_profile  # noqa: E402
from refrain.ir_json import ir_to_json_obj  # noqa: E402
from refrain.resolver import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ALL = sorted((ROOT / "protocols").rglob("*.refrain")) + sorted((ROOT / "drafts").rglob("*.refrain"))

# A real host always resolves against a connected amp's profile; `amp=None`
# (refrain's own default) is an artificial case that only exists in this test.
# Since the 2026-07 amp-portability sweep (docs/fork-audit-2026-07.md) moved
# most of this library's montages to `referential(..., reference:
# amp.reference)`, resolving amp-neutral makes `describe_protocol` fail closed
# before the editor's catalog-v1 matchers are ever reached — under-reporting
# how much of the library the editor can actually represent.
#
# `q21` is the amp profile chosen here: 256 Hz, linked-ears reference, and the
# full clinical 19-channel 10-20 set, vs. `brainbit_flex` (250 Hz,
# device-referenced) or `openbci_cyton` (8 channels) — the widest `requires`
# coverage of refrain's three bundled profiles, verified against every
# `requires.channels`/`requires.coupling`/placement `allowed` list in this
# corpus. It legitimately does NOT unblock everything: critical_fluctuation.refrain
# declares `sample_rate = ">= 256 Hz"` and STILL resolves fine against q21 (the
# 256 Hz is met) — its gap is unrelated to the amp. See KNOWN_GAPS below for
# the one file an EEG amp profile cannot help at all.
_EEG_AMP = load_amp_profile(str(Path(refrain.__file__).parent / "amp_profiles" / "q21.json"))


def _amp_for(path: Path):
    """The amp profile to resolve `path` against.

    hrv_resonance.refrain is this corpus's one non-EEG protocol (a cardiac
    tachogram input: `requires.channels = ["tachogram"]`, `passthrough()`
    montage, no `amp.reference` read at all). None of refrain's bundled amp
    profiles are cardiac devices, so handing it `_EEG_AMP` would fail closed on
    a missing "tachogram" channel — a false gap manufactured by this test's amp
    choice, not a property of the protocol or the editor. Resolve it
    amp-neutral, as every protocol in this corpus was resolved before this
    change.
    """
    return None if path.name == "hrv_resonance.refrain" else _EEG_AMP


# Protocols not yet covered by catalog v1 — each is a catalog-growth TODO.
# When the catalog grows to cover one, `test_known_gaps_stay_flagged` fails and
# reminds us to move it out of this set (it will then be gated as in-subset).
KNOWN_GAPS = {
    # bands{} fan-out + autocorr — a non-operant early-warning cue, outside
    # catalog v1 (`_build_model` raises "section 'bands' not in subset").
    # Unrelated to the amp: this file's `requires.sample_rate = ">= 256 Hz"` is
    # satisfied by q21, so it resolves fine and reaches (then fails) the real
    # catalog matcher, same as every other entry left in this set.
    "critical_fluctuation.refrain",
    # draft: resolves fine (no engine gap) — out of subset because its near-DC
    # derive pipeline (`bandpass(...), smooth(...)`, no hilbert/magnitude/rectify
    # envelope detector) isn't one of catalog v1's recognized derive shapes
    # (`_match_derive` only knows envelope/envelope_band/lf_envelope/rectify/
    # auto_range pipelines). Not the "needs engine SCP primitives" reason this
    # entry used to carry — that description predates this check and no longer
    # matches what `describe_protocol` actually reports.
    "scp_cz.refrain",
    # Configurable goal templates (2026-07, replace the whole SMR/alpha/beta/
    # theta family below): each combines a `placement` site control with PAIRED
    # `frequency` band-edge controls referenced directly in
    # `bandpass(band: (lo_ctrl, hi_ctrl))` — e.g. smr.refrain's
    # `bandpass(band: (smr_lo_hz, smr_hi_hz), order: 4)`. Verified directly:
    # `_build_model` raises "envelope needs center + bandwidth: ratio(R), or
    # band: (lo, hi)" for all five — catalog v1's envelope matcher accepts a
    # literal `(lo, hi)` Hz tuple, not a tuple of control references. Amp-neutral
    # resolution (q21) is NOT the blocker: all five read `amp.reference` and
    # resolve past that fine now; this matcher gap is reached and hit on every
    # one. (They'd also need catalog-v1 support for the artifact-guard `mode`
    # folded one level inside a call argument, not at `threshold.type`, but the
    # band-edge shape is what `_build_model` actually raises on first.)
    "smr.refrain",
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
# with a literal montage reference); its 19 amp-portable siblings stayed
# gapped by an ARTIFACT of this test: `describe_protocol`'s `resolve(amp=None)`
# call fails closed on their `amp.reference` montage read before the
# now-fixed threshold matcher is ever reached — 19 false gaps, not real ones.
#
# Closed by resolving against a real amp profile (this change, 2026-07):
# every one of those 19 amp-portable mode-threshold cores, plus
# alpha_coherence.refrain and 7 more amp-portable operant cores that carried
# no threshold_style control at all, describe in-subset and round-trip
# EXACTLY against `_EEG_AMP` (q21) — 27 entries moved out of KNOWN_GAPS with
# zero round-trip mismatches (verified by running the suite, not by
# reasoning). The amp-neutral gate was their only blocker, exactly as this
# file predicted before landing the fix. 34 -> 7.
_IN_SUBSET = [p for p in ALL if p.name not in KNOWN_GAPS]
_GAPS = [p for p in ALL if p.name in KNOWN_GAPS]


def _ir(src: str, amp) -> dict:
    return ir_to_json_obj(resolve(refrain.parse(src), amp))


def test_corpus_is_non_empty():
    assert ALL, "no .refrain files found — wrong ROOT?"


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_describe_never_crashes(path: Path):
    editor.describe_protocol(path.read_text(), amp=_amp_for(path))  # must return, never raise


@pytest.mark.parametrize("path", _IN_SUBSET, ids=lambda p: p.name)
def test_in_subset_round_trips_to_equal_ir(path: Path):
    src = path.read_text()
    amp = _amp_for(path)
    d = editor.describe_protocol(src, amp=amp)
    assert d["in_subset"] is True, f"{path.name} unexpectedly fell out of catalog subset"
    assert _ir(src, amp) == _ir(editor.render_protocol(d["model"]), amp), (
        f"{path.name} round-trip IR differs"
    )


@pytest.mark.parametrize("path", _GAPS, ids=lambda p: p.name)
def test_known_gaps_stay_flagged(path: Path):
    # A documented catalog gap must degrade gracefully (no crash) and NOT claim
    # in-subset. If this fails, the catalog now covers it — move it out of
    # KNOWN_GAPS so it gets gated by the round-trip test above.
    d = editor.describe_protocol(path.read_text(), amp=_amp_for(path))
    assert d["in_subset"] is False

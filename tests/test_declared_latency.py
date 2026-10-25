# Copyright 2026 Refrain Protocols Authors.
"""Every band envelope in the live library declares its latency.

The four-stage chain `bandpass -> hilbert -> magnitude -> smooth` carries a
delay nobody chose: the sum of four filters, ~566 ms on a 12-15 Hz band.
`band_envelope(band:, latency:)` makes the delay a number in the source.
This gate holds the migration in place:

- every envelope derive under protocols/ (outside legacy/) is a one-stage
  `band_envelope`, or is named in EXCLUDED with the reason it stays as it is,
  or sits in a file listed in WAITING against the roadmap item that will
  redesign it (docs/superpowers/specs/2026-10-21-protocol-feedback-roadmap-design.md).
  Files wait because the swap alone collapsed reward holds in every protocol
  on replayed recordings: each family migrates together with its reward
  redesign, not ahead of it. Nothing is silently skipped;
- each declared latency sits at or above its band's bandwidth-time floor
  (1 / band width, at the band's default edges). Below the floor the filter
  asks for less delay than the bandwidth can deliver and is *less* accurate
  than the chain it replaced (measured: 250 ms on 12-15 Hz gives r=0.873
  against 0.904 at 360 ms);
- legacy/ is frozen. A subject assigned a retired protocol keeps running
  exactly what they were assigned, so nothing under it is migrated.
"""
from __future__ import annotations

from pathlib import Path

import pytest

refrain = pytest.importorskip("refrain")
from refrain.amp_profile import load_amp_profile  # noqa: E402
from refrain.ir_json import ir_to_json_obj  # noqa: E402
from refrain.resolver import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROTOCOLS = ROOT / "protocols"
LIVE = sorted(p for p in PROTOCOLS.rglob("*.refrain") if "legacy" not in p.parts)
LEGACY = sorted((PROTOCOLS / "eeg" / "legacy").glob("*.refrain"))
_EEG_AMP = load_amp_profile(Path(refrain.__file__).parent / "amp_profiles" / "q21.json")

# (file, derive) -> why it is not a band_envelope.
EXCLUDED = {
    # `center:` + `bandwidth: ratio(R)`. band_envelope takes explicit edges
    # only, so migrating would change the authoring form as well as the
    # filter. Deferred as its own decision.
    ("faa_f3f4.refrain", "alpha_l"): "center+ratio band form; deferred",
    ("faa_f3f4.refrain", "alpha_r"): "center+ratio band form; deferred",
    # Three stages, no smoothing: the raw envelope feeds a fluctuation
    # measure (variance, autocorrelation) that the smoother would distort.
    ("critical_fluctuation.refrain", "env"): "unsmoothed envelope for a fluctuation measure",
    # 0.04-0.15 Hz heart-rate band via rectify, not Hilbert: a different
    # envelope method on a band whose bandwidth-time floor is ~9 s.
    ("hrv_resonance.refrain", "lf_env"): "rectify envelope on a sub-hertz band",
}

# File -> the roadmap item (Stage 3 numbering) that migrates its envelopes.
# Remove a file once its last four-stage envelope is gone.
_SMR = "Stage 3 #1 SMR family (REC-15)"
_BETA = "Stage 3 #2 beta family"
_ALPHA_THETA = "Stage 3 #4 alpha-theta family"
WAITING = {
    "smr.refrain": _SMR,
    "placement_smr_bipolar.refrain": _SMR,
    "placement_smr_set.refrain": _SMR,
    "smr_classic_baseline_staged_cz.refrain": _SMR,
    "beta_attention.refrain": _BETA,
    "beta_focus_staged_fz.refrain": _BETA,
    "alpha_up.refrain": "Stage 3 #3 alpha_up",
    "alpha_theta.refrain": _ALPHA_THETA,
    "alpha_theta_narrowband.refrain": _ALPHA_THETA,
    "alpha_theta_narrowband_melodic.refrain": _ALPHA_THETA,
    "alpha_theta_narrowband_theta_rise.refrain": _ALPHA_THETA,
    "high_beta_down.refrain": "Stage 3 #5 high_beta_down (keep or retire)",
}

_FOUR_STAGE = ["bandpass", "hilbert", "magnitude", "smooth"]


def _classify(path_name: str, names: list[str]) -> str:
    if names == ["band_envelope"]:
        return "migrated"
    if names == ["bandpass"]:
        return "bare_bandpass"  # an inhibit or coherence input, not an envelope
    if path_name in WAITING and names == _FOUR_STAGE:
        return "waiting"
    return "unlisted"


def _chain(expr: dict) -> tuple[list[str], dict | None]:
    names, band_call = [], None
    while expr.get("node") == "call":
        names.append(expr["callee"])
        if any(a.get("name") in ("band", "center") for a in expr["args"]):
            band_call = expr
        expr = expr["args"][0]["value"]
    return names[::-1], band_call


def _envelopes(path: Path):
    """(derive name, callee chain, band-carrying call) for every band-filtered derive.

    A fanned-out derive (`smr_envelope@C3`, `env@delta`) is reported under its
    base name: the source has one derive, so it migrates or is excluded once.
    """
    amp = None if path.name == "hrv_resonance.refrain" else _EEG_AMP
    ir = ir_to_json_obj(resolve(refrain.parse_file(str(path)), amp))
    for name, d in ir["derives"].items():
        names, call = _chain(d["expression"])
        if call is not None and names[0] in ("bandpass", "band_envelope"):
            yield name.split("@", 1)[0], names, call


def _num(v: dict) -> float:
    return float(v["value"] if v["node"] == "number" else v["default"])


def _live_envelopes():
    seen, out = set(), []
    for p in LIVE:
        for name, names, call in _envelopes(p):
            if (p.name, name) not in seen:
                seen.add((p.name, name))
                out.append((p, name, names, call))
    return out


@pytest.mark.parametrize(
    "path,name,names,call",
    _live_envelopes(),
    ids=lambda v: v.name if isinstance(v, Path) else (v if isinstance(v, str) else ""),
)
def test_envelope_is_declared_or_excluded(path, name, names, call):
    if (path.name, name) in EXCLUDED:
        assert names != ["band_envelope"], (
            f"{path.name}:{name} is migrated; take it off EXCLUDED"
        )
        return
    assert _classify(path.name, names) != "unlisted", (
        f"{path.name}:{name} is {' -> '.join(names)}; migrate it to band_envelope, "
        "add it to EXCLUDED with the reason, or add the file to WAITING with the "
        "roadmap item that will redesign it"
    )


def _floor_violation(call: dict) -> str | None:
    """Why a band_envelope call sits below its bandwidth-time floor, or None."""
    args = {a["name"]: a["value"] for a in call["args"] if a["name"]}
    lo, hi = (_num(e) for e in args["band"]["elements"])
    latency_ms = _num(args["latency"])
    if args["latency"].get("unit") == "s":
        latency_ms *= 1000.0
    floor_ms = 1000.0 / (hi - lo)
    if latency_ms >= floor_ms:
        return None
    return (
        f"declares {latency_ms:g} ms on {lo:g}-{hi:g} Hz, below its {floor_ms:.0f} ms "
        "bandwidth-time floor; it would be less accurate than the chain it replaced"
    )


@pytest.mark.parametrize(
    "path,name,call",
    # Every chain that starts with band_envelope, whatever follows it.
    [(p, n, c) for p, n, names, c in _live_envelopes() if names[0] == "band_envelope"],
    ids=lambda v: v.name if isinstance(v, Path) else (v if isinstance(v, str) else ""),
)
def test_declared_latency_clears_the_bandwidth_floor(path, name, call):
    problem = _floor_violation(call)
    assert problem is None, f"{path.name}:{name} {problem}"


@pytest.mark.parametrize("path", LEGACY, ids=lambda p: p.name)
def test_legacy_is_frozen(path):
    assert "band_envelope" not in path.read_text(), (
        f"legacy/{path.name} was migrated; legacy/ is frozen so an assigned "
        "subject keeps running what they were assigned"
    )


def test_exclusions_name_real_derives():
    live = {(p.name, n) for p, n, _, _ in _live_envelopes()}
    assert set(EXCLUDED) <= live, sorted(set(EXCLUDED) - live)


def test_unlisted_four_stage_fails():
    assert _classify("new_protocol.refrain", _FOUR_STAGE) == "unlisted"


def test_waiting_four_stage_passes():
    assert _classify("smr.refrain", _FOUR_STAGE) == "waiting"


def test_band_envelope_is_migrated_anywhere():
    assert _classify("smr.refrain", ["band_envelope"]) == "migrated"
    assert _classify("new_protocol.refrain", ["band_envelope"]) == "migrated"


def test_bare_bandpass_is_not_an_envelope():
    assert _classify("new_protocol.refrain", ["bandpass"]) == "bare_bandpass"


def test_waiting_files_still_wait():
    """A WAITING file with no four-stage envelope left has been migrated: drop it from WAITING."""
    still = {p.name for p, _, names, _ in _live_envelopes() if names == _FOUR_STAGE}
    assert set(WAITING) <= still, sorted(set(WAITING) - still)


def test_waiting_files_exist():
    live = {p.name for p in LIVE}
    assert set(WAITING) <= live, sorted(set(WAITING) - live)


def test_waiting_file_only_excuses_the_four_stage_chain():
    """A waiting file may keep its old chains, not grow new unchecked shapes."""
    assert _classify("smr.refrain", ["band_envelope", "smooth"]) == "unlisted"


def _call(lo: float, hi: float, latency: float, unit: str = "ms") -> dict:
    num = lambda v: {"node": "number", "value": v}  # noqa: E731
    return {"node": "call", "callee": "band_envelope", "args": [
        {"name": None, "value": {"node": "stream_ref", "target": "input/raw"}},
        {"name": "band", "value": {"node": "tuple", "elements": [num(lo), num(hi)]}},
        {"name": "latency", "value": {**num(latency), "unit": unit}},
    ]}


def test_floor_rejects_a_latency_below_the_bandwidth_floor():
    assert _floor_violation(_call(12, 15, 100)) is not None
    assert _floor_violation(_call(12, 15, 0.1, unit="s")) is not None


def test_floor_accepts_a_latency_at_or_above_it():
    assert _floor_violation(_call(12, 15, 360)) is None
    assert _floor_violation(_call(20, 30, 100)) is None

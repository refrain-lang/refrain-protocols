"""Gates for smr_burst.refrain: how it is wired, and what the chime does.

Two kinds of test, because the repo's behavioural gate does not reach this
file. `refrain fuzz` skips every `band_envelope` reward as "non-bandpass
(coherence) reward signal" (see test_smr_spindle.py), so the structural tests
below would otherwise be the only thing standing between the header and the
engine. The last three tests therefore RUN the engine, on synthetic input
whose answer is known by construction: a 14 Hz burst must chime while it is
still under way, and the skirt of a larger 10 Hz burst must not chime at all -
with a control showing that the skirt does clear the amplitude bar, so it is
the shape test refusing it. They say nothing about EEG; tools/score_burst_trigger.py
does that, on recordings that do not ship here.
"""
from pathlib import Path

import numpy as np
import pytest

refrain = pytest.importorskip("refrain")
from refrain.amp_profile import load_amp_profile  # noqa: E402
from refrain.eval_ import Evaluator  # noqa: E402
from refrain.ir_json import ir_to_json_obj  # noqa: E402
from refrain.resolver import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "protocols" / "eeg" / "smr_burst.refrain"
_PROFILES = Path(refrain.__file__).parent / "amp_profiles"
Q21 = load_amp_profile(str(_PROFILES / "q21.json"))
BRAINBIT = load_amp_profile(str(_PROFILES / "brainbit_flex.json"))
FS = 250


def _ir(amp=Q21) -> dict:
    return ir_to_json_obj(resolve(refrain.parse_file(str(PATH)), amp))


def _named(call: dict) -> dict:
    return {a["name"]: a["value"] for a in call["args"] if a.get("name")}


def test_resolves_on_both_amps_with_no_bindings():
    for amp in (Q21, BRAINBIT):
        assert resolve(refrain.parse_file(str(PATH)), amp) is not None


def test_one_weighted_envelope_at_160_ms_carries_both_sounds():
    ir = _ir()
    args = _named(ir["derives"]["smr_envelope"]["expression"])
    assert args["kind"]["value"] == "weighted"
    assert args["latency"]["default"] == 160.0
    assert [e["default"] for e in args["band"]["elements"]] == [12.0, 16.0]
    # The tone reads the same derive the chime's bar is built from.
    assert "smr_envelope" in str(ir["reward"]["continuous"])
    assert ir["thresholds"]["smr_median"]["signal"] == "derive/smr_envelope"


def test_the_shape_test_compares_two_envelopes_at_one_latency():
    # A ratio of envelopes with different delays compares two different
    # moments. The shoulder derive must track the SMR envelope's latency
    # control and design, not the 320 ms tapered guard envelope's.
    ir = _ir()
    smr = _named(ir["derives"]["smr_envelope"]["expression"])
    sh = _named(ir["derives"]["shoulder_envelope"]["expression"])
    assert sh["kind"]["value"] == smr["kind"]["value"] == "weighted"
    assert sh["latency"]["target"] == smr["latency"]["target"]
    assert [e["default"] for e in sh["band"]["elements"]] == [8.0, 12.0]


def test_the_chime_is_a_rearmed_commit_on_bar_and_shape_and_not_the_reward_event():
    ir = _ir()
    chime = ir["output"]["audio_chime"]
    assert chime["callee"] == "dwell_rearm"
    args = _named(chime)
    assert args["rearm"]["value"] == 300.0 and args["duration"]["value"] == 4.0
    terms = args["condition"]["args"][0]["value"]["elements"]
    assert args["condition"]["callee"] == "all_of" and len(terms) == 2
    seen = {t["args"][0]["value"]["target"].split("/", 1)[1] for t in terms}
    assert seen == {"smr_burst_level", "smr_dominance"}
    # The bar is a multiple of the MEDIAN, not a high percentile: a percentile
    # is crossed equally often on noise, which is the property this protocol
    # exists to not have.
    call = ir["thresholds"]["smr_median"]["threshold_call"]
    assert call["callee"] == "percentile" and _named(call)["target_pct"]["value"] == 50.0
    assert ir["controls"]["burst_ratio"]["default"]["value"] == 2.5
    assert ir["controls"]["burst_dominance"]["default"]["value"] == 1.0


def test_state_guards_do_not_pause_the_chime_and_scenes_keep_no_score():
    ir = _ir()
    for name in ("theta", "low"):
        inh = ir["inhibits"][name]
        assert inh["kind"] == "artifact" and inh["exempt"] == ["audio_chime"], name
    for name in ("emg", "hbeta"):
        assert ir["inhibits"][name]["action_kind"] == "mute", name
    assert "score_increment" not in str(ir["output"])


def test_the_header_keeps_to_the_timing_language():
    text = PATH.read_text().lower()
    for banned in ("waxing", "onset detection", "anticipat"):
        assert banned not in text, banned


# --------------------------------------------------------------------------
# behaviour, on input whose answer is known
# --------------------------------------------------------------------------
def _background(seconds: float, seed: int = 0) -> np.ndarray:
    """Pink-ish noise at EEG scale: no rhythm anywhere, so nothing should chime."""
    rng = np.random.default_rng(seed)
    n = int(seconds * FS)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / FS)
    spec[1:] /= f[1:] ** 0.75
    spec[0] = 0
    x = np.fft.irfft(spec, n)
    return 10.0 * x / x.std()


def _burst(x: np.ndarray, at_s: float, hz: float, uv: float, dur_s: float) -> None:
    n = int(dur_s * FS)
    t = np.arange(n) / FS
    x[int(at_s * FS): int(at_s * FS) + n] += uv * np.hanning(n) * np.sin(2 * np.pi * hz * t)


def _chimes(x: np.ndarray, backend: str) -> list[float]:
    ir = resolve(refrain.parse_file(str(PATH)), BRAINBIT)
    chans = tuple(sorted(BRAINBIT.channel_names()))
    ev = Evaluator.live(ir, sample_rate_hz=float(FS), channel_names=chans, backend=backend)
    ev.start(skip_warmup=True)
    X = np.zeros((len(x), len(chans)))
    X[:, [c.upper() for c in chans].index("CZ")] = x
    out, step = [], FS // 20
    for k in range(0, len(x) - step + 1, step):
        out += [e.timestamp_s for e in ev.step_chunk(X[k: k + step]) if e.channel == "audio_chime"]
    return out


def _backends() -> list[str]:
    import importlib.util

    return ["python"] + (["rust"] if importlib.util.find_spec("refrain_core") else [])


# Short on purpose: the rolling percentile is O(window) per sample on both
# backends, and it reports from a partly filled window, so 40 s is enough.
BURSTS_AT = (20.0, 25.0, 30.0, 35.0)


@pytest.mark.parametrize("backend", _backends())
def test_a_14_hz_burst_chimes_while_it_is_still_under_way(backend):
    x = _background(40.0)
    quiet = _chimes(x.copy(), backend)
    for t in BURSTS_AT:
        _burst(x, t, hz=14.0, uv=14.0, dur_s=1.0)
    got = [t for t in _chimes(x, backend) if t not in quiet]
    for t0 in BURSTS_AT:
        mine = [t for t in got if t0 <= t < t0 + 1.0]
        # Inside the burst - before it has ended - and not a stream of them.
        # NOT "exactly one", and not "early": these are Hann-shaped bursts
        # that peak at +500 ms, so the bar is met between +224 and +624 ms
        # depending on the noise under them, and over noise one burst's
        # envelope can dip under the bar for 300 ms and re-arm (one of these
        # four does, at +224 and +852 ms). The re-arm bounds chimes per
        # burst; it does not make them one.
        assert 1 <= len(mine) <= 2, (t0, mine)
    assert all(any(t0 <= t < t0 + 1.0 for t0 in BURSTS_AT) for t in got), got   # nothing new anywhere else


@pytest.mark.parametrize("backend", _backends())
def test_the_skirt_of_a_10_hz_burst_does_not_chime(backend):
    # 60 uV at 10 Hz puts far more than 2.5x the median into the 12-16 Hz
    # envelope through the filter's skirt. Amplitude alone would chime on it;
    # the dominance test is what refuses, and the control shows that.
    x = _background(40.0)
    quiet = set(_chimes(x.copy(), backend))
    for t in BURSTS_AT:
        _burst(x, t, hz=10.0, uv=60.0, dur_s=1.0)
    got = [t for t in _chimes(x, backend) if t not in quiet]
    assert not [t for t in got if any(t0 - 0.2 <= t < t0 + 1.4 for t0 in BURSTS_AT)], got


def test_the_10_hz_skirt_really_does_clear_the_amplitude_bar():
    # Without this the test above could pass because the skirt is too small
    # to matter. Same input, shape test switched off by text substitution.
    text = PATH.read_text().replace('        above("smr_dominance", 1.0),\n', "")
    assert text != PATH.read_text()
    tmp = PATH.with_name("_smr_burst_noshape.refrain")
    try:
        tmp.write_text(text)
        ir = resolve(refrain.parse_file(str(tmp)), BRAINBIT)
    finally:
        tmp.unlink(missing_ok=True)
    chans = tuple(sorted(BRAINBIT.channel_names()))
    x = _background(40.0)

    def run(sig):
        ev = Evaluator.live(ir, sample_rate_hz=float(FS), channel_names=chans, backend="python")
        ev.start(skip_warmup=True)
        X = np.zeros((len(sig), len(chans)))
        X[:, [c.upper() for c in chans].index("CZ")] = sig
        out, step = [], FS // 20
        for k in range(0, len(sig) - step + 1, step):
            out += [e.timestamp_s for e in ev.step_chunk(X[k: k + step]) if e.channel == "audio_chime"]
        return out

    quiet = set(run(x.copy()))
    for t in BURSTS_AT:
        _burst(x, t, hz=10.0, uv=60.0, dur_s=1.0)
    got = [t for t in run(x) if t not in quiet]
    assert sum(any(t0 - 0.2 <= t < t0 + 1.4 for t in got) for t0 in BURSTS_AT) >= 3, got

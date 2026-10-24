# Copyright 2026 Refrain Protocols Authors.
"""The command itself: what it prints, in what order, and what it writes.

The first test runs the documented invocation (``python -m tools.session_report``)
as a subprocess from the repo root, because that is the only way to catch a
package that imports fine but cannot be started.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
refrain = pytest.importorskip("refrain")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from session_fixture import build_session  # noqa: E402
from session_report.replay import replay_session  # noqa: E402
from session_report.session import load_session, resolve_for_session  # noqa: E402

FS = 250.0
CHUNK = 25
CHANS = ["Pz"]
BURSTS = (20.0, 40.0)
BURST_LEN_S = 1.5

# the metric names the report carries per protocol replayed
METRIC_KEYS = {
    "reward_share_of_unmuted", "rewards_per_min", "episodes_per_min", "episode_len_ms",
    "rewarded_in_episode", "rewarded_by_end_plus_250", "latency_from_episode_ms",
    "latency_from_condition_true_ms", "deadline_curve", "continuous_rise_ms",
    "stray_rewards_per_min", "mute_share", "muscle_time_muted", "muted_without_muscle",
    "episodes_lost_to_mute", "thresholds_per_block", "derive_lag_r",
    "ding_decided_vs_rendered", "per_phase", "protocol_views",
}

HEAD = '''
  meta { version = "1.0.0" evidence = "exploratory" description = "t" title = "t" summary = "t"
         family = "t" status = "draft" modality = "eeg" }
  requires { coupling = "ac" sample_rate = ">= 250 Hz" impedance = "not_required" markers = "not_required" }
  input "raw" { montage = referential(active: "Pz", reference: amp.reference) }
  derive "smr_envelope" { from = "raw"
    pipeline = [ bandpass(band: (12 Hz, 15 Hz), order: 4), hilbert(), magnitude(), smooth(tau: 250 ms) ] }
'''
TAIL = '''
  reward { event = dwell(condition: above("smr_envelope", "smr_t"), duration: 250 ms)
           continuous = sigmoid("smr_envelope" / "smr_t", midpoint: 1.0, steepness: 3) }
  output { audio_chime = reward.event
           audio_gain = reward.event.holds ? reward.continuous : 0 }
  session { phases = [ phase { name = "work"; duration = 2 min; mode = timed_with_floor } ] }
}
'''
# the session's own protocol: its reward level is a control the clinician moved
RAN = 'protocol "cli_probe" {' + HEAD + '''
  threshold "smr_t" { signal = "smr_envelope" type = absolute(value: level_uv) }
  controls { level_uv = voltage { default = 5 uV  range = (1 uV, 20 uV)
                                  label = "Reward level"  live_tunable = true } }
''' + TAIL
# a comparison design with no such control, so the logged change cannot be applied to it
COMPARE = 'protocol "cli_compare" {' + HEAD + '''
  threshold "smr_t" { signal = "smr_envelope" type = absolute(6 uV) }
''' + TAIL

LOWERED = {"type": "control_change", "name": "level_uv", "value": 4.0, "engine_value": 4.0,
           "previous_value": 5.0, "source": "clinician", "t_s": 55.0}


def _eeg(seconds: float) -> np.ndarray:
    n = int(seconds * FS)
    t = np.arange(n) / FS
    rng = np.random.default_rng(7)
    pz = 10.0 * np.sin(2 * np.pi * 10.0 * t) + 0.2 * rng.standard_normal(n)
    for onset in BURSTS:
        on = (t >= onset) & (t < onset + BURST_LEN_S)
        pz[on] += 12.0 * np.sin(2 * np.pi * 13.5 * t[on])
    return pz[:, None]


def _reward_records(events, *, rendered: bool) -> list[tuple[int, dict]]:
    """The reward_event records the recorder would have written for ``events``."""
    out = []
    for e in events:
        rec = {"type": "reward_event", "channel": e["channel"], "kind": e["kind"],
               "t_s": e["t_sample"] / FS}
        if e["kind"] == "value":
            rec["value"] = e["value"]
        else:
            rec["value"] = None
            rec["rendered_sound"] = rendered
        # keep each record on a chunk boundary, so logging it does not re-chunk the EEG
        out.append((-(-e["t_sample"] // CHUNK) * CHUNK, rec))
    return out


def _frames(replay) -> list[dict]:
    out = []
    for tap, pos in zip(replay.taps_per_chunk, replay.chunk_sample_offsets):
        out.append({"type": "telemetry", "t_s": pos / FS, "audio_muted": False,
                    "paused": False, "output_muted": bool(tap["phase/output_muted"]),
                    "muted": bool(tap["muted"]), "inhibits": {},
                    # this protocol's first phase is not output-muted, so refrain never
                    # enters warmup and every frame the recorder writes says "run"
                    "state": "run",
                    "reward_event_holds": bool(tap["reward/event.holds"])})
    return out


def _session(tmp_path: Path, *, seconds: float = 60.0, controls: bool = False) -> tuple[Path, Path]:
    """Write a session whose log is what this protocol actually did on this EEG."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    protocol = tmp_path / "ran.refrain"
    protocol.write_text(RAN)
    eeg = _eeg(seconds)
    markers: list[tuple[int, dict]] = [(int(LOWERED["t_s"] * FS), LOWERED)] if controls else []
    first = build_session(tmp_path / "a", fs=FS, channel_names=CHANS, eeg=eeg, chunk=CHUNK,
                          protocol_id="cli_probe", markers=markers, telemetry=[])
    session = load_session(first)
    ir, _, chans = resolve_for_session(session, protocol)
    replay = replay_session(session, ir, chans, follow_log=True)
    folder = build_session(tmp_path / "b", fs=FS, channel_names=CHANS, eeg=eeg, chunk=CHUNK,
                           protocol_id="cli_probe",
                           markers=markers + _reward_records(replay.events, rendered=False),
                           telemetry=_frames(replay))
    return folder, protocol


def test_cli_prints_reconciliation_first_and_writes_json(tmp_path):
    folder, protocol = _session(tmp_path)
    out = tmp_path / "out.json"
    run = subprocess.run([sys.executable, "-W", "error", "-m", "tools.session_report", str(folder),
                          "--protocol", str(protocol), "--json", str(out)],
                         cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stderr == "", run.stderr
    lines = run.stdout.splitlines()

    assert lines[0].startswith("Reconciliation:"), lines[:3]
    assert "RECONCILED" in lines[0] and "DID NOT" not in lines[0]
    printed = "\n".join(lines)
    # which protocol ran, and in which refrain
    assert str(protocol) in printed
    assert hashlib.sha256(protocol.read_bytes()).hexdigest() in printed
    assert refrain.__version__ in printed
    assert "live refrain version: not recorded" in printed
    # the three failures a reader has to be able to tell apart
    assert "coverage" in printed
    # what the tool chose, so the numbers can be read
    assert "70-112.5 Hz" in printed and "3x" in printed
    assert "trusted window" in printed
    # the muscle count cannot be read without its noise floor and its blind spots
    assert "on pure noise at this sample rate the same rule finds about 0.84 a minute" in printed
    assert "first and last 0.5 s cannot be seen at all" in printed
    # this protocol's first phase is not output-muted, so there is no warmup to drop,
    # and the log's own state field is what says so
    assert "no warmup excluded, according to the live telemetry's state field" in printed
    # the reconciliation notes that are not a failure are still printed, not dropped
    assert "Reconciliation detail:" in printed
    assert "match tolerance at most" in printed and "never more than the chunk an event sits in" in printed and "dings:" in printed
    assert "None" not in printed

    doc = json.loads(out.read_text())
    assert doc["reconciliation"]["reconciled"] is True
    assert doc["reconciliation"]["coverage"] == 1.0
    assert doc["tool"]["live_refrain_version"] is None
    assert len(doc["protocols"]) == 1
    entry = doc["protocols"][0]
    assert entry["role"] == "session" and entry["sha256"] == hashlib.sha256(protocol.read_bytes()).hexdigest()
    assert METRIC_KEYS <= set(entry), sorted(METRIC_KEYS - set(entry))
    assert entry["judged"] is True and entry["episodes"] == len(BURSTS)
    assert entry["rewarded_in_episode"] == 1.0
    # no chime was rendered to this client, and the report keeps that apart from the decision
    assert entry["ding_decided_vs_rendered"]["rendered"] == 0
    assert entry["ding_decided_vs_rendered"]["decided"] == len(BURSTS)


def test_cli_compares_a_second_design_and_lists_skipped_controls(tmp_path, capsys):
    from session_report.__main__ import main

    folder, protocol = _session(tmp_path, controls=True)
    compare = tmp_path / "compare.refrain"
    compare.write_text(COMPARE)
    out = tmp_path / "out.json"
    assert main([str(folder), "--protocol", str(protocol), "--compare", str(compare),
                 "--json", str(out)]) == 0

    printed = capsys.readouterr().out
    assert printed.splitlines()[0].startswith("Reconciliation:")
    assert "cli_compare" in printed or str(compare) in printed
    assert "level_uv" in printed                     # the control the comparison cannot take

    doc = json.loads(out.read_text())
    assert [p["role"] for p in doc["protocols"]] == ["session", "comparison"]
    session_entry, comparison = doc["protocols"]
    assert session_entry["skipped_controls"] == []
    assert [s["name"] for s in comparison["skipped_controls"]] == ["level_uv"]
    assert METRIC_KEYS <= set(comparison)
    # the comparison never ran live, so nothing of it was rendered to anyone
    assert comparison["ding_decided_vs_rendered"]["rendered"] is None


def test_a_session_too_short_to_judge_says_so_without_none_percentages(tmp_path, capsys):
    from session_report.__main__ import main

    # 12 s leaves no stretch between the zero-phase filters' head and tail guards, so
    # the truth model could not look anywhere. That must not print as "no episodes".
    folder, protocol = _session(tmp_path, seconds=12.0)
    assert main([str(folder), "--protocol", str(protocol)]) == 0

    printed = capsys.readouterr().out
    assert printed.splitlines()[0].startswith("Reconciliation:")
    assert "could not be judged" in printed
    assert "None" not in printed
    assert "%None" not in printed


# a design that reads a site this recording does not carry
WRONG_SITE = COMPARE.replace('active: "Pz"', 'active: "Cz"').replace("cli_compare", "cli_wrong_site")


def test_a_comparison_it_cannot_replay_is_reported_not_fatal(tmp_path, capsys):
    from session_report.__main__ import main

    folder, protocol = _session(tmp_path)
    wrong = tmp_path / "wrong.refrain"
    wrong.write_text(WRONG_SITE)
    out = tmp_path / "out.json"
    assert main([str(folder), "--protocol", str(protocol), "--compare", str(wrong),
                 "--json", str(out)]) == 0

    printed = capsys.readouterr().out
    assert printed.splitlines()[0].startswith("Reconciliation:")    # the rest of the report survives
    assert "could not be replayed" in printed and "'Cz'" in printed
    doc = json.loads(out.read_text())
    assert "Cz" in doc["protocols"][1]["error"]
    assert doc["protocols"][0]["judged"] is True                   # the session's own is unaffected


def test_a_session_folder_that_is_not_there_is_refused_not_a_traceback(tmp_path, capsys):
    from session_report.__main__ import main

    assert main([str(tmp_path / "no-such-session")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: ")


def test_the_default_protocol_comes_from_the_repo_at_a_ref(tmp_path, capsys):
    """End to end on a shipped protocol: the file is found by id at a git ref.

    This is the invocation with no --protocol, which is how the tool is meant to be
    run, and it exercises what no synthetic protocol does: an artifact inhibit that
    actually mutes, a layered-texture declaration in the protocol's own meta, a
    protocol with no thresholds at all, and derives the truth model cannot reproduce.
    """
    from session_report.__main__ import main

    # Long enough to outlast the protocol's own two-minute output-muted settle phase,
    # which is its warmup window and is excluded from every figure.
    seconds, fs, warmup_s = 200.0, 250.0, 120.0
    n = int(seconds * fs)
    t = np.arange(n) / fs
    rng = np.random.default_rng(3)
    pz = 10.0 * np.sin(2 * np.pi * 10.0 * t) + 3.0 * np.sin(2 * np.pi * 7.0 * t) \
        + 0.3 * rng.standard_normal(n)
    crossover = (t >= 140.0) & (t < 170.0)                     # theta overtakes alpha, in deep1
    pz[crossover] = (20.0 * np.sin(2 * np.pi * 7.0 * t[crossover])
                     + 3.0 * np.sin(2 * np.pi * 10.0 * t[crossover]))
    folder = build_session(tmp_path / "s", fs=fs, channel_names=["Pz"], eeg=pz[:, None], chunk=CHUNK,
                           protocol_id="alpha_theta_narrowband", markers=[], telemetry=[],
                           placements={"site": "Pz"})
    out = tmp_path / "out.json"
    assert main([str(folder), "--protocols-ref", "HEAD", "--json", str(out)]) == 0

    printed = capsys.readouterr().out
    assert printed.splitlines()[0].startswith("Reconciliation:")
    assert "equals HEAD (it was read at HEAD)" in printed
    assert "alpha_theta_narrowband" in printed
    # the warmup it excluded is stated, with the span and where it was read from
    assert f"warmup excluded from every figure below: samples 0 to {int(warmup_s * fs)}" in printed
    assert "the protocol's own first phase, which is output_muted" in printed
    assert "None" not in printed

    entry = json.loads(out.read_text())["protocols"][0]
    assert entry["source"].startswith("ref ")
    assert entry["judged"] is True
    assert entry["warmup"]["end_sample"] == int(warmup_s * fs)
    assert entry["warmup"]["logged_end_sample"] is None        # this fixture logs no telemetry
    assert entry["elapsed_s"] == pytest.approx(seconds - warmup_s, abs=0.1)
    # the ratio view's share is measured after warmup too, while its buckets are not
    assert entry["protocol_views"]["ratio"]["share_measured_from_s"] == pytest.approx(warmup_s)
    # the two derives the recorder itself could not classify, named but not blocking
    assert entry["unreproducible"] == ["theta_progress", "ratio_progress"]
    # its own review contract, read from the protocol rather than from a manifest
    ratio = entry["protocol_views"]["ratio"]
    assert ratio["ratio_stream"] == "theta_alpha_ratio"
    assert ratio["declared_in"] == "the protocol's own meta"
    assert all(b["target_median"] == 0.85 for b in ratio["buckets"])     # the control's default
    # layered texture is declared in the protocol's meta, not in this session's audio block
    assert "feedback_state" in entry["protocol_views"]
    # its artifact inhibit really mutes, and this protocol declares no threshold at all
    assert entry["mute_share"]["artifact"] > 0.0
    assert entry["thresholds_per_block"] == {}
    assert any("no threshold" in note for note in entry["notes"])

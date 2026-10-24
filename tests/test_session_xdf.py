"""The XDF chunk reader of tools/session_report: items come back in file order."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from session_fixture import EEG_ID, EEG_T0, _chunk, _varlen, build_session  # noqa: E402
from session_report.xdf_chunks import read_xdf_items  # noqa: E402


def test_reader_preserves_chunk_and_marker_order(tmp_path):
    d = build_session(tmp_path, fs=250, channel_names=["Pz"], eeg=np.arange(1000.)[:, None], chunk=25,
                      protocol_id="p", markers=[(100, {"type": "control_change", "t_s": 0.4})], telemetry=[])
    infos, items, _ = read_xdf_items(d / "raw.xdf")
    kinds = [i.kind for i in items]
    assert kinds[:5] == ["samples"] * 4 + ["marker"]          # marker after sample 100 = after chunk 4
    assert np.concatenate([i.data for i in items if i.kind == "samples"])[:, 0].tolist() == list(range(1000))
    assert infos[1].channel_names == ["Pz"] and infos[1].srate == 250


def test_reader_tolerates_missing_footer(tmp_path):
    d = build_session(tmp_path, fs=250, channel_names=["Pz"], eeg=np.zeros((500, 1)), chunk=25,
                      protocol_id="p", markers=[], telemetry=[], footer=False)
    _, items, _ = read_xdf_items(d / "raw.xdf")
    assert sum(len(i.data) for i in items if i.kind == "samples") == 500


def test_reader_steps_over_unmodelled_chunks_and_reports_trailing_junk(tmp_path):
    d = build_session(tmp_path, fs=250, channel_names=["Pz"], eeg=np.arange(50.)[:, None], chunk=25,
                      protocol_id="p", markers=[], telemetry=[], footer=False)
    raw = (d / "raw.xdf").read_bytes()
    clean_size = len(raw)
    # flag-0 form: second sample carries no timestamp, so it is deduced as previous + 1/fs
    t_last = EEG_T0 + 50 / 250
    flag0 = (struct.pack("<I", EEG_ID) + _varlen(2)
             + struct.pack("<Bd", 8, t_last) + struct.pack("<d", 50.0)
             + struct.pack("<B", 0) + struct.pack("<d", 51.0))
    spliced = (raw + _chunk(5, bytes(16)) + _chunk(99, b"unknown") + _chunk(3, flag0)
               + _chunk(4, struct.pack("<Idd", EEG_ID, 0.0, 0.0)))
    (d / "raw.xdf").write_bytes(spliced + b"\xff\xff\xff")

    _, items, notes = read_xdf_items(d / "raw.xdf")
    samples = [i for i in items if i.kind == "samples"]
    assert np.concatenate([i.data for i in samples])[:, 0].tolist() == [float(v) for v in range(52)]
    assert samples[-1].timestamps[1] == pytest.approx(t_last + 1 / 250)
    assert notes.stopped_early and notes.reason
    assert notes.bytes_parsed == len(spliced) and notes.file_size == len(spliced) + 3
    assert clean_size < notes.bytes_parsed


def test_reader_reports_clean_end(tmp_path):
    d = build_session(tmp_path, fs=250, channel_names=["Pz"], eeg=np.zeros((50, 1)), chunk=25,
                      protocol_id="p", markers=[], telemetry=[])
    _, _, notes = read_xdf_items(d / "raw.xdf")
    assert not notes.stopped_early and notes.reason is None and notes.bytes_parsed == notes.file_size

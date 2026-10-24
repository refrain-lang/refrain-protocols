"""The XDF chunk reader of tools/session_report: items come back in file order."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from session_fixture import build_session  # noqa: E402
from session_report.xdf_chunks import read_xdf_items  # noqa: E402


def test_reader_preserves_chunk_and_marker_order(tmp_path):
    d = build_session(tmp_path, fs=250, channel_names=["Pz"], eeg=np.arange(1000.)[:, None], chunk=25,
                      protocol_id="p", markers=[(100, {"type": "control_change", "t_s": 0.4})], telemetry=[])
    infos, items = read_xdf_items(d / "raw.xdf")
    kinds = [i.kind for i in items]
    assert kinds[:5] == ["samples"] * 4 + ["marker"]          # marker after sample 100 = after chunk 4
    assert np.concatenate([i.data for i in items if i.kind == "samples"])[:, 0].tolist() == list(range(1000))
    assert infos[1].channel_names == ["Pz"] and infos[1].srate == 250


def test_reader_tolerates_missing_footer(tmp_path):
    d = build_session(tmp_path, fs=250, channel_names=["Pz"], eeg=np.zeros((500, 1)), chunk=25,
                      protocol_id="p", markers=[], telemetry=[], footer=False)
    _, items = read_xdf_items(d / "raw.xdf")
    assert sum(len(i.data) for i in items if i.kind == "samples") == 500

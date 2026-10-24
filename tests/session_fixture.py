"""Helper (not a test module): write a synthetic recorder session to disk.

``build_session`` writes raw.xdf, feedback-history.jsonl and
feedback-session.json in the layout the recorder produces. The byte layout is
copied from the recorder's xdf_writer; that project is not imported.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

EEG_ID, MARKER_ID = 1, 2
EEG_T0 = 1.79e9          # EEG timestamps are a large absolute clock


def _varlen(v: int) -> bytes:
    if v <= 0xFF:
        return struct.pack("<BB", 1, v)
    if v <= 0xFFFFFFFF:
        return struct.pack("<BI", 4, v)
    return struct.pack("<BQ", 8, v)


def _chunk(tag: int, content: bytes) -> bytes:
    return _varlen(2 + len(content)) + struct.pack("<H", tag) + content


def _stream_header(stream_id, name, ctype, labels, srate, fmt) -> bytes:
    chans = "".join(f"<channel><label>{c}</label></channel>" for c in labels)
    xml = (f'<?xml version="1.0"?><info><name>{name}</name><type>{ctype}</type>'
           f"<channel_count>{len(labels)}</channel_count><nominal_srate>{srate}</nominal_srate>"
           f"<channel_format>{fmt}</channel_format><desc><channels>{chans}</channels></desc></info>")
    return _chunk(2, struct.pack("<I", stream_id) + xml.encode())


def _eeg_chunk(ts: np.ndarray, data: np.ndarray) -> bytes:
    buf = struct.pack("<I", EEG_ID) + _varlen(len(data))
    for t, row in zip(ts, data):
        buf += struct.pack("<Bd", 8, t) + row.astype("<f8").tobytes()
    return _chunk(3, buf)


def _marker_chunk(ts: float, record: dict) -> bytes:
    label = json.dumps(record).encode()
    return _chunk(3, struct.pack("<I", MARKER_ID) + _varlen(1) + struct.pack("<Bd", 8, ts)
                  + _varlen(len(label)) + label)


def _footer(stream_id, first, last, count, srate) -> bytes:
    xml = (f'<?xml version="1.0"?><info><first_timestamp>{first}</first_timestamp>'
           f"<last_timestamp>{last}</last_timestamp><sample_count>{count}</sample_count>"
           f"<measured_srate>{srate}</measured_srate></info>")
    return _chunk(6, struct.pack("<I", stream_id) + xml.encode())


def build_session(dir: Path, *, fs: float, channel_names: list[str], eeg: np.ndarray, chunk: int,
                  protocol_id: str, markers: list[tuple[int, dict]], telemetry: list[dict],
                  footer: bool = True, device_model: str = "BrainBit Flex",
                  placements: dict | None = None, modes: dict | None = None,
                  audio: dict | None = None, manifest: dict | None = None) -> Path:
    """Write a session into ``dir`` and return ``dir``.

    ``markers`` are (sample_index, record) pairs, written into raw.xdf between
    EEG chunks at that sample position and into feedback-history.jsonl.
    ``telemetry`` records go to feedback-history.jsonl only. An entry may be a
    (sample_index, record) pair; if any is, the file keeps position order (markers
    first, then telemetry at the same sample) instead of ``t_s`` order, so a test can
    give telemetry a ``t_s`` that disagrees with where it sits in the file.
    ``audio`` and ``manifest`` are written into feedback-session.json only when
    given, as the recorder writes them (``audio.feedback_style`` declares layered
    texture; ``manifest.review_contract`` the ratio and target to review).
    """
    dir = Path(dir)
    dir.mkdir(parents=True, exist_ok=True)
    eeg = np.asarray(eeg, dtype=np.float64)
    ts = EEG_T0 + np.arange(len(eeg)) / fs
    by_pos: dict[int, list[dict]] = {}
    for pos, rec in markers:
        by_pos.setdefault(pos, []).append(rec)

    out = bytearray(b"XDF:")
    out += _chunk(1, b'<?xml version="1.0"?><info><version>1.0</version></info>')
    out += _stream_header(EEG_ID, "Feedback EEG", "EEG", channel_names, fs, "double64")
    out += _stream_header(MARKER_ID, "Feedback Markers", "Markers", ["marker"], 0, "string")

    stops = sorted({p for p in by_pos if 0 < p < len(eeg)} | set(range(0, len(eeg), chunk)) | {len(eeg)})
    for rec in by_pos.get(0, []):
        out += _marker_chunk(rec["t_s"], rec)
    for a, b in zip(stops, stops[1:]):
        out += _eeg_chunk(ts[a:b], eeg[a:b])
        for rec in by_pos.get(b, []):
            out += _marker_chunk(rec["t_s"], rec)
    for p in sorted(p for p in by_pos if p > len(eeg)):
        for rec in by_pos[p]:
            out += _marker_chunk(rec["t_s"], rec)
    if footer:
        if len(eeg):
            out += _footer(EEG_ID, ts[0], ts[-1], len(eeg), fs)
        times = [rec["t_s"] for _, rec in markers]
        out += _footer(MARKER_ID, min(times, default=0), max(times, default=0), len(markers), 0)
    (dir / "raw.xdf").write_bytes(bytes(out))

    if any(isinstance(t, tuple) for t in telemetry):
        keyed = [(p, 0, rec) for p, rec in markers] + [(t[0], 1, t[1]) for t in telemetry]
        records = [rec for _, _, rec in sorted(keyed, key=lambda x: x[:2])]
    else:
        records = [rec for _, rec in markers] + list(telemetry)
        records.sort(key=lambda r: r.get("t_s", 0.0))
    (dir / "feedback-history.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))

    session = {
        "protocol_id": protocol_id,
        "plugin_id": protocol_id,
        "device": {"model": device_model, "sample_rate_hz": fs, "channels": list(channel_names)},
        "placements": placements or {},
        "modes": modes or {},
        "initial_controls": {},
        "completed": footer,
    }
    if audio is not None:
        session["audio"] = audio
    if manifest is not None:
        session["manifest"] = manifest
    (dir / "feedback-session.json").write_text(json.dumps(session, indent=2))
    return dir

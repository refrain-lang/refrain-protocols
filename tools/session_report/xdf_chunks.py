"""Read a coherence-recorder raw.xdf in exact file order.

The reader returns what the file holds, chunk by chunk: EEG sample chunks and
marker chunks interleaved as they were written. Timestamps are returned as
stored (no dejittering, no rebasing). Chunk sizes are never assumed.

Only file header (1), stream header (2) and samples (3) are modelled. Every
other tag (clock offset, boundary, footer, unknown) is stepped over by its
length, so a session that ended without a footer still loads. A final chunk cut
short by an unclean exit ends the read rather than raising.
"""
from __future__ import annotations

import json
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

MAGIC = b"XDF:"
TAG_STREAM_HEADER = 2
TAG_SAMPLES = 3

_NUMERIC = {
    "double64": "<f8", "float32": "<f4",
    "int8": "<i1", "int16": "<i2", "int32": "<i4", "int64": "<i8",
}


@dataclass
class StreamInfo:
    stream_id: int
    name: str
    channel_format: str
    channel_names: list[str]
    srate: float


@dataclass
class Item:
    kind: Literal["samples", "marker"]
    stream_id: int
    data: np.ndarray | None        # samples x channels, float64 (None for a marker)
    timestamps: np.ndarray
    marker: dict | None            # parsed JSON label (None for samples)
    index: int                     # position in file order


@dataclass
class ReadNotes:
    """What the read covered, so a caller can tell a clean end from an early stop."""
    file_size: int
    bytes_parsed: int
    stopped_early: bool
    reason: str | None             # short explanation when stopped_early


def _varlen(buf: bytes, pos: int) -> tuple[int, int]:
    width = buf[pos]
    fmt = {1: "<B", 4: "<I", 8: "<Q"}[width]
    return struct.unpack_from(fmt, buf, pos + 1)[0], pos + 1 + width


def _parse_stream_header(content: bytes) -> StreamInfo:
    stream_id = struct.unpack_from("<I", content)[0]
    root = ET.fromstring(content[4:].decode("utf-8"))
    names = [(c.findtext("label") or "") for c in root.findall("./desc/channels/channel")]
    return StreamInfo(
        stream_id=stream_id,
        name=(root.findtext("name") or "").strip(),
        channel_format=(root.findtext("channel_format") or "").strip(),
        channel_names=names,
        srate=float(root.findtext("nominal_srate") or 0.0),
    )


def _decode_marker(label: str) -> dict:
    try:
        parsed = json.loads(label)
    except ValueError:
        return {"raw": label}
    return parsed if isinstance(parsed, dict) else {"raw": label}


def _parse_samples(content: bytes, info: StreamInfo, state: dict) -> list[Item]:
    n, pos = _varlen(content, 4)
    is_string = info.channel_format == "string"
    n_ch = max(len(info.channel_names), 1)
    dtype = None if is_string else np.dtype(_NUMERIC[info.channel_format])
    last_ts = state.get(info.stream_id, float("nan"))
    stamps = np.empty(n)
    rows: list[np.ndarray] = []
    labels: list[str] = []
    for i in range(n):
        flag = content[pos]
        pos += 1
        if flag == 8:
            last_ts = struct.unpack_from("<d", content, pos)[0]
            pos += 8
        elif flag == 0:
            # no stored timestamp: the spec deduces it from the previous sample
            last_ts = last_ts + (1.0 / info.srate if info.srate else 0.0)
        else:
            raise ValueError(f"bad timestamp width {flag} in stream {info.stream_id}")
        stamps[i] = last_ts
        if is_string:
            size, pos = _varlen(content, pos)
            labels.append(content[pos:pos + size].decode("utf-8"))
            pos += size
        else:
            rows.append(np.frombuffer(content, dtype=dtype, count=n_ch, offset=pos).astype(np.float64))
            pos += n_ch * dtype.itemsize
    state[info.stream_id] = last_ts
    if is_string:
        return [Item("marker", info.stream_id, None, stamps[i:i + 1], _decode_marker(labels[i]), 0)
                for i in range(n)]
    data = np.vstack(rows) if rows else np.empty((0, n_ch))
    return [Item("samples", info.stream_id, data, stamps, None, 0)]


def read_xdf_items(path: Path) -> tuple[dict[int, StreamInfo], list[Item], ReadNotes]:
    """Return the stream headers, every sample/marker item in file order, and read notes.

    A samples chunk yields one ``samples`` item; a marker chunk yields one
    ``marker`` item per marker sample. ``Item.index`` counts items in order.
    ``ReadNotes.stopped_early`` is True when bytes remain that could not be
    parsed as a chunk (corruption or a cut-off tail).
    """
    buf = Path(path).read_bytes()
    if buf[:4] != MAGIC:
        raise ValueError(f"{path} is not an XDF file")
    infos: dict[int, StreamInfo] = {}
    items: list[Item] = []
    state: dict[int, float] = {}
    pos = 4
    reason = None
    while pos < len(buf):
        try:
            length, body = _varlen(buf, pos)
        except (IndexError, struct.error, KeyError):
            reason = "unreadable chunk length"
            break
        if length < 2 or body + length > len(buf):
            reason = "chunk length is invalid or runs past the end of the file"
            break
        tag = struct.unpack_from("<H", buf, body)[0]
        content = buf[body + 2:body + length]
        pos = body + length
        if tag == TAG_STREAM_HEADER:
            info = _parse_stream_header(content)
            infos[info.stream_id] = info
        elif tag == TAG_SAMPLES:
            stream_id = struct.unpack_from("<I", content)[0]
            if stream_id in infos:
                for item in _parse_samples(content, infos[stream_id], state):
                    item.index = len(items)
                    items.append(item)
        # every other tag is stepped over by length
    return infos, items, ReadNotes(len(buf), pos, reason is not None, reason)

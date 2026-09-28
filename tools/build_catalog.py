#!/usr/bin/env python3
"""Build catalog.json — a derived CACHE, not the source of truth.

Scans protocols/ + drafts/, reads each file's `meta` tags by PARSE ONLY
(tolerant: a file that won't fully resolve still lists), and emits a flat
index the picker can read. A host app does exactly this at runtime over its
bundled set PLUS the user's own protocol folders — this script just produces
the committed convenience copy for the reference set.

Run:  python tools/build_catalog.py   ->  catalog.json
"""
from __future__ import annotations

import json
from pathlib import Path

from refrain.parser import parse

ROOT = Path(__file__).resolve().parents[1]


# Schema defaults the read path must APPLY. jsonschema validates against a
# default but never fills one in, so a host that filters on meta["modality"]
# would drop every user-authored EEG protocol -- they omit the line, since
# only the reference set was backfilled. Supply it here instead.
SCHEMA_DEFAULTS = {"modality": "eeg"}


def read_meta(path: Path) -> dict:
    """Parse-only meta extraction (no resolve, no amp). Returns {} + an
    _error marker if the file won't even parse, so the picker can show it.

    Schema defaults (see SCHEMA_DEFAULTS) are applied to the result, so a
    file that omits an optional-with-default tag still reads back with it.
    Unknown values are passed through untouched -- bucketing them into
    "Other" is the host's job, not this function's."""
    try:
        f = parse(path.read_text())
    except Exception as e:  # malformed user file: list it, flagged
        return {"_error": f"{type(e).__name__}: {e}"}
    out: dict = {}
    for stmt in f.protocol.body:
        if getattr(stmt, "keyword", None) == "meta":
            for a in stmt.body:
                v = a.value
                if hasattr(v, "elements"):
                    out[a.target] = [getattr(e, "value", None) for e in v.elements]
                else:
                    out[a.target] = getattr(v, "value", None)
    for key, default in SCHEMA_DEFAULTS.items():
        out.setdefault(key, default)
    return out


def main() -> None:
    entries = []
    for d in ("protocols", "drafts"):
        # rglob: retired/legacy protocols live in a subfolder (protocols/eeg/legacy/)
        for path in sorted((ROOT / d).rglob("*.refrain")):
            meta = read_meta(path)
            entries.append({
                "file": path.relative_to(ROOT).as_posix(),
                "name": path.stem,
                "draft": d == "drafts" or meta.get("status") in ("draft", "roadmap"),
                "meta": meta,
            })
    catalog = {"schema": "protocol-meta/1", "count": len(entries), "protocols": entries}
    (ROOT / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    n_draft = sum(1 for e in entries if e["draft"])
    print(f"catalog.json: {len(entries)} protocols ({n_draft} draft/roadmap)")


if __name__ == "__main__":
    main()

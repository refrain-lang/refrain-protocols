# refrain-protocols

Reference neurofeedback & HRV protocol library for [Refrain](https://github.com/refrain-lang/refrain) — **vendor-neutral, citation-backed, and organized by metadata, not folders.**

> ⚠️ **Every protocol here is `status = "draft"` (untested).** The clinical parameters are curated; the files are generated/seeded and have *not* been clinically validated in this system. Treat them as starting points, not turnkey clinical tools. See `docs/evidence.md`.

## How it's organized — by tags, not directories

`protocols/` is **flat**. A protocol's `meta` block carries the tags that organize it:

```refrain
meta {
  description     = "SMR/THETA up-train at Cz (adaptive)"
  status          = "draft"            // our maturity: draft | roadmap | reviewed | stable
  evidence        = "established"      // clinical support: established | probable | exploratory
  citation        = "Sterman; Lubar; Arns 2009"
  goals           = ["adhd_attention", "sensorimotor_sleep"]   // multi-membership!
  bands           = ["smr", "theta"]
  site            = "Cz"
  threshold_style = "adaptive"         // drives the Adaptive/Baseline filter
}
```

The same protocol legitimately appears under **both** ADHD/Attention and Sensorimotor/Sleep — folders can't do that; tags can. The controlled vocabulary is in `schema/protocol-meta.schema.json`; see `docs/tagging.md`.

## Files are the source of truth; the catalog is a cache

A host app **scans protocol folders and reads each file's `meta`** (`refrain.read_meta`, parse-only — works even if a protocol won't run on the attached amp). `catalog.json` is a regenerable convenience for the reference set — drop your own `.refrain` in a folder and it appears, no rebuild. See `docs/host-app-guide.md`.

## Layout

```
protocols/      # flat, runnable(ish) drafts — clear names: <target>_<site>[_baseline]
drafts/         # documented but NOT resolvable yet (e.g. SCP — needs engine features)
lib/sessions/   # canonical session templates (defaults; host overrides durations/counts)
schema/         # protocol-meta.schema.json — the tag contract
docs/           # host-app-guide, tagging, conventions, evidence, contributing
tools/          # gen_seed_protocols.py (regenerates the operant set), build_catalog.py
catalog.json    # derived cache (CI rebuilds it)
```

## Naming
`<target>_<site>[_baseline].refrain` — adaptive is the bare name, `_baseline` is the only suffix. No `_classic`/`_staged`/`_brainbit`/`_v1`. Hardware/session/goals live in `meta`.

## Use from a host
```python
import refrain
meta = refrain.read_meta("protocols/smr_theta_cz.refrain")  # parse-only tags
# ... bucket by meta['goals'], filter by meta['threshold_style'], etc.
```

## License
Apache-2.0.

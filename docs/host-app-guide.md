# Host-app guide — building a protocol chooser

Recommended best practice for apps (like a recorder) that present these protocols to a clinician. The guiding principle: **the protocol files are the source of truth; a catalog is a derived cache.** A clinician dropping their own `.refrain` into a folder must appear, correctly organized, with no rebuild.

## 1. Discovery
- Scan one or more directories — the **bundled reference set** *plus* the **user's folder(s)** — and run `refrain.read_meta(file)` on each. Build the index in memory.
- **List by parse, resolve on select.** Parsing is fast and tolerant; it lets you *show* every protocol (even ones that won't run on the attached amp). Full `resolve()` happens only when the clinician picks one — that's where "needs DC amp / missing channel" errors surface.
- Treat `catalog.json` as a **cache keyed by file mtime**, rebuilt on change — never the authority.

## 2. Organize from metadata
- **Primary grouping = `goals`**, and it's **multi-membership** — one protocol can sit under several categories.
- **Filter chips:** `threshold_style` (Adaptive / Baseline), amp-compatibility (works-with-attached-amp, from `hardware` + `requires_features`), ★ Favorites (host-side per-user state — *not* in the protocol).
- **Row chips:** `bands`, `site`, `evidence` tier.
- **Search** spans `description` + name + all tags.
- **Sort within a group:** `established` evidence first, then alphabetical; float Favorites/Recents up.

## 3. States & trust (clinically important)
Badge each protocol by what it is:
- **Vetted reference** — has `citation` + `evidence`, `status` ≥ `reviewed`.
- **Draft / untested** — `status` in `{draft, roadmap}` (everything in the seed library today). Show a clear "untested" badge.
- **Custom / user** — no citation; badge "Custom — not clinically validated."
- **⚠ Won't parse** — show the parse error, don't hide the file.
- **Incompatible / clinical-amp-only** — grey out with a tooltip ("requires DC-coupled amp", from `hardware`/`requires_features`).

Never crash the picker on a malformed user file.

## 4. Select → setup
- On select, `resolve()` against the attached amp → surfaces `requires` (channels, coupling) mismatches **before** Start.
- Show the **session structure** (blocks × durations) with the **override controls** — block length, block count, which-blocks — these are host-side parameters you send to the engine (the protocol carries defaults).
- Show the **live-tunable controls** (thresholds, weights) adjustable mid-session.

## 5. Clinical-safety UX
Surface `evidence` + `citation` + `indication`/`population` so the choice is informed; mark `custom`/untested clearly; never auto-select; show `safety_monitoring` if present.

## 6. Extensibility & performance
- Unknown `goals`/`bands` → an **"Other"** bucket, never dropped.
- Validate user files against `schema/protocol-meta.schema.json`; **warn** on unknown tags but still list them.
- Cache the index; virtualize long lists; lazy-`resolve()` on selection.

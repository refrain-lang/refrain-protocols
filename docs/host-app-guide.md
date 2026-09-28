# Host-app guide — building a protocol chooser

Recommended best practice for apps (like a recorder) that present these protocols to a practitioner. The guiding principle: **the protocol files are the source of truth; a catalog is a derived cache.** Someone dropping their own `.refrain` into a folder must see it appear, correctly organized, with no rebuild.

## 1. Discovery
- Scan one or more directories — the **bundled reference set** *plus* the **user's folder(s)** — and run `refrain.read_meta(file)` on each. Build the index in memory.
- **List by parse, resolve on select.** Parsing is fast and tolerant; it lets you *show* every protocol (even ones that won't run on the attached amp). Full `resolve()` happens only when the user picks one — that's where "needs DC amp / missing channel" errors surface.
- Treat `catalog.json` as a **cache keyed by file mtime**, rebuilt on change — never the authority.

## 2. Organize from metadata
- **Primary grouping = `goals`**, and it's **multi-membership** — one protocol can sit under several categories.
- **Filter chips:** `modality` (EEG / HRV / GSR / …), `threshold_style` (Adaptive / Baseline), device-compatibility (works-with-attached-device, from `hardware` + `requires_features`), ★ Favorites (host-side per-user state — *not* in the protocol).
- **Row chips:** `modality`, `bands`, `site`, `evidence` tier.
- **Search** spans `description` + name + all tags.
- **Sort within a group:** `established` evidence first, then alphabetical; float Favorites/Recents up.

## 3. States & trust
Badge each protocol by what it is:
- **Vetted reference** — has `citation` + `evidence`, `status` ≥ `reviewed`.
- **Draft / untested** — `status` in `{draft, roadmap}` (most of the library today). Show a clear "untested" badge.
- **Custom / user** — no citation; badge "Custom — not validated."
- **⚠ Won't parse** — show the parse error, don't hide the file.
- **Incompatible / research-amp-only** — grey out with a tooltip ("requires DC-coupled amp", from `hardware`/`requires_features`).

Never crash the picker on a malformed user file.

## 4. Select → setup
- On select, `resolve()` against the attached amp → surfaces `requires` (channels, coupling) mismatches **before** Start.
- Show the **session structure** (blocks × durations) with the **override controls** — block length, block count, which-blocks — these are host-side parameters you send to the engine (the protocol carries defaults).
- Show the **live-tunable controls** (thresholds, weights) adjustable mid-session.

## 5. Trust & provenance
Surface `evidence` + `citation` so the choice is informed — and present them as **where the technique comes from**, not as evidence that it will work for this person. An `established` tier means the approach has a track record in the literature; it is not an outcome claim, and the UI should not read like one.

Mark `custom` and untested protocols clearly; never auto-select.

The distributed library ships **no** `indication`, `population`, `safety_monitoring`, or `outcome_measures` tags — a neutral library makes no diagnostic or therapeutic claim. A host that needs any of that keeps it host-side, as its own data, and owns what it asserts.

## 6. Extensibility & performance
- Unknown `goals`/`bands`/`modality` → an **"Other"** bucket, never dropped. Closing the schema enum did not make the picker strict: a user's own goal string must still list.
- Validate user files against `schema/protocol-meta.schema.json`; **warn** on unknown tags but still list them.
- Cache the index; virtualize long lists; lazy-`resolve()` on selection.

# Contributing a protocol

1. **Add the file** to `protocols/` (or `drafts/` if it can't resolve yet). Use the naming convention (`docs/conventions.md`).
2. **Add its companion guide.** Every protocol must have a Markdown file with the same base name beside it: `foo.refrain` → `foo.md`. Start from [`docs/protocol-guide-template.md`](protocol-guide-template.md). The guide must distinguish cited source material from local implementation choices and include stable links for its references, in the same general-wellness vocabulary as `meta` — no indications, no populations, no diagnostic or therapeutic claim.
3. **Fill `meta`** per `schema/protocol-meta.schema.json` — at minimum `description`, `status`, `goals`. Add `citation` if `status` > `draft`.
4. **Regenerate the catalog:** `python tools/build_catalog.py`.
5. **Run CI locally:** `pytest -q` (parse + meta schema + catalog-current).
6. **Open a PR.**

The companion-guide rule applies to the whole library. Existing protocols are
being backfilled incrementally; a new protocol or a material change to an
existing protocol must include or update its guide in the same PR.

The generated operant set was originally produced by a seed generator that is no longer in this repo (`tools/` holds only `build_catalog.py`). Those files are now edited directly, like any other protocol.

## Bar for leaving `draft`
See `docs/evidence.md`. In short: must `resolve()` against a real amp profile, reviewed bands/sites/thresholds, and a real citation (CI rejects empty values and known placeholder strings; judging a thin reference is review's job).

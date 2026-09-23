# Contributing a protocol

1. **Add the file** to `protocols/` (or `drafts/` if it can't resolve yet). Use the naming convention (`docs/conventions.md`).
2. **Add its companion guide.** Every protocol must have a Markdown file with the same base name beside it: `foo.refrain` → `foo.md`. Start from [`docs/protocol-guide-template.md`](protocol-guide-template.md). The guide must distinguish cited source material from local implementation choices and include stable links for its references.
3. **Fill `meta`** per `schema/protocol-meta.schema.json` — at minimum `description`, `status`, `goals`. Add `citation` if `status` > `draft`.
4. **Regenerate the catalog:** `python tools/build_catalog.py`.
5. **Run CI locally:** `pytest -q` (parse + meta schema + catalog-current).
6. **Open a PR.**

The companion-guide rule applies to the whole library. Existing protocols are
being backfilled incrementally; a new protocol or a material change to an
existing protocol must include or update its guide in the same PR.

For the generated operant set, edit the `TABLE` in `tools/gen_seed_protocols.py` and re-run it rather than hand-editing the generated files.

## Bar for leaving `draft`
See `docs/evidence.md`. In short: must `resolve()` against a real amp profile, clinically reviewed bands/sites/thresholds, and a real citation.

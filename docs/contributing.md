# Contributing a protocol

1. **Add the file** to `protocols/` (or `drafts/` if it can't resolve yet). Use the naming convention (`docs/conventions.md`).
2. **Fill `meta`** per `schema/protocol-meta.schema.json` — at minimum `description`, `status`, `goals`. Add `citation` if `status` > `draft`.
3. **Regenerate the catalog:** `python tools/build_catalog.py`.
4. **Run CI locally:** `pytest -q` (parse + meta schema + catalog-current).
5. **Open a PR.**

For the generated operant set, edit the `TABLE` in `tools/gen_seed_protocols.py` and re-run it rather than hand-editing the generated files.

## Bar for leaving `draft`
See `docs/evidence.md`. In short: must `resolve()` against a real amp profile, clinically reviewed bands/sites/thresholds, and a real citation.

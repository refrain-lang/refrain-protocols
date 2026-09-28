# Contributing a protocol

1. **Add the file** to `protocols/` (or `drafts/` if it can't resolve yet). Use the naming convention (`docs/conventions.md`).
2. **Fill `meta`** per `schema/protocol-meta.schema.json` — at minimum `description`, `status`, `goals`. Add `citation` if `status` > `draft`.
3. **Regenerate the catalog:** `python tools/build_catalog.py`.
4. **Run CI locally:** `pytest -q` (parse + meta schema + catalog-current).
5. **Open a PR.**

The generated operant set was originally produced by a seed generator that is no longer in this repo (`tools/` holds only `build_catalog.py`). Those files are now edited directly, like any other protocol.

## Bar for leaving `draft`
See `docs/evidence.md`. In short: must `resolve()` against a real amp profile, reviewed bands/sites/thresholds, and a real citation (CI rejects empty values and known placeholder strings; judging a thin reference is review's job).

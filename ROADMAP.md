# Roadmap

## Status of the seed library
Everything in `protocols/` + `drafts/` is **`status = "draft"`** — parse-valid and tag-complete, but **not clinically validated in this system**. The path forward is to graduate protocols `draft → reviewed → stable` one at a time, which flips on the stricter CI gates (must `resolve()`, must have a citation).

## Known dependencies / engine work
1. **`number` control kind** (in `refrain-lang/refrain`). `composite_smr_theta_cz.refrain` uses `number` weights (unitless relative weights, replacing the misleading `percent`). It **parses today but won't `resolve()` until** refrain ships the `number` kind. → small additive refrain PR + release, then pin it here.
2. **`refrain.read_meta` / `refrain catalog`** (in refrain). Parse-only meta read as a *stable public API* (the host shouldn't walk `SectionBlock` internals). `tools/build_catalog.py` currently does the walk itself; it should switch to the public API once it lands.
3. **Amp profiles + resolve gate.** Add `amp_profiles/` and turn on a `resolve()` test for non-draft protocols (drafts only need to parse).
4. **SCP / trial paradigm** (`drafts/scp_cz.refrain`). Needs: unary-minus/signed literals, a `trials` construct, per-trial baseline correction, robust DC extraction. Tracked as the north-star for trial-based protocols.

## Protocol coverage (all draft)
- **Operant up/down** (generated): SMR/θ, θ/β, θ↓, slow↓ (Cz & Fz), SMR@C4, β↑@C3/Fz, α↑@Pz, hi-β↓@Cz, peak-α↑, Fmθ↑, α↓@Pz (Lanius), θ↑@Pz — each × adaptive/baseline.
- **Specials** (hand-authored): composite SMR/θ (weighted), α/θ crossover, α-coherence C3/C4, FAA F3/F4, HRV resonance.
- **Roadmap**: SCP.

## Wanted next
- Hardware overlays (`brainbit_flex`, `clinical_amp`) via `extends`, once the multi-parent `extends` story is confirmed in `refrain/compose.py`.
- A `refrain catalog <dir>` CLI so host apps don't ship their own scanner.
- Per-protocol clinical review + citation firming as each leaves `draft`.

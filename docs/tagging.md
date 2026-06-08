# Tagging — the metadata vocabulary

The shared contract that lets host apps organize protocols without folders. Refrain itself is **meta-agnostic** (any `meta` field is allowed); this vocabulary is a *convention*, enforced for this library by CI and consumed by host apps. Machine-checkable form: `schema/protocol-meta.schema.json`.

## The two orthogonal axes (don't conflate)

| Field | Means | Values |
|---|---|---|
| **`status`** | *Have we tested this file?* | `draft` → `roadmap` → `reviewed` → `stable` |
| **`evidence`** | *Does the science support it?* | `established` / `probable` / `exploratory` |

A protocol can be `evidence = "established"` (great science) but `status = "draft"` (we haven't validated our file yet) — which is the state of the **entire seed library** today.

## Organizing fields (drive the picker)

- **`goals`** *(list, controlled)* — the category groups; **multi-membership**. Vocab: `adhd_attention`, `sensorimotor_sleep`, `alertness_performance`, `calm_anxiety`, `flow_connectivity`, `deep_meditative`, `mood_regulation`, `trauma_recovery`.
- **`bands`** *(list)* — chips: `smr`, `theta`, `alpha`, `beta`, `high-beta`, `delta`, `hrv-lf`, …
- **`threshold_style`** — `adaptive` / `baseline` / `crossover` → the Adaptive/Baseline filter.
- **`site`**, **`direction`** — `up`/`down`/`composite`/`crossover`/`asymmetry`.
- **`hardware`** + **`requires_features`** — `generic` / `clinical_amp`; features like `dc_coupling`, `trials` → grey-out logic.
- **`modality`** — `eeg` (default) / `hrv`.

## Rules
- `description`, `status`, `goals` are **required**.
- `citation` is **required once `status` > `draft`**.
- Unknown enum values are **not errors** for a host — they fall into an "Other" bucket. CI for *this* repo is stricter (it validates against the schema) so the reference set stays consistent; user protocols are only warned.

## Favorites
Favorites are **host-side per-user state**, never a protocol tag.

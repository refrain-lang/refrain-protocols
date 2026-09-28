# Tagging — the metadata vocabulary

The shared contract that lets host apps organize protocols without folders. Refrain itself is **meta-agnostic** (any `meta` field is allowed); this vocabulary is a *convention*, enforced for this library by CI and consumed by host apps. Machine-checkable form: `schema/protocol-meta.schema.json`.

## The two orthogonal axes (don't conflate)

| Field | Means | Values |
|---|---|---|
| **`status`** | *Have we tested this file?* | `draft` → `roadmap` → `reviewed` → `stable` |
| **`evidence`** | *How established is the approach in prior art?* | `established` / `probable` / `exploratory` |

A protocol can be `evidence = "established"` (long track record for the approach) but `status = "draft"` (we haven't validated our file yet) — which is the state of most of the library today.

`evidence` and `citation` are **provenance**: where a technique comes from, not what it does for anyone. They are never an outcome claim.

## Organizing fields (drive the picker)

- **`goals`** *(list, controlled)* — the category groups; **multi-membership**. These are wellness-framed **training goals, not indications**: nothing here names a condition, and no diagnostic or therapeutic claim is made or implied.

  | Goal id | Label | Typical modalities |
  |---|---|---|
  | `focus_attention` | Focus & attention | EEG theta-beta, SMR |
  | `calm_stress` | Calm & stress relief | EEG alpha↑, HRV coherence, GSR arousal↓, temp warming |
  | `sleep_quality` | Sleep quality | EEG SMR |
  | `alertness_performance` | Alertness & performance | EEG, HRV |
  | `mood_balance` | Mood & balance | EEG frontal asymmetry |
  | `flow_connectivity` | Flow & connectivity | EEG coherence |
  | `deep_meditative` | Deep meditative states | EEG alpha-theta |
  | `interoception` | Body awareness | HRV, GSR, respiration |

- **`bands`** *(list, optional, modality-scoped)* — chips: `smr`, `theta`, `alpha`, `beta`, `high-beta`, `delta`, `hrv-lf`, … Omit for modalities with no band concept (a raw skin-conductance level, say).
- **`threshold_style`** — `adaptive` / `baseline` / `crossover` → the Adaptive/Baseline filter.
- **`site`** — channel / source label: an EEG scalp site (`Cz`, `F3/F4`) or a non-EEG source label (`tachogram`, `gsr`, `temp`).
- **`direction`** — `up`/`down`/`composite`/`crossover`/`asymmetry`.
- **`hardware`** + **`requires_features`** — `generic` / `brainbit_flex` / `research_amp`; features like `dc_coupling`, `trials` → grey-out logic.
- **`modality`** — `eeg` (default) / `ecg` / `hrv` / `gsr` / `emg` / `temp` / `resp`. Every EEG protocol in this library declares it explicitly; a user's own file may rely on the default.

## Not in the distributed contract

A neutral library ships no indications. These are **host-side only** and are rejected by CI if they appear in a protocol file: `indication`, `population`, `safety_monitoring`, `outcome_measures`. `control_ref` (a pointer to a matching sham protocol) *is* kept — study design, not a health claim.

## Rules
- `description`, `status`, `goals` are **required**.
- `citation` is **required once `status` > `draft`**.
- Unknown enum values are **not errors** for a host — they fall into an "Other" bucket. CI for *this* repo is stricter (it validates against the schema) so the reference set stays consistent; user protocols are only warned.

## Favorites
Favorites are **host-side per-user state**, never a protocol tag.

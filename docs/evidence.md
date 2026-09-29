# Evidence & status policy

Two orthogonal axes (see `tagging.md`):

- **`evidence`** — how established the signal-training **approach** is in prior art: `established` / `probable` / `exploratory`.

  | Level | What qualifies |
  |---|---|
  | `established` | The approach has a long track record in the literature, cited in `citation`. |
  | `probable` | Some prior-art support — a published source or a written practice guideline — but not a long track record. |
  | `exploratory` | A practitioner's judgement, or untested starting points. Fine to ship; hosts should visibly label it so a practitioner can weigh it accordingly. |

  This is the **same three-tier scale** `refrain`'s `autopilot { }` blocks use
  for their numbers (see `docs/AUTOPILOT-AUTHORING.md` §7). Same words, same
  meaning, different subject: here it describes the *training approach*, there
  the *autopilot numbers*. A protocol can legitimately carry a different tier
  in each — an `established` technique driven by `exploratory` autopilot
  numbers is a normal and honest combination.
- **`status`** — *our* file maturity: `draft` → `roadmap` → `reviewed` → `stable` (plus `legacy` for a file superseded by a newer one).

## What `evidence` does and does not say

`evidence` and `citation` describe **where a technique comes from**, not what it
will do for anyone. An `established` tier means the approach has a long track
record in the literature; it is not a claim that the protocol treats anything.
The library ships general-wellness building blocks and makes no diagnostic or
therapeutic claim. Pretending these techniques have no origin in research would
be dishonest — citing that origin as provenance is not the same as claiming an
outcome.

## Current state
**Most of the library is untested in this system.** That includes protocols whose underlying approach is `established` (e.g. SMR/θ training). Draft means *we have not validated this file here* — the bands/sites/thresholds are reasonable starting points, not turnkey settings.

## Graduating a protocol
A protocol leaves `draft` only after:
1. it **resolves** against a real amp profile (not just parses),
2. its **bands/sites/thresholds** are reviewed,
3. it carries a real **`citation`** (required by CI once `status` > `draft`; CI rejects empty values and the known placeholder strings, but it cannot tell a thin reference from a good one — that is review's job),
4. (ideally) bench/oracle validation of its feedback behavior.

Until then, host apps must badge it "untested." Nothing here is a medical device or a substitute for professional judgement, and whoever runs a protocol owns the decision to run it.

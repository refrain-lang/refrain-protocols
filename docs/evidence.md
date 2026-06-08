# Evidence & status policy

Two orthogonal axes (see `tagging.md`):

- **`evidence`** — clinical-literature support: `established` / `probable` / `exploratory`.
- **`status`** — *our* file maturity: `draft` → `roadmap` → `reviewed` → `stable`.

## Current state
**The entire seed library is `status = "draft"` (untested).** That includes protocols whose underlying science is `established` (e.g. SMR/θ for ADHD). Draft means *we have not validated this file in this system* — the bands/sites/thresholds are reasonable starting points, not turnkey clinical settings.

## Graduating a protocol
A protocol leaves `draft` only after:
1. it **resolves** against a real amp profile (not just parses),
2. its **bands/sites/thresholds** are clinically reviewed,
3. it carries a real **`citation`** (required by CI once `status` > `draft`),
4. (ideally) bench/oracle validation of its feedback behavior.

Until then, host apps must badge it "untested," and clinicians own the responsibility for use. Nothing here is a medical device or a substitute for clinical judgment.

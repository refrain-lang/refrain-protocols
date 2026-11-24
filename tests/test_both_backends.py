"""Every protocol must build and step on BOTH evaluator backends.

Why this gate exists, and what it caught. A host picks its backend through
`Evaluator.live(backend=...)`, whose default is `"auto"` — Rust whenever the
`refrain_core` wheel is importable. The recorder resolves `auto` the same way
and ships the wheel, so **a real session runs the Rust evaluator**. Every other
gate in this repository runs the Python reference backend: the structural tests
never construct an evaluator, and `refrain fuzz` uses the default in an
environment that usually has no wheel.

So a protocol could use a primitive the Rust core does not implement, pass
everything here, and then fail at session start. One did. `smr_spindle.refrain`
gave its inhibits `metric = passthrough(input: <derive>)`; the Python resolver
accepts it because it checks only that the metric is a call, but
`refrain-core`'s compute dispatch ends

    other => panic!("PoC: unsupported compute primitive {other:?}")

and `passthrough` exists in that crate only as a montage. Building the
evaluator raised `RuntimeError: refrain_core: evaluator construction failed in
the Rust core (PoC: unsupported compute primitive "passthrough")`. 46 of the 47
protocols were fine; that one was not, and nothing in CI could see it.

This does not test that the two backends AGREE — refrain's own drift gate owns
that, and it is a stronger claim needing matched inputs and sample-exact
comparison. This tests only that each protocol is expressible in both, which is
the failure mode a protocol file can introduce on its own.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import numpy as np
import pytest

refrain = pytest.importorskip("refrain")
from refrain.amp_profile import load_amp_profile  # noqa: E402
from refrain.eval_ import Evaluator  # noqa: E402
from refrain.resolver import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ALL = sorted((ROOT / "protocols").rglob("*.refrain"))
_PROFILES = Path(refrain.__file__).parent / "amp_profiles"
Q21 = load_amp_profile(str(_PROFILES / "q21.json"))

_RUST_AVAILABLE = importlib.util.find_spec("refrain_core") is not None


def _amp_for(path: Path):
    """The widest bundled profile, except for the corpus's one cardiac file.

    Mirrors `test_corpus_roundtrip._amp_for`: `hrv_resonance` declares a
    tachogram input, so handing it an EEG profile would fail closed on a
    missing channel — a gap manufactured by the test's amp choice.
    """
    return None if path.name == "hrv_resonance.refrain" else Q21


def test_the_rust_backend_is_actually_being_exercised():
    """A skipped Rust gate is worse than no Rust gate, so say when it is skipped.

    CI builds the wheel with maturin before running the suite
    (.github/workflows/ci.yml), so the skip below must never apply there. A
    developer without a local Rust toolchain gets the skip and a reason; CI
    gets a failure if the wheel went missing, rather than a quietly green run
    that proved nothing about the backend a session uses.
    """
    if os.environ.get("CI"):
        assert _RUST_AVAILABLE, (
            "refrain_core is not importable under CI, so every rust-backend case "
            "below skipped. CI builds the wheel with maturin — check that step."
        )
    elif not _RUST_AVAILABLE:
        pytest.skip("refrain_core wheel not built in this environment")


@pytest.mark.parametrize("path", ALL, ids=lambda p: str(p.relative_to(ROOT / "protocols")))
@pytest.mark.parametrize(
    "backend",
    [
        "python",
        pytest.param(
            "rust",
            marks=pytest.mark.skipif(
                not _RUST_AVAILABLE,
                reason="refrain_core wheel not built (build with maturin, as CI does)",
            ),
        ),
    ],
)
def test_protocol_builds_and_steps(path: Path, backend: str):
    amp = _amp_for(path)
    ir = resolve(refrain.parse_file(str(path)), amp)
    channels = tuple(sorted(amp.channel_names())) if amp is not None else ("tachogram",)
    fs = float(ir.requires.sample_rate_chosen_hz)
    # Noise, not authored signal: this asks whether the protocol is
    # EXPRESSIBLE on this backend, not what it decides. A panic in the Rust
    # core surfaces at construction, before any sample is pushed.
    rng = np.random.default_rng(7)
    evaluator = Evaluator.live(
        ir,
        sample_rate_hz=fs,
        channel_names=channels,
        backend=backend,
        record_streams=True,
    )
    evaluator.start(skip_warmup=True)
    for _ in range(10):
        if evaluator.state == "stopped":
            break  # a short phase plan ended; stepping on would raise
        evaluator.step_chunk(rng.normal(0, 10, size=(16, len(channels))))

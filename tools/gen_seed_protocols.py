#!/usr/bin/env python3
"""Generate the seed reference protocols from a curated table.

These are **draft** artifacts (`status = "draft"`): the clinical parameters
(band, site, direction, citation, evidence tier) are human-curated in TABLE
below; the .refrain structure is templated here so the whole library stays
consistent. Generated files are parse-valid; they graduate from `draft` to
`reviewed`/`stable` by hand as they're tested.

Run:  python tools/gen_seed_protocols.py
Emits: protocols/<name>.refrain

Each generated core carries a single `threshold_style` `mode` control
("adaptive" default / "baseline") that switches the threshold between a
percentile target and an absolute clinician-set value at resolve time —
one file per target, no separate `_baseline` variant.

Specials that don't fit the operant template (composite, coherence,
alpha-theta crossover, HRV, SCP) are hand-authored, not generated here.
"""
from __future__ import annotations

import math
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "protocols"

# Each entry = one TARGET, emitted as a single mode-based core.
#   bands:     low/high edges in Hz for the trained envelope
#   direction: "up" (reward above) or "down" (reward below)
#   site:      scalp site (also the requires channel + montage active)
#   goals:     controlled-vocab category memberships (multi)
#   band_tags: chips shown in the picker
#   evidence:  established | probable | exploratory
#   title:     curated plain-language label
#   summary:   curated plain-language one-liner
TABLE = [
    # name, band, dir, site, goals, band_tags, evidence, citation, title, summary
    ("smr_theta_cz",    (12,15), "up",  "Cz", ["adhd_attention","sensorimotor_sleep"], ["smr","theta"], "established", "Sterman; Lubar; Arns 2009", "Steady focus — boost SMR, calm theta (top of head)", "Rewards a calm-but-alert sensorimotor rhythm at the top of the head while keeping drowsy theta down."),
    ("theta_beta_cz",   (15,18), "up",  "Cz", ["adhd_attention"], ["beta","theta"], "established", "Lubar (theta/beta)", "Sharpen attention — beta up over theta (top of head)", "Trains focused beta up relative to daydreamy theta at the top of the head."),
    ("theta_beta_fz",   (15,18), "up",  "Fz", ["adhd_attention"], ["beta","theta"], "established", "Lubar (theta/beta); frontal-theta excess", "Sharpen attention — beta up over theta (forehead)", "Trains focused beta up relative to theta at the forehead, where theta excess is common in inattention."),
    ("theta_down_cz",   (4,8),   "down","Cz", ["adhd_attention"], ["theta"], "probable", "Lubar (theta downtraining)", "Quiet daydreaming — lower theta (top of head)", "Rewards lowering the slow, drifting theta rhythm at the top of the head."),
    ("theta_down_fz",   (4,8),   "down","Fz", ["adhd_attention"], ["theta"], "probable", "Lubar; frontal-theta excess", "Quiet daydreaming — lower theta (forehead)", "Rewards lowering excess frontal theta associated with mind-wandering."),
    ("slow_down_cz",    (2,7),   "down","Cz", ["alertness_performance","adhd_attention"], ["delta","theta"], "exploratory", "Thatcher; Walker (qEEG-guided slowing)", "Clear mental fog — lower slow waves (top of head)", "Rewards reducing sluggish delta/theta slow-wave activity at the top of the head."),
    ("slow_down_fz",    (2,7),   "down","Fz", ["alertness_performance","adhd_attention"], ["delta","theta"], "exploratory", "Thatcher; Walker (frontal slowing)", "Clear mental fog — lower slow waves (forehead)", "Rewards reducing frontal delta/theta slow-wave activity linked to under-arousal."),
    ("smr_up_c4",       (12,15), "up",  "C4", ["sensorimotor_sleep","calm_anxiety"], ["smr"], "established", "Sterman; Hoedlmoser 2008", "Wind down for sleep — boost SMR (right side)", "Rewards the calm sensorimotor rhythm over the right sensorimotor cortex, associated with sleep spindles and settling."),
    ("beta_up_c3",      (15,18), "up",  "C3", ["alertness_performance","adhd_attention"], ["beta"], "probable", "Othmer & Othmer (arousal model)", "Alert and engaged — boost beta (left side)", "Rewards raising engaged beta activity over the left sensorimotor cortex."),
    ("beta_up_fz",      (15,18), "up",  "Fz", ["alertness_performance"], ["beta"], "probable", "frontal beta activation", "Alert and engaged — boost beta (forehead)", "Rewards raising engaged frontal beta activity."),
    ("alpha_up_pz",     (8,12),  "up",  "Pz", ["calm_anxiety","deep_meditative"], ["alpha"], "probable", "Hardt & Kamiya 1978", "Calm the mind — boost alpha (back of head)", "Rewards raising relaxed alpha waves at the back of the head, the classic eyes-closed calm state."),
    ("hibeta_down_cz",  (22,30), "down","Cz", ["calm_anxiety"], ["high-beta"], "probable", "clinical convention (anxiety/rumination)", "Ease over-arousal — quiet high-beta (top of head)", "Rewards lowering fast high-beta activity associated with anxiety and rumination."),
    ("peak_alpha_up_pz",(9,11),  "up",  "Pz", ["alertness_performance","deep_meditative"], ["alpha"], "exploratory", "Hanslmayr; Gruzelier 2014", "Sharpen peak alpha (back of head)", "Rewards raising the individual peak-alpha frequency band at the back of the head."),
    ("fm_theta_up_fz",  (4,8),   "up",  "Fz", ["deep_meditative","alertness_performance"], ["theta"], "exploratory", "Ishihara & Yoshii; Gruzelier", "Frontal-midline theta — focused calm (forehead)", "Rewards raising frontal-midline theta, associated with focused absorption and meditation."),
    ("alpha_down_pz",   (8,12),  "down","Pz", ["trauma_recovery","deep_meditative"], ["alpha"], "probable", "Kluetsch/Ros/Lanius 2014; Nicholson 2016", "Down-regulate alpha (back of head)", "Rewards lowering alpha at the back of the head, used in trauma-oriented desensitization work."),
    ("theta_up_pz",     (4,8),   "up",  "Pz", ["deep_meditative"], ["theta"], "exploratory", "Gruzelier (creativity/deep states)", "Theta up — reverie state (back of head)", "Rewards raising theta at the back of the head, associated with hypnagogic, creative reverie states."),
]

_SITE_REF = {  # vendor-neutral reference montage; hardware overlay is a meta concern
    "Cz": "linked_ears", "Fz": "linked_ears", "Pz": "linked_ears",
    "C3": "linked_ears", "C4": "linked_ears",
}

OPERANT_SESSION = """\
  // Default: 4x5-min blocks with 2-min rests on one baseline (host overrides
  // block_minutes / block_count by sending a different phase list).
  session {
    phases = [
      phase { name = "warmup";   duration = 90 s;  output_muted = true },
      phase { name = "block1";   duration = 5 min; mode = timed_with_floor },
      phase { name = "rest1";    duration = 2 min; output_muted = true },
      phase { name = "block2";   duration = 5 min; mode = timed_with_floor },
      phase { name = "rest2";    duration = 2 min; output_muted = true },
      phase { name = "block3";   duration = 5 min; mode = timed_with_floor },
      phase { name = "rest3";    duration = 2 min; output_muted = true },
      phase { name = "block4";   duration = 5 min; mode = timed_with_floor },
      phase { name = "cooldown"; duration = 30 s;  output_muted = true },
    ]
  }"""


def _meta(name, desc, ev, cite, goals, bands, site, direction, title, summary):
    g = ", ".join(f'"{x}"' for x in goals)
    b = ", ".join(f'"{x}"' for x in bands)
    return f"""\
  meta {{
    version         = "0.1.0"
    title           = "{title}"
    summary         = "{summary}"
    family          = "{name}"
    description     = "{desc}"
    status          = "draft"
    evidence        = "{ev}"
    citation        = "{cite}"
    goals           = [{g}]
    bands           = [{b}]
    site            = "{site}"
    direction       = "{direction}"
    threshold_style = "selectable"
    feedback_style  = "discrete"
    session_shape   = "staged"
    hardware        = "generic"
  }}"""


def emit(name, band, direction, site, goals, bands, ev, cite, title, summary):
    lo, hi = band
    ref = _SITE_REF[site]
    cmp = "above" if direction == "up" else "below"
    desc = f"{'/'.join(bands).upper()} {direction}-train at {site}"

    # The trained band is exposed as a clinician knob: a single `env_center`
    # frequency control (set at session setup, frozen during the run — the
    # live knob is the threshold/reward-%, not the band). bandpass's
    # center/bandwidth form takes a geometric center and a width *ratio*
    # (low = center/sqrt(R), high = center*sqrt(R)), so a literal (lo, hi)
    # maps to center = sqrt(lo*hi), ratio = hi/lo — behaviour-preserving at
    # the default. The center range is a uniform +-20% starting heuristic;
    # it tightens per-band as protocols graduate from draft.
    center = math.sqrt(lo * hi)
    ratio = hi / lo
    c_lo, c_hi = round(center * 0.8, 2), round(center * 1.2, 2)
    bandpass_call = f"bandpass(center: env_center, bandwidth: ratio({ratio:.6g}), order: 4)"
    center_control = (
        f'    env_center = frequency {{\n'
        f'      default = {center:.6g} Hz\n'
        f'      range   = ({c_lo} Hz, {c_hi} Hz)\n'
        f'      label   = "{"/".join(bands).upper()} band center"\n'
        f'    }}'
    )

    pct = 70 if direction == "up" else 30
    p_lo, p_hi = (50, 90) if direction == "up" else (10, 50)

    thr = (
        '    type = threshold_style == "baseline"\n'
        '             ? absolute(value: thr_uv)\n'
        '             : percentile(target_pct: reward_pct, window: 2 min)\n'
        '    live_tunable = true'
    )
    controls = f"""
  controls {{
    threshold_style = mode {{
      choices = ["adaptive", "baseline"]
      default = "adaptive"
      label   = "Threshold style"
    }}
{center_control}
    reward_pct = percent {{
      default      = {pct}
      range        = ({p_lo}, {p_hi})
      label        = "Target reward %"
      live_tunable = true
    }}
    thr_uv = voltage {{
      default      = 2.0 uV
      range        = (0.5 uV, 30.0 uV)
      label        = "Threshold (baseline-seeded)"
      live_tunable = true
    }}
  }}"""

    body = f"""\
// {name}.refrain  —  DRAFT (status=draft, untested)
// {desc}.  {cite}
protocol "{name}" {{
{_meta(name, desc, ev, cite, goals, bands, site, direction, title, summary)}

  requires {{
    sample_rate = ">= 256 Hz"
    channels    = ["{site}"]
  }}

  input "raw" {{ montage = referential(active: "{site}", reference: "{ref}") }}

  derive "env" {{
    from = "raw"
    pipeline = [
      {bandpass_call},
      hilbert(),
      magnitude(),
      smooth(tau: 250 ms),
    ]
  }}

  threshold "env_t" {{
    signal = "env"
{thr}
  }}

  reward {{
    event      = dwell(condition: {cmp}("env", "env_t"), duration: 250 ms)
    continuous = sigmoid("env" / "env_t", midpoint: 1.0, steepness: 3)
  }}

  output {{
    audio_chime = reward.event
    audio_gain  = reward.event.holds ? reward.continuous : 0
  }}
{controls}
{OPERANT_SESSION}
}}
"""
    (OUT / f"{name}.refrain").write_text(body)
    return name


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for name, band, direction, site, goals, bands, ev, cite, title, summary in TABLE:
        written.append(emit(name, band, direction, site, goals, bands, ev, cite, title, summary))
    for f in sorted(written):
        print("  wrote protocols/%s.refrain" % f)
    print(f"{len(written)} mode-based protocols generated (all status=draft).")


if __name__ == "__main__":
    main()

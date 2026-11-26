"""Does a live-computable percentile bar reach the oracle bar's catch rate?

The oracle arm is a CONTROL IN THIS RUN, not a figure quoted from an earlier
one: same recordings, same ground truth, same refractory, same matching rule.
It must reproduce 358 / 67.0% or the script is wrong and nothing else here
means anything.

`bar_percentile.py` measured the oracle bar at causal percentile 93.3 +- 1.7
(range 88.9-95.5), so the sweep brackets that.
"""
import os
import sys

import numpy as np

sys.path.insert(0, "tools")
import refrain  # noqa: E402
from measure_envelopes import (  # noqa: E402
    SKIP_HEAD_S, SKIP_TAIL_S, load_amp_profile, load_recordings, reference_envelope, resolve,
)
from session_report.replay import step_through  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath("tools/score_onset_trigger.py")))
from score_onset_trigger import REFRACTORY_MS, ground_truth, refract  # noqa: E402

ORACLE_TMPL = sys.argv[1]       # carries __BAR__
PCT_TMPL = sys.argv[2]          # carries __WAXPCT__
PCTS = [91, 93, 95]

amp = load_amp_profile(
    os.path.join(os.path.dirname(refrain.__file__), "amp_profiles", "brainbit_flex.json")
)
oracle_src = open(ORACLE_TMPL).read()
pct_src = open(PCT_TMPL).read()
probe = "/tmp/_sweep_probe.refrain"
open(probe, "w").write(oracle_src.replace("__BAR__", "4.5"))
ir0 = resolve(refrain.parse_file(probe), amp)
fs = float(ir0.requires.sample_rate_chosen_hz)
chans = tuple(sorted(amp.channel_names()))
cn = max(1, int(round(0.05 * fs)))
look = int(round(0.5 * fs))

# Pre-resolve the percentile arms once; the oracle arm must be resolved per
# recording because its bar IS per recording.
pct_irs = {}
for p in PCTS:
    f = f"/tmp/_sweep_pct{p}.refrain"
    open(f, "w").write(pct_src.replace("__WAXPCT__", str(p)))
    pct_irs[p] = resolve(refrain.parse_file(f), amp)

ARMS = ["oracle"] + [f"pct{p}" for p in PCTS]
tot = {a: [0, 0] for a in ARMS}          # [caught, spindles]
fires_tot = {a: [0, 0] for a in ARMS}    # [fires, matched fires]
minutes = {a: 0.0 for a in ARMS}
muted_frac = {a: [] for a in ARMS}
n_rec = 0

for case, rec in load_recordings("/Users/jcroall/tmp/file_io_corpus", fs, 4.0):
    n = len(next(iter(rec.values())))
    X = np.column_stack([rec.get(c.upper(), np.zeros(n)) for c in chans])
    pre = step_through(ir0, fs, chans, (X[k:k + cn] for k in range(0, n - cn + 1, cn)),
                       skip_warmup=True, keep_streams={"raw", "smr_envelope"})
    lo, hi = int(SKIP_HEAD_S * fs), n - int(SKIP_TAIL_S * fs)
    src, env = pre.streams.get("raw"), pre.streams.get("smr_envelope")
    if src is None or env is None:
        continue
    ref = reference_envelope(np.asarray(src), fs, (12.0, 16.0))[lo:hi]
    spindles, peak = ground_truth(ref, fs)
    # The SAME exclusion why_not_all.py applies, so the recording set and the
    # 534-spindle denominator match exactly.
    if not spindles or peak is None or 0.8 * peak < 0.5:
        continue
    n_rec += 1
    bar = 0.8 * peak

    for arm in ARMS:
        if arm == "oracle":
            f = f"/tmp/_sweep_oracle_{case}.refrain"
            open(f, "w").write(oracle_src.replace("__BAR__", f"{bar:.3f}"))
            ir = resolve(refrain.parse_file(f), amp)
        else:
            ir = pct_irs[int(arm[3:])]
        res = step_through(ir, fs, chans,
                           (X[k:k + cn] for k in range(0, n - cn + 1, cn)),
                           skip_warmup=True, keep_streams={"smr_envelope"})
        fires = np.zeros(hi - lo, dtype=bool)
        for e in res.events:
            if e.get("channel") == "audio_chime":
                t = int(e["t_sample"]) - lo
                if 0 <= t < fires.size:
                    fires[t] = True
        fires = refract(fires, fs, REFRACTORY_MS)
        idxs = np.flatnonzero(fires)
        fired = 0
        for a, b in spindles:
            if len(idxs[((idxs >= a - look) & (idxs <= a + look))
                        | ((idxs >= a) & (idxs < b))]):
                fired += 1
        tot[arm][0] += fired
        tot[arm][1] += len(spindles)
        # Precision, the half the first run left out. A fire is MATCHED when it
        # falls in some spindle's window by the same rule used for catch, so
        # recall and precision are scored off one relation rather than two.
        matched = 0
        for i in idxs:
            if any((i >= a - look and i <= a + look) or (i >= a and i < b)
                   for a, b in spindles):
                matched += 1
        fires_tot[arm][0] += int(idxs.size)
        fires_tot[arm][1] += matched
        minutes[arm] += (hi - lo) / fs / 60.0
        mut = np.zeros(hi - lo, dtype=bool)
        for i, off in enumerate(res.chunk_sample_offsets):
            if lo <= off < hi and i < len(res.taps_per_chunk):
                s0 = off - lo
                mut[s0:min(s0 + cn, mut.size)] = bool(res.taps_per_chunk[i].get("muted"))
        muted_frac[arm].append(100.0 * mut.mean())
    print(f"  {case[:34]:34s} done", flush=True)

print()
print(f"n = {n_rec} recordings, {tot['oracle'][1]} ground-truth spindles")
print()
print("arm        caught (recall)   fires  fires/min  matched (precision)  fizzled")
print("-" * 78)
for arm in ARMS:
    caught, sp = tot[arm]
    fires, matched = fires_tot[arm]
    prec = 100.0 * matched / max(fires, 1)
    print(f"{arm:9s}  {caught:4d}  {100.0 * caught / max(sp, 1):5.1f}%     "
          f"{fires:5d}   {fires / max(minutes[arm], 1e-9):6.1f}      "
          f"{matched:5d}  {prec:5.1f}%           {100.0 - prec:5.1f}%")
print()
print("A lower bar buys recall with precision. At bar 0 recall is 100% and the")
print("ding is continuous, so recall alone cannot pick an arm.")
print()
print("CONTROL: the oracle arm must read 358 / 67.0%. If it does not, the")
print("harness differs from why_not_all.py and no row here is comparable.")

#!/usr/bin/env python3
"""STAGE 1 follow-up: what truncation bounds does the scalar `speedFactor` +
`speedDev` syntax actually get?

The scalar-syntax probes in stage1_characterize showed sd == speedDev with no
visible truncation, but the deviations tested were too small for any bound to
bind. Here we deliberately use deviations large enough that a candidate bound
MUST bind, and read off where the sample is actually cut.

Candidate hypotheses:
  H1  absolute bounds [0.2, 2.0]  (the documented default distribution's cutoffs)
  H2  relative bounds mu +/- 2*speedDev
"""
import json
import os
import sys

sys.path.append(os.environ['SUMO_HOME'] + '/tools')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from stage1_characterize import probe_run, stats  # noqa: E402

NET = sys.argv[1]
OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True)

cases = [
    ('E1_mu1_dev05', 'speedFactor="1.0" speedDev="0.5"', 1.0, 0.5),
    ('E2_mu15_dev03', 'speedFactor="1.5" speedDev="0.3"', 1.5, 0.3),
    ('E3_mu05_dev02', 'speedFactor="0.5" speedDev="0.2"', 0.5, 0.2),
]
R = {}
for label, spec, mu, dev in cases:
    rec, _, csvf = probe_run(label, OUT, NET, spec, n_target=8000, vph=7200,
                             sample_only=True)
    sf = [r['speedFactor'] for r in rec.values()]
    st = stats(sf)
    R[label] = {
        'spec': spec, 'csv': os.path.basename(csvf), 'sample': st,
        'H1_absolute_0.2_2.0': {'lo': 0.2, 'hi': 2.0,
                                'frac_at_lo': sum(1 for v in sf if abs(v - 0.2) < 1e-6) / len(sf),
                                'frac_at_hi': sum(1 for v in sf if abs(v - 2.0) < 1e-6) / len(sf)},
        'H2_mu_pm_2dev': {'lo': mu - 2 * dev, 'hi': mu + 2 * dev,
                          'frac_below_lo': sum(1 for v in sf if v < mu - 2 * dev - 1e-9) / len(sf),
                          'frac_above_hi': sum(1 for v in sf if v > mu + 2 * dev + 1e-9) / len(sf)},
        'sd_over_speeddev': st['sd'] / dev,
    }
    print(label, json.dumps(R[label], indent=1))

json.dump(R, open(os.path.join(OUT, 'stage1b_bounds.json'), 'w'), indent=2)
print('wrote', os.path.join(OUT, 'stage1b_bounds.json'))

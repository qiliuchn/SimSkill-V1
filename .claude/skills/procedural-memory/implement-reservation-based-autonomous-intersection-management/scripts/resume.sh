#!/bin/bash
# Re-run driver for the resumed attempt: everything that either (a) used the
# buggy mixed-autonomy controller, (b) used the max-pressure baseline before its
# all-red clearance was restored, or (c) was never run at all (s5 SSM, s6
# communication realism).
#
# NOT re-run: s1 AIM arms, s2, s4 AIM arms.  Every fix in this round is inside a
# code path that can only execute when an HDV exists (_hdv_logic returns
# immediately when penetration == 1.0, and the conflict-point guard is gated on
# a non-empty hdv_in_junction), so all-CAV runs are unchanged -- verified
# explicitly by scripts/verify_pure_cav.sh.
set -e
export SUMO_HOME=${SUMO_HOME:-/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo}
cd "$(dirname "$0")/.."
W=${W:-9}

echo "=== s1 (max-pressure baseline, all-red clearance restored) ==="
rm -rf runs/s1/maxpressure_*
python3 scripts/experiments.py s1 --workers $W --best-plan net/plans/best.json

echo "=== s3 (H2 penetration sweep, post-fix controller) ==="
python3 scripts/experiments.py s3 --workers $W

echo "=== s4 (H3 unbalanced demand, completing the 2 killed runs) ==="
python3 scripts/experiments.py s4 --workers $W

echo "=== s5 (H4 surrogate safety, SSM device) ==="
python3 scripts/experiments.py s5 --workers $W --best-plan net/plans/best.json

echo "=== s6 (communication realism: latency + position noise) ==="
python3 scripts/experiments.py s6 --workers $W

echo "=== aggregate ==="
python3 scripts/report.py

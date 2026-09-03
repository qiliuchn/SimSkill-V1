#!/bin/bash
# Stage 2..n of the pipeline: replications -> analysis -> maps -> teleport sweep.
set -e
cd "$(dirname "$0")/.."
rm -rf runs/sim
for v in A B C D E F; do python3 scripts/run_variants.py --sim --variants $v > runs/sim_$v.log 2>&1 & done
wait
echo "SIMS DONE"
python3 scripts/analyze.py > analysis/analyze.log 2>&1
echo "ANALYSIS DONE"
python3 scripts/make_maps.py
python3 scripts/teleport_check.py A C F > analysis/teleport_sweep.log 2>&1
echo "ALL DONE"

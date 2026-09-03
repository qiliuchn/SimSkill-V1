#!/bin/bash
# Waits for the DUE stage, selects each variant's equilibrium of record, then:
# replications -> analysis -> maps -> teleport sweep.
cd "$(dirname "$0")/.."
while [ ! -f analysis/due_convergence.txt ] || pgrep -f "assign/duaIterate.py -n" >/dev/null; do sleep 20; done
echo "=== DUE stage complete ==="
python3 scripts/select_equilibrium.py 12 | tee analysis/equilibrium_selection.txt
echo "=== equilibrium of record selected ==="
rm -rf runs/sim
for v in A B C D E F; do python3 scripts/run_variants.py --sim --variants $v > runs/sim_$v.log 2>&1 & done
wait
echo "SIMS DONE"
python3 scripts/analyze.py > analysis/analyze.log 2>&1
echo "ANALYSIS DONE"
python3 scripts/make_maps.py
python3 scripts/emergency_access.py > analysis/emergency_access.log 2>&1
python3 scripts/teleport_check.py A C F > analysis/teleport_sweep.log 2>&1
echo "ALL DONE"

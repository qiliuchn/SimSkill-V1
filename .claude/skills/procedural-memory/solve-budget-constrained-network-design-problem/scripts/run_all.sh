#!/bin/bash
# Full pipeline, in order.  Steps 1-5 are the expensive simulation stages;
# steps 6-9 are pure analysis on their outputs.
set -e
cd "$(dirname "$0")"
EP="$(cd ../../.. && pwd)"

# 1. candidate project set: every project must be a real compiled-net change
python3 verify_projects.py

# 2. demand sweep -> flow-vs-demand knee, and v/c calibration
python3 demand_sweep.py
python3 calibrate_vc.py

# 3. convergence study -> fixes the iteration budget and the gap criterion,
#    and saves the do-nothing equilibrium route file
python3 conv_study.py

# 4. protocol validation: is a warm-started equilibrium good enough? (it is not)
python3 validate_warmstart.py

# 5. the design search itself
python3 enumerate_designs.py --masks planned --workers 10

# 6. analysis: optimum / GA / greedy baselines / interactions / frontier
python3 analyze.py

# 7. capacity-paradox replication (candidate + positive control, 10 CRN seeds)
python3 replicate_paradox.py N1,NB,L1 L2 --seeds 10

# 8. evaluation noise floor under the enumeration protocol
python3 noise_floor.py   # derived from the replication runs

# 9. figures, decision rule, tables
python3 plots.py
python3 diagnostics.py
python3 make_tables.py
echo "outputs in $EP/outputs"

#!/bin/bash
# Run the full perimeter-gating experiment.  Network, demand, routes and RNG
# seed are IDENTICAL across every run; only the gating set-point changes.
set -e
export SUMO_HOME=/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo
SUMO_BIN=/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin
BASE=/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-31_10-30-00
A=$BASE/attempts/attempt-1
NET=$BASE/outputs/grid.net.xml
ROU=$BASE/outputs/routes.rou.xml
CG=$BASE/outputs/core_gate.json
GAIN=0.6
GMIN=10

one () {   # label  mode  n_set
  L=$1; M=$2; NS=$3
  D=$A/runs/$L
  rm -rf "$D"; mkdir -p "$D"
  python3 "$A/scripts/make_additional.py" --net "$NET" --core-gate "$CG" \
      --outdir "$D" --out "$D/additional.add.xml" > /dev/null
  python3 "$A/scripts/perimeter_gating.py" \
      --net "$NET" --routes "$ROU" --additional "$D/additional.add.xml" \
      --core-gate "$CG" --outdir "$D" --label "$L" --mode "$M" \
      --n-set "$NS" --gain $GAIN --g-min $GMIN --interval 60 --seed 42 \
      --sumo-bin "$SUMO_BIN/sumo" 2>&1 | grep -E "^\[|rror" || true
}

one baseline          baseline 1e9      &
one gate_nonbinding   gated    100000   &
one gate_nset240      gated    240      &
wait
one gate_nset200      gated    200      &
one gate_nset160      gated    160      &
one gate_nset120      gated    120      &
one gate_nset80       gated    80       &
wait
echo "ALL RUNS DONE"

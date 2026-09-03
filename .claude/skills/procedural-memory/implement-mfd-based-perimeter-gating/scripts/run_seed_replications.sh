#!/bin/bash
# Multi-seed replication: identical network / demand / routes everywhere.
# Only (a) the SUMO RNG seed and (b) the gating set-point vary.
set -e
export SUMO_HOME=/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo
SUMO_BIN=/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/bin
BASE=/Users/liuqi/Desktop/simskill/episodic-memory/2026-07-31_10-30-00
A=$BASE/attempts/attempt-1
R=$A/rep_runs
mkdir -p "$R"

SEEDS="42 7 1234 2 99 555 8888 31337"
CFGS="nset20:20 nset30:30 nset50:50"

one () {  # seed cfgname nset
  SD=$1; CN=$2; NS=$3
  L=s${SD}_${CN}
  D=$R/$L
  if [ -f "$D/run_meta.json" ]; then echo "[skip $L]"; return; fi
  rm -rf "$D"; mkdir -p "$D"
  MODE=gated; [ "$CN" = "baseline" ] && MODE=baseline
  python3 "$A/scripts/make_additional.py" --net "$BASE/outputs/grid.net.xml" \
      --core-gate "$BASE/outputs/core_gate.json" --outdir "$D" \
      --out "$D/additional.add.xml" --light > /dev/null
  python3 "$A/scripts/perimeter_gating.py" \
      --net "$BASE/outputs/grid.net.xml" --routes "$BASE/outputs/routes.rou.xml" \
      --additional "$D/additional.add.xml" --core-gate "$BASE/outputs/core_gate.json" \
      --outdir "$D" --label "$L" --mode "$MODE" --n-set "$NS" \
      --gain 0.6 --g-min 10 --interval 60 --seed "$SD" --light \
      --sumo-bin "$SUMO_BIN/sumo" 2>&1 | grep -E "^\[|rror" || true
}

N=0
for SD in $SEEDS; do
  for C in $CFGS; do
    CN=${C%%:*}; NS=${C##*:}
    one "$SD" "$CN" "$NS" &
    N=$((N+1))
    if [ $((N % 6)) -eq 0 ]; then wait; fi
  done
done
wait
echo "REPLICATIONS DONE"

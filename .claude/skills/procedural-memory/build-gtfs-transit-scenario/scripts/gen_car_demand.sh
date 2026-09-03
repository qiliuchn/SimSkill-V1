#!/bin/bash
# Background car demand for the transit scenario: randomTrips with a fringe factor
# so trips enter/leave the network at its boundary rather than popping up mid-block.
# One route file per (insertion-rate, seed) cell; the SAME file is reused by every
# transit-representation arm at that cell (Common Random Numbers).
#   usage: gen_car_demand.sh <net> <outdir> "<rates>" "<seeds>" [parallel]
# NOTE: jobs are written as small shell scripts and fed to xargs by PATH, because
# macOS xargs -I has a 255-char replacement limit that absolute SUMO paths blow past.
set -e
NET=$1; OUT=$2; RATES=$3; SEEDS=$4; P=${5:-4}
mkdir -p "$OUT/jobs"
export PYTHONPATH=$SUMO_HOME/tools
rm -f "$OUT/jobs"/*.sh
for r in $RATES; do
  for s in $SEEDS; do
    f="$OUT/cars_r${r}_s${s}.rou.xml"
    [ -s "$f" ] && continue
    j="$OUT/jobs/j_${r}_${s}.sh"
    cat > "$j" <<EOF
export PYTHONPATH=$SUMO_HOME/tools
python3 "$SUMO_HOME/tools/randomTrips.py" -n "$NET" -o "$OUT/t_r${r}_s${s}.trips.xml" \
  -r "$f" -b 25200 -e 30600 --insertion-rate $r --fringe-factor 5 \
  --vehicle-class passenger --edge-permission passenger --min-distance 500 \
  --prefix car --seed $s --validate > "$OUT/jobs/j_${r}_${s}.log" 2>&1
EOF
  done
done
ls "$OUT"/jobs/*.sh 2>/dev/null | xargs -P "$P" -n 1 bash || true
for r in $RATES; do for s in $SEEDS; do
  f="$OUT/cars_r${r}_s${s}.rou.xml"
  echo "$f  vehicles=$(grep -c '<vehicle' "$f" 2>/dev/null || echo MISSING)"
done; done

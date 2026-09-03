#!/bin/bash
# Full factorial batch: transit-representation arm x background-car-demand level x seed.
#   arms:  gtfs_rel  = gtfs2pt route file as written (relative <stop until>)
#          gtfs_abs  = same routes/departures, ABSOLUTE published until per trip
#          ptlines   = ptlines2flows headway-based flows from the OSM ptLines
#   demand: insertion rate in veh/h of background cars (0 = negative control)
#   seeds : same seed drives car-demand generation AND the simulation (CRN)
# usage: run_batch.sh <workdir_with_outputs> <cars_dir> <runs_dir> "<rates>" "<seeds>" [parallel]
set -e
W=$1; CARS=$2; RUNS=$3; RATES=$4; SEEDS=$5; P=${6:-5}
G=$W/outputs/gtfs
N=$W/outputs/net/pdxse.net.xml
mkdir -p "$RUNS/jobs"
rm -f "$RUNS"/jobs/*.sh

for arm in ${ARMS:-gtfs_rel gtfs_abs ptlines gtfs_nohold}; do
  case $arm in
    gtfs_rel)    ADD="$G/gtfsid_stops.add.xml,$G/gtfsid_vtypes.xml"; PT="$G/gtfsid_pt_vehicles.rou.xml";;
    gtfs_abs)    ADD="$G/gtfsid_stops.add.xml";                      PT="$G/gtfs_abs_pt_vehicles.rou.xml";;
    gtfs_nohold) ADD="$G/gtfsid_stops.add.xml,$G/gtfsid_vtypes.xml"; PT="$G/gtfs_nohold_pt_vehicles.rou.xml";;
    ptlines)     ADD="$W/outputs/net/pdxse_stops.add.xml";           PT="$G/ptlines_flows.rou.xml";;
  esac
  for r in $RATES; do
    for s in $SEEDS; do
      d="$RUNS/${arm}_r${r}_s${s}"
      [ -s "$d/stats.xml" ] && continue
      mkdir -p "$d"
      if [ "$r" = "0" ]; then ROUTES="$PT,$G/persons.rou.xml";
      else ROUTES="$PT,$G/persons.rou.xml,$CARS/cars_r${r}_s${s}.rou.xml"; fi
      cat > "$RUNS/jobs/${arm}_${r}_${s}.sh" <<EOF
cd "$d"
sumo -n "$N" -a "$ADD" -r "$ROUTES" \
  --begin 25200 --end 34200 \
  --tripinfo-output tripinfo.xml --stop-output stopinfo.xml \
  --summary-output summary.xml --statistic-output stats.xml \
  --duration-log.statistics --pedestrian.model striping \
  --ignore-route-errors --no-step-log --seed $s > sumo.log 2>&1
EOF
    done
  done
done
n=$(ls "$RUNS"/jobs/*.sh 2>/dev/null | wc -l)
echo "launching $n runs with parallelism $P"
ls "$RUNS"/jobs/*.sh 2>/dev/null | xargs -P "$P" -n 1 bash || true
echo "done; completed run dirs: $(ls -d "$RUNS"/*/ | wc -l)"

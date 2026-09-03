#!/bin/bash
# Regression check for the mixed-autonomy fixes.
#
# Claim: every fix added in the resumed attempt lives in a code path that cannot
# execute when there are no HDVs, so all-CAV (penetration = 1.0) results are
# unchanged and runs/s1, runs/s2, runs/s4 did NOT need re-running.  Rather than
# assert that from code reading, re-run three all-CAV configurations with the
# fixed controller and byte-compare their tripinfo against the stored ones.
set -e
export SUMO_HOME=${SUMO_HOME:-/Library/Frameworks/EclipseSUMO.framework/Versions/1.27.1/EclipseSUMO/share/sumo}
cd "$(dirname "$0")/.."
OUT=runs/verify/purecav_regression
rm -rf $OUT && mkdir -p $OUT

check () {   # $1 stored run dir, $2 policy, $3 demand, $4 seed, $5 route tag
  local name=$(basename $1)
  python3 scripts/runner.py \
      --net net/inter_static.net.xml \
      --routes demand/d$3_s$4$5.rou.xml \
      --meta demand/d$3_s$4$5.rou.meta.json \
      --conflicts net/conflicts.json --controller aim --policy $2 \
      --outdir $OUT/$name --seed $4 --end 3600 > $OUT/$name.stdout 2>&1
  # tripinfo carries a generation timestamp in a comment -> compare the data only
  if diff <(grep '<tripinfo ' $1/tripinfo.xml) \
          <(grep '<tripinfo ' $OUT/$name/tripinfo.xml) > /dev/null; then
      echo "IDENTICAL   $name"
  else
      echo "*** DIFFERS $name"
      diff <(grep '<tripinfo ' $1/tripinfo.xml) \
           <(grep '<tripinfo ' $OUT/$name/tripinfo.xml) | head -5
  fi
}

check runs/s1/aimfcfs_d900_s101  fcfs  900 101 ""
check runs/s1/aimbatch_d1200_s102 batch 1200 102 ""
check runs/s4/aimbatch_d600_s103  batch 600 103 "_ub"

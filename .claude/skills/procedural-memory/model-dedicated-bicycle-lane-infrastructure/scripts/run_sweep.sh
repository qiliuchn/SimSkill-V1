#!/bin/bash
# Run the full 2-variant x 3-level sweep (6 SUMO runs).
# Each mode-share level's SINGLE route file is run against BOTH nets, with an
# identical fixed --seed, so demand+seed are identical across variants at each level.
set -e
cd "$(dirname "$0")/../work"

SEED=42
END=2000

make_cfg () {   # $1 net  $2 route  $3 tag
  cat > "cfg_$3.sumocfg" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
    <input>
        <net-file value="$1"/>
        <route-files value="$2"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="$END"/>
    </time>
    <processing>
        <time-to-teleport value="-1"/>
    </processing>
    <output>
        <tripinfo-output value="tripinfo_$3.xml"/>
        <summary-output value="summary_$3.xml"/>
    </output>
    <random_number>
        <seed value="$SEED"/>
    </random_number>
    <report>
        <no-step-log value="true"/>
        <duration-log.statistics value="true"/>
    </report>
</configuration>
EOF
}

for LVL in 05 20 40; do
  ROU="demand_bike${LVL}.rou.xml"
  for VAR in mixed dedicated; do
    NET="${VAR}.net.xml"
    TAG="${VAR}_${LVL}"
    make_cfg "$NET" "$ROU" "$TAG"
    echo "=== RUN $TAG (net=$NET, demand=$ROU) ==="
    sumo -c "cfg_$TAG.sumocfg" 2>"stderr_$TAG.txt"
    # surface any real SUMO error/warning
    if grep -qiE 'error' "stderr_$TAG.txt"; then
      echo "!!! ERRORS in $TAG:"; grep -iE 'error' "stderr_$TAG.txt" | head
    fi
    echo -n "  arrived (tripinfo records): "; grep -c '<tripinfo ' "tripinfo_$TAG.xml"
  done
done
echo "ALL RUNS DONE"
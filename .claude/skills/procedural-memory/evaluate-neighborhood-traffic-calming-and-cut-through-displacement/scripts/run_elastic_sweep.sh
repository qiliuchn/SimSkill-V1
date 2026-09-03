#!/bin/bash
# Elastic-demand sweep.  usage: run_elastic_sweep.sh <VARIANT>
cd "$(dirname "$0")/.."
V=${1:-F}
python3 scripts/elastic_demand.py --variant A --elasticity 0 > runs/elastic_A_0.log 2>&1 &
for e in 0 0.25 0.5 1.0 1.5; do
  python3 scripts/elastic_demand.py --variant "$V" --elasticity $e > runs/elastic_${V}_${e}.log 2>&1 &
done
wait
python3 scripts/summarize_elastic.py "$V"

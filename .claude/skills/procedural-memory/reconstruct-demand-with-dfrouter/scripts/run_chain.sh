#!/bin/bash
# Full dfrouter demand-reconstruction chain: ground-truth sim -> dfrouter -> validation sim.
#
# Usage: run_chain.sh <run_dir> <net.xml> <gt_routes.xml> <e1_gt.add.xml> <e1_val.add.xml>
#
# IMPORTANT: e1_gt.add.xml and e1_val.add.xml must define every detector at the
# SAME lane/pos in both files. A mismatch here (e.g. a ramp detector moved in one
# file but not the other) silently invalidates the ground-truth-vs-realized
# comparison without erroring — verify both files agree before trusting results.
set -e
RUN="$1"; NET="$2"; GT_ROUTES="$3"; E1_GT="$4"; E1_VAL="$5"
SC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RUN"

echo "### 1. ground-truth simulation -> gt_e1.xml"
sumo --net-file "$NET" --route-files "$GT_ROUTES" --additional-files "$E1_GT" \
     --begin 0 --end 3600 --tripinfo-output gt_tripinfo.xml --no-step-log true 2>gt_sumo.err

echo "### 2. build dfrouter inputs (detectors.det.xml, flows.txt)"
python3 "$SC/make_dfrouter_inputs.py"

echo "### 3. run dfrouter"
dfrouter --net-file "$NET" --detector-files detectors.det.xml --measure-files flows.txt \
     --routes-output df_routes.xml --emitters-output df_emitters.xml --detector-output df_dettype.xml \
     --highway-mode 2>df_router.log
echo "dfrouter exit=$?"

echo "### 4. validation simulation from dfrouter emitters -> val_e1.xml"
# routes must load as an additional file BEFORE emitters (loading gt/df routes via
# --route-files errors — dfrouter's emitters reference route-distribution ids that
# only resolve once the routes additional is already loaded).
sumo --net-file "$NET" --additional-files df_routes.xml,df_emitters.xml,"$E1_VAL" \
     --begin 0 --end 3600 --tripinfo-output val_tripinfo.xml --no-step-log true 2>val_sumo.err

echo "### done"
grep -ci 'error' val_sumo.err | sed 's/^/validation insertion-errors: /'

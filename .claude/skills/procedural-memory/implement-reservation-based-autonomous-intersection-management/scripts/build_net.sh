#!/bin/bash
# Build the shared 4-approach / 2-lane isolated intersection in two TLS-type
# variants from IDENTICAL plain-XML source (see create-single-intersection skill;
# control-signals-with-actuated-tls: --tls.default-type only works at build time,
# never on an already-compiled net -> both variants are rebuilt from source).
set -e
NET=/Users/liuqi/Desktop/simskill/episodic-memory/2026-08-02_17-00-00/outputs/net
NC=$(dirname $(which sumo))/netconvert

COMMON="--node-files $NET/base.nod.xml --edge-files $NET/base.edg.xml \
  --no-turnarounds true --default.junctions.keep-clear true \
  --tls.yellow.time 3 --tls.allred.time 2 --no-internal-links false"

$NC $COMMON -o $NET/inter_static.net.xml
$NC $COMMON --tls.default-type actuated -o $NET/inter_actuated.net.xml
echo "built"

#!/bin/bash
set -x
cd "$(dirname "$0")"
L=/tmp
export STRUCT=trunkfeeder BUDGET=24
python3 -u s7_optimize.py      > $L/s7.log  2>&1 ; echo "s7  rc=$?"
python3 -u s9_h3_congestion.py > $L/s9.log  2>&1 ; echo "s9  rc=$?"
python3 -u s13_gap.py          > $L/s13.log 2>&1 ; echo "s13 rc=$?"
python3 -u s8_h1_frontier.py   > $L/s8.log  2>&1 ; echo "s8  rc=$?"
python3 -u s10_h4_interaction.py > $L/s10.log 2>&1 ; echo "s10 rc=$?"
python3 -u s14_crossover.py    > $L/s14.log 2>&1 ; echo "s14 rc=$?"
python3 -u s11_post.py         > $L/s11.log 2>&1 ; echo "s11 rc=$?"
python3 -u s16_budget_audit.py > $L/s16.log 2>&1 ; echo "s16 rc=$?"
python3 -u s12_plots.py        > $L/s12.log 2>&1 ; echo "s12 rc=$?"
echo ALLDONE

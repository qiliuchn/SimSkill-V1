#!/bin/bash
# Full pipeline for the LC2013 diverge-calibration episode, in dependency order.
# PY is the venv interpreter (numpy/scipy/matplotlib/pandas); SUMO 1.27.1.
set -x
PY=/private/tmp/claude-501/-Users-liuqi-Desktop-simskill/73c4d241-de1e-411f-9fbf-eda6b9d3b094/scratchpad/lcvenv/bin/python
cd "$(dirname "$0")"
L=../../../outputs/logs

$PY build_net.py                > $L/build_net.log 2>&1     # STEP 1  network + compiled-net verification
$PY smoke.py                    > $L/smoke.log 2>&1         # STEP 1a instrument check (laneData vs E1, raw reason strings)
$PY lookahead_probe.py          > $L/lookahead.log 2>&1     # STEP 1b strategic-lookahead / advance-signing geometry
$PY noise_floor.py 16           > $L/noise_floor.log 2>&1   # STEP 2  seed noise floor
$PY screen_morris.py 10 4       > $L/screen_morris.log 2>&1 # STEP 3  Morris screening (8 params incl. --lanechange.duration)
$PY calibrate.py both "lcStrategic,lcCooperative,lcSpeedGain,lcKeepRight,lcAssertive,lcLookaheadLeft,lcSpeedGainRight" > $L/calibrate.log 2>&1  # STEP 4
$PY identifiability.py all      > $L/identifiability.log 2>&1  # STEP 5  equifinality + known-answer recovery
$PY traps.py all                > $L/traps.log 2>&1         # STEP 6  the three traps
$PY validate.py                 > $L/validate.log 2>&1      # STEP 7  hold-out validation
$PY emit_demand.py              > $L/emit_demand.log 2>&1
$PY make_outputs.py             > $L/make_outputs.log 2>&1  # STEP 8  figures + profile CSVs
$PY make_tables.py              > $L/make_tables.log 2>&1   # STEP 9  markdown deliverables
echo PIPELINE_DONE

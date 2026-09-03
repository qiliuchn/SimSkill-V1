#!/bin/bash
set -x
cd "$(dirname "$0")"
A=../analysis
python3 run_sweeps.py --sweeps G --procs 10           >> $A/sweep_G.log 2>&1
python3 probe_stopgo.py --mode boundary               >  $A/probe_boundary.log 2>&1 &
python3 probe_stopgo.py --mode params                 >  $A/probe_params.log 2>&1 &
python3 probe_stopgo.py --mode grade                  >  $A/probe_grade.log 2>&1 &
python3 probe_stopgo.py --mode scan                   >  $A/probe_scan.log 2>&1 &
wait
python3 measure_lost_time.py --procs 10               >  $A/losttime.log 2>&1
python3 crosscheck_actuated.py --procs 10             >  $A/crosscheck.log 2>&1
python3 analyze.py                                    >  $A/analyze.log 2>&1
python3 webster_impact.py                             >> $A/losttime.log 2>&1
python3 report.py                                     >> $A/analyze.log 2>&1
python3 make_plots.py                                 >> $A/analyze.log 2>&1
echo ALL_DONE

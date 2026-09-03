#!/bin/bash
# Full study pipeline. Run from outputs/ .  Each stage appends to work/pipeline.log
set -u
cd "$(dirname "$0")/.."
LOG=work/pipeline.log
: > "$LOG"
for stage in verify_offsets verify_plan h1_resonance h3_cycle h4_leadlag h5_dispersion \
             h6_spillback h2_band_vs_delay reconcile make_figures summarize; do
    echo "=== STAGE $stage $(date +%H:%M:%S) ===" | tee -a "$LOG"
    python3 -u "scripts/${stage}.py" >> "$LOG" 2>&1
    rc=$?
    echo "=== STAGE $stage rc=$rc $(date +%H:%M:%S) ===" | tee -a "$LOG"
    if [ $rc -ne 0 ]; then echo "STAGE FAILED: $stage" | tee -a "$LOG"; fi
done
echo "PIPELINE COMPLETE" | tee -a "$LOG"

#!/bin/bash
# Concatenate the narrative sections and the machine-generated tables into FINDINGS.md.
cd "$(dirname "$0")/.."
python3 scripts/make_findings_tables.py > /dev/null
{
  cat report_parts/part0_summary.md
  cat report_parts/part1.md
  cat report_parts/part2.md
  cat report_parts/part3.md
  cat report_parts/part4.md
  cat report_parts/part5.md
  cat report_parts/part6.md
  cat report_parts/part7.md
  printf '\n---\n\n## 8. Machine-generated tables\n\nEmitted verbatim by `scripts/make_findings_tables.py` from `analysis/variant_aggregate.json`,\n`analysis/equilibrium_selection.json` and `analysis/emergency_access.json`.\nMean of 5 CRN seeds unless noted.\n\n'
  cat analysis/findings_tables.md
} > FINDINGS.md
wc -l FINDINGS.md

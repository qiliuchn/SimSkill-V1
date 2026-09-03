#!/usr/bin/env bash
# Render spatial congestion heatmaps from a time-sliced edgeData file using
# SUMO's plot_net_dump.py ($SUMO_HOME/tools/visualization/plot_net_dump.py),
# one PNG per interval per metric.
#
# Key mappings (verified against real plot_net_dump.py behavior):
#   -m <attr>            : the color measure MUST be an exact <edge> attribute
#                          name from the edgeData file (speed, occupancy,
#                          density, speedRelative, timeLoss, ...). A typo or a
#                          non-existent attribute silently yields default-colored
#                          (missing-data) edges, not an error.
#   --colormap RdYlGn    : low->red, high->green. Use plain RdYlGn for SPEED and
#                          speedRelative (low = red = bad). Use RdYlGn_r for
#                          OCCUPANCY/DENSITY (high value = red = bad).
#   --min/--max-color-value : fix the color scale so multiple intervals/PNGs are
#                          visually comparable against each other.
#   -w <float>           : DEFAULT edge WIDTH. Without a *second* dump file for
#                          width, --min-width/--max-width are ignored and every
#                          edge falls back to --defaultwidth (0.1, effectively
#                          invisible). Set -w explicitly for legible edges.
#   GOTCHA: '%s' is substituted only in the -o (output filename), NOT in
#           --title -- render one interval at a time from split single-interval
#           files (see split_intervals.py) to give each PNG a descriptive title.
#   GOTCHA: on a DEGENERATE 1-D network (all nodes collinear, e.g. all y=0) the
#           rendered LineCollection can come out uniformly black regardless of
#           color data -- the network needs genuine 2-D extent for the color
#           mapping to render correctly.
#   GOTCHA: SUMO's "density" edgeData attribute is normalized PER EDGE, not per
#           lane -- a multi-lane edge can out-rank a genuine single-lane
#           bottleneck on density alone. Color by "occupancy" or
#           "speedRelative" instead to correctly localize a lane-count-change
#           bottleneck.
#
# Usage:
#   render_congestion_heatmaps.sh <net.xml> <edgedata_dir_with_per_interval_files> <plots_out_dir> <interval_begin_1> [<interval_begin_2> ...]
set -euo pipefail
NET="$1"; shift
EDGEDATA_DIR="$1"; shift
PLOTS_DIR="$1"; shift
INTERVALS=("$@")

PND="$SUMO_HOME/tools/visualization/plot_net_dump.py"
export MPLBACKEND=Agg
mkdir -p "$PLOTS_DIR"

render () { # begin measure colormap cmin cmax barlabel prettyname outprefix
  local b="$1" m="$2" cmap="$3" cmin="$4" cmax="$5" bar="$6" name="$7" pre="$8"
  python3 "$PND" -n "$NET" -i "$EDGEDATA_DIR/edgedata_${b}.out.xml" \
    -m "$m" --colormap "$cmap" --min-color-value "$cmin" --max-color-value "$cmax" \
    -w 14 --color-bar-label "$bar" --title "$name @ t=${b}s" \
    --adjust 0.28,0.12 \
    -o "$PLOTS_DIR/${pre}_${b}.png" -b
}

for b in "${INTERVALS[@]}"; do
  render "$b" speed         RdYlGn   0 14 "mean speed (m/s)"   "Mean speed"       speed
  render "$b" occupancy     RdYlGn_r 0 45 "occupancy (%)"      "Lane occupancy"   occupancy
  render "$b" density       RdYlGn_r 0 85 "density (veh/km)"   "Density"          density
  render "$b" speedRelative RdYlGn   0 1  "speed / free-flow"  "Congestion index" congindex
done

echo "done. plots in $PLOTS_DIR:"; ls -1 "$PLOTS_DIR"

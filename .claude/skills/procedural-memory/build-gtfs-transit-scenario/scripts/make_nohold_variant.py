#!/usr/bin/env python
"""Strip the schedule from a gtfs2pt route file: keep routes/vehicles/departures and
per-stop dwell `duration`, but drop every `until`, so stop dwell is endogenous
(minimum duration + person boarding) and no bus is ever HELD to the timetable.
Used as the H4 contrast against the schedule-holding variants."""
import argparse
import re

ap = argparse.ArgumentParser()
ap.add_argument('--routes', required=True)
ap.add_argument('--out', required=True)
a = ap.parse_args()
src = open(a.routes).read()
out, n = re.subn(r'\s+until="[^"]*"', '', src)
open(a.out, 'w').write(out)
print('removed %d until attributes -> %s' % (n, a.out))

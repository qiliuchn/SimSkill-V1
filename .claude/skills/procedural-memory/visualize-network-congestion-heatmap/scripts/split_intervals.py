"""
Split a multi-interval edgeData (meandata) file into one file per interval.

Gotcha this works around: plot_net_dump.py, given a single edgeData file
containing multiple <interval> blocks, does not reliably cycle through them
per invocation -- rendering one interval per file with a single <interval>
element each gives explicit, unambiguous control over which interval's data
colors a given PNG.

Usage:
    python split_intervals.py edgedata_congestion.out.xml "per_interval/edgedata_{b}.out.xml"
"""

import sys
import xml.etree.ElementTree as ET


def main():
    src, out_template = sys.argv[1], sys.argv[2]
    root = ET.parse(src).getroot()
    written = []
    for iv in root.findall("interval"):
        b = int(float(iv.get("begin")))
        e = int(float(iv.get("end")))
        new_root = ET.Element("meandata")
        new_root.append(iv)
        path = out_template.format(b=b, e=e)
        ET.ElementTree(new_root).write(path, encoding="UTF-8", xml_declaration=True)
        written.append((b, e, path))
        print(f"interval {b}-{e} -> {path}")
    print(f"done: {len(written)} files")


if __name__ == "__main__":
    main()

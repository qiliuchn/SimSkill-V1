"""
Rewrite selected edges of a plain-XML .edg.xml with explicit per-lane
allow/disallow permissions, then recompile to a .net.xml with netconvert.

Use this to build a network variant where specific lanes are restricted to
(or excluded from) a vClass -- e.g. a bicycle-only lane, a bus lane, a
truck-restricted lane -- while other edges keep default permissions.

Usage:
    python build_lane_permission_variant.py \
        --node-file base.nod.xml --edge-file base.edg.xml \
        --edge-ids A0B0,B0C0,C0D0,D0E0,E0F0 \
        --lane "0:allow=bicycle" --lane "1:disallow=bicycle" \
        --out-edge-file separated.edg.xml --out-net separated.net.xml

    # or select edges by regex instead of an explicit list:
    python build_lane_permission_variant.py \
        --node-file base.nod.xml --edge-file base.edg.xml \
        --edge-id-regex '^[A-F]0[A-F]0$' \
        --lane "0:allow=bicycle" --lane "1:disallow=bicycle" \
        --out-edge-file separated.edg.xml --out-net separated.net.xml

`--lane` may be repeated, one per lane index that needs an explicit
permission; lane indices not mentioned are left with the network's default
(all vClasses) permissions. Each spec is "<index>:allow=<space-separated
vClasses>" or "<index>:disallow=<space-separated vClasses>".

IMPORTANT: do not pass an existing .con.xml/.tll.xml from the original
(unedited-lane) network alongside the rewritten .edg.xml -- those hard-code
lane-to-lane connections and TLS link indices for the OLD lane layout. When a
lane's permitted classes change (especially when a lane is dropped to a
single-vClass subset), the surviving general-traffic lane(s) need their turn
connections regenerated so routing doesn't fail with "no connection" errors.
Let netconvert regenerate connections and TLS logic from the node+edge files
alone (see compile_net below) -- this is the single most common way this
kind of variant silently breaks.
"""

import argparse
import re
import subprocess
import sys


def parse_args():
    p = argparse.ArgumentParser(description="Build a lane-permission network variant via plain-XML edit + netconvert.")
    p.add_argument("--node-file", required=True)
    p.add_argument("--edge-file", required=True, help="Base .edg.xml to rewrite (only matched edges are touched)")
    p.add_argument("--edge-ids", help="Comma-separated explicit edge id list")
    p.add_argument("--edge-id-regex", help="Regex to select edges by id (alternative to --edge-ids)")
    p.add_argument("--lane", action="append", required=True, help='"<index>:allow=<classes>" or "<index>:disallow=<classes>", repeatable')
    p.add_argument("--out-edge-file", required=True)
    p.add_argument("--out-net", required=True)
    p.add_argument("--extra-edge-file", action="append", default=[], help="Additional unedited .edg.xml file(s) to pass to netconvert (e.g. attach arms), repeatable")
    return p.parse_args()


def build_edge_selector(args):
    if args.edge_ids:
        ids = set(args.edge_ids.split(","))
        return lambda eid: eid in ids
    if args.edge_id_regex:
        rx = re.compile(args.edge_id_regex)
        return lambda eid: bool(rx.match(eid))
    raise SystemExit("Must pass --edge-ids or --edge-id-regex")


def parse_lane_specs(specs):
    """"0:allow=bicycle" -> (0, 'allow', 'bicycle')"""
    parsed = []
    for s in specs:
        idx_part, perm_part = s.split(":", 1)
        key, classes = perm_part.split("=", 1)
        if key not in ("allow", "disallow"):
            raise SystemExit(f"Bad --lane spec {s!r}: expected allow= or disallow=")
        parsed.append((int(idx_part), key, classes))
    return parsed


def rewrite_edg(text, is_target, lane_specs):
    """Turn each matched self-closing <edge id="..." .../> into an open tag
    with explicit <lane index=".." allow/disallow=".."/> children."""
    edge_open_re = re.compile(r'<edge id="([^"]+)"([^/>]*)/>')
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        m = edge_open_re.search(stripped)
        if m and is_target(m.group(1)):
            indent = line[: len(line) - len(line.lstrip())]
            eid, attrs = m.group(1), m.group(2).rstrip()
            out.append(f'{indent}<edge id="{eid}"{attrs}>')
            for idx, key, classes in lane_specs:
                out.append(f'{indent}    <lane index="{idx}" {key}="{classes}"/>')
            out.append(f"{indent}</edge>")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def compile_net(node_file, edge_files, out_net):
    cmd = ["netconvert", "--node-files", node_file, "--edge-files", ",".join(edge_files), "-o", out_net]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"--- netconvert exit={r.returncode} ---")
    if r.stderr.strip():
        print(r.stderr.strip()[:3000])
    return r.returncode


def main():
    args = parse_args()
    is_target = build_edge_selector(args)
    lane_specs = parse_lane_specs(args.lane)

    with open(args.edge_file) as f:
        base = f.read()
    rewritten = rewrite_edg(base, is_target, lane_specs)
    with open(args.out_edge_file, "w") as f:
        f.write(rewritten)

    edge_files = [args.out_edge_file] + args.extra_edge_file
    rc = compile_net(args.node_file, edge_files, args.out_net)
    if rc != 0:
        sys.exit(rc)
    print(f"Wrote {args.out_edge_file} and compiled {args.out_net}")


if __name__ == "__main__":
    main()

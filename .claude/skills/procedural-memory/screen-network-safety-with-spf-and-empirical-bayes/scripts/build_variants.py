"""
Build treatment / diagnostic VARIANTS of an inventory site.

Every variant reuses the parent site's demand (same .rou.xml content, same
Poisson rates) so that running it with the same seed family is a genuine Common
Random Numbers paired design in the sense of `quantify-sumo-run-to-run-variability`.

Usage:
  python build_variants.py --root outputs/variants \
      --variant S06_prot:S06:phasing=prot \
      --variant S19_c35:S19:cycle_mode=short35
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inventory import by_id, approach_volumes
import build_sites as B


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--variant", action="append", required=True,
                    help="NEWID:PARENTID:key=val[,key=val]")
    ap.add_argument("--begin", type=int, default=0)
    ap.add_argument("--end", type=int, default=4200)
    a = ap.parse_args()

    os.makedirs(a.root, exist_ok=True)
    idx = by_id()
    manifest = []
    for spec in a.variant:
        new_id, parent_id, kvs = spec.split(":", 2)
        site = dict(idx[parent_id])
        site["site"] = new_id
        site["parent"] = parent_id
        for kv in kvs.split(","):
            k, v = kv.split("=")
            site[k] = int(v) if v.isdigit() else v

        d = os.path.join(a.root, new_id)
        os.makedirs(d, exist_ok=True)
        geo = B.site_geometry(site)
        vols = approach_volumes(site)
        paths = B.write_plain_xml(site, geo, d)
        net = os.path.join(d, "%s.net.xml" % new_id)
        B.compile_net(paths, net)

        web = None
        if site["control"] == "4SG":
            links = B.read_tl_links(net)
            import xml.etree.ElementTree as ET
            r = ET.parse(net).getroot()
            n_links = max(int(c.get("linkIndex")) for c in r.findall("connection")
                          if c.get("tl") == "center") + 1
            web = B.webster(site, geo, vols)
            phases, table = B.build_program(site, links, web, n_links)
            open(os.path.join(d, "phases.txt"), "w").write(table + "\n")
            json.dump(web, open(os.path.join(d, "webster.json"), "w"), indent=2)
            tll = os.path.join(d, "%s.tll.xml" % new_id)
            B.write_tll(tll, phases)
            B.compile_net(paths, net, tll=tll)

        B.write_additional(site, os.path.join(d, "%s.add.xml" % new_id), None)
        B.write_routes(site, os.path.join(d, "%s.rou.xml" % new_id), vols, a.begin, a.end)
        manifest.append(dict(site=new_id, parent=parent_id, control=site["control"],
                             aadt_major=site["aadt_major"], aadt_minor=site["aadt_minor"],
                             lanes_major=site["lanes_major"], lanes_minor=site["lanes_minor"],
                             phasing=site["phasing"], speed_mph=site["speed_mph"],
                             cycle_mode=site["cycle_mode"],
                             cycle_s=(web["cycle"] if web else None),
                             dir=d))
        print("built variant %s (from %s) phasing=%s cycle=%s"
              % (new_id, parent_id, site["phasing"], web["cycle"] if web else "-"))

    json.dump(manifest, open(os.path.join(a.root, "manifest.json"), "w"), indent=2)


if __name__ == "__main__":
    main()

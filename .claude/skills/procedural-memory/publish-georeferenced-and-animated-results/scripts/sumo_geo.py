"""Georeference a SUMO network and emit / validate RFC 7946 GeoJSON.

The transform, stated exactly:

    (x_local, y_local) = proj(lon, lat) + netOffset
    (lon, lat)         = proj_inverse(x_local - netOffset.x, y_local - netOffset.y)

`netOffset` is a pure translation in PROJECTED METRES -- no rotation, no scale.  All of
it lives in the net's <location> element.

The one thing to understand before trusting any of this: a round-trip
XY -> lon/lat -> XY residual proves NOTHING.  A wrong offset or a wrong projection
inverts just as cleanly as a right one (measured: applying netOffset twice still
round-trips exactly, while sitting 4 209 729 m from the truth).  Only a comparison
against an EXTERNAL ground truth -- the source .osm node coordinates -- discriminates.
`validate_against_osm()` is therefore the load-bearing check, not `roundtrip_residual()`.

Usage as a library:
    loc   = read_location("net.net.xml")
    net   = sumolib.net.readNet("net.net.xml")
    lon,lat = net.convertXY2LonLat(x, y)
    stats = validate_against_osm("net.net.xml", "source.osm.xml")
    write_geojson("network.geojson", features, precision=6)
    errs  = validate_rfc7946("network.geojson")
"""
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

if "SUMO_HOME" in os.environ:
    sys.path.insert(0, os.path.join(os.environ["SUMO_HOME"], "tools"))


# ------------------------------------------------------------------ location ---
def read_location(net_path):
    """Return the <location> element's attributes as a dict.

    projParameter == "!" means NO PROJECTION.  Check this FIRST: sumolib raises
    'Network does not provide geo-projection or pyproj not installed', which
    conflates a missing projection with a missing dependency.  Reading
    projParameter tells you which it actually is.
    """
    for _, el in ET.iterparse(net_path):
        if el.tag == "location":
            d = dict(el.attrib)
            d["has_projection"] = d.get("projParameter", "!") not in ("!", "")
            ox, oy = d.get("netOffset", "0,0").split(",")
            d["netOffset_xy"] = (float(ox), float(oy))
            return d
        if el.tag in ("edge", "junction"):
            break               # <location> is always first; stop early
    return None


def haversine_m(lon1, lat1, lon2, lat2):
    R = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- validation ---
def roundtrip_residual(net, points):
    """XY -> lon/lat -> XY residual in metres. Self-consistent: proves nothing alone."""
    errs = []
    for x, y in points:
        lon, lat = net.convertXY2LonLat(x, y)
        x2, y2 = net.convertLonLat2XY(lon, lat)
        errs.append(math.hypot(x2 - x, y2 - y))
    return _summary(errs)


def validate_against_osm(net_path, osm_path, min_matches=20):
    """THE discriminating check: SUMO junctions vs their source OSM nodes, in metres.

    SUMO keeps OSM node ids as junction ids for junctions it did not synthesise, so the
    join is exact where it exists. Returns error stats plus the match count; a run with
    fewer than `min_matches` joins is not evidence of anything.
    """
    import sumolib
    net = sumolib.net.readNet(net_path)
    osm_nodes = {}
    for _, el in ET.iterparse(osm_path):
        if el.tag == "node":
            try:
                osm_nodes[el.get("id")] = (float(el.get("lon")), float(el.get("lat")))
            except (TypeError, ValueError):
                pass
            el.clear()
    errs, matched = [], []
    for j in net.getNodes():
        ref = osm_nodes.get(j.getID())
        if ref is None:
            continue
        x, y = j.getCoord()
        lon, lat = net.convertXY2LonLat(x, y)
        errs.append(haversine_m(lon, lat, ref[0], ref[1]))
        matched.append(j.getID())
    out = _summary(errs)
    out["matched"] = len(matched)
    out["sufficient"] = len(matched) >= min_matches
    return out


def _summary(errs):
    if not errs:
        return {"n": 0}
    s = sorted(errs)
    n = len(s)
    return {"n": n, "max_m": s[-1], "min_m": s[0],
            "mean_m": sum(s) / n, "median_m": s[n // 2],
            "rms_m": math.sqrt(sum(e * e for e in s) / n),
            "p90_m": s[min(n - 1, int(0.90 * n))],
            "p95_m": s[min(n - 1, int(0.95 * n))]}


# -------------------------------------------------------------- geojson out ---
def write_geojson(path, features, precision=6, metadata=None, bbox=True):
    """Write an RFC 7946 FeatureCollection.

    precision=6 is the default for a reason: it is the last precision with ZERO vertex
    collapse (5 dp silently collapsed 53 vertices on a 402-edge network, 4 dp collapsed
    572), and going coarser buys almost no file size because properties and JSON
    punctuation dominate -- 4 dp was only 13.7% smaller. Do not expect coordinate
    precision to be your compression lever.

    RFC 7946 FORBIDS a `crs` member -- lon/lat WGS84 is mandatory and implicit. To
    publish a non-WGS84 frame (see local_enu_metadata), declare it in a top-level
    `metadata` object, which is a foreign member and legal.
    """
    def rnd(c):
        if isinstance(c[0], (list, tuple)):
            return [rnd(p) for p in c]
        return [round(c[0], precision), round(c[1], precision)]

    feats = []
    for f in features:
        g = f.get("geometry")
        if g:
            g = dict(g, coordinates=rnd(g["coordinates"]))
        feats.append({"type": "Feature", "geometry": g,
                      "properties": f.get("properties", {})})
    fc = {"type": "FeatureCollection", "features": feats}
    if metadata:
        fc["metadata"] = metadata
    if bbox and feats:
        xs, ys = [], []
        for f in feats:
            for lon, lat in _positions(f["geometry"]):
                xs.append(lon)
                ys.append(lat)
        if xs:
            fc["bbox"] = [min(xs), min(ys), max(xs), max(ys)]
    with open(path, "w") as fh:
        json.dump(fc, fh, separators=(",", ":"))
    return os.path.getsize(path)


def local_enu_metadata(loc, assumed_lonlat=None):
    """Metadata block for an UNPROJECTED network. Emit local metres, never fake lon/lat.

    If the operator supplies an anchor, it is recorded as an explicitly DECLARED
    assumption, never as something derived from the network. Note the tangent-plane
    error such an anchor implies: measured max 11.38 m / RMS 7.93 m over a 1.6 x 1.5 km
    extent.
    """
    md = {"coordinate_frame": "LOCAL ENGINEERING / ENU (metres) -- NOT WGS84 lon/lat",
          "axis_order": ["easting_m", "northing_m"],
          "netOffset": loc.get("netOffset"),
          "convBoundary": loc.get("convBoundary"),
          "projParameter": loc.get("projParameter")}
    if assumed_lonlat:
        md["assumed_lonlat"] = list(assumed_lonlat)
        md["declared_by"] = "user/publisher, NOT derived from the network"
    return md


# --------------------------------------------------------------- validation ---
def _positions(geom):
    if not geom:
        return []
    c, t = geom["coordinates"], geom["type"]
    if t == "Point":
        return [c]
    if t in ("LineString", "MultiPoint"):
        return list(c)
    if t in ("Polygon", "MultiLineString"):
        return [p for ring in c for p in ring]
    if t == "MultiPolygon":
        return [p for poly in c for ring in poly for p in ring]
    return []


def validate_rfc7946(path):
    """Return a list of conformance errors ([] means clean).

    Validate a KNOWN-BAD file too (swap lon/lat, add a `crs` member) -- a validator that
    has never rejected anything is not evidence.
    """
    errs = []
    with open(path) as fh:
        fc = json.load(fh)
    if "crs" in fc:
        errs.append("`crs` member present -- forbidden by RFC 7946")
    if fc.get("type") != "FeatureCollection":
        errs.append("root type is not FeatureCollection")
    npos = 0
    for i, f in enumerate(fc.get("features", [])):
        if f.get("type") != "Feature":
            errs.append(f"feature {i}: type is not Feature")
        g = f.get("geometry")
        if g is None:
            continue
        for lon, lat in _positions(g):
            npos += 1
            if not (-180 <= lon <= 180):
                errs.append(f"feature {i}: longitude {lon} out of range "
                            f"(lon/lat swapped?)")
            if not (-90 <= lat <= 90):
                errs.append(f"feature {i}: latitude {lat} out of range "
                            f"(lon/lat swapped?)")
        if g["type"] == "Polygon":
            for r in g["coordinates"]:
                if len(r) < 4 or r[0] != r[-1]:
                    errs.append(f"feature {i}: polygon ring not closed")
    return errs, npos


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    loc = read_location(sys.argv[1])
    print("projParameter:", loc.get("projParameter"))
    print("has_projection:", loc["has_projection"], " netOffset:", loc["netOffset_xy"])
    if len(sys.argv) > 2 and loc["has_projection"]:
        print("vs OSM:", json.dumps(validate_against_osm(sys.argv[1], sys.argv[2]),
                                    indent=2, default=float))

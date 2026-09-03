"""Generate the 3 tlLogic programs, driven by the link-index mapping read from the net.
Guarantees state strings are consistent with the actual link indices."""
import xml.etree.ElementTree as ET

net = ET.parse("../outputs/net.net.xml").getroot()
# movement -> linkIndex
mv = {}
for c in net.findall("connection"):
    if c.get("tl") == "center":
        approach = c.get("from").split("_")[1]  # N/E/S/W
        d = c.get("dir")  # r/s/l
        mv[(approach, d)] = int(c.get("linkIndex"))

N = 12
def blank():
    return ["r"] * N

def setc(state, idx, ch):
    state[idx] = ch

# convenience index lookups
L = {a: mv[(a, "l")] for a in "NESW"}   # left
T = {a: mv[(a, "s")] for a in "NESW"}   # through (straight)
R = {a: mv[(a, "r")] for a in "NESW"}   # right

def phase(spec):
    """spec: dict movement-idx -> char"""
    s = blank()
    for idx, ch in spec.items():
        s[idx] = ch
    return "".join(s)

# ---------- PERMISSIVE-ONLY ----------
perm = []
# NS green: N,S through/right G, left g (permissive)
perm.append((36, phase({R['N']:'G',T['N']:'G',L['N']:'g', R['S']:'G',T['S']:'G',L['S']:'g'})))
perm.append((4,  phase({R['N']:'y',T['N']:'y',L['N']:'y', R['S']:'y',T['S']:'y',L['S']:'y'})))
# EW green
perm.append((36, phase({R['E']:'G',T['E']:'G',L['E']:'g', R['W']:'G',T['W']:'G',L['W']:'g'})))
perm.append((4,  phase({R['E']:'y',T['E']:'y',L['E']:'y', R['W']:'y',T['W']:'y',L['W']:'y'})))

# ---------- PROTECTED-ONLY ----------
prot = []
# NS leading protected left only
prot.append((12, phase({L['N']:'G', L['S']:'G'})))
prot.append((3,  phase({L['N']:'y', L['S']:'y'})))
# NS through/right, left RED
prot.append((21, phase({R['N']:'G',T['N']:'G', R['S']:'G',T['S']:'G'})))
prot.append((4,  phase({R['N']:'y',T['N']:'y', R['S']:'y',T['S']:'y'})))
# EW leading protected left only
prot.append((12, phase({L['E']:'G', L['W']:'G'})))
prot.append((3,  phase({L['E']:'y', L['W']:'y'})))
# EW through/right, left RED
prot.append((21, phase({R['E']:'G',T['E']:'G', R['W']:'G',T['W']:'G'})))
prot.append((4,  phase({R['E']:'y',T['E']:'y', R['W']:'y',T['W']:'y'})))

# ---------- PROTECTED-PERMISSIVE ----------
pp = []
# NS leading protected left (through red)
pp.append((12, phase({L['N']:'G', L['S']:'G'})))
pp.append((3,  phase({L['N']:'y', L['S']:'y'})))
# NS through/right green, left permissive g
pp.append((21, phase({R['N']:'G',T['N']:'G',L['N']:'g', R['S']:'G',T['S']:'G',L['S']:'g'})))
pp.append((4,  phase({R['N']:'y',T['N']:'y',L['N']:'y', R['S']:'y',T['S']:'y',L['S']:'y'})))
# EW leading protected left
pp.append((12, phase({L['E']:'G', L['W']:'G'})))
pp.append((3,  phase({L['E']:'y', L['W']:'y'})))
# EW through/right green, left permissive g
pp.append((21, phase({R['E']:'G',T['E']:'G',L['E']:'g', R['W']:'G',T['W']:'G',L['W']:'g'})))
pp.append((4,  phase({R['E']:'y',T['E']:'y',L['E']:'y', R['W']:'y',T['W']:'y',L['W']:'y'})))

programs = {"permissive": perm, "protected": prot, "protperm": pp}

for name, phases in programs.items():
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<additional>',
             f'    <tlLogic id="center" type="static" programID="{name}" offset="0">']
    for dur, st in phases:
        lines.append(f'        <phase duration="{dur}" state="{st}"/>')
    lines.append('    </tlLogic>')
    lines.append('</additional>')
    with open(f"../outputs/tl_{name}.add.xml", "w") as f:
        f.write("\n".join(lines) + "\n")

# ---- verification print ----
print("Link map (movement -> idx):")
print("  Left  :", L)
print("  Thru  :", T)
print("  Right :", R)
print()
for name, phases in programs.items():
    cyc = sum(d for d, _ in phases)
    print(f"=== {name}  (cycle={cyc}s) ===")
    print("        idx: " + "".join(str(i%10) for i in range(N)))
    for dur, st in phases:
        # annotate left-link chars
        lchars = {a: st[L[a]] for a in 'NESW'}
        print(f"  {dur:2d}s  {st}   leftL(N,S,E,W)={lchars['N']}{lchars['S']}{lchars['E']}{lchars['W']}")
    print()

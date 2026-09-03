---
title: "sumo/tools/tlsCoordinator.py at main"
source: "https://github.com/eclipse-sumo/sumo/blob/main/tools/tlsCoordinator.py"
author:
published:
created: 2026-07-21
description: "Eclipse SUMO is an open source, highly portable, microscopic and continuous traffic simulation package designed to handle large networks. It allows for intermodal simulation including pedestrians and comes with a large set of tools for scenario creation. - sumo/tools/tlsCoordinator.py at main · eclipse-sumo/sumo"
tags:
  - "clippings"
---
1

2

3

4

5

6

7

8

9

10

11

12

13

14

15

16

17

18

19

20

21

22

23

24

25

26

27

28

29

30

31

32

33

34

35

36

37

38

39

40

41

42

43

44

45

46

47

48

49

50

51

52

53

54

55

56

57

58

59

60

61

62

63

64

65

66

67

68

69

70

71

72

73

74

75

76

77

78

79

80

81

82

83

84

85

86

87

88

89

90

91

92

93

94

95

96

97

98

99

100

101

102

103

104

105

106

107

108

109

110

111

112

113

114

115

116

117

118

119

120

121

122

123

124

125

126

127

128

129

130

131

132

133

134

135

136

137

138

139

140

141

142

143

144

145

146

147

148

149

150

151

152

153

154

155

156

157

158

159

160

161

162

163

164

165

166

167

168

169

170

171

172

173

174

175

176

177

178

179

180

181

182

183

184

185

186

187

188

189

190

191

192

193

194

195

196

197

198

199

200

201

202

203

204

205

206

207

208

209

210

211

212

213

214

215

216

217

218

219

220

221

222

223

224

225

226

227

228

229

230

231

232

233

234

235

236

237

238

239

240

241

242

243

244

245

246

247

248

249

250

251

252

253

254

255

256

257

258

259

260

261

262

263

264

265

266

267

268

269

270

271

272

273

274

275

276

277

278

279

280

281

282

283

284

285

286

287

288

289

290

291

292

293

294

295

296

297

298

299

300

301

302

303

304

305

306

307

308

309

310

311

312

313

314

315

316

317

318

319

320

321

322

323

324

325

326

327

328

329

330

331

332

333

334

335

336

337

338

339

340

#!/usr/bin/env python

\# Eclipse SUMO, Simulation of Urban MObility; see https://eclipse.dev/sumo

\# Copyright (C) 2010-2026 German Aerospace Center (DLR) and others.

\# This program and the accompanying materials are made available under the

\# terms of the Eclipse Public License 2.0 which is available at

\# https://www.eclipse.org/legal/epl-2.0/

\# This Source Code may also be made available under the following Secondary

\# Licenses when the conditions for such availability set forth in the Eclipse

\# Public License 2.0 are satisfied: GNU General Public License, version 2

\# or later which is available at

\# https://www.gnu.org/licenses/old-licenses/gpl-2.0-standalone.html

\# SPDX-License-Identifier: EPL-2.0 OR GPL-2.0-or-later

\# @file tlsCoordinator.py

\# @author Martin Taraz (martin@taraz.de)

\# @author Jakob Erdmann

\# @date 2015-09-07

from \_\_future\_\_ import absolute\_import

from \_\_future\_\_ import print\_function

import sys

import subprocess

from collections import namedtuple

import sumolib

from sumolib.output import parse\_fast

from sumolib.options import ArgumentParser

TLTuple = namedtuple('TLTuple', \['edgeID', 'dist', 'time', 'connection'\])

PairKey = namedtuple('PairKey', \['edgeID', 'edgeID2', 'dist'\])

PairData = namedtuple('PairData', \['otl', 'oconnection', 'tl', 'connection', 'betweenOffset', 'startOffset',

'travelTime', 'prio', 'numVehicles', 'ogreen', 'green'\])

def pair2str(p, full=True):

brief = "%s,%s s=%.1f b=%.1f t=%.1f" % (

p.otl.getID(), p.tl.getID(), p.startOffset, p.betweenOffset, p.travelTime)

if full:

return brief + " og=%s g=%s p=%s n=%s" % (p.ogreen, p.green, p.prio, p.numVehicles)

else:

return brief

def logAddedPair(TLSP, sets, operation):

print("added pair %s,%s with operation %s" %

(TLSP.otl.getID(), TLSP.tl.getID(), operation))

for s in sets:

print(" " + " ".join(\[pair2str(p, False) for p in s\]))

def get\_options(args=None):

optParser = ArgumentParser()

optParser.add\_option("-n", "--net-file", category="input", dest="netfile", required=True,

type=ArgumentParser.net\_file, help="define the net file (mandatory)")

optParser.add\_option("-o", "--output-file", category="output", dest="outfile",

default="tlsOffsets.add.xml", type=ArgumentParser.file, help="define the output filename")

optParser.add\_option("-r", "--route-file", category="input", dest="routefile", required=True,

type=ArgumentParser.route\_file, help="define the input route file (mandatory)")

optParser.add\_option("-a", "--additional-file", category="input", dest="addfile",

type=ArgumentParser.additional\_file, help="define replacement tls plans to be coordinated")

optParser.add\_option("-v", "--verbose", category="processing", action="store\_true",

default=False, help="tell me what you are doing")

optParser.add\_option("-i", "--ignore-priority", category="processing", dest="ignorePriority", action="store\_true",

default=False, help="ignore road priority when sorting TLS pairs")

optParser.add\_option("--speed-factor", category="processing", type=float,

default=0.8, help="avg ratio of vehicle speed in relation to the speed limit")

optParser.add\_option("-e", "--evaluate", category="processing", action="store\_true",

default=False, help="run the scenario and print duration statistics")

return optParser.parse\_args(args=args)

def locate(tlsToFind, sets):

"""return

\- the set in which the given traffic light exists

\- the pair in which it was found

\- the index within the pair

"""

for s in sets:

for pair in s:

if tlsToFind == pair.otl:

return s, pair, 0

elif tlsToFind == pair.tl:

return s, pair, 1

return None, None, None

def coordinateAfterSet(TLSP, l1, l1Pair, l1Index):

\# print "coordinateAfter\\n TLSP: %s\\n l1Pair: %s\\n l1Index=%s" % (

\# pair2str(TLSP), pair2str(l1Pair), l1Index)

if l1Index == 0:

TLSPdepart = l1Pair.startOffset - TLSP.ogreen

TLSParrival = TLSPdepart + TLSP.travelTime

TLSPstartOffset2 = TLSParrival - TLSP.green

TLSP = TLSP.\_replace(startOffset=l1Pair.startOffset,

betweenOffset=TLSPstartOffset2 - l1Pair.startOffset)

else:

l1depart = l1Pair.startOffset + l1Pair.betweenOffset + TLSP.ogreen

TLSParrival = l1depart + TLSP.travelTime

TLSPstartOffset = TLSParrival - TLSP.green

TLSP = TLSP.\_replace(startOffset=l1depart, betweenOffset=TLSPstartOffset - l1depart)

l1.append(TLSP)

return TLSP

def coordinateBeforeSet(TLSP, l2, l2Pair, l2Index):

\# print "coordinateBeforeSet\\n TLSP: %s\\n l2Pair: %s\\n l2Index=%s" % (

\# pair2str(TLSP), pair2str(l2Pair), l2Index)

if l2Index == 0:

l2arrival = l2Pair.startOffset + TLSP.green

TLSPdepart = l2arrival - TLSP.travelTime

TLSPstartOffset = TLSPdepart - TLSP.ogreen

TLSP = TLSP.\_replace(

startOffset=TLSPstartOffset, betweenOffset=l2Pair.startOffset - TLSPstartOffset)

else:

l2arrival = l2Pair.startOffset + l2Pair.betweenOffset + TLSP.green

TLSPdepart = l2arrival - TLSP.travelTime

TLSPstartOffset = TLSPdepart - TLSP.ogreen

TLSP = TLSP.\_replace(

startOffset=TLSPstartOffset, betweenOffset=l2arrival - TLSPstartOffset)

l2.append(TLSP)

return TLSP

def computePairOffsets(TLSPList, verbose):

c1, c2, c3, c4, c5 = 0, 0, 0, 0, 0

sets = \[\] # sets of coordinate TLPairs

operation = ""

for TLSP in TLSPList:

l1, l1Pair, l1Index = locate(TLSP.otl, sets)

l2, l2Pair, l2Index = locate(TLSP.tl, sets)

\# print(l1)

if l1 is None and l2 is None:

\# new set

newlist = \[\]

newlist.append(TLSP)

sets.append(newlist)

c1 += 1

operation = "newSet"

elif l2 is None and l1 is not None:

\# add to set 1 - add after existing set

TLSP = coordinateAfterSet(TLSP, l1, l1Pair, l1Index)

c2 += 1

operation = "addAfterSet"

elif l1 is None and l2 is not None:

\# add to set 2 - add before existing set

TLSP = coordinateBeforeSet(TLSP, l2, l2Pair, l2Index)

c3 += 1

operation = "addBeforeSet"

else:

if l1 == l2:

\# cannot uncoordinated both tls. coordinate the first

\# arbitrarily

TLSP = coordinateAfterSet(TLSP, l1, l1Pair, l1Index)

c4 += 1

operation = "addHalfCoordinated"

else:

\# merge sets

TLSP = coordinateAfterSet(TLSP, l1, l1Pair, l1Index)

if verbose:

logAddedPair(TLSP, sets, "addAfterSet (intermediate)")

\# print "merge\\n TLSP: %s\\n l1Pair: %s\\n l1Index=%s\\n l2Pair: %s\\n l2Index=%s" % (

\# pair2str(TLSP), pair2str(l1Pair), l1Index, pair2str(l2Pair),

\# l2Index)

if l2Index == 0:

dt = TLSP.startOffset + \\

TLSP.betweenOffset - l2Pair.startOffset

else:

dt = TLSP.startOffset + TLSP.betweenOffset - \\

(l2Pair.startOffset + l2Pair.betweenOffset)

merge(sets, l1, l2, dt)

c5 += 1

operation = "mergeSets"

if verbose:

logAddedPair(TLSP, sets, operation)

print("operations: newSet=%s addToSet=%s addToSet2=%s addHalfCoordinated=%s mergeSets=%s" % (

c1, c2, c3, c4, c5))

return sets

def merge(sets, list1, list2, dt):

for elem in list2:

list1.append(elem.\_replace(startOffset=elem.startOffset + dt))

sets.remove(list2)

def finalizeOffsets(sets):

offsetDict = {}

for singleSet in sets:

singleSet.sort(

key=lambda pd: (pd.prio, pd.numVehicles / pd.travelTime), reverse=True)

for pair in singleSet:

\# print " %s,%s:%s,%s" % (pair.otl.getID(), pair.tl.getID(),

\# pair.startOffset, pair.betweenOffset)

tl1 = pair.otl.getID()

tl2 = pair.tl.getID()

betweenOffset = pair.betweenOffset

startOffset = pair.startOffset

if tl1 not in offsetDict:

\# print " added %s offset %s" % (tl1, startOffset)

offsetDict\[tl1\] = startOffset

if tl2 not in offsetDict:

\# print " added %s offset %s" % (tl2, startOffset +

\# betweenOffset)

offsetDict\[tl2\] = startOffset + betweenOffset

return offsetDict

def getTLSInRoute(net, edge\_ids):

rTLSList = \[\] # list of traffic lights along the current route

dist = 0

time = 0

edgesSeen = set()

for edgeID, nextEdgeID in zip(edge\_ids\[:-1\], edge\_ids\[1:\]):

edge = net.getEdge(edgeID)

nextEdge = net.getEdge(nextEdgeID)

if nextEdge not in edge.getOutgoing():

sys.stderr.write("Warning: Skipping disconnected route (edges %s, %s)\\n" % (edgeID, nextEdgeID))

return \[\]

connection = edge.getOutgoing()\[nextEdge\]\[0\]

TLS = None if edge.getToNode().getType() in ("rail\_crossing", "rail\_signal") else edge.getTLS()

dist += edge.getLength()

time += edge.getLength() / edge.getSpeed()

if TLS and edgeID not in edgesSeen:

rTLSList.append(TLTuple(edgeID, dist, time, connection))

edgesSeen.add(edgeID)

dist = 0

time = 0

return rTLSList

def getFirstGreenOffset(tl, connection):

index = connection.getTLLinkIndex()

tlp = tl.getPrograms()

if len(tlp)!= 1:

raise RuntimeError("Found %s programs for tl %s" %

(len(tlp), connection.\_tls))

phases = list(tlp.values())\[0\].getPhases()

start = 0

for p in phases:

if p.state\[index\] in \['G', 'g'\]:

return start

else:

start += p.duration

raise RuntimeError(

"No green light for tlIndex %s at tl %s" % (index, connection.\_tls))

def getTLPairs(net, routeFile, speedFactor, ignorePriority):

\# pairs of traffic lights

TLPairs = {} # PairKey -> PairData

for route in parse\_fast(routeFile, 'route', \['edges'\]):

rTLSList = getTLSInRoute(net, route.edges.split())

for oldTL, TLelement in zip(rTLSList\[:-1\], rTLSList\[1:\]):

key = PairKey(oldTL.edgeID, TLelement.edgeID, oldTL.dist)

numVehicles = 0 if key not in TLPairs else TLPairs\[key\].numVehicles

tl = net.getEdge(TLelement.edgeID).getTLS()

otl = net.getEdge(oldTL.edgeID).getTLS()

edge = net.getEdge(TLelement.edgeID)

connection = TLelement.connection

oconnection = oldTL.connection

ogreen = getFirstGreenOffset(otl, oconnection)

green = getFirstGreenOffset(tl, connection)

travelTime = TLelement.time / speedFactor

betweenOffset = travelTime + ogreen - green

startOffset = 0

\# relevant data for a pair of traffic lights

prio = 1 if ignorePriority else edge.getPriority()

TLPairs\[key\] = PairData(otl, oconnection, tl, connection, betweenOffset, startOffset, travelTime,

prio, numVehicles + 1, ogreen, green)

return TLPairs

def removeDuplicates(TLPairs):

\# @todo: for multiple pairs with the same edges but different dist, keep only the one with the largest numVehicles

return TLPairs

def main(options):

net = sumolib.net.readNet(options.netfile, withLatestPrograms=True)

if options.addfile is not None:

sumolib.net.readNet(options.addfile, withLatestPrograms=True, net=net)

TLPairs = getTLPairs(net, options.routefile, options.speed\_factor, options.ignorePriority)

TLPairs = removeDuplicates(TLPairs)

sortHelper = \[(

(pairData.prio, pairData.numVehicles / pairData.travelTime), # sortKey

(pairKey, pairData)) # payload

for pairKey, pairData in TLPairs.items()\]

tlPairsList = \[

value for sortKey, value in sorted(sortHelper, reverse=True)\]

print("number of tls-pairs: %s" % len(tlPairsList))

if options.verbose:

print('\\n'.join(\["edges=%s,%s prio=%s numVehicles/time=%s" % (

pairKey.edgeID, pairKey.edgeID2, pairData.prio, pairData.numVehicles / pairData.travelTime)

for pairKey, pairData in tlPairsList\]))

coordinatedSets = computePairOffsets(

\[pairData for pairKey, pairData in tlPairsList\], options.verbose)

offsetDict = finalizeOffsets(coordinatedSets)

with open(options.outfile, 'w') as outf:

sumolib.xml.writeHeader(outf, root="additional", options=options)

for ID, startOffset in sorted(offsetDict.items()):

programID = list(net.getTLSSecure(ID).getPrograms().keys())\[0\]

outf.write(' \<tlLogic id="%s" programID="%s" offset="%.2f"/>\\n' %

(ID, programID, startOffset))

outf.write('\</additional>\\n')

sumo = sumolib.checkBinary('sumo')

if options.evaluate:

additionals = \[options.outfile\]

if options.addfile:

additionals = \[options.addfile\] + additionals

subprocess.call(\[sumo,

'-n', options.netfile,

'-r', options.routefile,

'-a', ','.join(additionals),

'-v', '--no-step-log', '--duration-log.statistics'\], stdout=sys.stdout)

if \_\_name\_\_ == "\_\_main\_\_":

options = get\_options()

main(options)
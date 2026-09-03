---
title: "duarouter - SUMO Documentation"
source: "https://sumo.dlr.de/docs/duarouter.html"
author:
published:
created: 2026-07-21
description:
tags:
  - "clippings"
---
## duarouter

## From 30.000 feet

**duarouter** imports different demand definitions, computes vehicle routes that may be used by [sumo](https://sumo.dlr.de/docs/sumo.html) using shortest path computation; When called iteratively **duarouter** performs [dynamic user assignment (DUA)](https://sumo.dlr.de/docs/Demand/Dynamic_User_Assignment.html). This is facilitated by the tool [duaIterate.py](https://sumo.dlr.de/docs/Tools/Assign.html#duaiteratepy) which converges to an equilibrium state (DUE).

- **Purpose:**
	A) Building vehicle routes from demand definitions
	B) Computing routes during a user assignment
	C) Repairing connectivity problems in existing route files
- **System:** portable (Linux/Windows is tested); runs on command line
- **Input (mandatory):**
	A) a road network as generated via [netconvert](https://sumo.dlr.de/docs/netconvert.html) or [netgenerate](https://sumo.dlr.de/docs/netgenerate.html), see [Building Networks](https://sumo.dlr.de/docs/index.html#network_building)
- **Output:** [Definition of Vehicles, Vehicle Types, and Routes](https://sumo.dlr.de/docs/Definition_of_Vehicles%2C_Vehicle_Types%2C_and_Routes.html) usable by [sumo](https://sumo.dlr.de/docs/sumo.html)
- **Programming Language:** C++

## Usage Description

Duarouter has two main purposes: [Computing fastest/optimal routes](https://sumo.dlr.de/docs/Demand/Shortest_or_Optimal_Path_Routing.html) directly as well as iteratively in the context of [Dynamic\_User\_Assignment](https://sumo.dlr.de/docs/Demand/Dynamic_User_Assignment.html).

## Outputs

The primary output of duarouter is a *.rou.xml* file which has its name specified by the option **\-o**). Additionally a *.rou.alt.xml* with the same name prefix as the *.rou.xml* file will be generated. This *route alternative* file holds a [routeDistribution for every vehicle](https://sumo.dlr.de/docs/Definition_of_Vehicles%2C_Vehicle_Types%2C_and_Routes.html#route_and_vehicle_type_distributions). Such a *routeDistribution* is used during [dynamic user assignment (DUA)](https://sumo.dlr.de/docs/Demand/Dynamic_User_Assignment.html) but can also be loaded directly into [sumo](https://sumo.dlr.de/docs/sumo.html).

## Options

You may use a XML schema definition file for setting up a duarouter configuration: [duarouterConfiguration.xsd](https://sumo.dlr.de/xsd/duarouterConfiguration.xsd).

### Configuration

All applications of the **SUMO** -suite handle configuration options the same way. These options are discussed at [Basics/Using the Command Line Applications#Configuration Files](https://sumo.dlr.de/docs/Basics/Using_the_Command_Line_Applications.html#configuration_files).

| Option | Description |
| --- | --- |
| **\-c** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--configuration-file** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Loads the named config on startup |
| **\-C** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--save-configuration** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Saves current configuration into FILE |
| **\--save-configuration.relative** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Enforce relative paths when saving the configuration; *default:* **false** |
| **\--save-template** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Saves a configuration template (empty) into FILE |
| **\--save-schema** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Saves the configuration schema into FILE |
| **\--save-commented** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Adds comments to saved template, configuration, or schema; *default:* **false** |

### Input

| Option | Description |
| --- | --- |
| **\-n** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--net-file** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use FILE as SUMO-network to route on |
| **\-a** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--additional-files** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Read additional network data (districts, bus stops) from FILE(s) |
| **\-r** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--route-files** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Read sumo routes, alternatives, flows, and trips from FILE(s) |
| **\--phemlight-path** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Determines where to load PHEMlight definitions from; *default:* **./PHEMlight/** |
| **\--phemlight-year** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Enable fleet age modelling with the given reference year in PHEMlight5; *default:* **0** |
| **\--phemlight-temperature** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set ambient temperature to correct NOx emissions in PHEMlight5; *default:* **1.79769e+308** |
| **\-w** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--weight-files** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Read network weights from FILE(s) |
| **\--lane-weight-files** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Read lane-based network weights from FILE(s) |
| **\-x** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--weight-attribute** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Name of the xml attribute which gives the edge weight; *default:* **traveltime** |
| **\--junction-taz** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Initialize a TAZ for every junction to use attributes toJunction and fromJunction; *default:* **false** |

### Output

| Option | Description |
| --- | --- |
| **\-o** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--output-file** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write generated routes to FILE |
| **\--vtype-output** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write used vehicle types into separate FILE |
| **\--keep-vtype-distributions** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Keep vTypeDistribution ids when writing vehicles and their types; *default:* **false** |
| **\--emissions.volumetric-fuel** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Return fuel consumption values in (legacy) unit l instead of mg; *default:* **false** |
| **\--named-routes** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write vehicles that reference routes by their id; *default:* **false** |
| **\--write-license** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Include license info into every output file; *default:* **false** |
| **\--write-metadata** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write parsable metadata (configuration etc.) instead of comments; *default:* **false** |
| **\--output-prefix** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Prefix which is applied to all output files. The special string 'TIME' is replaced by the current time. |
| **\--output-suffix** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Suffix which is applied to all output files. The special string 'TIME' is replaced by the current time. |
| **\--precision** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines the number of digits after the comma for floating point output; *default:* **2** |
| **\--precision.geo** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines the number of digits after the comma for lon,lat output; *default:* **6** |
| **\--output.compression** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines the standard compression algorithm (currently only for parquet output) |
| **\--output.format** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines the standard output format if not derivable from the file name ('xml', 'csv', 'parquet'); *default:* **xml** |
| **\--output.column-header** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | How to derive column headers from attribute names ('none', 'tag', 'auto', 'plain'); *default:* **tag** |
| **\--output.column-separator** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Separator in CSV output; *default:* **;** |
| **\-H** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--human-readable-time** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write time values as hour:minute:second or day:hour:minute:second rather than seconds; *default:* **false** |
| **\--alternatives-output** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write generated route alternatives to FILE |
| **\--intermodal-network-output** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write edge splits and connectivity to FILE |
| **\--intermodal-weight-output** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write intermodal edges with lengths and travel times to FILE |
| **\--write-trips** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write trips instead of vehicles (for validating trip input); *default:* **false** |
| **\--write-trips.geo** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write trips with geo-coordinates; *default:* **false** |
| **\--write-trips.junctions** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write trips with fromJunction and toJunction; *default:* **false** |
| **\--write-costs** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Include the cost attribute in route output; *default:* **false** |
| **\--exit-times** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write exit times (weights) for each edge; *default:* **false** |
| **\--route-length** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Include total route length in the output; *default:* **false** |

### Processing

| Option | Description |
| --- | --- |
| **\--max-alternatives** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Prune the number of alternatives to INT; *default:* **5** |
| **\--with-taz** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use origin and destination zones (districts) for in- and output; *default:* **false** |
| **\--unsorted-input** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assume input is unsorted; *default:* **false** |
| **\-s** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--route-steps** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Load routes for the next number of seconds ahead; *default:* **200** |
| **\--no-internal-links** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disable (junction) internal links; *default:* **false** |
| **\--randomize-flows** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | generate random departure times for flow input; *default:* **false** |
| **\--remove-loops** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Remove loops within the route; Remove turnarounds at start and end of the route; *default:* **false** |
| **\--repair** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Tries to correct a false route; *default:* **false** |
| **\--repair.from** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Tries to correct an invalid starting edge by using the first usable edge instead; *default:* **false** |
| **\--repair.to** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Tries to correct an invalid destination edge by using the last usable edge instead; *default:* **false** |
| **\--repair.max-detour-factor** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Backtrack on route if the detour is longer than the gap by FACTOR; *default:* **10** |
| **\--mapmatch.distance** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Maximum distance when mapping input coordinates (fromXY etc.) to the road network; *default:* **100** |
| **\--mapmatch.junctions** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Match positions to junctions instead of edges; *default:* **false** |
| **\--mapmatch.taz** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Match positions to taz instead of edges; *default:* **false** |
| **\--bulk-routing** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Aggregate routing queries with the same origin; *default:* **false** |
| **\--routing-threads** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The number of parallel execution threads used for routing; *default:* **0** |
| **\--routing-algorithm** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Select among routing algorithms \['dijkstra', 'astar', 'CH', 'CHWrapper'\]; *default:* **dijkstra** |
| **\--restriction-params** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Comma separated list of param keys to compare for additional restrictions |
| **\--weights.interpolate** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Interpolate edge weights at interval boundaries; *default:* **false** |
| **\--weights.expand** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Expand the end of the last loaded weight interval to infinity; *default:* **false** |
| **\--weights.minor-penalty** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Apply the given time penalty when computing routing costs for minor-link internal lanes; *default:* **1.5** |
| **\--weights.tls-penalty** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Apply the given time penalty when computing routing costs across a traffic light; *default:* **0** |
| **\--weights.turnaround-penalty** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Apply the given time penalty when computing routing costs for turnaround internal lanes; *default:* **5** |
| **\--weights.reversal-penalty** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Apply the given time penalty when computing routing costs for train reversal. Negative values disable reversal; *default:* **60** |
| **\--weights.random-factor** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Edge weights for routing are dynamically disturbed by a random factor drawn uniformly from \[1,FLOAT); *default:* **1** |
| **\--weight-period** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Aggregation period for the given weight files; triggers rebuilding of Contraction Hierarchy; *default:* **3600** |
| **\--weights.priority-factor** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Consider edge priorities in addition to travel times, weighted by factor; *default:* **0** |
| **\--astar.all-distances** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Initialize lookup table for astar from the given file (generated by marouter --all-pairs-output) |
| **\--astar.landmark-distances** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Initialize lookup table for astar ALT-variant from the given file |
| **\--astar.save-landmark-distances** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Save lookup table for astar ALT-variant to the given file |
| **\--scale** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Scale demand by the given factor (by discarding or duplicating vehicles); *default:* **1** |
| **\--scale-suffix** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Suffix to be added when creating ids for cloned vehicles; *default:* **.** |
| **\--taxi.vclasses** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Network permissions that can be accessed by taxis; *default:* **taxi** |
| **\--gawron.beta** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use FLOAT as Gawron's beta; *default:* **0.9** |
| **\--gawron.a** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use FLOAT as Gawron's a; *default:* **0.5** |
| **\--keep-all-routes** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Save routes with near zero probability; *default:* **false** |
| **\--skip-new-routes** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Only reuse routes from input, do not calculate new ones; *default:* **false** |
| **\--keep-route-probability** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The probability of keeping the old route; *default:* **0** |
| **\--ptline-routing** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Route all public transport input; *default:* **false** |
| **\--keep-flows** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write flows instead of expanding them into vehicles; *default:* **false** |
| **\--route-choice-method** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Choose a route choice method: gawron, logit, or lohse; *default:* **gawron** |
| **\--logit** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use c-logit model (deprecated in favor of --route-choice-method logit); *default:* **false** |
| **\--logit.beta** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use FLOAT as logit's beta; *default:* **\-1** |
| **\--logit.gamma** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use FLOAT as logit's gamma; *default:* **1** |
| **\--logit.theta** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use FLOAT as logit's theta (negative values mean auto-estimation); *default:* **\-1** |
| **\--persontrip.walkfactor** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use FLOAT as a factor on pedestrian maximum speed during intermodal routing; *default:* **0.75** |
| **\--persontrip.walk-opposite-factor** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use FLOAT as a factor on walking speed against vehicle traffic direction; *default:* **1** |
| **\--persontrip.transfer.car-walk** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Where are mode changes from car to walking allowed (possible values: 'parkingAreas', 'ptStops', 'allJunctions' and combinations); *default:* **parkingAreas** |
| **\--persontrip.transfer.taxi-walk** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Where taxis can drop off customers ('allJunctions, 'ptStops') |
| **\--persontrip.transfer.walk-taxi** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Where taxis can pick up customers ('allJunctions, 'ptStops') |
| **\--persontrip.taxi.waiting-time** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Estimated time for taxi pickup; *default:* **300** |
| **\--persontrip.ride-public-line** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Only use the intended public transport line rather than any alternative line that stops at the destination; *default:* **false** |
| **\--railway.max-train-length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use FLOAT as a maximum train length when initializing the railway router; *default:* **1000** |
| **\--max-traveltime** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Declare routing failure if traveltime exceeds the given positive TIME; *default:* **\-1** |

### Defaults

| Option | Description |
| --- | --- |
| **\--departlane** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default depart lane |
| **\--departpos** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default depart position |
| **\--departspeed** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default depart speed |
| **\--arrivallane** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default arrival lane |
| **\--arrivalpos** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default arrival position |
| **\--arrivalspeed** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default arrival speed |
| **\--defaults-override** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defaults will override given values; *default:* **false** |

### Time

| Option | Description |
| --- | --- |
| **\-b** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--begin** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines the begin time; Previous trips will be discarded; *default:* **0** |
| **\-e** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--end** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines the end time; Later trips will be discarded; Defaults to the maximum time that SUMO can represent; *default:* **\-1** |

### Report

All applications of the **SUMO** -suite handle most of the reporting options the same way. These options are discussed at [Basics/Using the Command Line Applications#Reporting Options](https://sumo.dlr.de/docs/Basics/Using_the_Command_Line_Applications.html#reporting_options).

| Option | Description |
| --- | --- |
| **\-v** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--verbose** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Switches to verbose output; *default:* **false** |
| **\--print-options** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Prints option values before processing; *default:* **false** |
| **\-?** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--help** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Prints this screen or selected topics; *default:* **false** |
| **\-V** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--version** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Prints the current version; *default:* **false** |
| **\-X** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--xml-validation** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set schema validation scheme of XML inputs ("never", "local", "auto" or "always"); *default:* **local** |
| **\--xml-validation.net** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set schema validation scheme of SUMO network inputs ("never", "local", "auto" or "always"); *default:* **never** |
| **\--xml-validation.routes** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set schema validation scheme of SUMO route inputs ("never", "local", "auto" or "always"); *default:* **local** |
| **\-W** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--no-warnings** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disables output of warnings; *default:* **false** |
| **\--aggregate-warnings** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Aggregate warnings of the same type whenever more than INT occur; *default:* **\-1** |
| **\-l** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--log** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes all messages to FILE (implies verbose) |
| **\--message-log** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes all non-error messages to FILE (implies verbose) |
| **\--error-log** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes all warnings and errors to FILE |
| **\--log.timestamps** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes timestamps in front of all messages; *default:* **false** |
| **\--log.processid** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes process ID in front of all messages; *default:* **false** |
| **\--language** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Language to use in messages; *default:* **C** |
| **\--ignore-errors** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Continue if a route could not be build; *default:* **false** |
| **\--stats-period** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines how often statistics shall be printed; *default:* **\-1** |
| **\--no-step-log** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disable console output of route parsing step; *default:* **false** |

### Random Number

All applications of the **SUMO** -suite handle randomisation options the same way. These options are discussed at [Basics/Using the Command Line Applications#Random Number Options](https://sumo.dlr.de/docs/Basics/Using_the_Command_Line_Applications.html#random_number_options).

| Option | Description |
| --- | --- |
| **\--random** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Initialises the random number generator with the current system time; *default:* **false** |
| **\--seed** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Initialises the random number generator with the given value; *default:* **23423** |
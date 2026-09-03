---
title: "sumo/docs/web/docs/duarouter.md at main"
source: "https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/duarouter.md"
author:
published:
created: 2026-07-21
description: "Eclipse SUMO is an open source, highly portable, microscopic and continuous traffic simulation package designed to handle large networks. It allows for intermodal simulation including pedestrians and comes with a large set of tools for scenario creation. - sumo/docs/web/docs/duarouter.md at main · eclipse-sumo/sumo"
tags:
  - "clippings"
---
| title | duarouter |
| --- | --- |

## From 30.000 feet

**duarouter** imports different demand definitions, computes vehicle routes that may be used by [sumo](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/sumo.md) using shortest path computation; When called iteratively **duarouter** performs [dynamic user assignment (DUA)](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/Demand/Dynamic_User_Assignment.md). This is facilitated by the tool [duaIterate.py](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/Tools/Assign.md#duaiteratepy) which converges to an equilibrium state (DUE).

- **Purpose:**
	A) Building vehicle routes from demand definitions
	B) Computing routes during a user assignment
	C) Repairing connectivity problems in existing route files
- **System:** portable (Linux/Windows is tested); runs on command line
- **Input (mandatory):**
	A) a road network as generated via [netconvert](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/netconvert.md) or [netgenerate](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/netgenerate.md), see [Building Networks](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/index.md#network_building)
	B) a demand definition, see [Demand Modelling](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/index.md#demand_modelling)
- **Output:** [Definition of Vehicles, Vehicle Types, and Routes](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/Definition_of_Vehicles,_Vehicle_Types,_and_Routes.md) usable by [sumo](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/sumo.md)
- **Programming Language:** C++

## Usage Description

Duarouter has two main purposes: [Computing fastest/optimal routes](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/Demand/Shortest_or_Optimal_Path_Routing.md) directly as well as iteratively in the context of [Dynamic\_User\_Assignment](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/Demand/Dynamic_User_Assignment.md).

## Outputs

The primary output of duarouter is a *.rou.xml* file which has its name specified by the option **\-o**). Additionally a *.rou.alt.xml* with the same name prefix as the *.rou.xml* file will be generated. This *route alternative* file holds a [routeDistribution for every vehicle](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/Definition_of_Vehicles,_Vehicle_Types,_and_Routes.md#route_and_vehicle_type_distributions). Such a *routeDistribution* is used during [dynamic user assignment (DUA)](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/Demand/Dynamic_User_Assignment.md) but can also be loaded directly into [sumo](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/sumo.md).

## Options

You may use a XML schema definition file for setting up a duarouter configuration: [duarouterConfiguration.xsd](https://sumo.dlr.de/xsd/duarouterConfiguration.xsd).

### Configuration

All applications of the **SUMO** -suite handle configuration options the same way. These options are discussed at [Basics/Using the Command Line Applications#Configuration Files](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/Basics/Using_the_Command_Line_Applications.md#configuration_files).

| Option | Description |
| --- | --- |
| **\-c** {{DT\_FILE}}   **\--configuration-file** {{DT\_FILE}} | Loads the named config on startup |
| **\-C** {{DT\_FILE}}   **\--save-configuration** {{DT\_FILE}} | Saves current configuration into FILE |
| **\--save-configuration.relative** {{DT\_BOOL}} | Enforce relative paths when saving the configuration; *default:* **false** |
| **\--save-template** {{DT\_FILE}} | Saves a configuration template (empty) into FILE |
| **\--save-schema** {{DT\_FILE}} | Saves the configuration schema into FILE |
| **\--save-commented** {{DT\_BOOL}} | Adds comments to saved template, configuration, or schema; *default:* **false** |

### Input

| Option | Description |
| --- | --- |
| **\-n** {{DT\_FILE}}   **\--net-file** {{DT\_FILE}} | Use FILE as SUMO-network to route on |
| **\-a** {{DT\_FILE}}   **\--additional-files** {{DT\_FILE}} | Read additional network data (districts, bus stops) from FILE(s) |
| **\-r** {{DT\_FILE}}   **\--route-files** {{DT\_FILE}} | Read sumo routes, alternatives, flows, and trips from FILE(s) |
| **\--phemlight-path** {{DT\_FILE}} | Determines where to load PHEMlight definitions from; *default:* **./PHEMlight/** |
| **\--phemlight-year** {{DT\_INT}} | Enable fleet age modelling with the given reference year in PHEMlight5; *default:* **0** |
| **\--phemlight-temperature** {{DT\_FLOAT}} | Set ambient temperature to correct NOx emissions in PHEMlight5; *default:* **1.79769e+308** |
| **\-w** {{DT\_FILE}}   **\--weight-files** {{DT\_FILE}} | Read network weights from FILE(s) |
| **\--lane-weight-files** {{DT\_FILE}} | Read lane-based network weights from FILE(s) |
| **\-x** {{DT\_STR}}   **\--weight-attribute** {{DT\_STR}} | Name of the xml attribute which gives the edge weight; *default:* **traveltime** |
| **\--junction-taz** {{DT\_BOOL}} | Initialize a TAZ for every junction to use attributes toJunction and fromJunction; *default:* **false** |

### Output

| Option | Description |
| --- | --- |
| **\-o** {{DT\_FILE}}   **\--output-file** {{DT\_FILE}} | Write generated routes to FILE |
| **\--vtype-output** {{DT\_FILE}} | Write used vehicle types into separate FILE |
| **\--keep-vtype-distributions** {{DT\_BOOL}} | Keep vTypeDistribution ids when writing vehicles and their types; *default:* **false** |
| **\--emissions.volumetric-fuel** {{DT\_BOOL}} | Return fuel consumption values in (legacy) unit l instead of mg; *default:* **false** |
| **\--named-routes** {{DT\_BOOL}} | Write vehicles that reference routes by their id; *default:* **false** |
| **\--write-license** {{DT\_BOOL}} | Include license info into every output file; *default:* **false** |
| **\--write-metadata** {{DT\_BOOL}} | Write parsable metadata (configuration etc.) instead of comments; *default:* **false** |
| **\--output-prefix** {{DT\_STR}} | Prefix which is applied to all output files. The special string 'TIME' is replaced by the current time. |
| **\--output-suffix** {{DT\_STR}} | Suffix which is applied to all output files. The special string 'TIME' is replaced by the current time. |
| **\--precision** {{DT\_INT}} | Defines the number of digits after the comma for floating point output; *default:* **2** |
| **\--precision.geo** {{DT\_INT}} | Defines the number of digits after the comma for lon,lat output; *default:* **6** |
| **\--output.compression** {{DT\_STR}} | Defines the standard compression algorithm (currently only for parquet output) |
| **\--output.format** {{DT\_STR}} | Defines the standard output format if not derivable from the file name ('xml', 'csv', 'parquet'); *default:* **xml** |
| **\--output.column-header** {{DT\_STR}} | How to derive column headers from attribute names ('none', 'tag', 'auto', 'plain'); *default:* **tag** |
| **\--output.column-separator** {{DT\_STR}} | Separator in CSV output; *default:* **;** |
| **\-H** {{DT\_BOOL}}   **\--human-readable-time** {{DT\_BOOL}} | Write time values as hour:minute:second or day:hour:minute:second rather than seconds; *default:* **false** |
| **\--alternatives-output** {{DT\_FILE}} | Write generated route alternatives to FILE |
| **\--intermodal-network-output** {{DT\_FILE}} | Write edge splits and connectivity to FILE |
| **\--intermodal-weight-output** {{DT\_FILE}} | Write intermodal edges with lengths and travel times to FILE |
| **\--write-trips** {{DT\_BOOL}} | Write trips instead of vehicles (for validating trip input); *default:* **false** |
| **\--write-trips.geo** {{DT\_BOOL}} | Write trips with geo-coordinates; *default:* **false** |
| **\--write-trips.junctions** {{DT\_BOOL}} | Write trips with fromJunction and toJunction; *default:* **false** |
| **\--write-costs** {{DT\_BOOL}} | Include the cost attribute in route output; *default:* **false** |
| **\--exit-times** {{DT\_BOOL}} | Write exit times (weights) for each edge; *default:* **false** |
| **\--route-length** {{DT\_BOOL}} | Include total route length in the output; *default:* **false** |

### Processing

| Option | Description |
| --- | --- |
| **\--max-alternatives** {{DT\_INT}} | Prune the number of alternatives to INT; *default:* **5** |
| **\--with-taz** {{DT\_BOOL}} | Use origin and destination zones (districts) for in- and output; *default:* **false** |
| **\--unsorted-input** {{DT\_BOOL}} | Assume input is unsorted; *default:* **false** |
| **\-s** {{DT\_TIME}}   **\--route-steps** {{DT\_TIME}} | Load routes for the next number of seconds ahead; *default:* **200** |
| **\--no-internal-links** {{DT\_BOOL}} | Disable (junction) internal links; *default:* **false** |
| **\--randomize-flows** {{DT\_BOOL}} | generate random departure times for flow input; *default:* **false** |
| **\--remove-loops** {{DT\_BOOL}} | Remove loops within the route; Remove turnarounds at start and end of the route; *default:* **false** |
| **\--repair** {{DT\_BOOL}} | Tries to correct a false route; *default:* **false** |
| **\--repair.from** {{DT\_BOOL}} | Tries to correct an invalid starting edge by using the first usable edge instead; *default:* **false** |
| **\--repair.to** {{DT\_BOOL}} | Tries to correct an invalid destination edge by using the last usable edge instead; *default:* **false** |
| **\--repair.max-detour-factor** {{DT\_FLOAT}} | Backtrack on route if the detour is longer than the gap by FACTOR; *default:* **10** |
| **\--mapmatch.distance** {{DT\_FLOAT}} | Maximum distance when mapping input coordinates (fromXY etc.) to the road network; *default:* **100** |
| **\--mapmatch.junctions** {{DT\_BOOL}} | Match positions to junctions instead of edges; *default:* **false** |
| **\--mapmatch.taz** {{DT\_BOOL}} | Match positions to taz instead of edges; *default:* **false** |
| **\--bulk-routing** {{DT\_BOOL}} | Aggregate routing queries with the same origin; *default:* **false** |
| **\--routing-threads** {{DT\_INT}} | The number of parallel execution threads used for routing; *default:* **0** |
| **\--routing-algorithm** {{DT\_STR}} | Select among routing algorithms \['dijkstra', 'astar', 'CH', 'CHWrapper'\]; *default:* **dijkstra** |
| **\--restriction-params** {{DT\_STR\_LIST}} | Comma separated list of param keys to compare for additional restrictions |
| **\--weights.interpolate** {{DT\_BOOL}} | Interpolate edge weights at interval boundaries; *default:* **false** |
| **\--weights.expand** {{DT\_BOOL}} | Expand the end of the last loaded weight interval to infinity; *default:* **false** |
| **\--weights.minor-penalty** {{DT\_FLOAT}} | Apply the given time penalty when computing routing costs for minor-link internal lanes; *default:* **1.5** |
| **\--weights.tls-penalty** {{DT\_FLOAT}} | Apply the given time penalty when computing routing costs across a traffic light; *default:* **0** |
| **\--weights.turnaround-penalty** {{DT\_FLOAT}} | Apply the given time penalty when computing routing costs for turnaround internal lanes; *default:* **5** |
| **\--weights.reversal-penalty** {{DT\_FLOAT}} | Apply the given time penalty when computing routing costs for train reversal. Negative values disable reversal; *default:* **60** |
| **\--weights.random-factor** {{DT\_FLOAT}} | Edge weights for routing are dynamically disturbed by a random factor drawn uniformly from \[1,FLOAT); *default:* **1** |
| **\--weight-period** {{DT\_TIME}} | Aggregation period for the given weight files; triggers rebuilding of Contraction Hierarchy; *default:* **3600** |
| **\--weights.priority-factor** {{DT\_FLOAT}} | Consider edge priorities in addition to travel times, weighted by factor; *default:* **0** |
| **\--astar.all-distances** {{DT\_FILE}} | Initialize lookup table for astar from the given file (generated by marouter --all-pairs-output) |
| **\--astar.landmark-distances** {{DT\_FILE}} | Initialize lookup table for astar ALT-variant from the given file |
| **\--astar.save-landmark-distances** {{DT\_FILE}} | Save lookup table for astar ALT-variant to the given file |
| **\--scale** {{DT\_FLOAT}} | Scale demand by the given factor (by discarding or duplicating vehicles); *default:* **1** |
| **\--scale-suffix** {{DT\_STR}} | Suffix to be added when creating ids for cloned vehicles; *default:* **.** |
| **\--taxi.vclasses** {{DT\_STR\_LIST}} | Network permissions that can be accessed by taxis; *default:* **taxi** |
| **\--gawron.beta** {{DT\_FLOAT}} | Use FLOAT as Gawron's beta; *default:* **0.9** |
| **\--gawron.a** {{DT\_FLOAT}} | Use FLOAT as Gawron's a; *default:* **0.5** |
| **\--keep-all-routes** {{DT\_BOOL}} | Save routes with near zero probability; *default:* **false** |
| **\--skip-new-routes** {{DT\_BOOL}} | Only reuse routes from input, do not calculate new ones; *default:* **false** |
| **\--keep-route-probability** {{DT\_FLOAT}} | The probability of keeping the old route; *default:* **0** |
| **\--ptline-routing** {{DT\_BOOL}} | Route all public transport input; *default:* **false** |
| **\--keep-flows** {{DT\_BOOL}} | Write flows instead of expanding them into vehicles; *default:* **false** |
| **\--route-choice-method** {{DT\_STR}} | Choose a route choice method: gawron, logit, or lohse; *default:* **gawron** |
| **\--logit** {{DT\_BOOL}} | Use c-logit model (deprecated in favor of --route-choice-method logit); *default:* **false** |
| **\--logit.beta** {{DT\_FLOAT}} | Use FLOAT as logit's beta; *default:* **\-1** |
| **\--logit.gamma** {{DT\_FLOAT}} | Use FLOAT as logit's gamma; *default:* **1** |
| **\--logit.theta** {{DT\_FLOAT}} | Use FLOAT as logit's theta (negative values mean auto-estimation); *default:* **\-1** |
| **\--persontrip.walkfactor** {{DT\_FLOAT}} | Use FLOAT as a factor on pedestrian maximum speed during intermodal routing; *default:* **0.75** |
| **\--persontrip.walk-opposite-factor** {{DT\_FLOAT}} | Use FLOAT as a factor on walking speed against vehicle traffic direction; *default:* **1** |
| **\--persontrip.transfer.car-walk** {{DT\_STR\_LIST}} | Where are mode changes from car to walking allowed (possible values: 'parkingAreas', 'ptStops', 'allJunctions' and combinations); *default:* **parkingAreas** |
| **\--persontrip.transfer.taxi-walk** {{DT\_STR\_LIST}} | Where taxis can drop off customers ('allJunctions, 'ptStops') |
| **\--persontrip.transfer.walk-taxi** {{DT\_STR\_LIST}} | Where taxis can pick up customers ('allJunctions, 'ptStops') |
| **\--persontrip.taxi.waiting-time** {{DT\_TIME}} | Estimated time for taxi pickup; *default:* **300** |
| **\--persontrip.ride-public-line** {{DT\_BOOL}} | Only use the intended public transport line rather than any alternative line that stops at the destination; *default:* **false** |
| **\--railway.max-train-length** {{DT\_FLOAT}} | Use FLOAT as a maximum train length when initializing the railway router; *default:* **1000** |
| **\--max-traveltime** {{DT\_TIME}} | Declare routing failure if traveltime exceeds the given positive TIME; *default:* **\-1** |

### Defaults

| Option | Description |
| --- | --- |
| **\--departlane** {{DT\_STR}} | Assigns a default depart lane |
| **\--departpos** {{DT\_STR}} | Assigns a default depart position |
| **\--departspeed** {{DT\_STR}} | Assigns a default depart speed |
| **\--arrivallane** {{DT\_STR}} | Assigns a default arrival lane |
| **\--arrivalpos** {{DT\_STR}} | Assigns a default arrival position |
| **\--arrivalspeed** {{DT\_STR}} | Assigns a default arrival speed |
| **\--defaults-override** {{DT\_BOOL}} | Defaults will override given values; *default:* **false** |

### Time

| Option | Description |
| --- | --- |
| **\-b** {{DT\_TIME}}   **\--begin** {{DT\_TIME}} | Defines the begin time; Previous trips will be discarded; *default:* **0** |
| **\-e** {{DT\_TIME}}   **\--end** {{DT\_TIME}} | Defines the end time; Later trips will be discarded; Defaults to the maximum time that SUMO can represent; *default:* **\-1** |

### Report

All applications of the **SUMO** -suite handle most of the reporting options the same way. These options are discussed at [Basics/Using the Command Line Applications#Reporting Options](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/Basics/Using_the_Command_Line_Applications.md#reporting_options).

| Option | Description |
| --- | --- |
| **\-v** {{DT\_BOOL}}   **\--verbose** {{DT\_BOOL}} | Switches to verbose output; *default:* **false** |
| **\--print-options** {{DT\_BOOL}} | Prints option values before processing; *default:* **false** |
| **\-?** {{DT\_BOOL}}   **\--help** {{DT\_BOOL}} | Prints this screen or selected topics; *default:* **false** |
| **\-V** {{DT\_BOOL}}   **\--version** {{DT\_BOOL}} | Prints the current version; *default:* **false** |
| **\-X** {{DT\_STR}}   **\--xml-validation** {{DT\_STR}} | Set schema validation scheme of XML inputs ("never", "local", "auto" or "always"); *default:* **local** |
| **\--xml-validation.net** {{DT\_STR}} | Set schema validation scheme of SUMO network inputs ("never", "local", "auto" or "always"); *default:* **never** |
| **\--xml-validation.routes** {{DT\_STR}} | Set schema validation scheme of SUMO route inputs ("never", "local", "auto" or "always"); *default:* **local** |
| **\-W** {{DT\_BOOL}}   **\--no-warnings** {{DT\_BOOL}} | Disables output of warnings; *default:* **false** |
| **\--aggregate-warnings** {{DT\_INT}} | Aggregate warnings of the same type whenever more than INT occur; *default:* **\-1** |
| **\-l** {{DT\_FILE}}   **\--log** {{DT\_FILE}} | Writes all messages to FILE (implies verbose) |
| **\--message-log** {{DT\_FILE}} | Writes all non-error messages to FILE (implies verbose) |
| **\--error-log** {{DT\_FILE}} | Writes all warnings and errors to FILE |
| **\--log.timestamps** {{DT\_BOOL}} | Writes timestamps in front of all messages; *default:* **false** |
| **\--log.processid** {{DT\_BOOL}} | Writes process ID in front of all messages; *default:* **false** |
| **\--language** {{DT\_STR}} | Language to use in messages; *default:* **C** |
| **\--ignore-errors** {{DT\_BOOL}} | Continue if a route could not be build; *default:* **false** |
| **\--stats-period** {{DT\_INT}} | Defines how often statistics shall be printed; *default:* **\-1** |
| **\--no-step-log** {{DT\_BOOL}} | Disable console output of route parsing step; *default:* **false** |

### Random Number

All applications of the **SUMO** -suite handle randomisation options the same way. These options are discussed at [Basics/Using the Command Line Applications#Random Number Options](https://github.com/eclipse-sumo/sumo/blob/main/docs/web/docs/Basics/Using_the_Command_Line_Applications.md#random_number_options).

| Option | Description |
| --- | --- |
| **\--random** {{DT\_BOOL}} | Initialises the random number generator with the current system time; *default:* **false** |
| **\--seed** {{DT\_INT}} | Initialises the random number generator with the given value; *default:* **23423** |
---
title: "netgenerate - SUMO Documentation"
source: "https://sumo.dlr.de/docs/netgenerate.html"
author:
published:
created: 2026-07-21
description:
tags:
  - "clippings"
---
## netgenerate

## From 30.000 feet

**netgenerate** generates abstract road networks that may be used by other SUMO-applications.

- **Purpose:** Abstract road network generation
- **System:** portable (Linux/Windows is tested); runs on command line
- **Input (mandatory):** Command line parameter
- **Output:** A generated SUMO-road network; optionally also other outputs
- **Programming Language:** C++

## Usage Description

The usage is described at [Networks/Abstract\_Network\_Generation](https://sumo.dlr.de/docs/Networks/Abstract_Network_Generation.html)

## Options

You may use a XML schema definition file for setting up a netgenerate configuration: [netgenerateConfiguration.xsd](https://sumo.dlr.de/xsd/netgenerateConfiguration.xsd).

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

### Grid Network

| Option | Description |
| --- | --- |
| **\-g** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--grid** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Forces NETGEN to build a grid-like network; *default:* **false** |
| **\--grid.number** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The number of junctions in both dirs; *default:* **5** |
| **\--grid.length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The length of streets in both dirs; *default:* **100** |
| **\--grid.x-number** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The number of junctions in x-dir; Overrides --grid-number; *default:* **5** |
| **\--grid.y-number** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The number of junctions in y-dir; Overrides --grid-number; *default:* **5** |
| **\--grid.x-length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The length of horizontal streets; Overrides --grid-length; *default:* **100** |
| **\--grid.y-length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The length of vertical streets; Overrides --grid-length; *default:* **100** |
| **\--grid.attach-length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The length of streets attached at the boundary; 0 means no streets are attached; *default:* **0** |
| **\--grid.x-attach-length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The length of streets attached at the boundary in x direction; 0 means no streets are attached; *default:* **0** |
| **\--grid.y-attach-length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The length of streets attached at the boundary in y direction; 0 means no streets are attached; *default:* **0** |

### Spider Network

| Option | Description |
| --- | --- |
| **\-s** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--spider** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Forces NETGEN to build a spider-net-like network; *default:* **false** |
| **\--spider.arm-number** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The number of axes within the net; *default:* **7** |
| **\--spider.circle-number** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The number of circles of the net; *default:* **5** |
| **\--spider.space-radius** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The distances between the circles; *default:* **100** |
| **\--spider.omit-center** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Omit the central node of the network; *default:* **false** |
| **\--spider.attach-length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The length of streets attached at the boundary; 0 means no streets are attached; *default:* **0** |

### Random Network

> [!note] Note
> It is not recommended to set **\--rand.connectivity** to 1 as the algorithm may fail to terminate in this case.

| Option | Description |
| --- | --- |
| **\-r** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--rand** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Forces NETGEN to build a random network; *default:* **false** |
| **\--rand.iterations** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Describes how many times an edge shall be added to the net; *default:* **100** |
| **\--rand.max-distance** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The maximum distance for each edge; *default:* **250** |
| **\--rand.min-distance** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The minimum distance for each edge; *default:* **100** |
| **\--rand.min-angle** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The minimum angle for each pair of (bidirectional) roads in DEGREES; *default:* **45** |
| **\--rand.num-tries** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The number of tries for creating each node; *default:* **50** |
| **\--rand.connectivity** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Probability for roads to continue at each node; *default:* **0.95** |
| **\--rand.neighbor-dist1** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Probability for a node having at most 1 neighbor; *default:* **0** |
| **\--rand.neighbor-dist2** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Probability for a node having at most 2 neighbors; *default:* **0** |
| **\--rand.neighbor-dist3** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Probability for a node having at most 3 neighbors; *default:* **10** |
| **\--rand.neighbor-dist4** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Probability for a node having at most 4 neighbors; *default:* **10** |
| **\--rand.neighbor-dist5** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Probability for a node having at most 5 neighbors; *default:* **2** |
| **\--rand.neighbor-dist6** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Probability for a node having at most 6 neighbors; *default:* **1** |
| **\--rand.grid** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Place nodes on a regular grid with spacing rand.min-distance; *default:* **false** |

### Input

| Option | Description |
| --- | --- |
| **\-t** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--type-files** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Read edge-type defs from FILE |

### Output

| Option | Description |
| --- | --- |
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
| **\--alphanumerical-ids** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The Ids of generated nodes use an alphanumerical code for easier readability when possible; *default:* **true** |
| **\-o** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--output-file** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The generated net will be written to FILE |
| **\-p** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--plain-output-prefix** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Prefix of files to write plain xml nodes, edges and connections to |
| **\--plain-output.lanes** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Write all lanes and their attributes even when they are not customized; *default:* **false** |
| **\--junctions.join-output** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes information about joined junctions to FILE (can be loaded as additional node-file to reproduce joins |
| **\--prefix** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines a prefix for edge and junction IDs |
| **\--prefix.junction** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines a prefix for junction IDs |
| **\--prefix.edge** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines a prefix for edge IDs |
| **\--amitran-output** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The generated net will be written to FILE using Amitran format |
| **\--matsim-output** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The generated net will be written to FILE using MATSim format |
| **\--opendrive-output** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The generated net will be written to FILE using OpenDRIVE format |
| **\--dlr-navteq-output** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The generated net will be written to dlr-navteq files with the given PREFIX |
| **\--dlr-navteq.version** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The dlr-navteq output format version to write; *default:* **6.5** |
| **\--dlr-navteq.precision** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The network coordinates are written with the specified level of output precision; *default:* **2** |
| **\--output.street-names** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Street names will be included in the output (if available); *default:* **false** |
| **\--output.original-names** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes original names, if given, as parameter; *default:* **false** |
| **\--output.removed-nodes** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes IDs of nodes remove with --geometry.remove into edge param; *default:* **false** |
| **\--street-sign-output** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes street signs as POIs to FILE |
| **\--opendrive-output.straight-threshold** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Builds parameterized curves whenever the angular change between straight segments exceeds FLOAT degrees; *default:* **1e-08** |

### Processing

Normally, both [netconvert](https://sumo.dlr.de/docs/netconvert.html) and [netgenerate](https://sumo.dlr.de/docs/netgenerate.html) translate the read network so that the left- and down-most node are at coordinate (0,0). The options --offset.x and --offset.y allow to disable this and to apply different offsets for both the x- and the y-axis. If there are explicit offsets given, the normalization is disabled automatically (thus there is no need to give --offset.disable-normalization if there is at least one of the offsets given).

| Option | Description |
| --- | --- |
| **\--turn-lanes** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Generate INT left-turn lanes; *default:* **0** |
| **\--turn-lanes.length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set the length of generated turning lanes to FLOAT; *default:* **20** |
| **\--perturb-x** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Apply random spatial perturbation in x direction according to the given distribution; *default:* **0** |
| **\--perturb-y** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Apply random spatial perturbation in y direction according to the given distribution; *default:* **0** |
| **\--perturb-z** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Apply random spatial perturbation in z direction according to the given distribution; *default:* **0** |
| **\--bidi-probability** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines the probability to build a reverse edge; *default:* **1** |
| **\--random-lanenumber** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Draw lane numbers randomly from \[1,default.lanenumber\]; *default:* **false** |
| **\--random-priority** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Draw edge priority randomly from \[1,default.priority\]; *default:* **false** |
| **\--random-type** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Draw edge type randomly from all loaded types; *default:* **false** |
| **\--numerical-ids** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Remaps alphanumerical IDs of nodes and edges to ensure that all IDs are integers; *default:* **false** |
| **\--numerical-ids.node-start** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Remaps IDs of nodes to integers starting at INT; *default:* **2147483647** |
| **\--numerical-ids.edge-start** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Remaps IDs of edges to integers starting at INT; *default:* **2147483647** |
| **\--reserved-ids** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Ensures that generated ids do not included any of the typed IDs from FILE (sumo-gui selection file format) |
| **\--kept-ids** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Ensures that objects with typed IDs from FILE (sumo-gui selection file format) are not renamed |
| **\--geometry.split** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Splits edges across geometry nodes; *default:* **false** |
| **\-R** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--geometry.remove** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Replace nodes which only define edge geometry by geometry points (joins edges); *default:* **false** |
| **\--geometry.remove.keep-edges.explicit** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Ensure that the given list of edges is not modified |
| **\--geometry.remove.keep-edges.input-file** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Ensure that the edges in FILE are not modified (Each id on a single line. Selection files from sumo-gui are also supported) |
| **\--geometry.remove.min-length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Allow merging edges with differing attributes when their length is below min-length; *default:* **0** |
| **\--geometry.remove.width-tolerance** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Allow merging edges with differing lane widths if the difference is below FLOAT; *default:* **0** |
| **\--geometry.remove.max-junction-size** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Prevent removal of junctions with a size above FLOAT as defined by custom edge endpoints; *default:* **\-1** |
| **\--geometry.max-segment-length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | splits geometry to restrict segment length; *default:* **0** |
| **\--geometry.max-grade** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Warn about edge geometries with a grade in % above FLOAT.; *default:* **10** |
| **\--geometry.max-grade.fix** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Smooth edge geometries with a grade above the warning threshold.; *default:* **true** |
| **\--offset.disable-normalization** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Turn off normalizing node positions; *default:* **false** |
| **\--offset.x** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Adds FLOAT to net x-positions; *default:* **0** |
| **\--offset.y** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Adds FLOAT to net y-positions; *default:* **0** |
| **\--offset.z** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Adds FLOAT to net z-positions; *default:* **0** |
| **\--flip-y-axis** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Flips the y-coordinate along zero; *default:* **false** |
| **\--roundabouts.guess** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Enable roundabout-guessing; *default:* **true** |
| **\--roundabouts.guess.max-length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Structures with a circumference above FLOAT threshold are not classified as roundabout; *default:* **3500** |
| **\--roundabouts.visibility-distance** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Default visibility when approaching a roundabout; *default:* **9** |
| **\--opposites.guess** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Enable guessing of opposite direction lanes usable for overtaking; *default:* **false** |
| **\--opposites.guess.fix-lengths** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Ensure that opposite edges have the same length; *default:* **true** |
| **\--fringe.guess** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Enable guessing of network fringe nodes; *default:* **false** |
| **\--fringe.guess.speed-threshold** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Guess disconnected edges above the given speed as outer fringe; *default:* **13.8889** |
| **\--lefthand** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assumes left-hand traffic on the network; *default:* **false** |
| **\--edges.join** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Merges edges which connect the same nodes and are close to each other (recommended for VISSIM import); *default:* **false** |

### Building Defaults

See the [docs](https://sumo.dlr.de/docs/Networks/PlainXML.html) for more info on [junction types](https://sumo.dlr.de/docs/Networks/PlainXML.html#node_types) and [edge types](https://sumo.dlr.de/docs/Networks/PlainXML.html#type_descriptions).

| Option | Description |
| --- | --- |
| **\-L** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--default.lanenumber** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default number of lanes in an edge; *default:* **1** |
| **\--default.lanewidth** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default width of lanes; *default:* **\-1** |
| **\--default.spreadtype** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default method for computing lane shapes from edge shapes; *default:* **right** |
| **\-S** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--default.speed** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default speed on an edge (in m/s); *default:* **13.89** |
| **\--default.friction** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default friction on an edge; *default:* **1** |
| **\-P** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--default.priority** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default priority of an edge; *default:* **\-1** |
| **\--default.type** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default edge type |
| **\--default.sidewalk-width** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default width of added sidewalks; *default:* **2** |
| **\--default.bikelane-width** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default width of added bike lanes; *default:* **1** |
| **\--default.crossing-width** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default width of a pedestrian crossing; *default:* **4** |
| **\--default.crossing-speed** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default speed 'limit' on a pedestrian crossing (in m/s); *default:* **2.78** |
| **\--default.walkingarea-speed** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default speed 'limit' on a pedestrian walkingarea (in m/s); *default:* **2.78** |
| **\--default.allow** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default for allowed vehicle classes |
| **\--default.disallow** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default for disallowed vehicle classes |
| **\--default.junctions.keep-clear** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Whether junctions should be kept clear by default; *default:* **true** |
| **\--default.junctions.radius** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default turning radius of intersections; *default:* **4** |
| **\-j** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--default.junctions.type** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | \[traffic\_light,priority,right\_before\_left,left\_before\_right,traffic\_light\_right\_on\_red,priority\_stop,allway\_stop,...\] Determines default junction type (see docs/Networks/PlainXML#node\_types) |
| **\--default.connection-length** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default length when overriding connection lengths; *default:* **\-1** |
| **\--default.connection.cont-pos** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Whether/where connections should have an internal junction; *default:* **\-1** |
| **\--default.right-of-way** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The default algorithm for computing right of way rules ('default', 'edgePriority'); *default:* **default** |

### Tls Building

| Option | Description |
| --- | --- |
| **\--tls.set** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Interprets STR\[\] as list of junctions to be controlled by TLS |
| **\--tls.unset** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Interprets STR\[\] as list of junctions to be not controlled by TLS |
| **\--tls.guess** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Turns on TLS guessing; *default:* **false** |
| **\--tls.guess.threshold** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Sets minimum value for the sum of all incoming lane speeds when guessing TLS; *default:* **69.4444** |
| **\--tls.guess.joining** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Includes node clusters into guess; *default:* **false** |
| **\--tls.join** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Tries to cluster tls-controlled nodes; *default:* **false** |
| **\--tls.join-dist** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Determines the maximal distance for joining traffic lights (defaults to 20); *default:* **20** |
| **\--tls.join-exclude** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Interprets STR\[\] as list of tls ids to exclude from joining |
| **\--tls.uncontrolled-within** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Do not control edges that lie fully within a joined traffic light. This may cause collisions but allows old traffic light plans to be used; *default:* **false** |
| **\--tls.ignore-internal-junction-jam** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Do not build mutually conflicting response matrix, potentially ignoring vehicles that are stuck at an internal junction when their phase has ended; *default:* **false** |
| **\--tls.cycle.time** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use INT as cycle duration; *default:* **90** |
| **\--tls.green.time** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use INT as green phase duration; *default:* **31** |
| **\-D** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--tls.yellow.min-decel** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines smallest vehicle deceleration; *default:* **3** |
| **\--tls.yellow.patch-small** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Given yellow times are patched even if being too short; *default:* **false** |
| **\--tls.yellow.time** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set INT as fixed time for yellow phase durations; *default:* **\-1** |
| **\--tls.red.time** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set INT as fixed time for red phase duration at traffic lights that do not have a conflicting flow; *default:* **5** |
| **\--tls.allred.time** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set INT as fixed time for intermediate red phase after every switch; *default:* **0** |
| **\--tls.minor-left.max-speed** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use FLOAT as threshold for allowing left-turning vehicles to move in the same phase as oncoming straight-going vehicles; *default:* **19.44** |
| **\--tls.left-green.time** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use INT as green phase duration for left turns (s). Setting this value to 0 disables additional left-turning phases; *default:* **6** |
| **\--tls.nema.vehExt** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set INT as fixed time for intermediate vehext phase after every switch; *default:* **2** |
| **\--tls.nema.yellow** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set INT as fixed time for intermediate NEMA yellow phase after every switch; *default:* **3** |
| **\--tls.nema.red** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set INT as fixed time for intermediate NEMA red phase after every switch; *default:* **2** |
| **\--tls.crossing-min.time** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use INT as minimum green duration for pedestrian crossings (s).; *default:* **4** |
| **\--tls.crossing-clearance.time** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use INT as clearance time for pedestrian crossings (s).; *default:* **5** |
| **\--tls.scramble.time** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use INT as green phase duration for pedestrian scramble phase (s).; *default:* **5** |
| **\--tls.half-offset** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | TLSs in STR\[\] will be shifted by half-phase |
| **\--tls.quarter-offset** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | TLSs in STR\[\] will be shifted by quarter-phase |
| **\--tls.default-type** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | TLSs with unspecified type will use STR as their algorithm; *default:* **static** |
| **\--tls.layout** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set phase layout four grouping opposite directions or grouping all movements for one incoming edge \['opposites', 'incoming'\]; *default:* **opposites** |
| **\--tls.no-mixed** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Avoid phases with green and red signals for different connections from the same lane; *default:* **false** |
| **\--tls.min-dur** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Default minimum phase duration for traffic lights with variable phase length; *default:* **5** |
| **\--tls.max-dur** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Default maximum phase duration for traffic lights with variable phase length; *default:* **50** |
| **\--tls.group-signals** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assign the same tls link index to connections that share the same states; *default:* **false** |
| **\--tls.ungroup-signals** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assign a distinct tls link index to every connection; *default:* **false** |
| **\--tls.rebuild** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | rebuild all traffic light plans in the network; *default:* **false** |
| **\--tls.discard-simple** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Does not instantiate traffic lights at geometry-like nodes; *default:* **false** |
| **\--railway.signal.permit-unsignalized** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | List rail classes that may run without rail signals; *default:* **tram,cable\_car** |

### Edge Removal

| Option | Description |
| --- | --- |
| **\--keep-edges.min-speed** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Only keep edges with speed in meters/second > FLOAT; *default:* **\-1** |
| **\--remove-edges.explicit** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Remove edges in STR\[\] |
| **\--keep-edges.explicit** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Only keep edges in STR\[\] or those which are kept due to other keep-edges or remove-edges options |
| **\--keep-edges.input-file** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Only keep edges in FILE (Each id on a single line. Selection files from sumo-gui are also supported) or those which are kept due to other keep-edges or remove-edges options |
| **\--remove-edges.input-file** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Remove edges in FILE. (Each id on a single line. Selection files from sumo-gui are also supported) |
| **\--keep-edges.in-boundary** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Only keep edges which are located within the given boundary (given either as CARTESIAN corner coordinates or as polygon ) |
| **\--keep-edges.in-geo-boundary** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Only keep edges which are located within the given boundary (given either as GEODETIC corner coordinates  or as polygon ) |
| **\--keep-lanes.min-width** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Only keep lanes with width in meters > FLOAT; *default:* **0.01** |

### Unregulated Nodes

| Option | Description |
| --- | --- |
| **\--keep-nodes-unregulated** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | All nodes will be unregulated; *default:* **false** |
| **\--keep-nodes-unregulated.explicit** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Do not regulate nodes in STR\[\] |
| **\--keep-nodes-unregulated.district-nodes** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Do not regulate district nodes; *default:* **false** |

### Junctions

| Option | Description |
| --- | --- |
| **\--junctions.right-before-left.speed-threshold** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Allow building right-before-left junctions when the incoming edge speeds are below FLOAT (m/s); *default:* **13.6111** |
| **\--junctions.left-before-right** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Build left-before-right junctions instead of right-before-left junctions; *default:* **false** |
| **\--no-internal-links** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Omits internal links; *default:* **false** |
| **\--no-turnarounds** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disables building turnarounds; *default:* **false** |
| **\--no-turnarounds.tls** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disables building turnarounds at tls-controlled junctions; *default:* **false** |
| **\--no-turnarounds.geometry** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disables building turnarounds at geometry-like junctions; *default:* **true** |
| **\--no-turnarounds.except-deadend** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disables building turnarounds except at dead end junctions; *default:* **false** |
| **\--no-turnarounds.except-turnlane** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disables building turnarounds except at junctions with a dedicated turning lane; *default:* **false** |
| **\--no-turnarounds.fringe** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disables building turnarounds at fringe junctions; *default:* **false** |
| **\--no-left-connections** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disables building connections to left; *default:* **false** |
| **\--junctions.join** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Joins junctions that are close to each other (recommended for OSM import); *default:* **false** |
| **\--junctions.join-dist** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Determines the maximal distance for joining junctions (defaults to 10); *default:* **10** |
| **\--junctions.join.parallel-threshold** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | The angular threshold in degrees for rejection of parallel edges when joining junctions; *default:* **30** |
| **\--junctions.join-same** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Joins junctions that have similar coordinates even if not connected; *default:* **\-1** |
| **\--junctions.join-reset** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Reset connections for joined junctions; *default:* **false** |
| **\--max-join-ids** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Abbreviate junction or TLS id if it joins more than INT junctions; *default:* **4** |
| **\--junctions.corner-detail** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Generate INT intermediate points to smooth out intersection corners; *default:* **5** |
| **\--junctions.internal-link-detail** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Generate INT intermediate points to smooth out lanes within the intersection; *default:* **5** |
| **\--junctions.scurve-stretch** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Generate longer intersections to allow for smooth s-curves when the number of lanes changes; *default:* **0** |
| **\--junctions.join-turns** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Builds common edges for turning connections with common from- and to-edge. This causes discrepancies between geometrical length and assigned length due to averaging but enables lane-changing while turning; *default:* **false** |
| **\--junctions.limit-turn-speed** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Limits speed on junctions to an average lateral acceleration of at most FLOAT (m/s^2); *default:* **5.5** |
| **\--junctions.limit-turn-speed.min-angle** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Do not limit turn speed for angular changes below FLOAT (degrees). The value is subtracted from the geometric angle before computing the turning radius.; *default:* **15** |
| **\--junctions.limit-turn-speed.min-angle.railway** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Do not limit turn speed for angular changes below FLOAT (degrees) on railway edges. The value is subtracted from the geometric angle before computing the turning radius.; *default:* **35** |
| **\--junctions.limit-turn-speed.warn.straight** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Warn about turn speed limits that reduce the speed of straight connections by more than FLOAT; *default:* **5** |
| **\--junctions.limit-turn-speed.warn.turn** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Warn about turn speed limits that reduce the speed of turning connections (no u-turns) by more than FLOAT; *default:* **22** |
| **\--junctions.small-radius** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Default radius for junctions that do not require wide vehicle turns; *default:* **1.5** |
| **\--junctions.higher-speed** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Use maximum value of incoming and outgoing edge speed on junction instead of average; *default:* **false** |
| **\--junctions.minimal-shape** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Build junctions with minimal shapes (ignoring edge overlap); *default:* **false** |
| **\--junctions.endpoint-shape** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Build junction shapes based on edge endpoints (ignoring edge overlap); *default:* **false** |
| **\--internal-junctions.vehicle-width** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assumed vehicle width for computing internal junction positions; *default:* **1.8** |
| **\--rectangular-lane-cut** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Forces rectangular cuts between lanes and intersections; *default:* **false** |
| **\--check-lane-foes.roundabout** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Allow driving onto a multi-lane road if there are foes on other lanes (at roundabouts); *default:* **true** |
| **\--check-lane-foes.all** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Allow driving onto a multi-lane road if there are foes on other lanes (everywhere); *default:* **false** |

### Pedestrian

| Option | Description |
| --- | --- |
| **\--sidewalks.guess** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Guess pedestrian sidewalks based on edge speed; *default:* **false** |
| **\--sidewalks.guess.max-speed** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Add sidewalks for edges with a speed equal or below the given limit; *default:* **13.89** |
| **\--sidewalks.guess.min-speed** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Add sidewalks for edges with a speed above the given limit; *default:* **5.8** |
| **\--sidewalks.guess.from-permissions** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Add sidewalks for edges that allow pedestrians on any of their lanes regardless of speed; *default:* **false** |
| **\--sidewalks.guess.exclude** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Do not guess sidewalks for the given list of edges |
| **\--crossings.guess** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Guess pedestrian crossings based on the presence of sidewalks; *default:* **false** |
| **\--crossings.guess.speed-threshold** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | At uncontrolled nodes, do not build crossings across edges with a speed above the threshold; *default:* **13.89** |
| **\--crossings.guess.roundabout-priority** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Give priority to guessed crossings at roundabouts; *default:* **true** |
| **\--walkingareas** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Always build walking areas even if there are no crossings; *default:* **false** |
| **\--walkingareas.join-dist** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Do not create a walkingarea between sidewalks that are connected by a pedestrian junction within FLOAT; *default:* **15** |

### Bicycle

| Option | Description |
| --- | --- |
| **\--bikelanes.guess** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Guess bike lanes based on edge speed; *default:* **false** |
| **\--bikelanes.guess.max-speed** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Add bike lanes for edges with a speed equal or below the given limit; *default:* **22.22** |
| **\--bikelanes.guess.min-speed** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Add bike lanes for edges with a speed above the given limit; *default:* **5.8** |
| **\--bikelanes.guess.from-permissions** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Add bike lanes for edges that allow bicycles on any of their lanes regardless of speed; *default:* **false** |
| **\--bikelanes.guess.exclude** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Do not guess bikelanes for the given list of edges |

### Report

All applications of the **SUMO** -suite handle most of the reporting options the same way. These options are discussed at [Basics/Using the Command Line Applications#Reporting Options](https://sumo.dlr.de/docs/Basics/Using_the_Command_Line_Applications.html#reporting_options).

| Option | Description |
| --- | --- |
| **\-v** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--verbose** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Switches to verbose output; *default:* **false** |
| **\--print-options** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Prints option values before processing; *default:* **false** |
| **\-?** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--help** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Prints this screen or selected topics; *default:* **false** |
| **\-V** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--version** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Prints the current version; *default:* **false** |
| **\-X** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--xml-validation** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Set schema validation scheme of XML inputs ("never", "local", "auto" or "always"); *default:* **local** |
| **\-W** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--no-warnings** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disables output of warnings; *default:* **false** |
| **\--aggregate-warnings** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Aggregate warnings of the same type whenever more than INT occur; *default:* **\-1** |
| **\-l** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--log** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes all messages to FILE (implies verbose) |
| **\--message-log** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes all non-error messages to FILE (implies verbose) |
| **\--error-log** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes all warnings and errors to FILE |
| **\--log.timestamps** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes timestamps in front of all messages; *default:* **false** |
| **\--log.processid** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes process ID in front of all messages; *default:* **false** |
| **\--language** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Language to use in messages; *default:* **C** |

### Random Number

All applications of the **SUMO** -suite handle randomisation options the same way. These options are discussed at [Basics/Using the Command Line Applications#Random Number Options](https://sumo.dlr.de/docs/Basics/Using_the_Command_Line_Applications.html#random_number_options).

| Option | Description |
| --- | --- |
| **\--random** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Initialises the random number generator with the current system time; *default:* **false** |
| **\--seed** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Initialises the random number generator with the given value; *default:* **23423** |

## Perturbance Distributions

Options **\--perturb-x**, **\--perturb-y** and **\--perturb-z** accept any of the following values:

- `norm(m,s)`: normal distribution with mean *m* and deviation *s*
- `normc(m,s,a,b)`: truncated normal distribution with mean *m*, deviation *s* lower boundary *a* and upper boundary *b*
- `s`: normal distribution with mean *0* and deviation *s*
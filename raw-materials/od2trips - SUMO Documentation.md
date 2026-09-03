---
title: "od2trips - SUMO Documentation"
source: "https://sumo.dlr.de/docs/od2trips.html"
author:
published:
created: 2026-07-21
description:
tags:
  - "clippings"
---
## od2trips

## From 30.000 feet

**od2trips** imports O/D-matrices and splits them into single vehicle trips.

- **Purpose:** Conversion of O/D-matrices to single vehicle trips
- **System:** portable (Linux/Windows is tested); runs on command line
- **Input (mandatory):**
	- A) O/D-Matrix
		- B) a set of districts
- **Output:** A list of vehicle trip definitions
- **Programming Language:** C++

## Usage Description

od2trips maps traffic that is defined via origin and destination zones onto the edges of a network. For details, see [Demand/Importing\_O/D\_Matrices](https://sumo.dlr.de/docs/Demand/Importing_O/D_Matrices.html).

## Options

You may use a XML schema definition file for setting up a od2trips configuration: [od2tripsConfiguration.xsd](https://sumo.dlr.de/xsd/od2tripsConfiguration.xsd).

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
| **\-n** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--taz-files** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Loads TAZ (districts; also from networks) from FILE(s) |
| **\-d** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--od-matrix-files** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Loads O/D-files from FILE(s) |
| **\--od-amitran-files** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Loads O/D-matrix in Amitran format from FILE(s) |
| **\-z** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--tazrelation-files** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Loads O/D-matrix in tazRelation format from FILE(s) |
| **\--tazrelation-attribute** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Define data attribute for loading counts (default 'count'); *default:* **count** |

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
| **\-o** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--output-file** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes trip definitions into FILE |
| **\--flow-output** [*\<FILE>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes flow definitions into FILE |
| **\--flow-output.probability** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes probabilistic flow instead of evenly spaced flow; *default:* **false** |
| **\--flow-output.poisson** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes poisson distributed flow instead of evenly spaced flow; *default:* **false** |
| **\--pedestrians** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes pedestrians instead of vehicles; *default:* **false** |
| **\--persontrips** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes persontrips instead of vehicles; *default:* **false** |
| **\--persontrips.modes** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Add modes attribute to personTrips |
| **\--ignore-vehicle-type** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Does not save vtype information; *default:* **false** |
| **\--junctions** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Writes trips between junctions; *default:* **false** |

### Time

| Option | Description |
| --- | --- |
| **\-b** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--begin** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines the begin time; Previous trips will be discarded; *default:* **0** |
| **\-e** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--end** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines the end time; Later trips will be discarded; Defaults to the maximum time that SUMO can represent; *default:* **\-1** |

### Processing

| Option | Description |
| --- | --- |
| **\-s** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types)   **\--scale** [*\<FLOAT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Scales the loaded flows by FLOAT; *default:* **1** |
| **\--spread.uniform** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Spreads trips uniformly over each time period; *default:* **false** |
| **\--different-source-sink** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Always choose source and sink edge which are not identical; *default:* **false** |
| **\--vtype** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines the name of the vehicle type to use |
| **\--prefix** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Defines the prefix for vehicle names |
| **\--timeline** [*<STRING\[ \]>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Uses STR\[\] as a timeline definition |
| **\--timeline.day-in-hours** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Uses STR as a 24h-timeline definition; *default:* **false** |
| **\--no-step-log** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Disable console output of current time step; *default:* **false** |

### Defaults

| Option | Description |
| --- | --- |
| **\--departlane** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default depart lane; *default:* **free** |
| **\--departpos** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default depart position |
| **\--departspeed** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default depart speed; *default:* **max** |
| **\--arrivallane** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default arrival lane |
| **\--arrivalpos** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default arrival position |
| **\--arrivalspeed** [*\<STRING>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Assigns a default arrival speed |

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
| **\--ignore-errors** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Continue on broken input; *default:* **false** |

### Random Number

All applications of the **SUMO** -suite handle randomisation options the same way. These options are discussed at [Basics/Using the Command Line Applications#Random Number Options](https://sumo.dlr.de/docs/Basics/Using_the_Command_Line_Applications.html#random_number_options).

| Option | Description |
| --- | --- |
| **\--random** [*\<BOOL>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Initialises the random number generator with the current system time; *default:* **false** |
| **\--seed** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) | Initialises the random number generator with the given value; *default:* **23423** |

## Notes

- The option --vtype only works when "--od-matrix-files" is used. For "Amitran" format, this is given by the "id" property of "actorConfig".
- With use of netedit it is possible to observe the demand amount distribution of edge-based or TAZ-based relations [network/TAZ related data](https://sumo.dlr.de/docs/Netedit/editModesData.html).
---
summary: Explains how SUMO's command-line applications take options and configuration files, the shared option conventions across the whole suite, and how to run the Python tools that ship in $SUMO_HOME/tools.
keywords:
  - command-line
  - options
  - configuration-file
  - sumocfg
  - SUMO_HOME
created: 2026-07-21T14:00:00
last_updated: 2026-07-21T14:00:00
sources:
  - "[[raw-materials/Using the Command Line Applications.md]]"
  - https://sumo.dlr.de/docs/Basics/Using_the_Command_Line_Applications.html
related_pages:
  - "[[traci]]"
  - "[[abstract-network-generation]]"
  - "[[duarouter]]"
  - "[[mesoscopic-simulation]]"
related_skills:
  - run-simulation
  - create-grid-network
  - convert-trips-to-routes
related_skills_for_graph_view:
  - "[[run-simulation]]"
  - "[[create-grid-network]]"
  - "[[convert-trips-to-routes]]"
---

# SUMO Command Line

Nearly every SUMO application — `sumo`, `netconvert`, `netgenerate`, `duarouter`, `od2trips`, and the tools in `tools/` — is a plain command-line executable that shares the same option conventions. `sumo-gui` and `netedit` are the exceptions with a GUI-first workflow.

## Setting options

An option with a value is given as `--long-name value` or `--long-name=value`. Many common options have a single-dash abbreviation, e.g. `--net-file` is `-n`. Abbreviations are **not consistent across applications** — the same short flag can mean different things in different tools.

List-valued options (additional files, edge lists, etc.) are comma-separated: `--additional-files a.xml,b.xml`. Appending to a list already set in a config file uses a single `+`, e.g. `+a extra.add.xml`.

## Configuration files

Because option lists get long, every application accepts a `-c`/`--configuration-file <FILE>` pointing at an XML file with a `<configuration>` root. Options become element names with a `value` (or `v`) attribute:

```xml
<configuration>
    <input>
        <net-file value="test.net.xml"/>
        <route-files value="test.rou.xml"/>
        <additional-files value="test.add.xml"/>
    </input>
</configuration>
```

`sumo -c test.sumocfg` loads it; if no other options are needed, the `-c` can even be dropped: `sumo test.sumocfg`. Command-line options override a config file's values for the same option, unless the `+` list-append syntax is used. `sumo-gui` specifically requires the `.sumocfg` extension to recognize a simulation config file — see the naming conventions on [File Extensions](https://sumo.dlr.de/docs/Other/File_Extensions.html).

Every application can also generate: an empty template (`--save-template FILE`), the currently-set configuration (`--save-configuration FILE`), or an XML schema to validate against (`--save-schema FILE`). Adding `--save-commented` annotates the output with descriptions. The application exits immediately after saving — it must be run a second time to actually do anything.

Configuration files can reference environment variables with `${VARNAME}`, plus a few built-ins: `${LOCALTIME}`, `${UTC}`, `${PID}`, `${SUMO_LOGO}`, and `~`/`${HOME}`.

## Options shared across the whole suite

- **Reporting**: `-v`/`--verbose`, `--print-options`, `-?`/`--help`, `-V`/`--version`, `-X`/`--xml-validation`, `-W`/`--no-warnings`, `-l`/`--log FILE`, `--message-log FILE`, `--error-log FILE`.
- **Random seed**: by default the seed is a fixed constant, so repeated runs with identical settings are reproducible. `--seed <INT>` picks a specific reproducible seed; `--random` picks a fresh seed each run (from `/dev/urandom` or system time) and **takes precedence over `--seed`** if both are set — this precedence can't be reversed from the command line.

## File-writing conventions

Output paths given on the command line are relative to the current working directory; paths inside a config file are relative to the config file's own location. Special filenames: `NUL`/`/dev/null` discards output, `<HOST>:<PORT>` writes to a socket, `stdout`/`-` and `stderr` print to the console, and `TIME` in a filename is replaced with the application's start time. `--output-prefix <STRING>` prepends a string to every output filename. Existing files are overwritten silently.

Time values are written in seconds by default; `-H`/`--human-readable-time` switches output to `HH:MM:SS` (or `DD:HH:MM:SS` past 24h). Time values in *input* XML/options may always be given as seconds or `HH:MM:SS`/`DD:HH:MM:SS`.

## Running the Python tools

Most tools distributed in `<SUMO_HOME>/tools` (`randomTrips.py`, `tlsCycleAdaptation.py`, `tlsCoordinator.py`, `osmGet.py`, `osmBuild.py`, etc.) are Python scripts, not compiled binaries. Running them requires Python 3.7+, `SUMO_HOME` set, and either invoking the script by its full path or adding `tools/` to `PATH`. This is the reason the `$SUMO_HOME/tools/` vs. `$SUMO_HOME/bin/` distinction matters throughout the toolchain — compiled applications (`sumo`, `netconvert`, `netgenerate`, `duarouter`, `od2trips`) live in `bin/`, while the Python helper scripts live in `tools/`.

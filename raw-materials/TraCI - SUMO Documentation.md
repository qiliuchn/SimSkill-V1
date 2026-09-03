---
title: "TraCI - SUMO Documentation"
source: "https://sumo.dlr.de/docs/TraCI/index.html"
author:
published:
created: 2026-07-21
description:
tags:
  - "clippings"
---
## TraCI

## Introduction to TraCI

TraCI is the short term for " **Tra** ffic **C** ontrol **I** nterface". Giving access to a running road traffic simulation, it allows to retrieve values of simulated objects and to manipulate their behavior "on-line". If performance is an issue you should consider using [libsumo](https://sumo.dlr.de/docs/Libsumo.html) instead. You can also start with TraCI and switch to libsumo later, since the function signatures are the same.

## Using TraCI

### SUMO startup

TraCI uses a TCP based client/server architecture to provide access to [sumo](https://sumo.dlr.de/docs/sumo.html). Thereby, [sumo](https://sumo.dlr.de/docs/sumo.html) acts as server that is started with additional command-line options: **\--remote-port** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) where [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) is the port [sumo](https://sumo.dlr.de/docs/sumo.html) will listen on for incoming connections.

When started with the **\--remote-port** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) option, [sumo](https://sumo.dlr.de/docs/sumo.html) only prepares the simulation and waits for all external applications to connect and take over the control. Please note, that the **\--end** [*\<TIME>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types) option is ignored when [sumo](https://sumo.dlr.de/docs/sumo.html) runs as a TraCI server, [sumo](https://sumo.dlr.de/docs/sumo.html) runs until the client demands a simulation end.

When using [sumo-gui](https://sumo.dlr.de/docs/sumo-gui.html) as a server, the simulation must either be started by using the [*play* button](https://sumo.dlr.de/docs/sumo-gui.html#usage_description) or by setting the option **\--start** before TraCI commands will be processed.

### Multiple clients

The number of clients which can connect can be given as an additional option **\--num-clients** [*\<INT>*](https://sumo.dlr.de/docs/Basics/Notation.html#referenced_data_types), where 1 is the default. Please note that in multi client scenarios you must explicitly specify the execution order of the clients using the [*SetOrder* -command](https://sumo.dlr.de/docs/TraCI/Control-related_commands.html#command_0x03_setorder).

Each client must specify a unique (but otherwise arbitrary) integer value and the client commands will be handled in the order from the lowest to the highest value within each simulation step.

The clients are automatically synchronized after every simulation step. This means, the simulation does not advance to the next step until all clients have called the 'simulationStep'' command. Also, the simulationStep command only returns control to the client after the simulation has advanced.

> [!caution] Caution
> The simulation will only start once all clients have connected.

### Protocol specification

Please see the [TraCI Protocol Specification](https://sumo.dlr.de/docs/TraCI/Protocol.html) (including [Basic Flow](https://sumo.dlr.de/docs/TraCI/Protocol.html#basic_flow), [Messages](https://sumo.dlr.de/docs/TraCI/Protocol.html#messages), [Data Types](https://sumo.dlr.de/docs/TraCI/Protocol.html#data_types)).

### Shutdown

When using TraCI, the **\--end** option of [sumo](https://sumo.dlr.de/docs/sumo.html) is ignored. Instead the simulation is closed by issuing the [*close* command](https://sumo.dlr.de/docs/TraCI/Control-related_commands.html#command_0x7f_close). To detect whether all route files have been exhausted and all vehicles have left the simulation, one can check whether the command [getMinExpectedNumber](https://sumo.dlr.de/docs/TraCI/Simulation_Value_Retrieval.html) returns 0. The simulation will end as soon as all clients have sent the *close* command.

It is also possible to reload the simulation with a new list of arguments by using the [*load* -command](https://sumo.dlr.de/docs/TraCI/Control-related_commands.html#command_0x01_load).

## TraCI Commands

- [Control-related commands](https://sumo.dlr.de/docs/TraCI/Control-related_commands.html): perform a simulation step, close the connection, reload the simulation.
- [Generic Parameters](https://sumo.dlr.de/docs/TraCI/GenericParameters.html)

For the following APIs, the ID is equal to the ID defined in [sumo](https://sumo.dlr.de/docs/sumo.html) 's input files. Here, you find their [general structure](https://sumo.dlr.de/docs/TraCI/SUMO_ID_Commands_Structure.html).

### Value Retrieval

- Traffic Objects
	- [Vehicle Value Retrieval](https://sumo.dlr.de/docs/TraCI/Vehicle_Value_Retrieval.html) retrieve information about vehicles
		- [Person Value Retrieval](https://sumo.dlr.de/docs/TraCI/Person_Value_Retrieval.html) retrieve information about persons
		- [Vehicle Type Value Retrieval](https://sumo.dlr.de/docs/TraCI/VehicleType_Value_Retrieval.html) retrieve information about vehicle types
		- [Route Value Retrieval](https://sumo.dlr.de/docs/TraCI/Route_Value_Retrieval.html) retrieve information about routes
- Detectors and Outputs
	- [Induction Loop Value Retrieval](https://sumo.dlr.de/docs/TraCI/Induction_Loop_Value_Retrieval.html) retrieve information about induction loops
		- [Lane Area Detector Value Retrieval](https://sumo.dlr.de/docs/TraCI/Lane_Area_Detector_Value_Retrieval.html) retrieve information about lane area detectors
		- [Multi-Entry-Exit Detectors Value Retrieval](https://sumo.dlr.de/docs/TraCI/Multi-Entry-Exit_Detectors_Value_Retrieval.html) retrieve information about multi-entry/multi-exit detectors
		- [Calibrator Value Retrieval](https://sumo.dlr.de/docs/TraCI/Calibrator.html) retrieve information about calibrators
		- [RouteProbe](https://sumo.dlr.de/docs/TraCI/RouteProbe.html) retrieve information about the RouteProbe
- Network
	- [Junction Value Retrieval](https://sumo.dlr.de/docs/TraCI/Junction_Value_Retrieval.html) retrieve information about junctions
		- [Edge Value Retrieval](https://sumo.dlr.de/docs/TraCI/Edge_Value_Retrieval.html) retrieve information about edges
		- [Lane Value Retrieval](https://sumo.dlr.de/docs/TraCI/Lane_Value_Retrieval.html) retrieve information about lanes
- Infrastructure
	- [Traffic Lights Value Retrieval](https://sumo.dlr.de/docs/TraCI/Traffic_Lights_Value_Retrieval.html) retrieve information about traffic lights
		- [BusStop Value Retrieval](https://sumo.dlr.de/docs/TraCI/BusStop.html) retrieve information about BusStops
		- [Charging Station Value Retrieval](https://sumo.dlr.de/docs/TraCI/ChargingStation.html) retrieve information about charging stations
		- [Parking Area Value Retrieval](https://sumo.dlr.de/docs/TraCI/ParkingArea.html) retrieve information about parking areas
		- [Overhead Wire Value Retrieval](https://sumo.dlr.de/docs/TraCI/OverheadWire.html) retrieve information about overhead wires
		- [Rerouter](https://sumo.dlr.de/docs/TraCI/Rerouter.html) retrieve information about the rerouter
- Misc
	- [Simulation Value Retrieval](https://sumo.dlr.de/docs/TraCI/Simulation_Value_Retrieval.html) retrieve information about the simulation
		- [GUI Value Retrieval](https://sumo.dlr.de/docs/TraCI/GUI_Value_Retrieval.html) retrieve information about the simulation visualization
		- [PoI Value Retrieval](https://sumo.dlr.de/docs/TraCI/POI_Value_Retrieval.html) retrieve information about points-of-interest
		- [Polygon Value Retrieval](https://sumo.dlr.de/docs/TraCI/Polygon_Value_Retrieval.html) retrieve information about polygons

### State Changing

- Traffic Objects
	- [Change Vehicle State](https://sumo.dlr.de/docs/TraCI/Change_Vehicle_State.html) change a vehicle's state
		- [Change Person State](https://sumo.dlr.de/docs/TraCI/Change_Person_State.html) change a persons state
		- [Change Vehicle Type State](https://sumo.dlr.de/docs/TraCI/Change_VehicleType_State.html) change a vehicle type's state
		- [Change Route State](https://sumo.dlr.de/docs/TraCI/Change_Route_State.html) change a route's state
- Detectors and Outputs
	- [Change Calibrator State](https://sumo.dlr.de/docs/TraCI/Change_Calibrator_State.html) change a calibrator state
		- [Change Inductionloop State](https://sumo.dlr.de/docs/TraCI/Change_Inductionloop_State.html) change a inductionloop state
		- [Change Lane Area Detector State](https://sumo.dlr.de/docs/TraCI/Change_Lane_Area_Detector_State.html) change a lane area detector state
- Network
	- [Change Edge State](https://sumo.dlr.de/docs/TraCI/Change_Edge_State.html) change an edge's state
		- [Change Lane State](https://sumo.dlr.de/docs/TraCI/Change_Lane_State.html) change a lane's state
- Infrastructure
	- [Change Traffic Lights State](https://sumo.dlr.de/docs/TraCI/Change_Traffic_Lights_State.html) change a traffic lights' state
		- [Change Charging Station State](https://sumo.dlr.de/docs/TraCI/Change_ChargingStation_State.html) change a charging stations's attributes
		- [Change Parking Area State](https://sumo.dlr.de/docs/TraCI/Change_ParkingArea_State.html) change parking area attributes
- Misc
	- [Change Simulation State](https://sumo.dlr.de/docs/TraCI/Change_Simulation_State.html) change the simulation
		- [Change GUI State](https://sumo.dlr.de/docs/TraCI/Change_GUI_State.html) change the simulation visualization
		- [Change PoI State](https://sumo.dlr.de/docs/TraCI/Change_PoI_State.html) change a point-of-interest's state (or add/remove one)
		- [Change Polygon State](https://sumo.dlr.de/docs/TraCI/Change_Polygon_State.html) change a polygon's state (or add/remove one)

### Subscriptions

Subscriptions are a way to get notified repeatedly about changes in variables. They are applicable to all variables mentioned in the respective value retrieval section of the domain in question unless noted otherwise. For details see the separate page on [object variable subscription](https://sumo.dlr.de/docs/TraCI/Object_Variable_Subscription.html).

It is also possible to subscribe to values of objects surrounding another object (e.g. all vehicles around a certain junction). This is called [context subscription](https://sumo.dlr.de/docs/TraCI/Object_Context_Subscription.html).

Subscriptions may be faster than repeated value retrieval, see the section on [Performance](#performance).

## Using SUMO as a library

Normally, TraCI is used to couple multiple processes: A SUMO server process and one or more TraCI client processes. Alternatively, [Libsumo](https://sumo.dlr.de/docs/Libsumo.html) can be used to embed SUMO as a library into the client process. This allows using the same method signatures as in the client libraries but avoids the overhead of socket communication. Libsumo supports generating client libraries using [SWIG](https://en.wikipedia.org/wiki/SWIG) and can therefore be used with a large number of programming languages. C++, Java and Python bindings are included when downloading a sumo-build.

## Example use

- There is a [tutorial on using TraCI for adaptive traffic lights](https://sumo.dlr.de/docs/Tutorials/TraCI4Traffic_Lights.html) (using Python).
- The [Tutorials/CityMobil](https://sumo.dlr.de/docs/Tutorials/CityMobil.html) tutorial uses TraCI for assigning new routes to vehicles (using Python).
- The [Tutorials/TraCIPedCrossing](https://sumo.dlr.de/docs/Tutorials/TraCIPedCrossing.html) tutorial uses TraCI for building a crossing with a pedestrian triggered traffic light.

## Resources

### Interfaces by Programming Language

- Python: [the python module traci](https://sumo.dlr.de/docs/TraCI/Interfacing_TraCI_from_Python.html) allows to interact with [sumo](https://sumo.dlr.de/docs/sumo.html) using Python (This library is part of the sumo source code and all releases, is tested daily and supports all TraCI commands). It is also [available on PyPI](https://pypi.org/project/traci/) and can thus be installed using `pip install traci`.
- C++: [libtraci](https://sumo.dlr.de/docs/Libtraci.html) is a client library that is part of the [sumo](https://sumo.dlr.de/docs/sumo.html) -source tree. It is fully API-compatible with [libsumo](https://sumo.dlr.de/docs/Libsumo.html).
- C++: [The C++ TraCIAPI](https://sumo.dlr.de/docs/TraCI/C%2B%2BTraCIAPI.html) is a client library that is part of the [sumo](https://sumo.dlr.de/docs/sumo.html) -source tree. (API coverage is good but this client is no longer updated. Please use libtraci instead.)
- C++: [The Veins project](https://veins.car2x.org/) provides a middle-ware for coupling [sumo](https://sumo.dlr.de/docs/sumo.html) with [OMNET++](https://omnetpp.org/). As part of the infrastructure it provides a C++ client library for the TraCI API (API completeness is a bit behind the python client).
- .NET: [TraCI.NET](https://github.com/CodingConnected/CodingConnected.Traci) is a client library with good API coverage.
- .NET: libtracics is an experimental SWIG generated binding to the original libtraci. It has full API coverage but is untested and needs to be generated by the user from the source.
- Matlab [TraCI4Matlab](https://mathworks.com/matlabcentral/fileexchange/44805-traci4matlab). The client is included as part of each SUMO release in ***<SUMO\_HOME>*** */tools/contributed/traci4matlab* Not all TraCI commands have been implemented. It is recommended to [use the python client](https://mathworks.com/help/matlab/call-python-libraries.html) from inside Matlab instead.
- Java: [libtraci](https://sumo.dlr.de/docs/Libtraci.html) is a client library that is part of the [sumo](https://sumo.dlr.de/docs/sumo.html) -source tree. It is fully API-compatible with [libsumo](https://sumo.dlr.de/docs/Libsumo.html) and a SUMO release provides pro-compiled Java bindings (via SWIG).
- Java: [TraaS](https://sumo.dlr.de/docs/TraCI/TraaS.html#java_client) provides a client library that is part of the [sumo](https://sumo.dlr.de/docs/sumo.html) -source tree (API coverage is large but this client is no longer updated. Use libtraci instead)
- Others: Any language that is supported by [SWIG](https://swig.org/) can in principle use the bindings provided by libsumo or libtraci.

### V2X simulation

TraCI allows to use [sumo](https://sumo.dlr.de/docs/sumo.html) in combination with communication network simulators for simulating [vehicular communication](https://sumo.dlr.de/docs/Topics/V2X.html). See [Topics/V2X](https://sumo.dlr.de/docs/Topics/V2X.html) for a list of available solutions.

### Other Resources

- [sumo](https://sumo.dlr.de/docs/sumo.html) 's TraCI Server is a part of the plain distribution. The source code is located in the folder `src/traci-server`.

## References

- Axel Wegener, Michal Piorkowski, Maxim Raya, Horst Hellbrück, Stefan Fischer and Jean-Pierre Hubaux. TraCI: An Interface for Coupling Road Traffic and Network Simulators. Proceedings of the 11th Communications and Networking Simulation Symposium, April 2008. [Available at ACM Digital Library](https://dl.acm.org/citation.cfm?doid=1400713.1400740)
- Axel Wegener, Horst Hellbrück, Christian Wewetzer and Andreas Lübke: VANET Simulation Environment with Feedback Loop and its Application to Traffic Light Assistance. Proceedings of the 3rd IEEE Workshop on Automotive Networking and Applications, New Orleans, LA, USA, 2008. [Available at IEEEXplore](https://doi.org/10.1109/GLOCOMW.2008.ECP.67)

## Performance

Using TraCI slows down the simulation speed. The amount of slow-down depends on many factors:

- number of TraCI function calls per simulation step
- types of TraCI functions being called (some being more expensive than others)
- computation within the TraCI script
- client language

> [!note] Note
> Please always consider using [libsumo](https://sumo.dlr.de/docs/Libsumo.html) if performance is important. While it is much faster in general, not all optimizations mentioned below are applicable to libsumo as well. Especially subscriptions might even turn out to be slower.

### Examples

As an example use-case consider retrieving the x,y position of each vehicle during every simulation step (using the python client):

```bash
while traci.simulation.getMinExpectedNumber() > 0:
    for veh_id in traci.vehicle.getIDList():
         position = traci.vehicle.getPosition(veh_id)
    traci.simulationStep()
```

- This script is able to process about 25000 vehicles per second.
- The same value retrieval can also be sped up to 50000 vehicles per second by using [subscriptions](https://sumo.dlr.de/docs/TraCI/Object_Variable_Subscription.html):

```bash
while traci.simulation.getMinExpectedNumber() > 0:
    for veh_id in traci.simulation.getDepartedIDList():
        traci.vehicle.subscribe(veh_id, [traci.constants.VAR_POSITION])
    positions = traci.vehicle.getAllSubscriptionResults()
    traci.simulationStep()
```

When using this script on the [Bologna scenario](https://sumo.dlr.de/docs/Data/Scenarios.html#bologna) (9000 vehicles, 5000 simulation steps) the following running times were recorded:

- without TraCI 8s
- plain position retrieval 90s
- retrieval using subscriptions 42s

The C++ client performance is higher:

- plain position retrieval 80s
- retrieval using subscriptions 28s

## Current and Future Development

Historically TraCI used a different (single byte) command ID for every domain (induction loops, vehicle etc.) where the more significant half of the byte denotes the command (get, set, subscribe,...) and the lesser significant the domain itself. To allow more than the 16 domains resulting from this split, the most significant bit (which was unused until version 1.7.0 because there were only 7 commands) is now used for the domain as well (and only three for the command). This allows for 28 domains because four general commands (like SIMSTEP) block some available combinations. Currently there are only four possible domains left.

Furthermore after the invention of libsumo some parts of the TraCI interface are so generic that it may be not so hard to invent a wrapper with Apache Kafka or Google protocol buffers which could in the long run replace the need for all the byte fiddling and the different hand crafted clients.

## Troubleshooting

### Output files are not closed.

This problem occurs if the client tries to access the output while the simulation is still closing down. This can be solved by letting the client wait for the simulation to shut down. The bug report was [#524](https://github.com/eclipse-sumo/sumo/issues/524 "GitHub Issue eclipse-sumo/sumo #524")

### Obsolete APIs

There used to be two "generations" of TraCI commands. The first one mainly uses an internal mapping between the string-typed IDs used in [sumo](https://sumo.dlr.de/docs/sumo.html) and an external representation of these which is int-based. The mapping was done internally (within TraCI). The second "generation", the current one uses string-IDs equal to those [sumo](https://sumo.dlr.de/docs/sumo.html) reads. If you are bound to the first generation API (for instance if you want to use TraNS) you can only use [sumo](https://sumo.dlr.de/docs/sumo.html) up to version 0.12.3. See [FAQ](https://sumo.dlr.de/docs/FAQ.html) about obtaining an old version.
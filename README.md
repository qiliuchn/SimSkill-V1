<h1 align="center">SimSkill</h1>

<p align="center">
  <b>A Lifelong Learning AI Agent for Autonomous Mastery of Traffic Simulation</b>
</p>

![Feature: Multi-Agent](https://img.shields.io/badge/✨%20Feature-Multi--Agent-800080)![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)![Feature: Easy-to-use](https://img.shields.io/badge/✨%20Feature-Easy--to--use-f1c40f)![Feature: Transparent](https://img.shields.io/badge/✨%20Feature-Transparent-7ed321)![Feature: Customization](https://img.shields.io/badge/✨%20Feature-Customization-5dade2)[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

![framework](assets/framework.png)

SimSkill is a self-evolving AI agent that discovers traffic simulation skills within the SUMO (Simulation of Urban MObility) environment. It self-improves by continuously proposing novel tasks, finding solutions to them, and distilling new skills and knowledge from the experience.

SimSkill runs in Claude Code. It has procedural memory (consisting of Claude Code skills), semantic memory (consisting of knowledge pages, markdown files) and episodic memory, which logs the history of past task attempts. SimSkill five core system skills: two for the inference and autonomous learning processes respectively, and three for memory management (retrieval, ingestion, and linting).
<!-- Check our arXiv paper [SimSkill: A Self-Evolving LLM Agent for Skill and Knowledge Accumulation in Traffic Simulation](https://arxiv.org/abs/2609.03753) for more details. --> 

This work is inspired by [Voyager](https://voyager.minedojo.org), the lifelong learning agent in Minecraft, and Andrej Karpathy's writing on LLM memory management (["LLM Wiki"](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)).



## Setup
**Install Claude Code (Required)**
Check out [Claude Code Official Installation Guide](https://code.claude.com/docs/en/quickstart) for installing Claude Code.

**Configure LLMs for Claude Code (Optional)**
You may use custom LLM by configuring `env` in `.claude/settings.json`. An example is given by `.claude/settings.local.json.example`.

**Install Claude Code plugins (Required)**
The following skills are required. You can install them by running the following command in Claude Code:
```
/plugin install skill-creator@claude-plugins-official
```



## Quickstart
**Start autonomous learning**
Start learning by starting Claude Code and typing the following instruction in Claude Code:
```
Start learning
```

You can resume a learning session by typing the following command in terminal:
```bash
claude --resume <session-id>
```
or you can just create a new Claude Code session to continue learning if there is no need to resume a previous session.

**Run an inference**
To run an inference on your task, you can type the following instruction in Claude Code:
```
(Use /infer) <your task>
```
Run inference in test mode (no changes to memory will be made):
Claude Code:
```
(Use /infer in test mode): <your task>
```

**Manual Memory Lint**
You can manually lint your memory by running the following commands in Claude Code.
For incremental mode memory lint:
```
run a memory lint
```
For a full memory lint:
```
run a full memory lint
```

**Check Memory Status**
To check the status of your memory, you can run the following command in terminal:
```bash
python utils/get_memory_statistics.py
```
Example:
```
=== Procedural Skills ===
['analyze-intersection-air-quality-hot-spots-from-microsimulation', 'analyze-intersection-safety-with-ssm', 'analyze-simulation-outputs', 'analyze-traffic-noise-with-harmonoise', 'appraise-project-alternatives-with-benefit-cost-analysis', 'assign-traffic-with-marouter', 'audit-repair-and-persist-imported-network-defects', 'build-and-benchmark-freeway-incident-detection', 'build-and-evaluate-park-and-ride-corridor', 'build-and-evaluate-system-interchange', 'build-atspm-pipeline-and-retime-arterial', 'build-diamond-interchange-with-signal-offset-spillback', 'build-diverging-diamond-interchange', 'build-four-step-model-with-feedback-loop', 'build-gtfs-transit-scenario', 'build-macroscopic-fundamental-diagram', 'build-pedestrian-crossings-and-phasing', 'build-rail-corridor-with-railsignal', 'build-rail-road-grade-crossing', 'build-rolling-horizon-traffic-forecast-with-state-warm-start', 'calibrate-car-following-parameters-against-field-targets', 'calibrate-demand-with-routesampler', 'calibrate-desired-speed-and-evaluate-speed-enforcement', 'calibrate-flow-with-in-simulation-calibrator', 'calibrate-lane-changing-parameters-at-a-freeway-diverge', 'calibrate-motorist-yielding-and-select-midblock-crossing-treatment', 'characterize-pedestrian-flow-and-striping-model-artifacts', 'choose-time-discretization-and-integration-method', 'compare-left-turn-signal-treatments', 'compare-one-way-vs-two-way-street-grid-conversion', 'compare-unsignalized-intersection-control-types', 'compare-zipper-vs-default-merge-at-lane-drop', 'compute-dynamic-user-equilibrium', 'conduct-driveway-signal-warrant-traffic-impact-analysis', 'construct-and-verify-braess-paradox', 'control-one-lane-two-way-alternating-flow-through-a-work-zone', 'control-signals-with-actuated-tls', 'convert-od-matrix-to-trips', 'convert-trips-to-routes', 'create-grid-network', 'create-roundabout-network', 'create-single-intersection', 'create-spider-network', 'demonstrate-and-control-bus-bunching', 'demonstrate-and-stabilize-phantom-traffic-jams', 'design-actuated-signal-detector-placement-and-fault-tolerance', 'design-and-control-freeway-work-zone-lane-closures', 'design-arterial-signal-progression-and-verify-bandwidth', 'design-bus-stop-placement-type-and-spacing', 'design-count-station-locations-for-od-estimation', 'design-left-turn-storage-bay-length', 'design-multimodal-signal-progression-for-bicycles-and-cars', 'design-restricted-crossing-uturn-and-michigan-left-intersections', 'design-signal-change-and-clearance-intervals', 'design-transit-service-plan-under-a-bus-hour-budget', 'emulate-and-evaluate-partial-sensor-traffic-state-estimation', 'equilibrate-departure-time-choice-in-bottleneck-model', 'equilibrate-endogenous-mode-choice-with-transit-supply-feedback', 'estimate-od-matrix-with-odme', 'estimate-stochastic-freeway-capacity-and-breakdown-probability', 'evaluate-corridor-access-management-and-median-treatments', 'evaluate-integrated-corridor-management-with-factorial-interaction-design', 'evaluate-multimodal-accessibility-and-equity', 'evaluate-neighborhood-traffic-calming-and-cut-through-displacement', 'evaluate-protected-bicycle-intersection-design', 'evaluate-right-turn-on-red-and-leading-pedestrian-interval', 'evaluate-two-lane-highway-with-hcm-and-passing-lanes', 'extract-subnetwork-scenario-with-boundary-demand', 'form-platoons-with-simpla', 'generate-activity-based-demand', 'generate-demand-with-jtrrouter', 'generate-hcm-los-report-and-validate-against-microsimulation', 'generate-random-trips', 'get-vehicles-state', 'implement-alinea-ramp-metering', 'implement-coordinated-corridor-ramp-metering', 'implement-detector-free-cv-adaptive-signal-control', 'implement-dynamic-hard-shoulder-running', 'implement-eco-routing', 'implement-emergency-vehicle-preemption', 'implement-glosa-speed-advisory-controller', 'implement-maxpressure-traci-controller', 'implement-mfd-based-perimeter-gating', 'implement-nema-dual-ring-controller', 'implement-predictive-rolling-horizon-signal-control', 'implement-railroad-preemption-at-a-signalized-intersection', 'implement-reservation-based-autonomous-intersection-management', 'implement-scats-style-coordinated-adaptive-signal-control', 'implement-transit-signal-priority', 'implement-variable-speed-limits', 'load-osm-network', 'map-match-gps-traces-to-reconstruct-demand', 'measure-av-penetration-effect-on-bottleneck-capacity', 'measure-heavy-vehicle-passenger-car-equivalent', 'measure-roundabout-capacity-and-implement-metering', 'measure-saturation-flow-and-validate-webster-method', 'measure-travel-time-reliability-with-simulated-days', 'model-adverse-weather-effects-on-freeway-traffic', 'model-capacity-constrained-transit-passenger-loading', 'model-cordon-tolling-with-generalized-cost-surcharge', 'model-cruising-for-parking-search-externality', 'model-curbside-delivery-and-lane-blocking-externality', 'model-dedicated-bicycle-lane-infrastructure', 'model-demand-arrival-process-and-its-effect-on-capacity-and-delay', 'model-freeway-weaving-segment', 'model-grade-aware-heavy-vehicle-performance-and-climbing-lanes', 'model-horizontal-curvature-and-evaluate-design-consistency', 'model-intersection-sight-distance-restriction-at-a-twsc-junction', 'model-managed-lanes-with-dynamic-tolling-and-self-selection', 'model-opposite-direction-overtaking', 'model-parking-with-rerouting', 'model-road-gradient-effects-on-energy', 'model-toll-plaza-as-queueing-facility', 'model-urban-freight-delivery-tours', 'model-vclass-lane-permissions', 'operate-reversible-tidal-flow-lane', 'optimize-signal-plan-with-simulation-in-the-loop-ga', 'optimize-signals-by-qlearning', 'optimize-signals-by-tlscoordinator', 'optimize-signals-by-tlscycleadaptation', 'optimize-under-simulation-noise-with-a-fixed-budget', 'publish-georeferenced-and-animated-results', 'quantify-opendrive-roundtrip-fidelity', 'quantify-sumo-run-to-run-variability', 'reconstruct-demand-with-dfrouter', 'reconstruct-simulation-demand-from-field-turning-movement-counts', 'run-mesoscopic-simulation', 'run-simulation', 'scan-network-link-criticality-and-vulnerability', 'screen-and-decompose-sumo-parameter-sensitivity', 'screen-network-safety-with-spf-and-empirical-bayes', 'set-vehicle-state', 'simulate-emergency-evacuation', 'simulate-ev-charging', 'simulate-fleet-emissions', 'simulate-incident-rerouting', 'simulate-motorcycle-lane-filtering-with-sublane-model', 'simulate-multimodal-transit', 'simulate-street-running-tram-corridor', 'simulate-taxi-and-drt-dispatch', 'size-battery-electric-bus-fleet-and-chargers', 'solve-budget-constrained-network-design-problem', 'specify-route-choice-models-and-generate-route-sets', 'sweep-rerouting-device-market-penetration', 'switch-signal-plans-by-time-of-day-with-waut', 'synthesize-population-and-generate-disaggregate-demand', 'validate-congested-scenario-results-against-teleport-artifacts', 'validate-kinematic-wave-theory-across-car-following-models', 'visualize-network-congestion-heatmap', 'visualize-trajectories-and-timeseries']
Count: 150

=== Semantic Memories ===
['abstract-network-generation', 'accessibility-measurement-and-transport-equity', 'activitygen', 'actuated-signal-detector-design-and-fault-tolerance', 'actuated-traffic-signals', 'arterial-signal-progression-resonance-bandwidth-and-delay', 'automated-traffic-signal-performance-measures', 'automatic-incident-detection-algorithms', 'autonomous-intersection-management-safety-and-performance-envelope', 'av-penetration-and-carfollowing-model-mechanism', 'battery-electric-bus-energy-and-charger-sizing', 'braess-paradox-in-sumo', 'bus-bunching-and-forward-headway-holding', 'bus-stop-infrastructure-design-parking-mechanism-and-tsp-interaction', 'car-following-parameter-calibration-and-identifiability', 'car-to-transit-intermodal-transfer-and-park-and-ride', 'change-vehicle-state', 'connected-vehicle-penetration-and-detector-free-signal-control', 'coordinated-adaptive-signal-control-detector-bias-and-transition-cost', 'coordinated-ramp-metering-delay-transfer-and-ramp-storage', 'cordon-tolling-and-e3-detectors', 'corridor-access-management-twltl-representation-and-density-effects', 'cruising-for-parking-search-externality-and-remedies', 'curbside-delivery-blocking-externality', 'cutroutes-and-subnetwork-extraction', 'dedicated-bicycle-lanes-and-mode-share', 'demand-arrival-process-and-unsignalized-capacity', 'dfrouter-detector-based-demand-reconstruction', 'diamond-interchange-signal-offset-and-spillback', 'discrete-network-design-and-project-interaction', 'diverging-diamond-interchange-unopposed-lefts', 'downs-thomson-paradox-and-mode-choice-equilibrium', 'driver-desired-speed-and-speed-enforcement-evaluation', 'duarouter', 'dynamic-hard-shoulder-running-with-traci-lane-permissions', 'dynamic-user-equilibrium-and-wardrop', 'effort-based-routing-and-eco-routing', 'electric-vehicle-battery-and-charging', 'emergency-vehicle-preemption-and-bluelight', 'evacuation-clearance-time-analysis', 'field-counts-to-simulation-demand-and-the-saturated-count-truncation-trap', 'four-step-model-feedback-loop-convergence', 'freeway-weaving-segment-turbulence', 'freeway-work-zone-capacity-closure-representation-and-merge-control', 'geh-statistic', 'georeferencing-sumo-output-and-cartographic-fidelity', 'global-sensitivity-analysis-and-parameter-interactions-in-sumo', 'glosa-eco-driving', 'gps-map-matching-and-probe-demand-reconstruction', 'grade-aware-heavy-vehicle-physics-and-climbing-lane-warrants', 'gtfs-import-and-pt-representation-semantics', 'harmonoise-traffic-noise-modeling', 'hcm-control-delay-vs-sumo-delay-metrics', 'heavy-vehicle-passenger-car-equivalent-in-sumo', 'horizontal-curvature-and-curve-speed-in-sumo', 'imported-network-defect-classes-and-traffic-impact', 'incident-rerouting-and-closures', 'information-penetration-and-congestible-routing', 'integrated-corridor-management-factorial-interaction-findings', 'intermodal-transfer-and-person-stage-semantics-in-sumo', 'intersection-air-quality-hot-spot-analysis', 'intersection-sight-distance-and-sumo-visibility-parameter', 'jtrrouter', 'kinematic-wave-theory-validity-across-car-following-models', 'lane-change-model-calibration-and-identifiability-at-a-diverge', 'left-turn-storage-bay-length-design', 'left-turn-treatment-tradeoffs', 'macroscopic-fundamental-diagram', 'managed-lanes-empty-lane-paradox-and-person-throughput', 'marouter-macroscopic-assignment', 'max-pressure-signal-control', 'mesoscopic-simulation', 'mfd-based-perimeter-gating', 'motorist-yielding-calibration-and-midblock-crossing-treatment-selection', 'multi-resolution-modeling-buffer-sizing-and-boundary-handoff', 'multimodal-signal-progression-and-the-bicycle-green-wave', 'mutcd-signal-warrants-and-the-demand-vs-served-volume-trap', 'neighborhood-traffic-calming-displacement-and-evaporation', 'nema-dual-ring-controller', 'network-link-criticality-and-proxy-validation', 'network-safety-screening-and-crash-prediction', 'od-matrix-estimation-and-underdetermination', 'od2trips', 'one-lane-two-way-alternating-flow-and-shared-lane-representation', 'one-way-vs-two-way-grid-performance-crossover', 'opendrive-and-network-format-interoperability', 'openstreetmap', 'opposite-direction-overtaking-mechanics', 'parking-areas-and-rerouters', 'pedestrian-crossings-and-signal-phasing', 'pedestrian-flow-theory-and-striping-model-artifacts', 'phantom-traffic-jams-and-single-av-stabilization', 'population-synthesis-and-aggregation-bias', 'protected-bicycle-intersection-design-and-right-hook-mechanics', 'public-transport-and-intermodal-routing', 'q-learning-agent', 'rail-crossing-junction-mechanics', 'rail-simulation-and-railsignal', 'railroad-preemption-of-nearby-signalized-intersections', 'ramp-metering-with-alinea', 'random-trips', 'rcut-and-michigan-left-alternative-intersection-design', 'reversible-lane-encoding-and-changeover-safety', 'right-turn-on-red-and-leading-pedestrian-interval', 'road-gradient-and-energy-consumption', 'roundabout-capacity-law-and-demand-metering', 'roundabout-modeling-and-comparison', 'route-choice-model-verification-overlap-and-route-set-effects', 'routesampler', 'sensor-location-design-for-od-estimation', 'signal-clearance-intervals-dilemma-zone-and-safety-capacity-tradeoff', 'simpla-platooning', 'simulation-based-optimization-under-noise-and-seed-overfitting', 'simulation-in-the-loop-ga-signal-optimization', 'spatial-congestion-heatmap-with-plot-net-dump', 'state-serialization-and-rolling-horizon-traffic-forecasting', 'station-based-shared-micromobility-in-sumo', 'stochastic-freeway-capacity-and-breakdown-probability', 'street-running-tram-reservation-and-right-of-way-tradeoffs', 'sublane-model-and-lane-filtering', 'sumo-calibrator', 'sumo-command-line', 'sumo-output-files', 'sumo-plotting-tools', 'sumo-rl-environment', 'sumo-stochastic-variability-and-replication-design', 'sumo-time-discretization', 'surrogate-safety-measures', 'system-interchange-weaving-and-design-selection', 'taxi-and-drt-dispatch', 'teleport-artifacts-and-gridlock-resolution-validity', 'tlscoordinator', 'tlscycleadaptation', 'toll-plaza-queueing-and-the-service-headway-floor', 'traci', 'traffic-state-estimation-sensor-bias-and-sensing-tradeoffs', 'transit-capacity-passenger-loading-and-pass-up-dynamics', 'transit-network-design-and-frequency-setting', 'transit-signal-priority', 'transport-economic-appraisal-from-microsimulation', 'travel-time-reliability-metrics-in-sumo', 'two-lane-highway-follower-density-and-passing-lane-effectiveness', 'unsignalized-vs-signalized-intersection-control', 'urban-freight-delivery-tours-container-semantics-and-policy-levers', 'value-of-anticipation-in-predictive-signal-control', 'variable-speed-limits-and-e2-detectors', 'vehicle-class-lane-permissions', 'vehicle-emissions-modeling', 'vickrey-bottleneck-departure-time-equilibrium', 'waut-time-of-day-signal-plan-switching', 'weather-friction-effects-on-capacity-and-safety', 'webster-method', 'zipper-merge-lane-drop-discharge']
Count: 153
```


## Architecture

SimSkill has the following components:

1. **Memory structure**: SimSkill has three types of memory — episodic, procedural, and semantic — plus a raw-materials store and a shared change log that ties procedural and semantic memory together.
    - **Episodic memory** (`episodic-memory/`): logs the history of user interactions with SimSkill and of self-directed learning attempts.
    - **Procedural memory** (`.claude/skills/procedural-memory/`): stores the skills SimSkill has discovered in the SUMO traffic simulation environment. Each skill describes the process for performing a specific task. Skills are interlinked — a complex skill may depend on simpler ones.
      Examples:
        - `run-simulation`: run a SUMO simulation, via command line or the TraCI API
        - `create-grid-network`: create a grid network in SUMO
        - `generate-random-trips`: generate random trips for a given network in SUMO
        - `optimize-signals-by-tlscycleadaptation`: optimize signal timing in SUMO using the tlsCycleAdaptation algorithm
        - `get-vehicles-state`: read vehicles' state in SUMO
        - `set-vehicle-state`: set a vehicle's state in SUMO
    - **Semantic memory** (`semantic-memory/`): a structured, interlinked knowledge base of facts about the SUMO traffic simulation environment. `semantic-memory/index.md` indexes every page with its summary and keywords, so relevant pages can be found without opening each one individually.
      Examples:
        - `abstract-network-generation`: how to generate an abstract (synthetic) network in SUMO
        - `openstreetmap`: how to import OpenStreetMap data into SUMO
        - `traci`: how to use the TraCI interface in SUMO
        - `od2trips`: how to convert an OD matrix into trips in SUMO
        - `duarouter`: how to use duarouter, which computes vehicle routes and performs traffic assignment in SUMO
    - **Raw materials** (`raw-materials/`): the raw source materials used to generate semantic memory pages — web page clippings, PDF documents, and similar. Knowledge pages cite the specific raw-materials file(s) they were derived from in their `sources` frontmatter.
    - **Change log** (`log.md`): an append-only record, at the project root, of every addition or update to procedural or semantic memory, plus the history of `memory-lint` runs. It's what lets `memory-lint` tell how much new material has accumulated since its last pass, so it isn't tied to either memory type individually.

2. **System skills** (`.claude/skills/system/`): the Claude Code skills that define how SimSkill operates. There are six: `infer`, `learn`, `memory-retrieve`, `memory-ingest`, and `memory-lint`.
    - `infer`: accomplish a given traffic simulation task
    - `learn`: autonomously discover new skills and knowledge in the SUMO environment
    - `memory-retrieve`: retrieve task-relevant skills and knowledge from memory
    - `memory-ingest`: ingest a new traffic simulation experience into memory
    - `memory-lint`: lint procedural and semantic memory
    - `log`: log procedural and semantic memory changes

3. **Sub-agents** (`.claude/agents/`): agents that perform specific steps of the system skills in a separate process with isolated context. SimSkill defines three: `curriculum-agent`, `action-agent`, and `critic-agent`.
    - `curriculum-agent`: proposes the next novel task to explore in the SUMO environment
    - `action-agent`: accomplishes the task proposed by `curriculum-agent`
    - `critic-agent`: evaluates `action-agent`'s performance and provides feedback



## Workflow
![Workflow Summary](assets/workflow.png)

### Inference flow

Flow diagram of skill `infer`:
```
User input to start inference
(e.g. "Generate a 3×3 road network. The central east–west and north–south corridors should each consist of six lanes (three lanes per direction),
while all other roads should consist of four lanes (two lanes per direction). At every intersection, provide one additional approach lane on each
incoming leg for channelization. Generate one-hour morning peak traffic demand. Assume that the central business district (CBD) is located to the
northeast of the network. Create two traffic demand scenarios, representing weekday and weekend conditions. Equip all intersections with traffic
signals. Using Webster's method, optimize the signal timing plans for each demand scenario, including phase design and signal timing parameters.")
        ↓
    [S] memory-retrieve:
    retrieve relevant skills
    and knowledge
        ↓
    [A] action-agent: ←───────────┐
    execute task                  │
        ↓                         │ add critic
    [A] critic-agent:             │ feedback to
    evaluate                      │ context
        ↓                         │
    <task complete, or        No  │
     max attempts reached?> ──────┘
        │ Yes
        ↓
    save to episodic memory
        ↓                          
    [S] memory-ingest:             
    create/update skill            
    or knowledge                   
        ↓                          
Return result to main process
```

`[S]` = a skill is used for this step. `[A]` = an agent is invoked for this step.


### Learning flow
Flow diagram of skill `learn`:
```
User input to start learning
(e.g. "Start learning")
        ↓
   begin loop iteration ←───────────┐
        ↓                           │       
    [S] memory-lint:                │
    lint memory                     │
        ↓                           │
    [A] curriculum-agent:           │
    propose next task               │
        ↓                           │
    [S] infer:                      │
    generate answer                 │
        ↓             No (default)  │
    <user stops?> ──────────────────┘
        │ Yes
        ↓
Return learning statistics
(e.g. skills/knowledge added or updated)
```

`[S]` = a skill is used for this step. `[A]` = an agent is invoked for this step.


## Project Structure

```
[project_root]/
├── CLAUDE.md                           # SimSkill system description
├── log.md                              # Change log for procedural/semantic memory additions and updates, and memory-lint run history
├── .claude/                            # Claude Code directory
│   ├── agents/                         # SimSkill sub-agents
│   └── skills/                         # Skills library
│       ├── system/                     # SimSkill system skills
│       └── procedural-memory/          # Procedural memory - traffic simulation skills automatically discovered by SimSkill
├── .obsidian/                          # Obsidian settings
├── episodic-memory/                    # Episodic memory - traffic simulation trials
├── raw-materials/                      # Raw materials used to generate semantic memory pages (web clippings, PDFs, etc.)
└── semantic-memory/                    # Semantic memory - a collection of knowledge pages (markdown files)
    └── index.md                        # Index of all knowledge pages (summary + keywords), for retrieval without opening every page
```


## Memory Representation
### Procedural Memory Formatting
File structure for a skill:
```
your-skill-name/
├── SKILL.md # Required - main skill file
├── scripts/ # Optional but recommended - executable code
├── references/ # Optional - documentation
│   ├── api-guide.md # Example
│   └── examples/ # Example
└── assets/ # Optional - templates, etc.
    └── report-template.md # Example
```

A `SKILL.md` file must contain the following:
```
---
name: your-skill-name
description: What it does. Use when user asks to [specific phrases].
---
<skill content>
```

SimSkill use `skill-creator` skill to create a new skill. Other skill-creating skills are also compatible.


### Semantic Memory Formatting

**Knowledge Page Format**
![Semantic Memory Visualization](assets/knowledge_page_format.png)


### Graph View
Use Obsidian to open the project root directory.

Run the following command in terminal to copy skills for graph visualization:
```
python utils/copy_skills_for_graph_view.py
```

![Semantic Memory Graph](assets/graph_view.png)

Note: Obsidian's `graph.json` sets:
```
  "search": "(path:\"semantic-memory\" OR path:\"procedural-memory-for-graph-view\") -file:\"index.md\""
```
PS: Obsidian’s search matches any file whose full path contains the specified string. Therefore, avoid placing folders or files with names such as ``semantic-memory`` or ``procedural-memory-for-graph-view`` anywhere in their path unless you want them to appear in the graph.


## Experimentation

Check out the [test](test/) directory for some ideas on how to experiment with SimSkill.
[Experiments](test/experiments.md) introduces the experiment design and how to run them.
Experiment results of the paper are documented in [save](test/save/).

### Main Results

Verified completion on Benchmark V1 as a function of observed monetary or wall-clock
budget. Each panel uses the budget shown on its horizontal axis. Red curves show complete SimSkill
and blue curves show vanilla Claude Code; endpoint labels give verified completions out of all 40 tasks,
and markers locate verified failures at their consumed resource levels.
![benchmark v1](assets/performance_benchmark_v1.png)

Verified completion on the hard Benchmark V2 as a function of observed monetary or wall-
clock budget.
![benchmark v2](assets/performance_benchmark_v1.png)


Complete SimSkill versus vanilla Claude Code. Completion is reported as verified tasks out of 40, with percentages in parentheses. Cost and time entries are per-run medians in the form full/vanilla.
```
  --------------------------------------------------------------------------------------
  Benchmark   Backbone                Full    Vanilla     Δ (pp)    Cost F/V    Time F/V
                                                                       (USD)         (s)
  ----------- ----------------- ---------- ---------- ---------- ----------- -----------
  V1          DeepSeek-V4-Pro   38 (95.0%) 34 (85.0%)      +10.0   0.78/0.49    1056/650

  V1          GLM-5.2           30 (75.0%) 31 (77.5%)       -2.5   1.02/1.47    918/1918

  V1          Qwen3.7-Max       23 (57.5%) 13 (32.5%)      +25.0   1.84/1.03     851/683

  V2          DeepSeek-V4-Pro   27 (67.5%) 19 (47.5%)      +20.0   3.93/2.92   4623/4796

  V2          GLM-5.2           10 (25.0%) 10 (25.0%)        0.0   2.29/2.44   2008/2899

  V2          Qwen3.7-Max         2 (5.0%)   0 (0.0%)       +5.0   2.16/2.35    916/1969
  --------------------------------------------------------------------------------------
```

**Findings**:
- SimSkill performance is significantly better than vanilla Claude Code. SimSkill also enables some long-horizon completion even when the baseline does not.
- The result is not universal across models. GLM-5.2 shows no gain.
- Results provide evidence that the accumulated library can support new compositions and first-principles tasks rather than only near-duplicates of past experience.


### Ablations

Benchmark V1 ablation curves for DeepSeek-V4-Pro (top) and Qwen3.7-Max (bottom),
under the Claude Opus 5 binary judge. The left panels use dollar cost and the right panels use wall-
clock time.

![ablations](assets/ablations.png)

Above figure compare all five conditions on V1. Procedural memory contributes slightly more than semantic memory for both backbones, but neither representation subsumes the other.

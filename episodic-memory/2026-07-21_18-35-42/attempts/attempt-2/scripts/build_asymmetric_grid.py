# Illustrative placeholder. Extends create-grid-network's approach: builds
# plain-XML edge definitions with per-corridor lane overrides (central
# corridors=3 lanes/direction, others=2), plus channelization lanes at
# every junction approach, then compiles via netconvert -- unlike attempt
# 1, no post-generation XML patching.
print("build network.net.xml via netconvert with corridor-specific lane counts")

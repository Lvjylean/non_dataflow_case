# Inherited parent rectangles

`directed_config.json` optionally supplies `inherited_parent_regions`, a map from
existing child module IDs to the exact `[x0, y0, x1, y1]` core rectangle of a parent.
The default configuration has no entries and its search behavior is unchanged.

Each valid parent rectangle is an additional candidate alongside the normal
`1.5 * minimum_area + 4` window. Only this exact rectangle bypasses the area
window. Other positions and shapes do not inherit that exception. Resource
capacity checks remain mandatory, including summed occupancy when modules overlap.
No change is made to J, resource limits, soft expansion, or module membership.

The caller must verify that the child members form the claimed subdivision of the
parent, bind the parent core solution and membership hashes, and record provenance.
This option does not infer logical lineage from module names. The GETRF controlled
experiment verifies both child sets and preserves S01–S08 membership/core/soft
geometry; both children receive the parent S00 rectangle X0Y8:X7Y11.

The search and independent verifier recognize the same explicit area exception.
The verifier independently recomputes geometry, all resource capacities and J.

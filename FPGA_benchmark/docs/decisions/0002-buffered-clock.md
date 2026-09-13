# Include a real global clock buffer in the U250 wrapper

The external-buffer OOC attempts leave one explicit clock-net gap and ROUTED_FULLY=0 despite all routable nets being counted fully routed. The selected flow directly synthesizes unchanged upstream HDL and the full VTA block design inside a wrapper with one BUFG. It adds no data/control pipeline stage. Earlier DCP-link attempts failed and are preserved; the maintained source flow avoids that import dependency.

Retain 10ns and 1ns boundary delays. Re-run synthesis, placement and routing under unique IDs. Require tool ROUTED_FULLY=1, zero GAPS/PARTIAL/UNROUTED/CONFLICTS and zero route errors. Verify independent reopen, no black boxes and no DRC errors/critical warnings. Overall timing remains separate; internal register-to-register timing supplements but never replaces full-interface timing.

The wrapper preserves all 44 CNNA ports and all 70 VTA ports. Only aclk maps through the BUFG; data/control/reset mappings are unchanged. The interface declarations are archived under configs/ for reproducibility. This remains an OOC accelerator core, not a U250 platform shell or board application.

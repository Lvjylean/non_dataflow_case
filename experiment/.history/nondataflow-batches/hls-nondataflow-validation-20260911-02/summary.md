# C simulation validation

- gematrixinverse_baseline: FAIL — NUMERICAL_SAMPLE N=4 KIND=6 ENTRIES=132 WORST_RELATIVE=0.5; NUMERICAL_SAMPLE_FAIL; ERROR: [SIM 211-100] 'csim_design' failed: nonzero return value.
- gematrixinverse_n256_u128: FAIL — NUMERICAL_SAMPLE N=256 KIND=6 ENTRIES=384 WORST_RELATIVE=0.5; NUMERICAL_SAMPLE_FAIL; ERROR: [SIM 211-100] 'csim_design' failed: nonzero return value.
- trtrs_n1024_u512: PASS — NUMERICAL_SAMPLE N=1024 KIND=5 ALL_RHS=2048 WORST_ABSOLUTE=1.6653345369377348e-16; NUMERICAL_SAMPLE_PASS

Sample coverage and limitations are documented in the combined report. No RTL co-simulation or DCP was produced.

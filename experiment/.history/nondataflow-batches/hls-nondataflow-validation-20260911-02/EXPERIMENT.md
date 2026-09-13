# Inverse diagnostic and triangular solve validation

Server: /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/hls-nondataflow-validation-20260911-02
Reason: scaled gematrixinverse failed A*Ainv=I with relative error 0.9298. Run exact diagonal A=2I against default 4/2 and scaled 256/128 to distinguish upstream algorithm behavior from scaling. An inverse must return I/2.
Also validate trtrs 1024/512 with two known RHS vectors, a dense lower-triangular matrix and all 2048 solution entries checked at absolute tolerance 1e-7. Same tool and no source/RTL edits. Retain all failures; do not silently repair third-party algorithms.

## Final results

# C simulation validation

- gematrixinverse_baseline: FAIL — NUMERICAL_SAMPLE N=4 KIND=6 ENTRIES=132 WORST_RELATIVE=0.5; NUMERICAL_SAMPLE_FAIL; ERROR: [SIM 211-100] 'csim_design' failed: nonzero return value.
- gematrixinverse_n256_u128: FAIL — NUMERICAL_SAMPLE N=256 KIND=6 ENTRIES=384 WORST_RELATIVE=0.5; NUMERICAL_SAMPLE_FAIL; ERROR: [SIM 211-100] 'csim_design' failed: nonzero return value.
- trtrs_n1024_u512: PASS — NUMERICAL_SAMPLE N=1024 KIND=5 ALL_RHS=2048 WORST_ABSOLUTE=1.6653345369377348e-16; NUMERICAL_SAMPLE_PASS

Sample coverage and limitations are documented in the combined report. No RTL co-simulation or DCP was produced.

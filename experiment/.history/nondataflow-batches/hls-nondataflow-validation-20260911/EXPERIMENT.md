# Selected scaled-kernel C simulation

Server: /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/hls-nondataflow-validation-20260911
Exact synthesized inputs: batch02 getrf/getrf_nopivot 1024/512; batch01 inversion 256/128; batch03 QR 768/384.
Checks: finite outputs; all diagonal plus 128 deterministic off-diagonal residual samples. LU uses PA=LU and deliberately swaps input rows to exercise pivoting, nonpivot LU uses A=LU, inverse uses A*Ainv=I, QR checks A^T*A=R^T*R. Relative tolerance 1e-7. This is sampled C-level numerical validation, not exhaustive verification or RTL co-simulation.
Compile/run on server with Vitis HLS 2023.2 csim_design, O2 C++14, unlimited process stack for large local arrays. No source or RTL changes. Each simulation has a 300-second limit. Synchronize logs and results locally.

Additional parameter audit: gesvdj NCU=32 is invalid for this source: tmp[16] at line 871 is indexed by i in loops bounded by UN at lines 895, 905 and 915. Exclude that configuration even though HLS generated RTL; retain as invalid-parameter evidence. NCU<=16 configurations did not meet compute threshold.

## Final results

# C simulation validation

- getrf_n1024_u512: PASS — NUMERICAL_SAMPLE N=1024 KIND=1 ENTRIES=1152 WORST_RELATIVE=3.1607772943064956e-15; NUMERICAL_SAMPLE_PASS
- getrf_nopivot_n1024_u512: PASS — NUMERICAL_SAMPLE N=1024 KIND=2 ENTRIES=1152 WORST_RELATIVE=3.1607772943064956e-15; NUMERICAL_SAMPLE_PASS
- gematrixinverse_n256_u128: FAIL — NUMERICAL_SAMPLE N=256 KIND=3 ENTRIES=384 WORST_RELATIVE=0.92980322838186347; NUMERICAL_SAMPLE_FAIL; ERROR: [SIM 211-100] 'csim_design' failed: nonzero return value.
- geqrf_n768_u384: PASS — NUMERICAL_SAMPLE N=768 KIND=4 ENTRIES=896 WORST_RELATIVE=1.3310463842231002e-12; NUMERICAL_SAMPLE_PASS

Sample coverage and limitations are documented in the combined report. No RTL co-simulation or DCP was produced.

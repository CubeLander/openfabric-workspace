# B-line Three-operator Upload Bundle

This validation bundle includes a progress-first three-operator payload set:

- `payloads/bline_gemm_no_relu`
- `payloads/bline_gemm_relu`
- `payloads/log10max_single_task`

The default `./run.sh` remains the conservative validation smoke entrypoint.
For the B-line three-operator upload run, use:

```bash
./scripts/run_bline_progress_payloads.sh
```

The three-operator launcher selects only the payloads listed above and then
delegates to the standard `scripts/run_payloads.sh` entrypoint.

Current status is progress-first: these payloads are packaged to drive upload
and runtime bring-up. Numerical correctness and B-line-native binary lowering
closure remain tracked in the root technical debt checkpoint.

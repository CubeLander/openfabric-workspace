# CSV Config Generator Notes

This note compares the two restored `csv_generate/test_app_conf_generate.c`
files:

```text
application/CASE/softmax_1/csv_generate/test_app_conf_generate.c
application/CASE/gemm_template_fusion/csv_generate/test_app_conf_generate.c
```

## Summary

The two files are not text-identical, but they implement the same build phase:

```text
csv_generate/test_app_conf_generate.c
  -> ../app*.conf
  -> instance_conf_info_file*.bin
  -> instance_conf_info_for_rtl_file*.bin

workflow aggregation
  -> simulator_bin/instance_conf_info_file.bin
  -> rtl_bin/cbufData_instance.bin
```

Observed sizes:

```text
softmax_1:            328 lines
gemm_template_fusion: 356 lines
```

The common skeleton is strong enough that this phase should become a common
workflow component. The case-specific math is still real, so the first
extraction should not force both cases into one monolithic C file.

## Common Structure

Both generators define the same runtime-facing structs:

```text
instance_conf_info_t
instance_conf_info_t_for_rtl
AA
```

Both generate `app*.conf` with the same textual shape:

```text
task(task_name:taskN;...;subtask_num:X)
{
subtask(subtask_name:subtaskM;...;Instance Times : ...;code_path:template/;csv_amount:...;graph height:...;graph width:...)
}
```

Both write the same binary file family:

```text
instance_conf_info_file0.bin ... instance_conf_info_file3.bin
instance_conf_info_for_rtl_file0.bin ... instance_conf_info_for_rtl_file3.bin
```

Both rely on `common_oper/write_file.cpp` for binary writes.

## Differences

The differences are not just formatting:

```text
softmax_1:
  includes conf.h and conf_PEmap.h
  uses SUBTASK_NUM, PER_TASK_PE_NUMBER, PE_NUM_BASE
  derives instance counts from PER_TASK_INSTANCE_NUMBER
  has operator-specific branches for SOFTMAX/RMSNORM/ROPE/SCALE style names

gemm_template_fusion:
  includes conf_PEmap.h only
  derives subtask_num from Secondary_Fusion_Array
  computes csv_amount from taskAddr_per_pe_A/B, loadA, copyA
  uses GEMM-specific SPM_GEMM_* addresses and instruction_num
```

`conf.h` and `conf_PEmap.h` are also case-specific. They carry the shape,
memory layout, PE map, and operator scheduling parameters. This is good: it
means much of the policy is already externalized, but the generator still has
case-specific control flow.

## Workflow Validation

The direct workflow successfully ran the `gemm_template_fusion` config
generation phase. It produced:

```text
app0.conf ... app3.conf
simulator_bin/instance_conf_info_file.bin
rtl_bin/cbufData_instance.bin
```

The full `gemm_template_fusion` package currently stops later because the
workflow assumes a task graph directory named `gpdpu_TestOp`, while this case
uses `gpdpu_tensor`. That is separate from the CSV config generator question.

## Extraction Plan

Recommended order:

1. Keep per-case `test_app_conf_generate.c` for now, but move the compile/run
   and aggregation behavior into a common workflow function. This is already
   mostly done in `build_package.sh`.
2. Add a small manifest for the config generator phase:

   ```text
   csv_generate_dir=csv_generate
   generator_source=test_app_conf_generate.c
   generator_headers=conf.h conf_PEmap.h tempfile.h
   output_app_conf_glob=app*.conf
   output_instance_glob=instance_conf_info_file*.bin
   output_rtl_instance_glob=instance_conf_info_for_rtl_file*.bin
   ```

3. Extract shared C/C++ definitions only after more cases are tested:

   ```text
   instance_conf_info_t structs
   app.conf writer helpers
   instance binary writer helpers
   padding logic for 2048 entries
   ```

4. Leave these as case-specific strategy functions or generated config data:

   ```text
   subtask_num calculation
   subtask_csv_amount calculation
   subtask_instance_times calculation
   base_addr update rules
   operator-specific memory layout rules
   ```

5. Generalize the next phase independently by detecting `gpdpu_TestOp` versus
   `gpdpu_tensor` as the task graph source directory.

The useful abstraction is therefore:

```text
common config-generator runner + common output contract
case-specific config-generator strategy
```

not:

```text
one universal copied C file for every operator
```


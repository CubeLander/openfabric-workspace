# 10. Conclusion

## Job of This Section

Return to the paper's central reframing:

```text
Spatial accelerator operator programming is tensor visibility programming.
```

## Desired Closing

The conclusion should be short and assertive:

```text
OpenFabric shows that spatial accelerators can be programmed as distributed
tensor machines. By making placement, tile values, and logical collectives
explicit, OpenFabric separates operator semantics from vendor artifacts while
still lowering to real case-authoring and package surfaces. The exposure cases
show that this model is not a GEMM-only generator, but a practical foundation
for building reusable compiler support for spatial accelerator operators.
```

## Avoid

- introducing new claims;
- promising full automation of all future operators;
- claiming final binary replacement if the paper does not evaluate it.

# SPM Data Operator Generation TODO

Date: 2026-06-30

`spm_data_program/` 现在仍保留 vendor helper 形态，只把配置入口切到
`openfabric_gemm_runtime_config.h`，避免继续依赖维护版 `conf.h` /
`conf_PEmap.h`。

后续可以把 input/SPM 数据生成也挂到算子主程序或同一个 operator plan 入口
下，目标是让输入布局、SPM 初始化、结果检查的形状和地址事实都来自算子逻辑，
而不是由独立 helper 源文件手工复述。

暂不处理：

- 不改 `spm_data_program` 的数据生成算法。
- 不把随机输入、half 转换、result check 逻辑塞进本轮 config refactor。
- 不把 SPM 数据文件纳入新的比较目标；当前仍以 replay 的 RISC-V、package、
  support binaries 为安全绳。

# 辅助兼容产物（Auxiliary Artifacts）

这一页只记录当前已经稳定的事实：`data_inst_replace.bin`、`instEnable.bin`、`taskEnable.bin` 是辅助产物，不属于主线 `cbuf_file.bin` / `micc_file.bin` 镜像。

它们容易被误读成 runtime 控制语义。当前证据不支持这么做。

## 1. 文件边界

| 文件 | 当前定位 | OpenFabric 处理 |
|---|---|---|
| `data_inst_replace.bin` | simulator / vendor packaging 兼容 sidecar | 可选生成 / 可选打包；不参与 runtime 语义推导 |
| `instEnable.bin` | RTL / debug collateral | 不作为 runtime instruction readiness 来源 |
| `taskEnable.bin` | RTL / debug collateral | 不作为 active task id 或 task count 来源 |

当前主线仍然只有：

```text
cbuf_file.bin = insts + exeblock + instance
micc_file.bin = tasks + subtasks
```

辅助产物最多作为旁路文件出现：

```text
result/
  cbuf_file.bin
  micc_file.bin
  data_inst_replace.bin   # optional compatibility sidecar
```

## 2. Writer 事实

当前已知 writer 是 vendor `Print_Task_Group::task_inst_enable_print()`。

它打开三个文件：

```text
./rtl_bin/instEnable.bin
./rtl_bin/taskEnable.bin
./simulator_bin/data_inst_replace.bin
```

对 `application_num = 1` 的可见输出是：

```text
instEnable.bin:
  1\n

data_inst_replace.bin:
  1 1\n

taskEnable.bin:
  一行 MAX_CUR_TASK_CONF_PER_APP 长度的 mask
  前面的 slot 写 0
  最后的 task_num 个 slot 写 1
```

这说明当前本地证据只支持“固定兼容标记 / RTL 辅助 mask”，不支持把这些文件解释成完整 runtime schema。

## 3. Packaging / Staging 事实

vendor packaging 会把主线 simulator 产物拼进 CBUF/MICC，同时把辅助文件追加到各自的 multi-app sidecar，而不是拼进 CBUF 或 MICC：

```text
simulator_bin/insts_file.bin              -> simulator_bin_multi_app/cbuf_file.bin
simulator_bin/exeblock_conf_info_file.bin -> simulator_bin_multi_app/cbuf_file.bin
simulator_bin/instance_conf_info_file.bin -> simulator_bin_multi_app/cbuf_file.bin
simulator_bin/tasks_conf_info_file.bin    -> simulator_bin_multi_app/micc_file.bin
simulator_bin/subtasks_conf_info_file.bin -> simulator_bin_multi_app/micc_file.bin

simulator_bin/data_inst_replace.bin       -> simulator_bin_multi_app/data_inst_replace.bin
rtl_bin/instEnable.bin                    -> rtl_bin_multi_app/instEnable.bin
rtl_bin/taskEnable.bin                    -> rtl_bin_multi_app/taskEnable.bin
```

partner validation staging 只在文件存在时复制：

```text
payload/result/data_inst_replace.bin
  -> runtime config/data_inst_replace.bin
```

当前 runtime staging 路径只观察到 `data_inst_replace.bin` 的可选复制；`instEnable.bin` / `taskEnable.bin` 停留在 RTL/debug collateral 范围内。

所以 OpenFabric 可以把 `data_inst_replace.bin` 当作 optional compatibility sidecar：有就随 payload/staging 走，没有也不改变 CBUF/MICC 主镜像定义。enable 文件不应升级为 runtime 必需输入。

## 4. Runtime Consumer 状态

当前本地源码审计只找到：

- 文件名定义
- writer
- packaging / staging copy

没有找到 `data_inst_replace.bin`、`instEnable.bin`、`taskEnable.bin` 的 C/C++ runtime consumer。

因此当前 runtime 侧必须保持保守：

- 不从 `data_inst_replace.bin` 推导 data replacement、instruction count 或 task count
- 不从 `instEnable.bin` 推导 instruction readiness
- 不从 `taskEnable.bin` 推导 active task id、launch count 或 MICC 有效 task 行

runtime launch count 和 active task ids 应来自 `TaskControlPlan` / `RuntimeControlPlan`，不是这些辅助文件。

## 5. Verifier / Hash 规则

这些文件不属于 `cbuf_file.bin` / `micc_file.bin` 的尺寸、hash 或 runtime readiness 判定。

稳定规则是：

1. `cbuf_file.bin` size/hash 只覆盖 CBUF 主镜像。
2. `micc_file.bin` size/hash 只覆盖 MICC 主镜像。
3. `data_inst_replace.bin` presence 应在 manifest 里显式记录为 optional sidecar。
4. runtime readiness 不要求 `data_inst_replace.bin`、`instEnable.bin`、`taskEnable.bin` 存在。
5. 未来如果要赋予 semantic runtime 意义，必须先引用明确 runtime consumer 或远端证据。

## 6. OpenFabric 结论

OpenFabric 当前应支持这些产物的兼容流转，但不要把它们纳入主线数据面语义。

```text
emit/copy if compatibility path needs it
do not pack into CBUF/MICC
do not count toward CBUF/MICC size or hash
do not gate runtime readiness on it
do not infer runtime semantics from it
```

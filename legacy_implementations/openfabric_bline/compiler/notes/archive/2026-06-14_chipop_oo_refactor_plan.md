# ChipOp 改造成对象化层级的执行计划

## 目标（当前阶段，不改源码实现）

把 `ChipOp` 从“`op: str` + 通用 attrs”改为“基类 + 子类（typed op）”的模型，以提升可读性与可维护性。  
本计划只产出文档，暂不改动源码；另一个 agent 可按这个计划直接实施。

约束与前提：
- 不改动 `ChipOp` 当前对外计划输出 `to_plan()["op"]` 的字符串语义（用于已有测试与日志）。
- `ChipEnv` 仍保持前端语义：不在 op 阶段维护 PE/DFU/subtask/instance 等底层状态。
- 保留与 `processor -> tile -> node -> packing -> asm -> vendor_abi -> bin` 的现有链路兼容。

## 现状与问题

当前实现里 `ChipOp` 位于 `core/program.py`，只有字段 `id/op/inputs/outputs/attrs`。  
`program_processor.py` 主要通过字符串分支做分发：
- `declare_sram_tensor / load_sram_tensor / store_sram_tensor` 特判
- 其它都走 `_lower_compute`，并在 `chip_op.op` 上再按 `"matmul"` 做额外逻辑

这会带来两类长期问题：
1. op 的“契约”分散在不同地方（`ops.py`, `chip_env.py`, `program_processor.py`），新增 op 时容易漏校验。
2. `attrs` 里混入语义字段，语义约束靠文档和人工记忆，较易和逻辑分叉。

## 目标设计（建议）

### 1）引入明确的 ChipOp 层级类型

在 `core/program.py` 增加：
- `ChipOpKind`（枚举）：`DECLARE_SRAM_TENSOR`, `LOAD_SRAM_TENSOR`, `STORE_SRAM_TENSOR`, `COMPUTE`, `MATMUL`, `RELU`, `ADD`, `REDUCE_SUM`, `UNKNOWN`
- `ChipOp` 抽象基类（或最终 dataclass）
  - 公共字段：`id`, `inputs`, `outputs`, `kind`, `attrs`（只放公共元数据）
  - `to_plan()` 仍返回：
    - `"op"`：与旧版字符串一致（如 `matmul`）
    - `"attrs"`：兼容旧结构（必要时保留同名 key）
  - `validate()` 钩子：每个子类可在构造/降级前进行参数校验（输入输出个数、shape约束占位等）

建议子类（起步）：
- `DeclareSRAMTensorOp`：仅用于显式 sram 声明，建议可保持原语义字段，当前主要用于兼容计划记录。
- `LoadSRAMTensorOp`
- `StoreSRAMTensorOp`
- `ComputeOp`（通用）
- `MatmulOp`（额外属性：`lowering_hint`, `execution_model`）
- `ReluOp`
- `AddOp`
- `ReduceSumOp`

### 2）在工厂/构造层统一创建

`ChipEnv._append_op` 继续作为唯一“入口点”：
- 内部调用 `ChipOp.from_kind(...)` 或 `ChipOp.from_name(...)` 生成子类实例；
- 旧入口保留兼容签名，默认使用字符串输入；
- 让 `ops.py` 中的 `append_compute_op`/`matmul`/`relu`/`add`/`reduce_sum` 不直接手写字符串，改为提交 typed op。

### 3）降级层按类型分发而非字符串分支

`program_processor.py` 降级流程改为：
- 先按 `chip_op.kind`/`isinstance` 分发，逻辑位置集中；
- 字符串 `chip_op.op == ...` 仅保留 fallback（兼容旧对象）。

建议映射：
- `LoadSRAMTensorOp` -> `_lower_load`
- `StoreSRAMTensorOp` -> `_lower_store`
- `MatmulOp` -> `_lower_compute` + `_add_matmul_logical_routes`
- `ComputeOp / ReluOp / AddOp / ReduceSumOp` -> `_lower_compute`
- `DeclareSRAMTensorOp` 直接跳过（或 no-op）

### 4）先不改 `program_tile.py`（仅兼容）

`program_tile.py` 当前消费的是 `ProcessorLogicalAction`，不直接消费 `ChipOp`。  
只需保证：
- `ProcessorLogicalAction.source_chip_op` 与 `chip_op.id` 关系不变；
- `action.op` 对外仍使用字符串（如 `matmul`, `relu`）；
- 不引入对 `ChipOp` 子类的硬依赖。

### 5）保持计划输出兼容（关键）

`ChipProgram.to_plan()` 及各层测试中 `ops` 的断言依赖：
- `op` 字符串数组（`["declare_sram_tensor", ...]`）；
不能变。  
因此对象化只是内部结构与 builder 接口强化，序列化字段保持不变。

## 实施步骤（建议顺序）

### Phase 0：文档与兼容点冻结（本次）
- 完成本执行计划并确认：
  - `op` 字符串输出不变；
  - plan schema 不增删字段；
  - 所有测试仍以 `to_plan()["op"]` 为准。

### Phase 1：program.py 重构类型层（低风险）
- 新增 `ChipOpKind`、`ChipOp` 子类/`from_*` 工厂；
- 让 `ChipOp.to_plan()` 统一保证 `op` 与旧版一致；
- 增加必要中文注释：何种层可改、何种层不能改。

### Phase 2：构造路径切换
- 更新 `ChipEnv._append_op` 使用工厂；
- `ops.py` 的 `matmul/relu/add/reduce_sum` 走 typed op；
- 保留字符串兼容构造（临时 fallback）。

### Phase 3：lowering 分发迁移
- `program_processor.py` 以 `kind`/`isinstance` 为主分发；
- 降低阶段中的 `chip_op.op == ...` 逐步替换；
- 特例逻辑（如 `matmul` route）改为通过 `isinstance` 或 `kind` 判断。

### Phase 4：清理与加固
- 统一 `__repr__`/`__str__`，便于日志中看出 op 的真实类型；
- 加入“最小单测补充”：校验构造 + 降级分发映射；
- 保留一个向后兼容用例，验证 `chip_program["ops"]` 与已有输出顺序一致。

## 风险与回退

### 主要风险
1. 迁移过程中 `to_plan()` 的字段兼容出现回归；
2. `program_processor` 分发出现重复分支导致行为变化；
3. 第三方/历史脚本依赖 `isinstance`/直接字段。

### 回退策略
- 先留字符串 fallback 分支（`chip_op.kind` 为空时回退到 `chip_op.op`）；
- 每一步仅改一层并跑现有测试（`core` 与 end-to-end）；
- 发现问题可立即回退到上一步提交，且不影响计划产物字段。

## 验收标准

实施完成后应满足：
- 架构上：`ChipOp` 有类型层级，`matmul/relu/add/...` 有明确类；
- 行为上：`generate()` 输出中 `chip_program["ops"][...]["op"]` 与历史行为一模一样；
- 覆盖上：现有 `test_chip_program_frontend.py` 的 op 顺序与关键字段断言通过；
- 可读性上：新增中文注释解释清楚“为什么这一层仍用字符串字段”、何处是层边界。

## 备注

如果你希望，我可以继续把这份计划细化成“逐文件改动清单（含 1:1 行号级别的 patch 顺序）”，方便另一个 agent 直接并行执行。

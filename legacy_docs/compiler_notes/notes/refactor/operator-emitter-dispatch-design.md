# Operator Emitter Dispatch 设计笔记

日期：2026-06-27

这份笔记记录下一步怎么消掉 `softmax_template_program.h` 里第一层
`switch (operation.op_type)`。

## 修正判断

第一版设计把 `op` 本体留成纯数据 record，只在旁边挂
`OperatorEmitter`。这个方案能小步降噪，但确实不彻底。

但这里还要再修正一个更重要的方向：`op` 继承体系不是 OpenFabric 的最高层
IR。真正更高层的对象应该是：

```text
FiberProgram
```

它操作的是：

```text
TileRef
LocalReduceValue
ScratchValue
FiberCompute
FiberCommunication
```

而不是直接操作 vendor 的：

```text
HLDT / HSTT / CAL / IMM / base_addr_idx / csv row
```

所以长期方向应该是：

```text
OpenFabric tensor graph
  -> FiberProgram
  -> vendor op emitter / vendor template
  -> vendor assembler inputs
  -> common_oper/build_app package
```

也就是说：

```text
FiberProgram -> VendorSoftmaxFiberEmitter -> vendor csv
```

而不是：

```text
SoftmaxOp -> FiberProgram
```

更彻底、也更接近 OpenFabric 后端路线的设计应该是：

```text
op 不再只是 vendor record；
op 变成 vendor op emitter 基类；
VendorSoftmaxFiberEmitter / VendorRmsNormFiberEmitter / VendorElementwiseFiberEmitter ... 继承它；
第一层 vendor emit phase 变成虚方法；
后续由 FiberProgram 调度这些 vendor emitter。
```

真正需要避开的不是“继承 `op`”，而是“按值继承”和“假的全局 op 列表”。
如果继续使用 `vector<op>`，派生类放进去会发生 C++ 对象切片，派生类方法和
状态都会丢。如果未来要做 fused multi-op，也不能再回到随手维护一个
`all_ops[now_op]` 的状态，而应该显式引入 `FiberProgram/OpGraph`。

当前 softmax sample 更简单：它只有一个 vendor emitter，所以不需要任何 op
容器。`op` 方法只是 vendor lowering 方法，不是 OpenFabric 高层调度方法。

## 当前问题

之前 `emit_subtask1_compute_phase(...)` / `emit_subtask2_compute_phase(...)`
这种函数还在做：

```cpp
switch (operation.op_type) {
  case OpType::SOFTMAX:
    ...
  case OpType::RMSNORM:
    ...
}
```

这很像 C 风格的手工虚表：

```text
OpType 决定这个 op 应该怎么 emit。
```

在当前 vendor 收容层，我们真正想表达的是：

```text
这个 op 自己知道怎么 emit 当前 phase。
```

但从 OpenFabric 长期视角看，更完整的说法是：

```text
FiberProgram 决定有哪些 tile/fiber 动作；
vendor op emitter 知道这些动作如何落到甲方 CSV 协议。
```

## 旧保守方案的问题

当前 vendor 的 `op` 是一个扁平数据 record：

```cpp
class op {
public:
  string op_owner;
  OpType op_type;
  vector<insts> ld_insts;
  vector<insts> cal_insts;
  vector<insts> st_insts;
  vector<insts> cp_insts;
  vector<string> allInput;
  vector<string> allOutput;
};
```

旧 vendor 代码和早期 refactor 曾大量依赖：

```text
vector<op>
all_ops[now_op]
write_csv(all_ops, ...)
EmitSite::operation() -> op&
```

如果把 `op` 改成虚基类或 `vector<unique_ptr<op>>`，会牵动：

```text
CSV writer
regmap alias
load/store buffers
task_main 构造方式
future vendor compatibility
```

这些牵动是真的，但它们不是不能动的理由。它们只是说明：

```text
不能只给 op 加 virtual；
要么显式升级多 op 图的所有权模型；
要么像当前 softmax sample 一样，为每个输出 CSV 构造一个短命 vendor emitter。
```

也就是说，危险点不是继承本身，而是半截继承。

## 真继承版设计

`op` 基类保留现有公共数据面，同时升级成 vendor emitter 基类：

```cpp
class op {
public:
  virtual ~op() = default;

  string op_owner;
  OpType op_type;

  vector<insts> ld_insts;
  vector<insts> cal_insts;
  vector<insts> st_insts;
  vector<insts> cp_insts;

  map<string, vector<unsigned>> input_name;
  map<string, vector<unsigned>> output_name;
  vector<string> allInput;
  vector<string> allOutput;

  virtual void emit_tile_to_local_reduction_summary(
      EmitSite &site, int instance_num_cal_unit) {}
  virtual void emit_store_reduction_summary_to_scratch(EmitSite &site) {}
  virtual void emit_consume_reduction_summary_to_output_tile(EmitSite &site) {}
  virtual void emit_store_output_tile(EmitSite &site) {}
};
```

派生类表达 vendor softmax 模板的发射行为。为了提醒自己它不是高层 IR，
概念上更应该叫 `VendorSoftmaxFiberEmitter`：

```cpp
class VendorSoftmaxFiberEmitter : public op {
public:
  VendorSoftmaxFiberEmitter() {
    op_owner = "softmax";
    op_type = OpType::SOFTMAX;
    allInput = {"softmax0_input0"};
    allOutput = {"softmax0_output0"};
  }

  void emit_tile_to_local_reduction_summary(
      EmitSite &site, int instance_num_cal_unit) override {
    emit_tile_to_local_reduction_summary<SoftmaxReductionFiberTemplate>(
        site, instance_num_cal_unit);
  }

  void emit_store_reduction_summary_to_scratch(EmitSite &site) override {
    emit_store_reduction_summary_to_scratch<SoftmaxReductionFiberTemplate>(site);
  }

  void emit_consume_reduction_summary_to_output_tile(EmitSite &site) override {
    emit_softmax_subtask2_template(site);
  }

  void emit_store_output_tile(EmitSite &site) override {
    ...
  }
};
```

入口从早期 vendor/初版 refactor 的：

```cpp
vector<op> all_ops;
op softmax;
...
all_ops.push_back(softmax);
```

现在收敛为在每个 PE 模板文件的生成点直接构造：

```cpp
VendorSoftmaxFiberEmitter softmax;
int instruction_count = 0;
```

当前 softmax sample 只有一个 vendor emitter，所以不维护假的 `all_ops`，也不让
同一个 emitter 横跨 task/subtask/PE。一个 emitter 只拥有一个 CSV 文件的临时
指令桶，`write_csv` 之后自然销毁。

调用侧不应该再写成“subtask1/2 compute/store”。当前 vendor subtask 外壳只负责
安排 action 顺序：

```cpp
softmax.emit_tile_to_local_reduction_summary(site, instance_num_cal_unit);
softmax.emit_store_reduction_summary_to_scratch(site);

softmax.emit_consume_reduction_summary_to_output_tile(site);
softmax.emit_store_output_tile(site);
```

这就是当前阶段的彻底版：vendor `op` 自己有 vendor emit 方法。

但它仍然不是最终抽象。最终应该继续演进成：

```cpp
FiberProgram program = plan_softmax(...);
VendorSoftmaxFiberEmitter emitter;
emitter.emit(program, vendor_context);
```

当前试点只是先把 vendor 手写模板收进一个可替换的类边界里。

## 真正吓人的地方

### 1. 对象切片

如果只写：

```cpp
class SoftmaxOp : public op { ... };
vector<op> all_ops;
all_ops.push_back(SoftmaxOp{});
```

那 `SoftmaxOp` 会被切成纯 `op`，虚方法行为消失。这种改法看起来继承了，
实际没有多态。

### 2. 多 op 图的访问面很宽

如果未来要恢复 fused multi-op 图，`EmitSite`、`write_csv`、输入复用判断、外层
task loop 都会接触 op 图。那时不能回到假的 `all_ops` 下标，而应该引入显式的
FiberProgram/OpGraph。早期按值代码是：

```cpp
all_ops[now_op].cal_insts
```

未来应该进一步封装成类似：

```cpp
FiberProgram program;
program.action(i).emit_to(site);
```

这不是概念难，但它已经超出当前单 softmax sample。当前 sample 直接持有：

```cpp
op &operation_ref
```

不再维护 `all_ops`。

### 3. `op` 现在同时扮演三个角色

当前 `op` 同时是：

```text
算子描述：op_type / allInput / allOutput
临时指令桶：ld_insts / cal_insts / st_insts
CSV 输出分组：write_csv 按 op 顺序输出各阶段指令
```

继承之后这些角色还可以先保留在基类里，但我们要知道这是历史债务。
后面更干净的方向是：

```text
VendorOp: vendor 模板发射器
InstructionBuffers: 当前 PE/task/subtask 的临时产物
CsvWriter: vendor 输出协议
```

第一阶段不拆这么深，只先把 phase 方法放进 `op`。

## 推荐第一阶段

第一阶段已经验证的做法是：

```text
1. 给 op 加 virtual fiber action 方法
2. 建 VendorSoftmaxFiberEmitter 继承类
3. 让当前 softmax_refactored 在每个 PE CSV 生成点构造短命 VendorSoftmaxFiberEmitter
4. 把 subtask1/subtask2 外壳里的第一层 switch 换成直接 action 调用
5. 删除假的 all_ops/now_op 维护
6. 跑 build_and_compare，要求二进制完全一致
```

这会比旁路 `OperatorEmitter` 更彻底，也更符合用户说的“optype 的方法”。
为了不一拳打歪，先只给当前可验证的 `VendorSoftmaxFiberEmitter` 落地；其它 vendor 通用
OpType 后面再迁移成派生类。

## 推广原则

这个继承 `op` 的办法可以推广，但推广的单位不能是 vendor subtask。

应该推广的是：

```text
VendorXXXFiberEmitter
```

也就是“某类 FiberProgram action 在甲方工具链上的 lowering 载体”。例如：

```text
VendorSoftmaxFiberEmitter
VendorRmsNormFiberEmitter
VendorElementwiseTileEmitter
VendorRopeTileEmitter
```

调用点应该直接写出 FiberProgram action 的顺序，不要再包一层一行 helper：

```cpp
softmax.emit_tile_to_local_reduction_summary(site, instance_num_cal_unit);
softmax.emit_store_reduction_summary_to_scratch(site);

softmax.emit_consume_reduction_summary_to_output_tile(site);
softmax.emit_store_output_tile(site);
```

这样调用点保留“这段 vendor subtask 实际执行了哪些 fiber actions”的可读性；
具体 action 怎么 lower 成 `HLDT/CAL/HSTT/CSV`，才交给继承类。

## 和 FiberProgram 的长期对齐

这个试点值得做，不是因为继承本身漂亮，而是因为它给未来的 FiberProgram
backend 留出一个位置。

当前：

```text
VendorSoftmaxFiberEmitter::emit_tile_to_local_reduction_summary(site, ...)
  -> 直接吐 vendor 指令
```

下一阶段应该变成：

```text
FiberProgram:
  TileToLocalReductionSummary(input_tile -> local_sum)
  StoreReductionSummaryToScratch(local_sum -> scratch_sum)
  LoadReductionScratch(scratch_sum -> local_sum)
  NormalizeTileWithSummary(input_tile, local_sum -> output_tile)
  StoreOutputTile(output_tile)

VendorSoftmaxFiberEmitter:
  把这些 fiber actions lowering 成 HLDT / CAL / HSTT / CSV
```

这样 fiber 计算和 fiber 通信会在同一张 FiberProgram 平面里出现，vendor op
继承体系只负责把这张平面落到甲方工具链。这个方向避免了再次自顶向下空降一个
大而空的 compiler，同时也避免永远被 vendor 小文件和 switch 牵着走。

## 已废弃备选：旁路 OperatorEmitter

第一版曾考虑保留 `vector<op>`，在旁边挂一张 `OpType -> OperatorEmitter`
方法表。这个方案能小步替换 switch，但它有两个问题：

```text
1. 它没有真正把 vendor 手写模板收进 op 继承边界；
2. 它容易继续使用 subtask1/subtask2 这种 vendor 壳子命名。
```

此前的 binary parity 已经证明直接调用 `VendorSoftmaxFiberEmitter` action 能站住；
当前继续把 emitter 生命周期收缩到单个 PE 模板文件，所以主路线不再采用旁路
方法表，也不维护假的 `all_ops`。

# Typed Vector Operand 设计笔记

日期：2026-06-27

Status: current implementation note.

这份笔记记录 `softmax_refactored` 寄存器/内存抽象的方向和已落地状态。

核心目标不是重新发明一套计算 API，而是让内存读出来的对象自然接入现有的：

```cpp
site.h2fp(...)
site.fmul(...)
site.fadd(...)
site.hmul(...)
site.hadd(...)
```

也就是说，新的向量对象必须长在当前 `Operand` / `EmitSite` 体系上。

## 当前已有底座

现在 `softmax_template_program.h` 里已经有一个很重要的最小 IR：

```cpp
struct Operand {
  enum class Class {
    None,
    Normal,
    Reuse,
  };

  Class operand_class;
  string symbol;
};
```

`EmitSite` 上的计算 helper 都围绕 `Operand` 工作：

```cpp
site.h2fp(dst, src, lane);
site.fmul(dst, src0, src1);
site.fadd(dst, src0, src1);
site.hmul(dst, src0, src1);
```

所以内存抽象不能绕开 `Operand`。正确方向应该是：

```text
typed vector object 是 Operand 的 wrapper，
而不是 Operand 的替代品。
```

## 建议对象模型

可以先定义几个轻量 wrapper：

```cpp
struct VecH256 {
  Operand root;

  operator Operand() const {
    return root;
  }
};

struct VecH64 {
  Operand root;

  operator Operand() const {
    return root;
  }
};

struct VecF32 {
  Operand root;

  operator Operand() const {
    return root;
  }
};
```

它们第一阶段只负责携带类型信息：

```text
VecH256:
  half[256] 逻辑向量

VecH64:
  half[64] 逻辑向量或 scratch slot

VecF32:
  fp32 vector 计算 operand
```

因为 wrapper 可以退化成 `Operand`，所以它们可以直接进入已有 helper：

```cpp
VecH256 x = site.load_h256(...);

Operand fp0 = site.local("fp0");
Operand fp1 = site.local("fp1");

site.h2fp(fp0, x, 0);
site.h2fp(fp1, x, 1);
site.fmul(fp0, fp0, site.reuse_symbol("rLog2E"));
```

这一步的重点是统一：

```text
load 返回带类型的对象；
compute 继续消费 Operand；
wrapper 负责把二者接起来。
```

## 原始实现到底怎么引用 load 出来的数据

原始 CSV 不是用某个隐藏对象引用 load 结果，也不是直接引用物理四段。它靠
同一个 operand symbol 串起来。

典型的 `subtask1/template/0.csv` 是：

```csv
HLDT,HLDT0,,,softmax0_input0_0_0_0,0,0,1
H2FP,H2FP10,softmax0_input0_0_0_0,,FP0_softmax0_input0_0_0_0,,0,0
FMUL,FMUL11,FP0_softmax0_input0_0_0_0,rLog2E,FP0_softmax0_input0_0_0_0,,,1
```

也就是：

```text
HLDT 写入 symbol x；
H2FP 读取同一个 symbol x，并写入 fp0；
FMUL/FMIN/FEXP2/FADD 继续读写 fp0。
```

所以更像下面这个程序模型：

```cpp
VecH256 x = site.load_h256(...);
VecF32 fp0 = site.h2fp(x, 0);

site.fmul(fp0, fp0, site.reuse_symbol("rLog2E"));
site.fmin(fp0, fp0, site.symbol("imm100"));
site.fexp2(fp0, fp0);
```

这里 `load_h256` 做的是：

```text
发出 HLDT；
给这个 HLDT 的 dst 绑定一个 symbol；
返回包着这个 symbol 的 VecH256。
```

后续 `h2fp(x, 0)` 只是引用同一个 symbol。它不需要知道 `HLDT` 在底层被拆成
几条 `LDN`，也不需要直接拿到物理 segment。

## 内存 load/store 应该返回 typed operand

推荐先给 `EmitSite` 增加这种 API：

```cpp
VecH256 load_h256(const TensorTileChunk &chunk);
VecH64  load_h64(const TensorTileChunk &chunk);

void store_h256(const TensorTileChunk &chunk, VecH256 value);
void store_h64(const TensorTileChunk &chunk, VecH64 value);
```

对 softmax 来说，程序可以逐步写成：

```cpp
VecH256 x0 = site.load_h256(X.row(row).chunk256(0));
VecH256 x1 = site.load_h256(X.row(row).chunk256(1));

Operand fp0 = site.local("fp0");
Operand fp1 = site.local("fp1");

site.h2fp(fp0, x0, 0);
site.h2fp(fp1, x0, 1);
```

lowering 到 vendor CSV 时，`load_h256` 仍然只是生成当前已经存在的：

```text
HLDT dst=<x0.symbol>, base_addr_idx=<X slot>, imm=<tile chunk imm>
```

也就是它不会绕开 vendor assembler 输入协议。

## 为什么不能直接把物理四段暴露出来

当前 softmax 的一个 256-half chunk，在 vendor 低层会进一步落到 4 个 64-half
segment。这个事实很重要，但不应该在算法层直接写成：

```cpp
auto x0_0 = load(...);
auto x0_1 = load(...);
auto x0_2 = load(...);
auto x0_3 = load(...);
```

原因有几个。

第一，当前计算 helper 并不是按四个物理段来消费输入。

例如 softmax 里常见的模式是：

```cpp
site.h2fp(fp0, x, 0);
site.h2fp(fp1, x, 1);
```

这里的 `x` 是一个逻辑 half operand。`h2fp` 的第三个参数选择的是 half lane /
转换模式，不等价于直接访问第 0 个或第 1 个物理 64-half segment。

第二，物理四段来自 vendor pseudo op expansion。

CSV 里写的是一条：

```text
HLDT x, ..., imm
```

`common_oper` 会把它展开成多条底层 `LDN`，并按硬件 operand RAM 布局处理。
这说明四段是 lowering 细节，不是算子语义本身。

第三，operand symbol 到 operand RAM index 还有一次 vendor 分配。

CSV 里的 `dst_reg_idx` 其实是 symbol，例如：

```text
softmax0_input0_0_0_0
sum_tmp_0_0_0
```

后面 `common_oper` / `inst_blk_map` 会把 symbol 映射到 PE-local operand index。
如果我们在高层直接手写物理四段，就会把这个分配策略提前泄漏到 OpenFabric。

第四，物理布局可能不是稳定语义。

现在看到的是：

```text
OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE = 4
OPERANDS_PER_OPERAND_RAM = 128
```

但这些是硬件配置和 vendor lowering 的结果。OpenFabric 更应该稳定表达：

```text
读 X[row, col:col+256] 到一个 half[256] 逻辑寄存器。
```

至于它在当前硬件上是不是拆成 4 段，是 backend projection 的事。

## 可以暴露 segment view，但要放在低层

物理 segment 不是不能表达，而是不能变成默认算法模型。

比较合理的做法是：

```cpp
VecH256 x = site.load_h256(...);

Operand seg0 = x.segment(0);
Operand seg1 = x.segment(1);
Operand seg2 = x.segment(2);
Operand seg3 = x.segment(3);
```

但 `segment(i)` 应该被定义成低层 view：

```text
用于 vendor lowering、调试、特殊 bank/operand 控制。
不用于普通 softmax/GEMM 算法描述。
```

也不要让 `operator[]` 默认表示单个 element。这里很危险：

```cpp
x[0]
```

它到底表示第 0 个 half element，还是第 0 个 64-half segment？两者差得很远。

如果未来要重载，建议写得很明确：

```cpp
x.segment(0)   // 第 0 个物理/布局 segment
x.lane(0)      // 某种指令语义 lane
x.element(i)   // 单个逻辑 element，暂时不实现
```

## 为什么现在还不能直接套 operator overload

可以做 operator overload，但不应该第一步就做。

原因是当前 emitter 是有副作用的：

```text
每次 fmul/fadd/h2fp 都会追加一条 CSV 指令；
同时还要分配临时 operand；
还要保持指令顺序；
还要维护 reuse operand 和 normal operand 的区别。
```

如果一上来写：

```cpp
auto y = exp2(min(x * rLog2E, imm100));
```

就需要立刻解决：

```text
临时变量什么时候创建？
表达式什么时候 emit？
同一个表达式被引用两次时是否重复 emit？
normal / reuse operand 怎么推断？
指令顺序和现有 count 如何保持？
```

所以更稳的推进顺序是：

```text
1. 先做 typed wrapper：VecH256 / VecH64 / VecF32。
2. 再做 typed load/store，让内存读写返回 wrapper。
3. 给 h2fp/fmul/fadd 等 helper 加 overload 或 unwrap。
4. 等这个稳定后，再考虑 operator overload / expression template。
```

## 推荐的第一阶段落地形态

第一阶段只追求一个小闭环：

```cpp
VecH256 x = site.load_input_h256(input_idx, chunk_idx);

Operand fp0 = site.fp_input(input_name, 0, chunk_idx);
Operand fp1 = site.fp_input(input_name, 1, chunk_idx);

site.h2fp(fp0, x, 0);
site.h2fp(fp1, x, 1);
site.fmul(fp0, fp0, site.reuse_symbol("rLog2E"));
site.fmul(fp1, fp1, site.reuse_symbol("rLog2E"));
```

这个形态有几个好处：

```text
仍然生成原来的 CSV；
仍然复用现有 Operand / EmitSite；
把 memory tile/chunk 语义显式提上来；
不把 vendor 物理四段提前暴露到算法层；
给后续 operator overload 留出口。
```

这就是现在最适合 `softmax_refactored` 的路线：

```text
内存对象有 shape；
计算对象仍然是 Operand；
物理 segment 是 backend/lowering view。
```

## 第一阶段实现状态

当前已经在 `softmax_template_program.h` 里落了一个最小闭环：

```cpp
struct VecH256;
struct VecH64;
struct VecF32;

VecH256 EmitSite::load_input_h256(int input_idx, int chunk_idx);
VecH256 EmitSite::input_h256(...);
VecF32  EmitSite::fp_input_vec(...);
VecF32  EmitSite::h2fp(const VecF32 &dst, const VecH256 &src, int fp32_lane);
```

softmax 的 input load 现在先走：

```cpp
site.load_input_h256(input_idx, inst_num);
```

softmax 的 exp2 pair 现在先走：

```cpp
const VecH256 in = site.input_h256(input_base, inst_num);
const VecF32 fp = site.h2fp(site.fp_input_vec(input_base, fp32, inst_num), in, fp32);
```

这一步没有改变生成的 vendor CSV 语义。验证命令是：

```bash
cmake --build build --target refactored_replay_compare_softmax
```

验证结果：

```text
All compared binaries match the freshly rebuilt vendor baseline.
```

## 读内存 helper 推广状态

在第一阶段闭环之后，业务层的 `HLDT` / `ILDMT` 读内存动作已经继续收进
`EmitSite`：

```cpp
VecH256 EmitSite::load_hldt_h256(const Operand &dst,
                                 int reg_offset,
                                 int imm_offset,
                                 const string &array_name);

VecH64 EmitSite::load_ildmt_h64(const Operand &dst,
                                int reg_offset,
                                int imm_offset,
                                const string &array_name);

VecH64 EmitSite::load_sum_slot_h64(int slot, int imm_stride);
```

现在业务模板里不再直接散落：

```cpp
emit_hldt(...)
emit_ildmt(...)
```

这些底层 emitter 只保留在 `EmitSite` helper 内部和底层定义处。

这一步把 softmax 的 input load、softmax/rmsnorm 的 SUM slot load，以及
RMSNORM/ROPE/SCALE/通用 input load 形式都统一到：

```text
选择一个 operand symbol；
通过 EmitSite 发出内存读；
返回 typed wrapper 或继续使用同一个 Operand。
```

验证命令仍然是：

```bash
cmake --build build --target refactored_replay_compare_softmax
```

验证结果：

```text
All compared binaries match the freshly rebuilt vendor baseline.
```

注意：当前二进制等价验证覆盖的是 `softmax_refactored` 活基线。RMSNORM/ROPE/SCALE
分支已经被 C++ 编译解析覆盖，但还没有对应的 runnable baseline parity 检查。

## store 侧模型

`HSTT` 是 `HLDT` 的 store 对偶，但 CSV 字段名有点误导：

```csv
HSTT,HSTT18,,,softmax0_input0_0_0_0,0,0,2
```

这一行里的 `dst_reg_idx` 字段，在 store 场景下不是“目的寄存器”，而是：

```text
要从 PE-local operand RAM 存出去的源 operand symbol。
```

所以更接近下面这个寄存器语言：

```cpp
VecH256 x = site.input_h256(0, chunk_idx);
site.store_output_h256(x, 0, chunk_idx);
```

当前 subtask2 store 已经先整理成：

```cpp
void EmitSite::store_hstt_operand(const Operand &src,
                                  int reg_offset,
                                  int imm_offset,
                                  const string &array_name);

void EmitSite::store_hstt_h256(const VecH256 &src,
                               int reg_offset,
                               int imm_offset,
                               const string &array_name);

void EmitSite::store_output_h256(const VecH256 &src,
                                 int output_idx,
                                 int chunk_idx);
```

`emit_subtask2_final_store_template` 也已经被吸收到调用者
`emit_subtask2_store_phase` 里。这样 store phase 直接表达：

```text
当前 subtask2 最终要把哪个寄存器对象写回哪个 output tile chunk。
```

验证命令仍然是：

```bash
cmake --build build --target refactored_replay_compare_softmax
```

验证结果：

```text
All compared binaries match the freshly rebuilt vendor baseline.
```

subtask1 的 store 也已经继续收进同一层抽象：

```cpp
VecH256 y = site.output_h256(0);
site.store_hstt_h256(y, 0, imm, operation.allOutput[0]);

site.store_sum_operand(site.sum(), stride);
```

`emit_subtask1_final_store_template` 已经被吸收到
`emit_subtask1_store_phase` 里。现在业务层不再直接调用裸 `emit_hstt`；
裸 `emit_hstt` 只留在 `EmitSite` helper 内部和底层定义处。

这里保留了一个单独的 `store_sum_operand`，因为 `SUM` 是 subtask1 的
scratch/storeable operand，不应该为了形式统一而伪装成普通 output
`VecH256`。这件事很关键：抽象要表达真实语义，而不是把 vendor 的坏命名换一层
新的坏命名。

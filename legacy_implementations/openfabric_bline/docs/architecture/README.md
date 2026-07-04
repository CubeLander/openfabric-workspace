# Architecture 总览

这一页是 `docs/architecture/` 的架构总入口。

它负责把所有 shared 知识先收成一条线，再分流到 `compiler` 和 `runtime` 两条主线里。
这里写的不是某个模块的实现细节，而是这套 SoC 从存储到 PE 的宏观结构。

## SoC 宏观链路

可以先把整个系统理解成下面这条路径：

```text
RISC-V control program
  -> MMIO / DMA
  -> DRAM image
  -> CBUF / MICC / SPM
  -> task / subtask / instance
  -> GRAPH_NODE / exeBlock
  -> PE mesh
  -> PE-local operand RAM + instruction memory
  -> LD / CAL / FLOW / ST execution
```

这条链路里，最重要的边界有三层：

1. **控制边界**: RISC-V 程序负责装载、启动、等待和回收。
2. **任务边界**: MICC / runtime 负责 task、subtask、instance 的推进。
3. **PE 边界**: 每个 PE 执行自己的本地 instruction stream 和 operand RAM 操作。

## 知识分组

当前架构知识按 6 个主题组织：

| 主题 | 关注什么 | 入口 |
|---|---|---|
| [SoC 系统架构](soc-system/README.md) | DRAM / CBUF / MICC / SPM / operand RAM / DMA | [存储层次总览](soc-system/storage-hierarchy-overview.md) |
| [PE 微架构](pe-microarchitecture/README.md) | PE mesh 拓扑、寄存器、operand 布局、执行模型、SIMD lane | [PE Mesh 与任务模型](pe-microarchitecture/pe-mesh-and-task-model.md) |
| [运行时执行模型](runtime-model/README.md) | task / subtask / instance 生命周期、Vendor ABI | [Task/Subtask 模型](runtime-model/task-subtask-instance-runtime-model.md) |
| [指令编码](instruction-encoding/README.md) | 指令集还原、inst_t / RTL packing、物理映射、容量 | [ISA 执行模型](instruction-encoding/isa-execution-model.md) |
| [GEMM 案例](gemm-case-study/README.md) | GEMM dataflow、operand strip、tile DAG、HMMAL 绑定 | [Task0 Dataflow](gemm-case-study/gemm-template-fusion-task0-dataflow.md) |
| [指令集原始材料](instruction-set/README.md) | 从甲方 Office 文档抽取的 SIMD / Tensor 指令语义 | [SIMD 指令集](instruction-set/dfu3500-simd/README.md) |

## 先读什么

如果你想先建立大图景，建议顺序是：

1. [RISC-V 控制程序与 DpuAPI](../vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md)
2. [存储层次总览](soc-system/storage-hierarchy-overview.md)
3. [CBUF/MICC 配置通道](soc-system/cbuf-micc-config-channel.md)
4. [SPM 与 operand RAM 数据通路](soc-system/data-pathway.md)
5. [PE Mesh 与任务模型](pe-microarchitecture/pe-mesh-and-task-model.md)
6. [PE 寄存器架构与 operand 布局](pe-microarchitecture/pe-register-architecture.md)
7. [PE 微架构执行模型](pe-microarchitecture/pe-microarchitecture-execution-model.md)
8. [SIMD Lane 解释模型](pe-microarchitecture/simd-lane-interpretation.md)
9. [Task/Subtask Instance 运行时模型](runtime-model/task-subtask-instance-runtime-model.md)
10. [ISA 执行模型](instruction-encoding/isa-execution-model.md)
11. [Instruction Format 与 RTL Packing](instruction-encoding/instruction-format-and-rtl-packing.md)
12. [GEMM Template Fusion Task0 Dataflow](gemm-case-study/gemm-template-fusion-task0-dataflow.md)
13. [指令集原始材料](instruction-set/README.md)

## 这页怎么继续长大

- 如果某个主题已经稳定成单一真相，就把它下钻成独立 README。
- 如果某个主题在 compiler 和 runtime 之间共享，就先留在这里。
- 如果内容开始同时讲"硬件事实"和"编译器写法"，就说明该拆页了。

这页的目标不是一次写完，而是把整个架构知识的总入口先立住。

# Case Authoring：算子 case 编写与生成方式

这里记录甲方原始 case 是怎么写出来、哪些文件手写、哪些文件由脚本生成。

## 文档

- [operator-case-development.md](operator-case-development.md)：operator case 开发方式。
- [manual-vs-generated.md](manual-vs-generated.md)：手写文件与生成文件边界。
- [handwritten-operator-contract.md](handwritten-operator-contract.md)：甲方手写算子职责清单，以及 OpenFabric 应该自动化的工作边界。
- [elementwise-template-frontend-chain.md](elementwise-template-frontend-chain.md)：elementwise template 前端链路。

## 边界

这里关注 case authoring，不负责解释最终 runtime 字段布局。字段和二进制结构请看
[common_oper](../common_oper/README.md) 与 [runtime/data](../../runtime/data/README.md)。

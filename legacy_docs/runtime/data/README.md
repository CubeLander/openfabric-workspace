# 运行时数据面（Data）

这一层只讲一件事：runtime 相关的二进制和消息，字节级别到底长什么样。

我们把它拆成五页：

- [CBUF 数据面](cbuf.md)：`insts`、`exeblock`、`instance`
- [RTL 编码层](rtl.md)：`inst_t` 的窄格式打包规则
- [MICC 数据面](micc.md)：`task`、`subtask`
- [消息层（Messages）](messages.md)：runtime / mesh / RTL 消息体
- [辅助兼容产物](auxiliary-artifacts.md)：`data_inst_replace.bin`、`instEnable.bin`、`taskEnable.bin`

## 先读顺序

1. 先看 [CBUF 数据面](cbuf.md)，因为它包含 `insts`、`exeblock`、`instance`。
2. 再看 [RTL 编码层](rtl.md)，如果你想确认宽指令是怎么被打成窄格式的。
3. 然后看 [MICC 数据面](micc.md)，因为它包含 `task`、`subtask`。
4. 最后看 [消息层](messages.md)，因为它讲的是 runtime 运行时传递的控制包。
5. 如果你看到 `data_inst_replace.bin` / enable 文件，再看 [辅助兼容产物](auxiliary-artifacts.md)，确认它们不是主线 runtime 数据面。

## 每页负责什么

- `cbuf.md` 负责静态执行体和 PE 级控制体：`inst_t`、`exeBlock_conf_info_t`、`instance_conf_info_t`，以及 `inst_t -> RTL` 的值级编码
- `rtl.md` 负责 `inst_t` 的窄格式结构、位域拆分与 opcode family 重打包
- `micc.md` 负责任务图控制体：`task_conf_info_t`、`sub_task_conf_info_t`
- `messages.md` 负责运行时通信体：`router_msg_t` 及其派生消息、`exe_block_ctrl_t`、RTL 紧凑表
- `auxiliary-artifacts.md` 负责辅助兼容 sidecar：writer、packaging / staging 边界，以及不参与 CBUF/MICC size/hash/runtime readiness 的规则

## 一张总图

```text
离线生成
  -> insts_file.bin
  -> exeblock_conf_info_file.bin
  -> instance_conf_info_file.bin
  -> tasks_conf_info_file.bin
  -> subtasks_conf_info_file.bin
  -> cbuf_file.bin / micc_file.bin
  -> runtime / DMA / MICC / PE 消费

旁路兼容产物
  -> optional data_inst_replace.bin compatibility sidecar
  -> RTL/debug enable files
  -> 不参与 cbuf/micc size/hash/runtime readiness
```

## 当前主线里的固定布局

```text
cbuf_file.bin = insts + exeblock + instance
micc_file.bin = tasks + subtasks
```

如果你要查某个字段的偏移、某个文件的大小、或者消息体的字节骨架，就直接下钻到对应页面。

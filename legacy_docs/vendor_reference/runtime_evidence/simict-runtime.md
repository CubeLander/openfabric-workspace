# SimICT runtime 和模拟器执行

## runtime 是什么

`core/bin/runtime` 是 SimICT 框架的主机侧运行时。它是 x86-64 ELF 可执行文件，不是 Scheme 脚本，也不是 DPU app 编译产物。

已知信息：

```text
ELF64 x86-64 executable
dynamically linked
not fully stripped
depends on pthread/readline/ncurses/dl/libc/tinfo
```

它的源码不在当前仓库中。`Makefile.am` 和 ELF 字符串显示它原本来自类似：

```text
/home/liyi/simict/core/runtime
```

当前应把它视为闭源边界。

## 启动命令

顶层测试脚本最终执行：

```sh
../../core/bin/runtime ./ top.so topPara.so common/src/libcommon.so
```

命令含义：

```text
argv[1] = run/search path
argv[2] = runtime config shared object, here top.so
argv[3...] = extra shared objects, here topPara.so and libcommon.so
```

`runtime_verbose` 是 verbose 版本；debug 模式会用 gdb 包一层。

## top.so 是什么

`top.so` 不是普通算子库。它是 SimICT 的 runtime config / module graph shared object。

它描述：

- 有多少 module；
- 有多少 object；
- 有多少 thread；
- object 如何分配给 thread；
- port 如何连接；
- 每个 object 的 latency / downstream / upstream 信息；
- 每个 module 对应哪个 shared object；
- runtime 应该如何创建对象和路由消息。

这个 `.so` 的生成和 `gpdpu/core/bin/gen-runtime-info`、`module-info-control-new.ss` 这套 Scheme 工具有关系。

## Scheme 工具链

`gpdpu/core/bin/env.sh` 显示该 SimICT 工具链建立在 Petite Chez Scheme v8.4 上。

相关脚本：

```text
gen-runtime-info
run-module
module-info-control-new.ss
gen-user-parameters-so
gen-main-c-code
gen-module-c-code
```

`gen-runtime-info` 的关键逻辑：

```text
petite/Scheme module-info-control-new.ss gen-runtime-conf-c-code ...
gcc -fPIC -shared -o <conf>.so <conf>.so.c
```

也就是说，Scheme 脚本生成 C 代码和 objects metadata，然后 gcc 编译成 runtime config `.so`。

## runtime 加载协议

通过 `runtime` 的符号表、字符串和部分反汇编，可以确认它大致做：

```text
main()
  -> open_so(top.so)
  -> dlsym runtime config symbols
  -> open extra user/support .so files
  -> open module .so files
  -> dlsym module callbacks
  -> build g_runtime_info
  -> create pthread simulation threads
  -> enter readline command loop
  -> join simulation threads
```

它会寻找模块导出的这些符号：

```text
simict_create_object
simict_start_object
simict_end_object
simict_port_msg_proc
simict_port_cmd_proc
cmd_list
cmd_list_size
```

这和 `simict.h` 中定义的 ABI 对得上。

## 模块如何运行

每个模拟模块以 C/C++ shared object 的形式存在。runtime 加载后，会调用：

```text
simict_create_object(object_id)
simict_start_object(object_id, usr_data)
simict_port_msg_proc(usr_data, port_id, data, data_bytes)
simict_end_object(object_id, usr_data)
```

模块需要向下游发消息时，调用 runtime 导出的：

```c
simict_write_port(port_id, delay, data, data_bytes);
```

这不是直接调用下游函数。runtime 会根据 `port_info` 找到连接关系，把消息放入 timed message queue。

## thread_main 调度循环

ELF 外围信息显示 runtime 内部有：

```text
thread_main
thread_msg_queue_send
thread_msg_queue_receive
safe_time_info_*
rb_insert_color / rb_erase / rb_next
```

可推断每个 simulation thread 大致做：

```text
1. 初始化 thread command mode
2. 调用本线程 object 的 start callback
3. 接收 upstream thread message
4. 更新 safe time
5. 从 active object / timed message 队列选可执行消息
6. 调 module 的 port_msg callback
7. 通过 simict_write_port 产生下游 delayed message
8. 重复直到仿真结束
```

`safe_time_info` 的存在说明它不是简单事件队列，而是多线程离散事件仿真，需要判断每个 object/thread 到什么时间点是安全可推进的。

## command mode

runtime 链接了 readline/ncurses，字符串里能看到：

```text
SimICT >
continue
quit
help
No such command for SimICT
```

所以 runtime 带交互式命令模式。它还能通过 signal 让 simulation thread 尝试进入 command mode。

## 和 DPU 仿真的关系

DPU 模拟器应该由多个 SimICT module 构成，例如：

```text
RISC-V / ARM control core
DMA
MICC
CBUF
SPM
PE
router / memory
```

RISC-V control program 写寄存器后，相关 device module 会在 SimICT 图中发消息，最终驱动 MICC/PE/SPM/DMA 模块执行由 app build 生成的 packed binary。

## 结论

对算子开发和工具链理解来说，我们不必拿到 runtime 的完整源码。关键 ABI 已经清楚：

```text
top.so 描述对象图
module .so 实现回调
runtime 负责创建对象、调度线程、路由 timed messages
simict_write_port 是模块间通信出口
```

## 对本地 mock runtime 的含义

本地 mock runtime 不需要第一版复刻完整 SimICT：

```text
不用加载 top.so
不用创建 object/port/thread graph
不用实现 timed message scheduler
不用实现 readline command mode
```

第一阶段真正需要替代的是闭源 runtime 对算子 examples 暴露出来的 DPU 行为：

```text
读取 config/result/*
读取 config/input_data.bin
建立 DDR/SPM 内存
模拟 DMA 搬运
加载或解释 CBUF/MICC/instance/task/subtask/exeBlock/inst
执行 PE 指令子集
输出结果和 trace
```

因此推荐实现顺序是：

```text
host 侧 functional mock executor
  -> runtime 兼容 CLI/wrapper
  -> packed binary 入口
  -> 可选 QEMU RISC-V 控制面
```

这样可以先解决算子开发的本地反馈问题，再逐步逼近真实 runtime / hardware 的控制面和时序行为。

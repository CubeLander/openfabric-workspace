# softmax_1 case 拆解

## 入口

case 目录：

```text
testcase/application/CASE/softmax_1
```

case 自己的入口脚本：

```sh
./run.sh
```

内容很短：

```sh
./clean.sh

cd csv_generate/
./run.sh
cd -

cd riscv/
make
cd -
```

也就是说，softmax case 本身只做两件事：

1. 生成/打包 CSV 和 app 数据；
2. 编译 RISC-V 控制程序。

真正启动模拟器是在更外层的：

```text
test/run_app_riscv.sh
```

## case 配置

主要配置：

```text
csv_generate/conf.h
csv_generate/conf_PEmap.h
```

这些文件定义 softmax case 的 shape、任务拆分、DMA 计划、SPM/DDR 布局和 case name。

当前判断它们是手工维护的 case contract。没有找到实际自动生成它们的脚本。

## 第一段：csv_generate/run.sh

该脚本做：

```text
1. 清理旧 app_build 和 bin
2. 编译 test_app_conf_generate.c
3. 执行 app_build
4. 合并 instance_conf_info_file*.bin
5. 进入 gpdpu_TestOp 生成 CSV
6. 对每个 task/subtask 执行 build_so/run.sh
7. 复制 gpdpu_TestOp/task* 到外层 task*
8. 执行 spm_data/run.sh
```

其中：

```text
test_app_conf_generate.c
```

消费 `conf.h`，生成 app/task/subtask 级配置。它不是 softmax 算子算法本身。

## 第二段：gpdpu_TestOp/run.sh

该脚本做：

```sh
make clean
rm task*/subtask*/template/*.csv
make -j
./app_build
```

`app_build` 来自：

```text
gpdpu_TestOp/task_main.cpp
gpdpu_TestOp/task*/subtask*/template/*.cpp
```

CSV 会被重新生成到：

```text
gpdpu_TestOp/task*/subtask*/template/*.csv
```

如果开发者改 softmax 的后端算法，最应该看的就是这些 template `.cpp`。

## softmax 的当前实现形态

当前 softmax 不是一个单独高层函数。它被拆成多个 task/subtask，每个 subtask template 针对 PE 生成 CSV。

大概形态是：

```text
task0/subtask1/template/task0_subtask1.cpp
task0/subtask2/template/task0_subtask2.cpp
...
task3/subtask*/template/*.cpp
```

每个 template 会按 PE id 写：

```c
sprintf(csvpath, "task%d/subtask%d/template/%d.csv", task_id, subtask_id, pe_id);
```

这说明最终 CSV 是 per-PE 的。

## 第三段：build_so/run.sh

`csv_generate/run.sh` 会遍历：

```text
task0/subtask1/build_so
task0/subtask2/build_so
...
task3/subtask2/build_so
```

执行每个目录下的 `run.sh`。

这些 build_so 目录会把 `template/*.csv` 和 `test_graph_extend.cpp` 等胶水代码编译/打包，调用 `common_oper` 生成：

```text
simulator_bin/*
rtl_bin/*
```

## 第四段：spm_data

`spm_data/run.sh` 生成输入数据、SPM 数据、检查数据。RISC-V 程序和最终 check 都依赖这里的文件。

顶层测试完成后会把 `gpdpu_data` 复制回：

```text
testcase/application/${app_name}/spm_data
```

然后运行：

```sh
spm_data/check.sh
```

## 第五段：RISC-V 控制程序

`riscv/makefile` 编译：

```text
riscv/testarm.c
dpuapi/DpuAPI.c
```

生成：

```text
riscv/riscv
```

这个程序会：

- 加载 CBUF；
- 加载 MICC；
- DMA input；
- 启动 kernel；
- 等待完成；
- DMA output；
- app finish。

## 第六段：外层 run_app_riscv.sh

最终从项目 test 目录启动时：

```text
test/run_app_riscv.sh
```

会做：

```text
1. cd testcase/application/${app_name}
2. ./run.sh
3. cd testcase/application/build_app
4. ./run_mtr.sh ${app_name} ${Duplicate_Application_Amount} ${app_num}
5. rm -rf stat log rtl_trace sim_trace config
6. cp result ./config -r
7. cp input_data.bin ./config
8. cp riscv/riscv ./config/riscv_program
9. runtime ./ top.so topPara.so common/src/libcommon.so
10. 收集 stat/trace/gpdpu_data/check.log
```

## 调试建议

如果 softmax 结果不对，可以按层定位：

1. 检查 `conf.h` / `conf_PEmap.h`：shape、task 数、SPM/DDR base 是否一致。
2. 检查生成的 `template/*.csv`：每个 PE 的 load/compute/store 是否符合预期。
3. 检查 `build_so` 输出：`simulator_bin/*` 是否生成完整。
4. 检查 `riscv/testarm.c`：DMA 方向、长度、buf id、instance base 是否正确。
5. 检查 `run.log` / `sim_trace` / `rtl_trace`。
6. 检查 `spm_data/check.log` 和 `gpdpu_data`。


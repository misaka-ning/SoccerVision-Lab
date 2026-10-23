# TensorRT 模型性能测试

仅使用已有 `.engine`，不构建、不转换模型、不修改部署配置、不调整功耗/时钟、不停止其他机器人程序。主控不加载 CUDA；每次只有一个模型工作进程，确认该进程组退出后才启动下一个。默认使用安装目录中的 E01_baseline.engine、E02_c3k2.engine。

## 使用

在机器人项目根目录执行：

```bash
# 编辑模型路径和公共测试参数
nano tool/model_benchmark/config.yaml

# 校验配置及实际 Engine 输入/输出；会逐个短暂创建 GPU context
bash tool/model_benchmark/run.sh --check

# 按配置完整运行
bash tool/model_benchmark/run.sh

# 短时功能验证（不能替代充分预热、多轮的正式比较）
bash tool/model_benchmark/run.sh --mode both --rounds 1 --duration 5 --warmup 5

# 单独测试 GPU 执行 / 完整系统
bash tool/model_benchmark/run.sh --mode engine
bash tool/model_benchmark/run.sh --mode system

# 指定另一份配置，路径相对该 YAML
bash tool/model_benchmark/run.sh --config /absolute/path/config.yaml
```

单模型：`models` 只保留一项，`baseline` 改为该名称或删掉。多模型：增加 `name/path` 条目。模型名使用英文、数字、下划线或连字符。`both` 先完成所有 Engine 轮次，再完成所有系统轮次；每种模式内按 E1→E2→E1→E2 顺序执行。每次加载后均重新预热。失败/超时会停止后续测试，已有记录保留。

## 输入尺寸、精度与可比性

固定形状用 `input_shape: auto`，从 TensorRT binding 读取尺寸；不需要手填 640。动态 Engine 必须填写实际 `[N,C,H,W]`，使用 profile 0 并检查 min/max 范围。当前支持一个 NCHW、3 通道、FP16/FP32 GPU 图像输入，输出需能在执行前确定尺寸。系统模式要求 batch=2，并需要现有 Ultralytics 能加载的 YOLO 检测 Engine 元数据；原始无元数据 Engine 可用于 engine 模式。系统预处理固定为读取的 H/W、rect=false，运行后核对实际形状。

多模型比较会核对实际输入/输出形状、I/O dtype、已知 half/int8/nms/end2end/task/class 元数据；不一致直接报错，可分别做单模型测试。I/O 为 FP32 并不意味着内部层全部 FP32：这台机器的两份 Engine 导出元数据 half=true，但图像与输出 binding 为 FP32。内部层精度不能仅靠这些信息完全证明，请自行保持构建配置一致，原始 metadata 会保存。

## 指标定义

- `engine_ms`：CUDA events 围住 TensorRT 异步执行；输入和输出预先驻留 GPU，同种子生成输入，单位 ms/batch。排除模型加载、内存分配、H2D/D2H、图像预处理和后处理。不是每张图的耗时，也不代表系统 Hz。
- `execute_wall_ms`：主机发起执行到等待该次 GPU 完成的时间，包含调用/同步开销。测试逐次同步，不测多请求流水线吞吐。
- `detector_ms`：生产检测器调用，包括预处理、推理、后处理和候选结果转 CPU，不含后续双目候选匹配。
- `pipeline_ms`：相机读取→检测→双目匹配/定位→跟踪。
- `read_ready_to_publish_ms`：左右图读取并转 BGR 完成→本轮 ROS 发布调用全部返回；含调度等待，不含相机曝光/缓存和 DDS 下游接收。
- `read_start_to_publish_ms`：开始调用相机读取→ROS 发布返回，包含 grab 等待；也不是可靠的曝光时刻到发布延迟。
- `processing_hz`：完成新帧数/完整循环的总耗时，包含 ROS、Viser、调度等待以及正常测量记录开销。
- `publish_hz`：(发布次数-1)/(最后与首次发布的时间差)，不把同一结果的多个 ROS topic 当作多帧。
- `visualization_ms`：ROS 发布后的 Viser 更新耗时。浏览器渲染完成不在测量范围内。

系统复用安装包原有 `run_ros_node()` 循环，仅在测试进程内包装方法采集计时；生产源文件、安装副本和生产 launch 均不修改。没有额外在系统模式强制 CUDA 同步，因此系统吞吐保留生产行为。

当前无法得到验证过的 ZED 曝光时间对应关系，报告明确使用“读取完成到发布”而不称其为完整图像采集延迟。原始每帧时间戳保存为单调时钟值。

## 配置说明

- `test.rounds`：每个模型每种模式的轮数。
- `test.warmup_iterations`：每轮排除的预热 batch/系统帧数，必须大于 0。开始计时前完成全部预热。
- `test.duration_seconds`：每轮正式测量时长；完成当前帧后结束。
- `system.publish_rate_hz: 50`：保留 50 Hz 调度上限。两个模型都达到上限时，不应得出“无加速”的结论。填 `null` 取消主动等待，单独测最大处理能力；两种设置的结果分开比较。
- `system.viser_enabled` / `point_cloud_enabled`：统一 Viser 及点云状态；点云还受部署 `zed_depth_mode` 控制。浏览器是否连接、客户端数量和场景需保持一致。
- `system.ros_domain_id: 87`：独立测试 ROS 域。测试域内可启动订阅观察；不要设为机器人控制链路的域，除非确实希望控制端消费测试输出。
- `system.parameter_overrides`：其他现有 BackendConfig 参数，例如 det_conf、yolo_top_k、zed_fps；不能覆盖模型路径、输入尺寸、device、half 等工具管理的字段。
- `monitor.*`：进度刷新、无进展警告、无进展超时、启动超时、退出宽限时长，单位秒。
- `output.save_frame_records: false`：完整成功结束并生成报告后删除逐帧 CSV，仅保留统计；失败/中断仍保留原始数据。默认 true。

工具沿用 `deployment/common.sh` 的解释器和 ROS 安装包路径。实际路径、最终部署参数、软件版本、Engine 哈希及元数据均保存在结果目录。若安装代码/YAML与源码不同，以报告记录的安装版本为准。

功耗、频率、温度及背景进程记录用于判断实验条件，不自动锁频或停进程。`nvpmodel`/`jetson_clocks --show` 无权限时保存错误原因；不能把未能读出的状态视为已固定。实时相机场景不能逐帧完全重现，建议固定场景并交错多轮。

## 进度、退出和结果

终端显示模型、模式、轮次、PID、阶段、完成次数、无新完成时长、运行均值以及系统 Hz。每隔配置的秒数刷新；进程活着但帧数不增加会警告并超时。详细第三方库日志写入各轮 `worker.log`，需要时另开终端 `tail -f` 查看。

Ctrl+C 会尝试结束当前进程、保存已有 CSV 和报告；超过退出宽限则只终止工具自身的进程组。父进程异常退出保护与同用户机器级锁可避免工具残留进程和误开第二份测试。不要手工删除正在使用的锁文件。重启/断电不能保证汇总完整，但已经刷盘的 CSV 和日志保留，可检查各轮 `controller_result.json` 是否有 complete；旧结果不会自动混入新测试。

结果位于 `results/日期时间_PID/`：

- `report.md`：均值、P95、系统 Hz及相对基线变化。
- `summary.csv` / `summary.json`：汇总、逐轮状态和统计；P95基于原始样本计算。
- `config_resolved.yaml`、`environment.json`、`engines.json`：测试条件与身份。
- `progress.log`：终端进度。
- 每轮目录中的 `frames.csv`、`worker.log`、`progress.json`、`telemetry.jsonl`、`controller_result.json`。

只有完整成功轮次进入汇总；双方均完成计划轮数才计算变化率。跨轮 Hz 按各轮有效时长汇总，不把模型退出/重载间隔计入。正式结论应看逐轮稳定性，短时功能验证不作为加速结论。

## 维护验证

```bash
source deployment/common.sh
soccer_load_runtime yes
PYTHONDONTWRITEBYTECODE=1 "$SOCCER_PERCEPTION_PYTHON" -m unittest discover -s tool/model_benchmark -p 'test_*.py' -v
```

`benchmark.py` 负责配置、串行工作进程和超时；`worker.py` 负责 Engine/生产循环测量；`reporting.py` 负责统计。支持当前机器人 TensorRT 8.5，代码包含 TensorRT 10 的 I/O API分支，但后者尚未实机验证。

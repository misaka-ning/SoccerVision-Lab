# 预处理候选交接

仅本目录增加候选和 CPU 测试，未改共享 source、A2、CUDA Graph 或生产配置。

```python
from candidates import install

# detector.load() 完成后安装，首个调用应是真实 Val 图，不是 load 内部 640 黑图。
handle = install(detector.model.predictor, "canvas")  # 或 "reuse"
try:
    ...  # 原检测器入口；单 predictor 串行执行
    state_before_restore = handle.describe()
finally:
    handle.restore()
state_after_restore = handle.describe()
```

需在 PYTHONPATH 保留机器人已有 `soccer_perception_ros`，本模块复用快照中的
`soccer_perception.adapters.fast_preprocess`。不依赖新安装的库。

## 两个候选

| variant | 修改范围 | 缓冲与归属 |
|---|---|---|
| canvas | 仅 predictor.pre_transform；原 preprocess 后续 stack、颜色/布局、传输、FP32、归一化全部保留 | 左右目各一个 HWC uint8 Canvas，返回借用数组。原 preprocess 随即同步 np.stack 复制，因此最终 FP32 输出独立。不能让其他线程并发调用或保留直接 pre_transform 返回值供以后使用。 |
| reuse | predictor.preprocess；已有 prepare_uint8 几何/resize-dst + RGB/CHW 直接 pack | 一个临时 Canvas、一个 BCHW uint8 host buffer、一个 torch host view。每次 blocking to(device) 后 .float()/div_(255)，最终 FP32 输出和 CUDA uint8 staging 每次独立。 |

只支持本轮静态 TensorRT、FP32、batch2、640、同形状 uint8 HWC3 左右图。
首次成功调用冻结原图 shape；后续 shape 改变、半精度、动态/pt backend、非支持输入
明确进入原方法并增加 fallback_count。非法 variant 或重复安装直接拒绝。

canvas 固定 padding=114，使用原 helper 的 letterbox_geometry 和 OpenCV INTER_LINEAR，
ROI resize-dst；每目独立 Canvas 避免共用 Canvas 使 np.stack 时左右目都变成末一图。
reuse 不直接调用已有 ReusablePreprocessor.preprocess，因为其 _device_float 输出会被
下一次覆盖。本实现不复用 CUDA 输出，不引入异步 H2D、额外流、双缓冲或 GPU Resize。

## Graph 兼容性审查

快照 Graph 在私有流 wait_stream(caller) 后从传入 FP32 tensor 复制到稳定输入，
对输入 record_stream，执行后 caller.wait_stream(private)。两个候选都保留原调用流，
返回逐调用独立 FP32 tensor，因此不增加跨帧输出覆盖窗口。blocking H2D 完成 host
读取后才允许下一次复用。未改 Graph 的稳定地址、捕获内容或等待逻辑。
这只构成源码与 CPU 所有权审查；仍需机器人 Golden 验证后才能比较性能。

## CPU 验证

运行命令（本机 Python，无 GPU）：

```bash
cd /home/misaka/workspace/experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/agents/c
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/home/misaka/workspace/experiments/E04_tensorrt_pipeline/preprocess_race/20261023T014627Z/source/soccer_perception_ros \
/home/misaka/miniconda3/envs/soccer_perception/bin/python -m unittest test_candidates -v
```

结果：9 tests passed，1.242 s。其中从 E04 Val tar 只读解码 61 对图（122 张），
对 audit/library 中实际机器人 Ultralytics 的 LetterBox、pre_transform、preprocess
源代码提取类/方法执行，两个候选均逐值 torch.equal，零回退。
另覆盖几何舍入、padding、颜色和左右目顺序、非连续/只读原图、输入不变、变化图像、
保留历史输出、shape 变化回退、fp16/dynamic/pt 回退、异常回退、重复安装拒绝、
无条件/幂等恢复、已有实例方法恢复。

测试主机 NumPy 1.24.4 / OpenCV 5.0.0 / Torch 2.4.1+cu121，CUDA unavailable。
CPU 精确结果不替代机器人 OpenCV/CUDA 正确性结果；无本任务实测性能收益。

## 正式采集门禁

- 两候选必须分别 Golden 通过，保存 handle.describe() 的实际 effective、calls、success_count、fallback_count。
- 对所有预热和正式 numpy batch，calls == success_count，fallback_count == 0。
- 稳定输入下 canvas 的 canvas_allocations==2、host allocations==0；reuse 的 canvas_allocations==1、host_buffer_allocations==1、host_tensor_view_allocations==1。
- reuse fp32_output_allocations==success_count，gpu_output_buffer_reused==False；不要误记为 GPU 输出复用。
- 正常退出和异常路径都 finally restore；after.restore_count==1、restored==True。
- 计数包含预热，不应把其当成仅正式测量帧数；正式墙钟由主控测量工具负责。
- 本轮只有 R0/canvas/reuse 一次离线赛马；是否达到 >=1 ms 系统复测门槛由 root 的实测裁定。

候选最初交付 SHA256：

- candidates.py：`75cf36564c67c909731417dbd14434e33056a639698865a6f6427a72d68e3281`
- 复用 fast_preprocess.py：`59dc1e9eb3c9cb5f8f4d5586361490dd8ae5d67d2c4411d3d127e09061505310`

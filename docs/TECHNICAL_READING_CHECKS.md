# 技术入口验证记录

2026-11-03，基线 `cd2ed6b1143d536301b8d3feec735b339779e65d`。独立 CPU venv 使用 Python 3.10.12，安装 `requirements-demo.txt` 成功；第三方运行时包仅 NumPy 2.2.6（venv 自带 pip/setuptools）。环境、缓存、临时文件和输出均位于本次指定工作空间。

- `python -B script/model-evaluation/synthetic_demo.py`：退出0，JSON 标记“合成演示：非模型成绩，非性能基准”；三行 TP/FP/FN 为 `(2,3,0)`、`(1,1,1)`、`(1,0,1)`，无球图片误报率为0.5、0.5、0。没有 AP 字段。
- `python -B -m unittest discover -s script/model-evaluation/tests -p test_synthetic_demo.py -v`：4项通过。覆盖重复框、阈值后重匹配、图片/框不同分母、未定义分母及 CLI 依赖隔离。
- 默认 Python 3.14 不在固定 NumPy 的支持范围，初次安装选中源码包后已中止；改用支持的 Python 3.10 二进制 wheel 成功。文档明确 Python 3.10–3.13，并要求 `--only-binary=:all:`，避免隐式源码构建。
- 检查新增文档相对链接目标、源码符号及 `git diff --check`。

未执行完整评估测试套件（包含 Torch/Ultralytics/AP/图表依赖）、真实数据/模型评估、正式训练、GPU、机器人或性能测试；本演示不能验证模型质量、AP或速度。冻结实验、历史结果和训练配置没有改动。

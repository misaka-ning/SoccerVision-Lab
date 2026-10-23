# 开发与交付

Python 运行代码位于 `soccer_perception_ros/soccer_perception/`，无硬件测试位于包内 `tests/`。
保持 `ros → pipeline → core / adapters` 的依赖方向。配置和模型由 ROS 包持有。
包内测试仅验证视觉感知、配置、ROS 接口和资源生命周期；测试数据使用包内文件或临时目录，
不依赖固定用户目录、外部机器人控制器或其他工作区，便于分发到不同机器。

## 配置维护

`config/camera_deploy.yaml` 是文件清单，参数按职责分布在 `camera.yaml`、
`detector.yaml`、`stereo.yaml`、`tracking.yaml`、`visualization.yaml` 和 `ros.yaml`。
每个参数只定义一次；新增参数时在 `BackendConfig` 中声明类型，并在对应 YAML 中设置值。
共享加载逻辑位于 `resources.py`，清单路径按包资源定位，子文件路径按清单目录解析。
launch 传递清单中的 ROS 参数文件，节点读取并合并相同清单后再应用 ROS 参数覆盖。
不要把文件清单本身传给 ROS 作为参数文件。完整配置目录由现有 CMake 规则安装，修改后需重新构建。

## 依赖

`requirements/common.txt` 声明公共部署依赖，`deployment/dependencies.sh` 读取它并声明
平台相关和可选依赖。安装脚本处理 Jetson 厂商 wheel、系统 ROS 和 ZED SDK。
部署版本保持不变；不要直接将测试环境依赖安装进机器人环境。

在独立 CPU 测试环境安装 `requirements/test.txt`：

```bash
python3 -m venv /tmp/soccer-test-env
/tmp/soccer-test-env/bin/python -m pip install -r requirements/test.txt
```

激活该环境后执行测试；此清单不锁定版本，不代表目标设备兼容性认证。

```bash
cd soccer_perception_ros
python3 -B -m unittest discover -s tests -t . -v
```

所有 Shell 入口与公共部署逻辑统一放入 `deployment/`。
修改入口时同步 README 和机器人服务调用配置。构建产物、环境文件和 engine 不提交。
模型来源、校验值和获取流程记录在包内 `models/README.md`。
CI 由上层仓库接入上述无硬件测试；ROS、ZED、TensorRT 另在目标设备验收。

## 发布前待确认

上层仓库根目录未找到许可证文件，包中的维护者邮箱和许可证仍为占位内容。
由项目所有者提供真实维护者和授权方式后更新 `package.xml` 及上层许可证；不要自行套用第三方许可。
模型的来源和分发授权也需所有者确认。

`maintenance.md` 保存历史迁移记录，历史测试数不代表当前验证结果。
历史备份由当时维护者本地保存，不属于仓库交付依赖。

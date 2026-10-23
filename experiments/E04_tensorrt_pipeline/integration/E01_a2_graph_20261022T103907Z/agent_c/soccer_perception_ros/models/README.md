# 模型资源

| 文件 | SHA-256 |
| --- | --- |
| yolo26s.pt | `646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b` |
| yolo26s.onnx | `d93d91621a80a198a5b7d8c38fd4ce0c6395b69f798855ec10b65933fff943b6` |

校验值来自既有维护记录。模型训练来源、版本说明和分发授权待项目所有者补充，文件名不能替代这些信息。
当前上层仓库使用 Git LFS 管理 ONNX，PT 为普通 Git 文件；此处不改变既有存储方式。

在上层 Git 仓库执行：

```bash
git lfs install
git lfs pull
```

然后在本项目根目录执行 `sha256sum soccer_perception_ros/models/yolo26s.*`，核对上表。
真实 ONNX 大小为 38292545 字节；以 `version https://git-lfs.github.com/spec/v1` 开头的是指针，不能推理。
下载失败时应向仓库维护者取得相同校验值的资源，不要用其他权重静默替换。
模型导出前检查缺失、空文件和 LFS 指针；完整性仍需按上表校验。CMake 不再复制模型。

此目录是源码与安装后节点共用的唯一模型目录。TensorRT `.engine`、ONNX 和 `.engine.json` 构建记录在目标设备通过 `bash deployment/build_engine.sh` 显式生成，由 `.gitignore` 排除，不随 CMake 安装。正常启动只加载；参数或权重改变时用 `--force` 明确重建。
旧安装目录中的模型由 `build_project.sh` 无覆盖迁移。旧 engine 没有构建记录时，人工核实参数后可用 `--adopt-existing` 记录当前配置；它不会解析或验证旧 engine 内部参数。
构建记录中的哈希与配置用于判断复用，不保证跨硬件、跨 TensorRT 版本兼容。
模型目录可通过绝对路径环境变量 `SOCCER_MODEL_DIR` 覆盖。

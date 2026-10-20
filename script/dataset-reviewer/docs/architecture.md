# 架构说明

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `review_dataset.sh` | 定位产品根目录，按需构建，设置 Qt 库 / 插件路径，选择默认数据集，启动程序 |
| `src/main.cpp` | 命令行解析、图片预览、筛选列表、场景分类、审核操作、快捷键、界面冒烟核验 |
| `src/label_editor.h` | label 编辑窗口：创建、选择、拖动、缩放、删除框及输入坐标 |
| `src/dataset_store.h` / `.cpp` | CSV 解析与校验、图片 / label 路径、dirty 状态、受控审核、哈希检查、备份和保存 |
| `tests/dataset_store_tests.cpp` | 数据层的正常、冲突与失败路径测试 |

这是一个本地桌面程序，主窗口通过 `DatasetStore` 管理数据与修改状态。画框窗口返回用户确认的框，写入操作集中在数据层；界面不直接覆盖 CSV 或 label。

## 主要数据流

加载数据集 → 校验 metadata → 按 split 定位图片与 label → 只读显示 → 用户编辑分类或检测框 → 数据层校验与备份 → 原子替换目标文件 → 更新当前已加载状态。

切换图片保留尚未保存的分类修改。关闭窗口或切换数据集前由界面提示处理修改。场景确认清除 `scene_review_required`；label 通过操作才清除 `label_review_required`。两种审核不会自动替对方通过。

## 保存边界

保存 CSV 时，数据层仅允许四项场景字段和 `scene_review_required` 的一般编辑；`annotation_status` 与 `label_review_required` 只能通过受控 label 操作改变。其他字段、附加列、BOM 和记录换行等内容按现有测试约定保留。

写入前使用已加载文件 SHA256 检测外部修改，用 `QLockFile` 协调本程序的 CSV 保存，将原始字节备份后使用 `QSaveFile` 提交。锁只能协调遵守同一锁约定的程序；不能将它当作所有外部编辑器的文件锁。

label 通过操作绑定当时显示内容的 SHA256，保存前再次确认。手工改框也检查文件是否与打开编辑窗口时一致，并备份原有完整字节。

手工改框先将 metadata 保存为待审核状态，再替换 label。CSV 和 label 是两个文件，不是跨文件事务：label 写入失败时，原 label 保留，但待审核状态可能已经保存。这个顺序确保旧的通过标记不会错误沿用到新框。

## 项目和数据的关系

项目目录保存程序、测试和说明；数据集目录保存图片、labels、metadata、dataset.yaml 和审核备份。构建与截图写在产品目录，审核结果写在用户选择的数据集。工具不自动训练模型，也不自动更新历史待办清单或整理报告。

## 不确定样本与导出

markUncertain 将不确定原因写入 annotation_status，并清除 No Ball、设置复核标记；仍使用原有受控字段校验、外部冲突检测、备份和原子保存。图片及 label 原件不动；恢复使用待修正操作，再完成独立审核。

exportDataset 要求无未保存修改、metadata 未被外部改动。持有 CSV 协作锁，在目标父目录的临时目录中准备完整快照，发布前再次核对全部已复制文件和 metadata 哈希。校验失败自动清理临时目录；成功后重命名发布到不存在的新目录。只复制审核通过的普通检测样本及独立不确定资料；旧 label 位于 reference_labels，普通训练配置仅扫描 images/train、val、test。导出不重划 split，也不覆盖源文件。每次导出保留规范版本与源 metadata 哈希。

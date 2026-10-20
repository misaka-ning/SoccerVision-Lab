# 复现与回滚

本版本独立复制8148对图片和label，旧datasets/、旧split、metadata和250项隔离样本均未改。dataset.yaml只读取新版本三个正式清单；reserved/保存buffer及heldout_unused，不进入训练配置。

## 直接使用

把训练/验证程序的data指向本目录dataset.yaml。Train4346、Val1223、Test464。Test是same_session_segment_holdout_v1；未来独立采集单独命名future_independent_session_test并分别评估。

仅做配置预检（不会训练）：

```bash
/opt/VisionStudio/runtime/bin/python -B /home/misaka/workspace/script/model-training/train.py --config /home/misaka/workspace/dataset_versions/football_holdout_20261019_v1/train_from_scratch.example.yaml --dry-run
```

示例从已保存架构随机初始化，pretrained:false，不把曝光史未知的original_best.pt当成未见Test权重。正式训练仍需采用未用过留出图片的初始化；本轮没有启动训练。

## 重建相同分配

不在已发布目录运行选择/复制脚本。先创建新的空版本目录，在新目录复制本版本scripts/、analysis/、evidence/及SOURCE_FACTS.json，创建lists/与runtime/子目录；不要复制MATERIALIZED.json、COMPLETED.json或labels/*.cache。然后运行新目录中的：

```text
scripts/materialize.py
scripts/validate_view.py
scripts/build_deliverables.py
```

使用/opt/VisionStudio/runtime/bin/python -B执行。common.py按自身位置推导新ROOT，源DATA和旧审计路径为本机绝对路径。materialize读取冻结allocation/curator_completion和源SHA，核对源照片与label后复制，拒绝覆盖已完成版本。它重现已冻结人工决策，不宣称自动重现视觉判断。源文件不再匹配SHA时会停止；不要绕过检查。

重新分析时可从prepare→draft_segments→select_candidates→screen_pairs开始，但必须写新目录。原图/label、metadata、已有embedding与来源清单的SHA、随机种子、阈值及每次边界修订都在分析资料中。重用旧观察前须匹配同一照片对及SHA，不能只按变化的N/F/Q编号关联。SOURCE_FACTS.json记录本轮用户确认事实，优先于旧审计对场次的猜测。

## 独立验证与缓存

validate_view.py全量比较8398对源文件（包括旧250排除）及8148对新副本，检查名单、像素/文件哈希、同帧侧别、完整片段/缓冲、Val锁定及旧关联；真正构造YOLODataset和读取批次。首次创建本版本cache，第二次读本版本cache核对。源码数据不建cache，不实例化模型。

缓存只在本版本labels/，不会改变原始label。若今后有人工改标，必须另建数据版本并重做校验；不要把本报告套用于已改动的文件。

## 回滚

把训练配置的data恢复为/home/misaka/workspace/datasets/dataset.yaml，即恢复此前Train6925/Val1223/Test0的来源划分。新版本可以保留供追溯，无须删除或移动原图。回滚数据视图不能撤销权重曾看过Test的训练曝光。切换后核对加载日志和配置路径，避免误用其他版本缓存/实验结果。

## 单文件HTML

review.html所有必要资源均内嵌；可单独复制到任意位置直接打开，不需要HTTP服务器、旁边的JS目录或图片文件。预览是缩略图及对照页，原始像素仍在本版本图片目录；本机复核选择只保存在浏览器，不回写manifest或label。

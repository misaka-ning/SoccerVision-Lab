# 训练安全性与分层视觉抽检审计（F / E3）

本子审计于2026-10-19执行。源metadata为全量8398条审核记录；用户后续明确授权将250张excluded图片及对应label移入`datasets/excluded/{images,labels}/{split}/`。本子任务只读原数据，隔离由主审计执行。以下严格区分隔离前历史证据和隔离后现状。

## 当前结论与覆盖

**隔离后数据路径层面的excluded混入问题已解决**：调用已安装Ultralytics 8.4.173的真实`BaseDataset.get_img_files`（只调用发现函数，不实例化Dataset）得到train=7857、val=164、test=127，合计8148；每个split发现的excluded均为0，4份实质越界标签均不在active目录。metadata8398是全量审核/追溯记录，不意味着8398均参加训练。训练可否开展仍须合并泄漏、独立测试集及标注质量审计结论。

安装环境为Python3.10.12、Ultralytics8.4.173、PyTorch2.9.1+cpu、NumPy2.2.6。审计设OMP/MKL/OPENBLAS线程为1，torch线程为1，nice10；YOLO_CONFIG_DIR、MPLCONFIGDIR均位于审计safety目录。没有修改依赖、下载权重、实例化YOLO、运行forward、构建训练批次、训练或更新生产模型/TensorRT Engine。已执行训练入口`--dry-run`并退出0，仅确认基本路径/配置规划。

## YAML、入口与类别

`datasets/dataset.yaml`路径为`/home/misaka/workspace/datasets`，分别指向`images/train`、`images/val`、`images/test`；`nc:1`、`names:{0:football}`。当前可用标签5417个框全部class_id=0；含归档样本全量5468框也全部为0。四个困难场景字段是metadata属性，不是四个目标类别。

`script/model-training/train.py:110`明确提示训练不按metadata审核标记筛选，`:119–120`才实例化YOLO并调用train；审计只运行`--dry-run`，不会走这些行。其配置model指向`baseline/original_best.pt`，参考架构`baseline/original_model.yaml`为nc80。80类预训练与本任务单类标签并不冲突：安装源码`ultralytics/models/yolo/detect/train.py:194`的`DetectionTrainer.get_model`显式调用`DetectionModel(cfg,nc=self.data["nc"],...)`，`:141–142`设置model.nc/names。这里仅确认源码传参路径，不声称已经实装/加载/训练成功。基线checkpoint没有在本子任务反序列化。

COCO的32类是`sports ball`（本地`ultralytics/cfg/datasets/coco.yaml:51`），当前任务0类是football，不能把现有标签改成32。若E00直接评估原80类参考模型，必须明确把预测sports_ball32与目标football0的语义对应纳入评测设计，否则不能把两套数字ID直接等同；本次未运行E00模型评估。未发现其他实际训练入口绕过该脚本的证据，但用户直接调用Ultralytics CLI同样不读取metadata筛选。

## 隔离前历史风险与隔离后复核

| split | 隔离前原loader发现 | 其中excluded | excluded空label | 隔离后原loader发现 | 现excluded混入 |
|---|---:|---:|---:|---:|---:|
| train |8100|243|199|7857|0|
| val |170|6|6|164|0|
| test |128|1|0|127|0|
| 合计 |8398|250|205|8148|0|

历史状态下，205份excluded空label会被标准loader当作background读入；它们不是确认负样本。其余45份excluded非空label含41份几何有效参考及4份实质越界参考。隔离前发现证据保留在`../safety/pre-isolation-training-safety.json`；隔离后真实发现结果在`../safety/training-safety.json`。归档在YAML三个递归image根目录之外，因此原YAML无需更改即可排除这些样本。未来若又把未确认样本写回active目录，原入口不会替使用者自动按metadata过滤。

隔离前另建立`../safety/filtered-view/`：8148张usable图片symlink与对应label副本，按三split独立存放，只执行真实文件发现函数验证7857/164/127、excluded0。这个视图用于加载路径审计，不是修改或认可原研究划分。没有在其上构建完整YOLODataset；源码`check_image`可能修复损坏JPEG，故避免通过symlink对源JPEG触发修复路径。

## 四份越界label：真实隔离verify结果

四份为`frame_001674_right.txt`、`frame_003650_right.txt`、`video_4bec9c343db72928_frame_00004643_left.txt`、`video_4bec9c343db72928_frame_00007724_right.txt`，均属于excluded。每份原图和原label物理复制到审计`verify-copies/`，再调用安装版本的`verify_image_label(...num_cls=1...)`；四份均accepted、corrupt=0、保留原非空框数，副本label未被改写。另复制一份excluded空label，结果accepted、empty=1、返回0框。

原因是本版本`data/utils.py:458–460`检查归一化xywh**各分量**上界1.01、下界-0.01，并未在这个验证阶段校验x±w/2、y±h/2是否落在图内；这些样本的分量均可通过，而展开边界越界。不能依赖“loader未报错”替代几何审计。后续增强/格式化是否裁剪及其影响没有执行，未据此下结论。严格几何筛查采用1e-6归一化容差以忽略边缘小数序列化舍入；真正4份超界远高于该容差。隔离后它们不被active目录发现。

## cache、路径与标签版本

对`datasets`（含当前excluded归档）、`script/model-training`、`baseline`、`experiments`实际扫描，未发现既有`.cache`；原active/归档目录未发现symlink。原三split图片无重复realpath、无重复(dev,inode)，没有发现同一物理文件多split路径引用。本审计视图中的8148 symlink为有意创建的审计输出，不能算原数据异常。

本版本`data/dataset.py:301–302`会在label目录旁定位`.cache`，`cache:false`并不禁用label扫描cache；其版本为1.0.9，`_load_or_scan_cache`同时核对version与hash。`get_cache_hash`包含扫描设置（keypoint/nc/single_cls），`data/utils.py:225–238`的`get_hash`逐文件纳入路径、size、mtime_ns。审计独立文件实测：同长度改label且mtime变化会失效；内容变但size和mtime完全恢复时hash可碰撞。因此此版本已比仅汇总size的旧实现严格，但仍不是内容SHA256。

现有cache没有用`np.load(...allow_pickle=True)`读取；源码自身的cache加载采用pickle，本审计若发现cache只会读NPY安全header/mtime/字节SHA，不执行payload。没有向源目录写cache。未发现cache掩盖当前label变化的现存证据；对于历史标签是否已过期，若缺逐图真值版本不能单靠文件时间证明，本子任务不宣称已经验证历史真值。

## E3：64张固定种子分层抽检

seed=20261019；按metadata分层，普通清晰有球、Small、Occluded、Blurred、No Ball、多球、Small+Occluded、Small+Blurred各7张，excluded8张（空label/非空label/越界及val/test代表）。顺序分层内按split定额、不放回随机抽样，候选按路径排序；不足split以剩余候选补足。每行`sampling_method`记录子层与实际抽取数/候选数，复杂重叠条件的无条件纳入概率没有假填，`sample_probability`留空。最终64个不重复路径，train37/val16/test11。该抽检是风险导向的定额分层，不能拿建议复核数估计全库错误率。

**已实际用view_image逐页打开全部32页、64张全景**。672×376原图保留原生像素，1280×720样本也保留原生像素，每页1或2张，红框来自原label；源图未改。64行均有独立`assistant_observation`，`review_result`全部为空，`assistant_visual_seen=true`；26条建议复核包含8条excluded。O/B只记录主观风险或合理可见依据，不宣称人工groundtruth，不覆盖源标签。

较具体的风险示例：

- S005 / `frame_005240_right.png`（test）：完整球原框33×37px，但Small=0；与长边672尺度约40px规范可能不符，待人复核。
- S035 / `video_4bec9c343db72928_frame_00004889_left.png`（train）：两球中远球框36.76×26.84px，Small=0存在风险；没有将大球残片尺寸误当小球。
- S026 / `legacy_test_000006.jpg`：桌面大球下部明显被原图下沿截断，Occluded=0与画边截断规范有不一致风险。
- S001：原框在机器人脚后暗区，当前可见证据不足以可靠核定球轮廓，须局部人工复核，不自动删除框。
- S060/S063是excluded参考，No Ball=1却有球框；该矛盾不能被扩散成usable样本问题，当前已归档并排除。

7个确认负样本抽检未见可可靠确认的漏标足球；这只说明此小样本未发现明确疑球，不能证明所有2928张负样本无漏标。多球层7张均逐框核对；部分远小目标身份/交界继续建议人工局部查看。高度相似但标注不一致的独立候选由主审计另补，不计入本64张分层覆盖。

原64张页面是在授权隔离前渲染，图像和label内容保持原样。CSV/JSON的path/label_path保留基线位置，`source_current_*`给出隔离后可访问路径，sample SHA用于核验内容；excluded样本在archive中仍可追溯。

## 文件与限制

- `../scripts/training_safety.py`：安全发现、隔离复制verify、静态版本证据、过滤视图及固定seed采样渲染。
- `../safety/pre-isolation-training-safety.json` / `../safety/training-safety.json`：历史/现状机器证据。
- `visual_sample_manifest.csv` / `visual-findings.json`：64张抽检原始标签、四flags、抽样方法、独立观察和空复核结果字段。
- `../samples/page-000.png`至`page-031.png`：实际查看全景页；`../safety/source-excerpts/`：安装源码行号/哈希。
- `../logs/safety-train-dry-run.log`、`safety-post-isolation.log`：运行凭据。

源metadata SHA256 `cb2386ef97c2f864cad27adf8fc06dc6fc74cea2caf828f32a685abc05985ef9`，YAML SHA256 `7781d543cc43364f2a2598ff596adb05a8e80b4547af40195665565a8eef05b6`，子任务前后均匹配。没有执行完整模型/训练/推理兼容性验证；dataset-level路径与类别检查通过不能替代YOLO26s架构成功加载，也不能覆盖其他子审计揭示的泄漏或评估可靠性风险。

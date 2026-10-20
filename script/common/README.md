# 公共配置组件与脚本索引

公共Python/Shell读取器、依赖说明和版本切换测试集中在本目录，其余四类工具仍位于各自目录。各文件夹的作用与启动方式见 [脚本总览](../README.md)。日常切换版本只修改 `../config.yaml`。

四类工具共用 [config.yaml](../config.yaml)：修改 `dataset_version: v1` 为 `v0`（或新增版本名），**保存后重新运行入口即可生效，无需重新编译Qt程序**。配置每次启动重新读取；已经运行的训练/窗口不会中途切换。

| 版本 | 根目录 | Train | Val | Test |
| --- | --- | ---: | ---: | ---: |
| v0 | `datasets/v0` | 6925 | 1223 | 0 |
| v1（默认） | `datasets/v1` | 4346 | 1223 | 464 |

所有配置路径相对仓库根目录，支持绝对路径及 `~/`。v1的Test是同场次片段留出，不是独立场次测试；buffer/heldout_unused/excluded不自动加入训练。新增版本须采用 `images/{train,val,test}`、`labels/{train,val,test}` 和根 `metadata.csv`，在 `datasets:` 下增加对应root。

共享读取器为 `script/common/dataset_config.py`，依赖PyYAML；本机可用 `/opt/VisionStudio/runtime/bin/python`。训练配置中的 `data: null` 表示跟随共享选择；评估、审阅和仓库工具默认跟随。命令行显式 `--data` / `--dataset` 或训练配置中非空data优先，适合临时使用其他数据；断点续训仍保留checkpoint原参数，更换版本应启动新训练。

每次训练/评估启动会按选定版本生成 `experiments/configs/datasets/<版本>.dataset.yaml`，指向本机实际目录，原始版本内的YAML、名单和manifest不改写。预检查也可能生成这个运行配置，但不会创建训练/评估结果。脚本不直接使用历史YAML和名单中的失效绝对路径。

可用 `FOOTBALL_DATASET_CONFIG=/另一份/config.yaml` 临时选择整份共享配置（四类入口通用）；Python入口也支持 `--dataset-config`、`--dataset-version`。审阅Shell启动器用 `FOOTBALL_DATASET_PYTHON=/环境/bin/python` 选择配置读取环境。

```bash
/opt/VisionStudio/runtime/bin/python script/common/dataset_config.py
/opt/VisionStudio/runtime/bin/python script/model-training/train.py --dry-run
bash script/model-evaluation/evaluate.sh --dry-run
bash script/dataset-reviewer/review_dataset.sh --gallery
/opt/VisionStudio/runtime/bin/python script/repository/verify_dataset.py
```

旧固定审核批次只属于v0；切v1后不沿用旧名单。如需v1批次，在config.yaml指定的review_records目录建立新名单。

共享配置依赖可用 `python -m pip install -r script/common/requirements.txt` 安装。版本切换回归测试：`python -B -m unittest discover -s script/common/tests -v`，覆盖四类入口、相对路径迁移、空Test、无效版本拒绝及Qt启动器不重新编译。

- [dataset-reviewer](../dataset-reviewer/README.md)：数据集审阅的全部代码与测试。入口 `script/dataset-reviewer/review_dataset.sh`；分批、每页50张平铺、改框、场景分类、审核状态和导出均在此目录维护。
- [model-evaluation](../model-evaluation/README.md)：输入检测模型，输出mAP、固定阈值P/R/F1、无球误报率、场景分组指标和论文图表。
- [repository](../repository/README.md)：按共享配置校验当前版本，生成可迁移运行配置，校验/恢复冻结留出副本。
- [model-training](../model-training/README.md)：模型训练、训练配置和相应测试。

审阅相关脚本不再散放在本目录顶层。原 `review_football_batch.sh`、`review_football_groups.py` 和 `render_football_review_grid.py` 已迁到 `dataset-reviewer/`；调用时更新路径。

`dataset_processing/` 保存历史审核记录、固定名单及最终统计；历史一次性处理源码已集中到 [审阅产品的历史目录](../dataset-reviewer/history/processing-code/README.md)。

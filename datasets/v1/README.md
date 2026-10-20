# football_holdout_20261019_v1

已完成分配和真实YOLO加载核验：Train **4346**、Val **1223**、Test **464**、buffer **755**、heldout_unused **1360**，合计8148张。原250张隔离样本仍在原目录，不属于以上五类。

Test是**同场次片段留出**，464个源帧时刻、8个核心片段、7个含Test的连续保留块，只有1个真实采集场次且与Train共享，不能当作独立场次泛化测试。

- [数据配置](dataset.yaml)、[Train](lists/train.txt)、[Val](lists/val.txt)、[Test](lists/test.txt)
- [分集报告](REPORT.md)、[完整分配manifest](manifest.csv)、[统计](statistics.json)
- [单文件HTML复核页](review.html)：50张平铺、片段联系图、最高风险对及两组可选回收疑点。
- [核验结果](verification.json)、[完成状态](COMPLETED.json)、[交付文件哈希索引](analysis/output_files.json)
- [复现和回滚](REPRODUCE.md)、[旧权重曝光记录](weight_exposure.json)、[评估口径](evaluation_protocol.json)

源图片、label、场景metadata和原分集未修改。本目录使用独立副本；新缓存只在本目录。MATERIALIZED.json记录复制完成时的历史状态，最终交付状态以COMPLETED.json及verification.json为准。

未知旧权重的训练成员历史不能靠移动图片消除；正式比较需从未接触留出图片的初始化按新分集重新训练。本轮未训练模型。

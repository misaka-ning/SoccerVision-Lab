# E04 原始证据索引

当前 run：`20261022T020842Z_78f1b7`。正式 Golden/三轮基线已回收验收，优化候选尚未测量。

本机根：`/home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7`。机器人根：`/home/nvidia/soccer_backend_tensorrt/results/E04_tensorrt_pipeline/20261022T020842Z_78f1b7`。run 内图片、模型、归档和私有工作树按现有规则不入主 Git。

| run 内文件 | 字节 | SHA256 |
|---|---:|---|
| `audit_bundle.tar.gz` | 204602 | `1c31b5683b2393a260c66a438ee2c25bbbae8b838ce82024af072971145c390c` |
| `audit_extra.tar.gz` | 7133 | `8deaffa8065e6432675e9ad6ed107aeaa3c6897830dd81a31295cbc939bf87e3` |
| `handoff_payload.tar.gz` | 20112838 | `b4fd5653e0b649c9713eb42070fa69edff4bd981e66279a8f246aef48b3381ac` |
| `frozen_contract.json` | 24358 | `29b6cbe0a85e42cb5b1816fb3e2d343ec08a623f448457ee0d341151652b1f09` |
| `readiness_bundle.tar.gz` | 3148 | `394237a3e251209ffdeb7943b5357167351c1abe645aff34cbfc1cf0954349d2` |
| `val_cases/cases.json` | 84457 | `e5241ccf4b2d7b864755adf5208805f26e144b793c37f68362a52098c411d11d` |
| `e03_evidence_manifest.json` | 1255 | `028cb370bb34b106a4231cecb6e99a03987593c9b6c9274dd0779d0561e00007` |
| `source_cpu_tests_complete.log` | 3048 | `0ca3e5a19cb4fd2e896bba3fc7e6a90f2db336a2088b7c8d39c6818f0fb3f5f9` |

`audit/source_manifest.json` 记录原路径和快照文件的逐项 SHA；`extra/source_manifest.json` 补充安装配置与既有测试 fixture。`runtime_probe.json` 记录实际有效参数、版本与 NMS ABI 错误。凭据不写入这些归档。

`readiness/` 已安全解包短测及前后 dry-run 证据；其中 `smoke_detector/frames.csv` 只有两次接口调用，不能用于正式性能结论。`smoke_detector/effective_runtime.json` 包含实际绑定 shape/dtype 与生效参数。

`e03_evidence_manifest.json` 冻结历史报告、Top20、trace 摘要和原始回收索引的指纹；E03 文件未改写。源码快照提交为 `b7dab3a1a738c73d3a64614f5aab7b4b1ef328f0`，实际部署上游 HEAD 为 `5ef358e9b7df2edcf36d4618d3e2b6aad70e0812`（有已有修改）。

用户正式运行后，机器人生成 `stage0_jobs.json`、`stage0_*_attempt*/`、`telemetry_stage0.jsonl`、原模型前后指纹、`stage0_metric_distributions.json` 与 `STAGE0_COLLECTION_COMPLETE.json`。完成标记仅代表采集完成，验收仍由协调 Agent 执行。

## 正式采集回收

`stage0_collection_v1.tar.gz`：58009554 字节，SHA256 `2b79ab5937146870ce1103c531b3b72c2cc98c5029de6782497da8dbbf6efd44`。安全解包至 `collection_v1/`，其中 `collection_file_manifest.json` 的150项大小/SHA逐项验证。原机器人目录保留。

`stage0_review.json`：SHA256 `2519bf205574dafc1381ee6c8f4b5e027b4339f87658d93d7f0f9869990b4dbc`。

`E04_0_GATE.json`：SHA256 `a78d6058802b57e92f20408be945dd5736096721ad5032e1decdc977c988587f`。

`review_stage0.py` 在本机 CPU 重算所有逐帧指标的 P50/P95/P99，检查九轮预热/时长/样本数、61对FP32张量与七字段ROS协议。`E04_0_GATE.json` 为协调验收通过记录。

## 候选准备

隔离集成提交 `e0672063ed58446a9ed3ecec59ad854380f5795b`；`integration_cpu_tests.log` 为65项CPU集成日志，`tool_tests_v2.log` 为9项工具日志。实际候选代码的可审查补丁为 `patches/E04_candidates.patch`，三Agent明细报告在实验根目录。

当前候选包 `phase1_20261022T031913Z_260f0c.tar.gz`，SHA256 `f196660b259d0fb688ecf946663e15f358f3feaf793d32eb8c03aea1a5290be5`，61001字节；manifest SHA256 `16d34236f9cf8f6ad7206afe6ad7b263102d6222b20a17506ae85e2f77d9ab43`。已上传、机器人dry-run通过，未启动候选GPU采集。`CURRENT_PHASE.json`记录本机/机器人目录。

## phase1实机正确性回收

`phase1_20261022T031913Z_260f0c/correctness_recovery_v1.tar.gz`：310281字节，SHA256 `f92a95877e40e7d19605b91ab6a6cee13d8f345894688a38b1b867ae3332d922`。`recovered_v1/recovery_manifest.json`含492文件，427个NPZ经文件hash确认与阶段0完全相同后以内容引用去重，其余65文件归档直接保存。本机逐项恢复并验证全部文件，原机器人路径保留。

`phase1_20261022T031913Z_260f0c/phase1_review.json` SHA256 `b6a487fc960ea91c5c1c5cd903df7a952224cc40b74ffae286f725a17dff635b`。单项GPU正确性通过，不包括正式性能/组合/长稳或生产准入。`CURRENT_CORRECTNESS_PHASE.json`保留已验phase，CURRENT_PHASE指向下一采集。

## 正式离线性能准备与短接口验证

旧验证目录 `phase2_20261022T040320Z_552071` 只运行1次预热/0.1秒的b0、Graph及检测器接口冒烟，不含正式数据。回收包SHA256 `1d23b75bdd39009c95310756f7e32a15b98021969d60a91546fbbf08df227199`，9614字节、17文件全部验证；原源码、候选源码、工具及原模型错误列表为空，formal_jobs_created=false。

正式目录 `phase2_20261022T040942Z_f1ef07` 复用完全相同的脚本代码，额外冻结cases.json与122个原Val图指纹；已通过新包robot dry-run，未重复GPU短测。包SHA256 `0ad7aca9ebc8cb600ba1f87ab96cb83217c11428694c2d16554d3e4593bc4a75`，30989字节；manifest SHA256 `c6b1bb6345eca6f41b8634d10b183afab63a02f9cc751326276b8b16bd353820`。当前默认离线范围28轮，每轮100预热/60秒；正式采集尚未启动。

## phase2离线正式性能回收（已完成）

2026-10-22用户完成execution6 + detector21 + diagnostic1，共28轮。offline_recovery_v1.tar.gz位于当前phase，1193995字节，SHA256 `b238a317f2a561125ee602014e96662fbfd80232c6ef255fcd9ea9854fd84701`；安全解包至recovered_offline_v1/，167项内容指纹及清单自身共168文件逐项验证。原机器人数据保留。

offline_recovery_v1_integrity.json核验99部署源码/配置、18受保护模型、36候选payload、10性能工具、189参考及156job artifact，errors=[]。Engine SHA仍为 `98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348`。

performance_jobs.json包含28条complete任务、命令/时间/源指纹/后台进程名/负载、逐项原始artifact SHA；各attempt/frames.csv共35356行。Graph独立execution含resources.jsonl，其他含effective_runtime.json和外层_hooks.json。telemetry_stage0.jsonl在phase根保存2224条本阶段遥测，文件名沿用工具，不属于阶段0旧数据。

review_performance.py从原始CSV重算均值/P50/P95/P99、三轮配对和时间插值敏感性，校验warm/final/Graph/A2/C2/C1计数、真实NMS/绑定/参数、restore及artifact hash，生成当前phase/offline_review.json。全部通过，仅准入后续单项system，不代表组合、长稳或生产采用。重现：

```bash
python3 /home/misaka/workspace/experiments/E04_tensorrt_pipeline/review_performance.py --recovered /home/misaka/workspace/experiments/E04_tensorrt_pipeline/runs/20261022T020842Z_78f1b7/phase2_20261022T040942Z_f1ef07/recovered_offline_v1 --output /tmp/e04_offline_review.json
```

此前“正式离线准备/未启动”段落保留为交接历史；当前状态以本段、CURRENT_PHASE.json与NEXT_RUN.md为准。

本机保存六份独立Agent MD/JSON至当前phase/independent_reviews/，逐项指纹见independent_reviews_manifest.json。OFFLINE_SYSTEM_GATE.json SHA256 `1234397d33c97e3693c59b6fc236635bd9beacbf6f060f1cc4b3fb022a09f9ed` 已与offline_review.json上传机器人独立结果目录。system_handoff_dry_run.json记录同一manifest的21job CPU-only ready结果，gpu_work=false、camera_work=false；未启动system。

## phase2完整49任务与无球system回收

single_matrix_recovery_v1.tar.gz：3224467字节，SHA256 `f49f2a7e99de43211d32a9823b0bfa458343ccd6669defc5d107320f0666a455`。安全解包recovered_single_matrix_v1/，364项内容+清单共365文件逐项大小/SHA验证；包括原28轮及新21system，旧offline_recovery_v1不改。

single_matrix_recovery_v1_integrity.json记录99源码/18模型/36候选/10工具/189参考及345job artifact全过。system_empty_review.json由review_system.py --scene-label empty生成；用户确认无球，不能验收有框/定位负载。21轮23455帧，左右同时非空0，未记录逐帧measurement/tracking valid。错误重复启动只产生独立锁失败console，正常父进程继续49任务完整。

新phase3_target见CURRENT_PHASE.json；只复制旧manifest中10个工具/门禁文件，逐项SHA完全相同，改变仅为独立phase与手动确认的有球场景描述。未合并scene_validation草稿、未改变候选/生产源或加入预检。

新phase3_target_20261022T074056Z_ae65c6：归档30971B，SHA256 `9509bd4a997536c79f0a415a72d9b004e5a0cd984911726e9f255ed4fa936328`；manifest `c2d2523d942bf6a75e17f6975293709fc68bd864b49224f9b1173c9127c4dcd9`。已上传；CPU-only dry-run因生产两份visualization.yaml的zed_viser_enabled false→true被配置保护拒绝，差异记录dry_run_config_difference.json。未更改生产、未绕过保护或启动新测试。

## phase3启动故障修复

用户首次启动PID12784在源配置核验处因两份visualization.yaml仍Viser=true退出，未产生job或正式样本。协调Agent在独立phase/visualization_backup_20261022T075045955365Z完整备份原true文件后，仅恢复两份zed_viser_enabled:false；恢复后SHA与冻结合同完全一致。未改其他参数、模型或ROS控制逻辑。恢复记录VISUALIZATION_RESTORATION.json和备份已保留，本机system_handoff_dry_run.json记录CPU-only ready21job。此次确实写回了两份可视化配置的冻结值，不能再笼统称生产配置从未被写过；候选代码仍未安装到生产，长测试未由协调Agent启动。

## phase3有球system回收（已审查）

target_recovery_v1.tar.gz：1712479字节，SHA256 `2479fff02fa2d1b37aa3549c92b5ba7a92c08710f27262342a74bbc4f5597056`；recovered_target_v1/含205内容条目+清单共206文件，逐项大小/hash过。target_recovery_v1_integrity.json为99源码/18模型/36候选/10工具/189参考/189job artifact，errors=[]。21轮19079帧/18948双目非空，纯数字独立重算target_numeric_review.json；适用范围与决定见TARGET_SYSTEM_REVIEW.md及TARGET_SYSTEM_GATE.json。

三Agent6份目标场景独立MD/JSON复制至target/independent_reviews/，指纹见independent_reviews_manifest.json。最初GPU数值重算status标reviewed_pending_scene_validation；后验人工场景/候选统计及三Agent审查后，根允许组合正确性，未批准组合收益/生产/长稳。

## phase4组合Golden准备

phase4_combo_correctness_20261022T083338Z_a40d24.tar.gz：72022字节，SHA256 `1ca66c1b7676bc907ec6793bd73973610a0c44c3bb8dfcccd234d52b6eff19da`；manifest SHA256 `f2fe308b67ef997e944828ecfad7c5abf0e56f1d6ec7404e71281b679acb107d`。复制原phase1的30份source/config/package与原Golden adapter/comparator；controller仅新增限定组合gate/参考hash与版本保护/240s自身子进程上限。24项CPU工具测试通过，组合GPU尚未运行。三项R0/R4_AB/R5_ABC，C2仅诊断比较，无自动有球脚本或现场预览。

phase4已上传并通过机器人CPU-only dry-run（ready，cuda_work=false、camera_work=false，R0/R4_AB/R5_ABC），结果本机cpu_dry_run.json。新源包完整30项与phase1逐项SHA相等，原Golden adapter/comparator亦相同；controller/helper更新工具测试24项通过。target/measurement_window_telemetry.json按逐帧cycle时间对齐1253个测量期遥测样本，全部408MHz，GPU45.312～50.687°C，未把启动/预热采样计入。未启动phase4 GPU正确性或长任务。

## phase4组合正确性回收与phase5组合性能交接

phase4/correctness_recovery_v1.tar.gz为148919B，SHA256 `1ef0180246900aa29bb909e7078212a02635513d9dbcf15fd181982287a55cc3`。recovered_v1/中清单216内容条目+清单自身共217文件，183个NPZ在完整SHA等于原Golden时引用去重，本机恢复后逐项验证。integrity记录99源码/18模型/38payload/189参考错误为空；原机器人结果保留。

phase4/combination_review.json为passed_for_combination_benchmark，R0/R4/R5各61对、732数组精确，计数/零回退/恢复均通过。六份独立MD/JSON在phase4/independent_reviews/，指纹见independent_reviews_manifest.json。CURRENT_COMBINATION_PHASE.json专门保留该验收；CURRENT_CORRECTNESS_PHASE.json仍保留原单项准入。

新phase `phase5_combo_performance_20261022T090140Z_4d6d9a`：包34478B，SHA256 `8f6d1344ab9c731f014b21dde62e72624819a106d77fe3ad9f131d43bb5f4f12`；performance_manifest SHA256 `304ad65b33cbe5c37f723f0e67e64c64beb70b0237817d0eb5798486b36cfe06`。matrix=combined_pipeline，引用phase4已验source，R0/A2/R4/R5、detector/system共30组。工具/门禁10文件及30job schedule SHA均冻结；本地local_package_provenance.json和COMBINATION_PERFORMANCE_PLAN.md为后补说明，不属于上传payload。

phase5/cpu_dry_run.json来自机器人，只读源码/配置/参考/模型/版本/功耗核验ready30，gpu_work=false、camera_work=false；交接时无活动E04控制/子作业。40项CPU工具测试通过，3.8/shell语法通过；没有启动正式组合性能。CURRENT_PHASE.json指向新包，NEXT_RUN.md是唯一当前长任务入口。B5工具仅私有开发和CPU验证，尚未实机运行。

## phase5低电量中断（2026-10-22 17:33 香港时间）

用户因机器人低电量要求中断。首次普通SIGINT被后台启动方式忽略，随后只对已核实的本次worker PID18716发送其支持的SIGTERM；worker返回1，控制器正常记录failed_requires_review并退出，复核活动phase进程为空。未向运控、ROS0或其他后台进程发信号，未自动关机。

停止时19个job标complete，最后system_r1_04_R0未完成；无整矩阵完成标记。15个detector任务构成三个完整首尾R0块，system第一块有4项完成但末端R0中断，不能作为完整配对结论。原始数据和日志保留在机器人，尚未正式回收审查；充电后先审查，再保留完整detector块、整块重跑system第一块并继续后续。没有自动重启或继续监视。SSH停止结果摘录保存在phase5/REMOTE_STOP_OBSERVATION.json，原详细标记为机器人phase5/USER_BATTERY_STOP_RESULT.json。

## phase5充电后恢复（2026-10-22 17:39 香港时间）

机器人新boot_id为4d135a1d-706c-44c7-95e7-a7b5e35d290e。启动前CPU-only核验ready15；99部署源码/配置、18受保护模型、38候选payload、10工具/门禁、189参考和126已完成job artifact指纹全部通过。15个detector的三个完整R0块保留，漂移1.901%/0.916%/0.938%均未超3%。原Engine/25W/408MHz上限/冻结有效配置一致，无冲突任务，未改生产设置或终止后台程序。

启动前中断快照interrupted_recovery_v1.tar.gz为1009682B、SHA256 ec954f9319f5e0824bfc4c7269a4a0eaddcca67967254656a0042a40cca320cf，本机recovered_interrupted_v1/共150文件逐项验证。保留19complete+1failed的原始历史，尚未把这些未审计指标作为完整组合结论。

用户明确授权Codex启动、不需监视，已后台运行system --with-system --resume，PID6086。一次性启动确认：保留15detector complete；system首块4条原complete已标superseded，原failed及所有文件保留；从system_r1_00_R0 attempt2开始，worker6133。此次总补15个system，预计约20–25分钟，未重复启动detector；全成功后可形成30个唯一作业的完整矩阵。

只做这一次启动确认，之后不轮询/监控，等用户通知完成再回收。现场继续由用户手动确认左右目有球、相机/球/照明稳定、自己的预览关闭；未增加有球脚本。恢复启动记录RESUME_REVIEW.json、RESUME_LAUNCH.json已本机保存。重启后monotonic归零，最终遥测须结合UTC及启动会话边界对齐，不能跨重启只按monotonic匹配；旧superseded/failed系统attempt不入正式统计。B5/生产采用仍未验收。

## phase5完整回收、最终审查与用户暂停

combined_recovery_v1.tar.gz：2390574B，SHA256 `3eeb8420148c04de902fa586b91075bc244b7a8e130c05258617e0dddf0d8b00`。安全解包recovered_combined_v1/；manifest292内容项+清单自身共293文件逐项大小/SHA通过，原机器人结果保留。最终35attempt=30complete+4superseded+1failed；只用六个完整5job块，共29495条有效测量（15887 detector、13608 system）。与既有70单项合计100有效性能作业、107385行，不含阶段0/正确性/中断尝试。

combined_recovery_v1_integrity.json核验99源码/18模型/38候选payload/10工具门禁/189参考及261历史/当前job artifact，errors=[]。performance manifest仍304ad65b33cbe5c37f723f0e67e64c64beb70b0237817d0eb5798486b36cfe06，Engine仍98c1b6bc703b29874d95db94d9cf51ef5b4a4142a7ca6cf22362a0c616fbf348。

combined_numeric_review.json由CPU审查器review_combined_performance.py重算，status=collection_review、validation_passed=true、full_matrix_reviewed=true、errors=[]。COMBINED_PHASE_GATE.json记录R4为研究主候选、C2不默认采用、B5/物理精度/生产批准为false、后续paused_by_user。三个独立FINAL_REVIEW的六份MD/JSON在phase5/independent_reviews/，逐项SHA见independent_reviews_manifest.json；measurement_window_telemetry.json/.csv按UTC、重启会话及system cycle窗口对齐，897测量期样本均408MHz。

新CPU工具49项通过；旧报告原文备份phase5/report_history/并保存内容manifest。CURRENT_PHASE.json已更新审查完成/暂停，PAUSE_STATUS.json与NEXT_RUN明确无待自动执行的长任务。没有启动B5、生产安装、E05或新的GPU/相机实验；没有安排自动监视。最终阶段报告REPORT.md及性能表已重写为统一口径，不能把旧阶段“待运行”语句当当前状态。

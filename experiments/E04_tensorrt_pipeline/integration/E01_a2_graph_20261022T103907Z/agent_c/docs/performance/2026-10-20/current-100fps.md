# 100 FPS 配置下的重新测量

机器人 192.168.98.244，SDK 确认 VGA@100，E01_best engine，batch=2、640，目标发布50 Hz，开启Viser、关闭点云。每组30秒，排除前20帧。正常计时发布频率13.5066 Hz。详细计时组使用CUDA同步和CUDA Event，不能与正常组各项直接相加。临时脚本运行于独立ROS domain 97，项目代码及配置未改动。

|阶段|正常组平均ms|P95 ms|
|---|---:|---:|
|camera_grab|1.794|1.925|
|camera_retrieve_each|1.111|1.251|
|camera_read_total|4.548|4.838|
|resize_letterbox|6.364|6.566|
|yolo_preprocess|9.771|10.038|
|yolo_inference|29.706|29.805|
|yolo_postprocess|13.890|15.812|
|candidates_each|2.088|2.558|
|detector_total|60.369|62.857|
|stereo_selection|0.523|0.592|
|localization|0.193|0.222|
|tracking|0.081|0.090|
|pipeline_total|65.892|68.425|
|payload|0.011|0.011|
|diagnostics|0.160|0.187|
|scheduler_wait|0.009|0.009|
|ros_publish|1.328|1.432|
|image_timestamp_to_publish|78.225|83.866|
|viser_image|4.356|4.485|
|viser_total|6.407|6.733|

详细组：engine execute_v2 的 CUDA Event 均值29.569 ms；Tensor.to均值1.486 ms（本次每帧一次，预处理搬入GPU）；Tensor.cpu每次0.752 ms，本组每帧累计约2.891 ms；NMS每次2.371 ms，每帧累计约3.038 ms。归一化和float转换钩子还覆盖其他后处理调用，不将其混同为预处理单项。

图像时间戳到发布返回均值78.225 ms，P95 83.866 ms，基于SDK当前时间减IMAGE时间戳，再加本地单调时钟耗时；不是订阅端或控制器实际接收延迟。grab包含SDK工作与等待，未独立分离纯等待。白平衡属于相机ISP，无独立Python计时。Decode与过滤未单独分离。嵌套项目不可重复相加；检测总计包含预处理、推理、后处理和候选转换。场景候选数量及浏览器连接可能变化。

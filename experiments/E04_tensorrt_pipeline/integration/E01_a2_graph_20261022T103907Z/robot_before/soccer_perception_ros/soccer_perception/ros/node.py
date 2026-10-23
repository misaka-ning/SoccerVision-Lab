"""足球感知的 ROS 2 接入层：读取参数、组织处理循环并发布消息。

调用链：scripts/soccer_perception_ros_node.py → main() → run_ros_node()。
本模块负责 ROS 通信和运行控制；相机采集、检测、定位与跟踪由 pipeline 执行，
算法模块本身不依赖 ROS。阅读主流程时，可先看文件末尾的 main()，再看
run_ros_node()，最后进入 pipeline.py 的 open() 和 next_packet()。
"""

from __future__ import annotations

import json
import math
from dataclasses import fields
from typing import Any

from soccer_perception.ros.output import (
    OutputScheduler,
    build_ball_camera_diagnostics,
    build_ball_position_camera_payload,
)
from soccer_perception.types import BackendConfig
from soccer_perception.pipeline import PipelineFactory
from soccer_perception.types import json_safe
from soccer_perception.resources import (
    deployment_config_path,
    load_deployment_parameters,
    resolve_resource_path,
)


def _read_deployment_params() -> dict[str, Any]:
    """按部署清单合并各职责 YAML，检查参数与 BackendConfig 字段是否完全一致。

    YAML 是配置值的来源；BackendConfig 只定义字段和类型，不提供默认值。
    文件加载器拒绝重复参数；这里拒绝缺失和未知参数，避免拼写错误被忽略。
    """
    # 由资源模块定位源码目录或安装目录中的配置，不依赖终端当前所在目录。
    path = deployment_config_path()
    # 清单列出的每份文件仍使用“节点名称 → ros__parameters”的 ROS 参数格式。
    params = load_deployment_parameters(path)
    # 从数据类中取出全部字段名，分别找出缺失项和多余项。
    required = {field.name for field in fields(BackendConfig)}
    missing = required - params.keys()
    unknown = params.keys() - required
    if missing or unknown:
        raise ValueError(f"{path}: missing parameters={sorted(missing)}, unknown parameters={sorted(unknown)}")
    return params


def _get_param(ros_node: Any, name: str, default: object) -> object:
    """以 YAML 值为默认值声明 ROS 参数，返回应用启动参数覆盖后的值。

    这里的 default 来自 YAML，并非代码中另设的配置值。
    如果参数已经声明，则直接读取；其他声明错误继续向上抛出。
    """

    try:
        # 声明时，ROS 会应用 launch 或命令行传入的同名参数覆盖。
        parameter = ros_node.declare_parameter(name, default)
    except Exception as exc:
        if exc.__class__.__name__ != "ParameterAlreadyDeclaredException":
            raise
        parameter = ros_node.get_parameter(name)
    return parameter.value


def _parameter_scalar(field: Any, value: Any) -> Any:
    """按字段类型，把配置值转换为 ROS 参数可使用的标量。

    可选字段不能直接用 Python 的 None 作为普通 ROS 标量，因此先使用
    "unchanged"、空字符串或负数作为占位值，再由 config_from_ros_params()
    还原为算法配置中的 None。类型注解只用于判断类型，不提供默认值。
    """

    # 本文件启用了延迟类型注解，例如 "int | None" 可拆成基础类型和可选标记。
    if field.name == "zed_fps" and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError("zed_fps must be a non-negative integer (0 selects SDK auto mode)")
    kind = str(field.type).split(" | ")[0]
    optional = "None" in str(field.type)
    camera_setting = optional and kind == "int" and field.name.startswith("zed_")
    if camera_setting:
        # ZED 的可选整数参数用 unchanged 表示保持原设置；-1 保留为相机控制值，
        # 不在这里转换成 None，因为它可能表示恢复自动设置。
        if value is None or str(value).lower() in {"", "none", "null", "unchanged"}:
            return "unchanged"
        return int(value)
    if value is None:
        if not optional:
            raise ValueError(f"{field.name}: null is not allowed")
        # 当前配置中的其他可选字段是路径或数值，分别用空字符串或负数占位。
        return "" if kind == "Path" else (-1 if kind == "int" else -1.0)
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            return value.lower() in {"true", "1", "yes", "on"}
        raise ValueError(f"{field.name}: expected boolean")
    if kind in {"str", "Path"}:
        # ROS 参数传递路径字符串；稍后再解析为 pathlib.Path。
        return str(value)
    if isinstance(value, bool):
        # Python 中 bool 是 int 的子类，需先拒绝，避免 True 被当成数值 1。
        raise ValueError(f"{field.name}: expected {kind}, got boolean")
    try:
        return int(value) if kind == "int" else float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field.name}: expected {kind}, got {value!r}") from exc


def config_from_ros_params(ros_node: Any = None) -> BackendConfig:
    """合并 YAML 和可选的 ROS 参数覆盖，构造算法使用的 BackendConfig。

    处理顺序：读取 YAML → 规范标量类型 → 应用 ROS 覆盖 → 还原可选值、
    解析资源路径 → 校验关键范围。ros_node 为 None 时只使用 YAML，
    便于不启动 ROS 就读取配置。ROS 覆盖仅影响本次运行，不写回 YAML。
    """

    params = _read_deployment_params()
    values = {}
    for field in fields(BackendConfig):
        value = _parameter_scalar(field, params[field.name])
        if ros_node is not None:
            # 覆盖后的值也重新检查类型，保证最终配置格式一致。
            value = _parameter_scalar(field, _get_param(ros_node, field.name, value))
        kind = str(field.type).split(" | ")[0]
        optional = "None" in str(field.type)
        if kind == "Path":
            # 可选路径的空值还原为 None；其余路径展开 ~，相对路径按包目录解析。
            value = None if optional and value.lower() in {"", "none", "null", "unchanged"} else resolve_resource_path(value)
        elif optional and kind == "int" and field.name.startswith("zed_"):
            # 相机参数的 unchanged 表示不修改该项 SDK 设置。
            value = None if value == "unchanged" else value
        elif optional and value < 0:
            # 其他可选数值的负数表示不额外限制或交由下游自动选择。
            value = None
        values[field.name] = value
    # 输出周期依赖正且有限的频率；短时漏检容错窗口限制在 (0, 0.5] 秒。
    rate_hz = values["deploy_packet_rate_hz"]
    if not math.isfinite(rate_hz) or rate_hz <= 0.0:
        raise ValueError("deploy_packet_rate_hz must be finite and greater than zero")
    timeout = values["short_loss_tolerance_s"]
    if not math.isfinite(timeout) or not 0 < timeout <= 0.5:
        raise ValueError("short_loss_tolerance_s must be finite and in (0, 0.5]")
    return BackendConfig(**values)


def _log_info(ros_node: Any, message: str, *args: object) -> None:
    """格式化普通日志，优先使用 ROS 2 logger，也兼容提供 loginfo 的对象。"""
    text = message % args if args else message
    if hasattr(ros_node, "get_logger"):
        ros_node.get_logger().info(text)
    elif hasattr(ros_node, "loginfo"):
        ros_node.loginfo(text)


def _log_error(ros_node: Any, message: str, *args: object) -> None:
    """格式化错误日志，优先使用 ROS 2 logger，也兼容提供 logerr 的对象。"""
    text = message % args if args else message
    if hasattr(ros_node, "get_logger"):
        ros_node.get_logger().error(text)
    elif hasattr(ros_node, "logerr"):
        ros_node.logerr(text)


def _ros_should_continue(ros_node: Any) -> bool:
    """判断主循环能否继续：优先查询对象接口，否则检查 ROS 上下文状态。"""
    if hasattr(ros_node, "is_shutdown"):
        return not ros_node.is_shutdown()
    import rclpy

    # 使用该节点所属的上下文，避免误查询其他 ROS 上下文的关闭状态。
    context = getattr(ros_node, "context", None)
    return rclpy.ok(context=context) if context is not None else rclpy.ok()


def _config_summary(config: BackendConfig, *, frame_id: str, position_topic: str, valid_topic: str, status_topic: str) -> str:
    """生成单行启动配置摘要，便于从终端确认实际使用的模型、设备和话题。"""

    return (
        "frame_id={frame_id} "
        "topics(ball_position_camera={position_topic}, valid={valid_topic}, status={status_topic}) "
        "zed(resolution={zed_resolution}, fps={zed_fps}, depth_mode={zed_depth_mode}) "
        "yolo(model={yolo_model}, imgsz={imgsz}, conf={det_conf}, device={device}, tensorrt={yolo_tensorrt}) "
        "tracking(max_coast_frames={max_coast_frames}, max_coast_time_s={max_coast_time_s}, velocity_decay={velocity_decay}) "
        "short_loss(enabled={short_loss_tolerance_enabled}, timeout_s={short_loss_tolerance_s}) "
        "deploy(rate_hz={deploy_packet_rate_hz}, send_invalid={deploy_send_invalid_state}) "
        "measurement=stereo_triangulation "
        "viser(enabled={zed_viser_enabled}, port={zed_viser_port})"
    ).format(
        frame_id=frame_id,
        position_topic=position_topic,
        valid_topic=valid_topic,
        status_topic=status_topic,
        zed_resolution=config.zed_resolution,
        zed_fps=config.zed_fps,
        zed_depth_mode=config.zed_depth_mode,
        yolo_model=config.yolo_model,
        imgsz=config.imgsz,
        det_conf=config.det_conf,
        device=config.device,
        yolo_tensorrt=config.yolo_tensorrt,
        max_coast_frames=config.max_coast_frames,
        max_coast_time_s=config.max_coast_time_s,
        velocity_decay=config.velocity_decay,
        short_loss_tolerance_enabled=config.short_loss_tolerance_enabled,
        short_loss_tolerance_s=config.short_loss_tolerance_s,
        deploy_packet_rate_hz=config.deploy_packet_rate_hz,
        deploy_send_invalid_state=config.deploy_send_invalid_state,
        zed_viser_enabled=config.zed_viser_enabled,
        zed_viser_port=config.zed_viser_port,
    )


class RosBallStatePublisher:
    """将感知结果转换为 ROS 消息，发布位置、有效性和诊断状态。

    坐标采用相机 FLU，单位米：x 向前、y 向左、z 向上。
    PointStamped 只携带时间、坐标系名称和位置，有效性通过独立 Bool 话题发布；
    状态和可选的完整位置数据则以 JSON 字符串形式发布。
    """

    def __init__(
        self,
        ros_node: Any,
        *,
        frame_id: str,
        position_topic: str,
        valid_topic: str,
        status_topic: str,
        json_topic: str,
        publish_json: bool,
        publish_invalid_position: bool,
    ):
        """创建消息发布器，并保存控制 JSON 和无效位置发布行为的开关。"""
        # 在创建发布器时导入 ROS 消息，模块加载阶段不要求导入这些消息类型。
        from geometry_msgs.msg import PointStamped
        from std_msgs.msg import Bool, String

        self.ros_node = ros_node
        self.frame_id = frame_id
        self.publish_json = publish_json
        self.publish_invalid_position = publish_invalid_position
        # 保存消息类，后续发布时通过这些类构造消息实例。
        self._point_cls = PointStamped
        self._bool_cls = Bool
        self._string_cls = String
        # 第三个参数 10 指保留最近消息的队列深度，不是发布频率。
        self.position_pub = ros_node.create_publisher(PointStamped, position_topic, 10)
        self.valid_pub = ros_node.create_publisher(Bool, valid_topic, 10)
        self.status_pub = ros_node.create_publisher(String, status_topic, 10)
        self.json_pub = ros_node.create_publisher(String, json_topic, 10) if publish_json else None

    def publish(self, payload: dict[str, Any], diagnostics: dict[str, Any] | None = None) -> None:
        """发布一次结果；位置是否发送由结果有效性及无效位置开关共同决定。"""

        # 将 NumPy 值转成普通 Python 类型，并把非有限浮点数转成 None。
        safe_payload = json_safe(payload)
        # PointStamped 使用发布时刻的 ROS 时间；payload 中保留流水线结果时间戳。
        stamp = self.ros_node.get_clock().now().to_msg()
        valid = bool(safe_payload.get("valid"))
        # 此处只判断前向坐标是否存在，不代替整份跟踪结果的 valid 标记。
        front_valid = safe_payload.get("x_m") is not None
        # 即使不发送无效位置，也发送有效性，通知下游当前结果是否可用。
        self.valid_pub.publish(self._bool_cls(data=valid))

        # 允许发布无效位置时，缺失坐标会在 _point_from_payload() 中填为 0。
        # 下游需结合有效性话题判断，不能把零坐标直接视为真实位置。
        if valid or self.publish_invalid_position:
            self.position_pub.publish(self._point_from_payload(safe_payload, stamp))

        # 状态话题保存坐标约定及有效性；frame_id 改名不会执行坐标变换。
        status = {
            "valid": valid,
            "confidence": safe_payload.get("confidence"),
            "front_valid": front_valid,
            "coordinate_frame": "camera_flu",
            "axes": {"x": "front", "y": "left", "z": "up"},
            "timestamp": safe_payload.get("timestamp"),
            "frame_id": self.frame_id,
            "publish_invalid_position": self.publish_invalid_position,
        }
        if isinstance(diagnostics, dict):
            # 补充跟踪/预测状态、原始测量有效性、候选筛选原因和实际输出频率。
            # 跟踪结果 valid 与原始测量 measurement_valid 含义不同：短时预测时，
            # 原始测量可能无效，但跟踪位置仍可在容错窗口内供下游使用。
            status.update(
                {
                    "track_mode": diagnostics.get("track_mode"),
                    "coasting": diagnostics.get("coasting"),
                    "frames_since_measurement": diagnostics.get("frames_since_measurement"),
                    "measurement_source": diagnostics.get("measurement_source"),
                    "measurement_valid": diagnostics.get("measurement_valid"),
                    "short_loss_tolerated": diagnostics.get("short_loss_tolerated", False),
                    "short_loss_age_s": diagnostics.get("short_loss_age_s"),
                    "short_loss_timeout_s": diagnostics.get("short_loss_timeout_s", 0.0),
                    "measurement_quality": diagnostics.get("measurement_quality"),
                    "measurement_reject_reasons": diagnostics.get("measurement_reject_reasons"),
                    "measurement_status": diagnostics.get("measurement_status"),
                    "candidate_selection": diagnostics.get("candidate_selection"),
                    "output_rate_hz": diagnostics.get("output_rate_hz"),
                }
            )
        self.status_pub.publish(self._json(status))
        # 完整位置 JSON 由 publish_json 控制，不影响上面的状态话题。
        if self.json_pub is not None:
            self.json_pub.publish(self._json(safe_payload))

    def publish_status_only(self, payload: dict[str, Any], diagnostics: dict[str, Any] | None = None) -> None:
        """无效结果被配置为不完整发送时，仅发布 valid=false 和状态。

        主循环在 payload 无效且 deploy_send_invalid_state 为 false 时调用。
        此分支不发布位置或完整位置 JSON，即使 publish_invalid_position 为 true。
        """

        safe_payload = json_safe(payload)
        status = {
            "valid": bool(safe_payload.get("valid")),
            "confidence": safe_payload.get("confidence"),
            "front_valid": safe_payload.get("x_m") is not None,
            "coordinate_frame": "camera_flu",
            "axes": {"x": "front", "y": "left", "z": "up"},
            "timestamp": safe_payload.get("timestamp"),
            "frame_id": self.frame_id,
            # 告知下游：这一帧未发送完整的位置 JSON。
            "dropped_json": True,
        }
        if isinstance(diagnostics, dict):
            status.update(
                {
                    "track_mode": diagnostics.get("track_mode"),
                    "coasting": diagnostics.get("coasting"),
                    "frames_since_measurement": diagnostics.get("frames_since_measurement"),
                    "measurement_source": diagnostics.get("measurement_source"),
                    "measurement_valid": diagnostics.get("measurement_valid"),
                    "short_loss_tolerated": diagnostics.get("short_loss_tolerated", False),
                    "short_loss_age_s": diagnostics.get("short_loss_age_s"),
                    "short_loss_timeout_s": diagnostics.get("short_loss_timeout_s", 0.0),
                    "measurement_quality": diagnostics.get("measurement_quality"),
                    "measurement_reject_reasons": diagnostics.get("measurement_reject_reasons"),
                    "measurement_status": diagnostics.get("measurement_status"),
                    "candidate_selection": diagnostics.get("candidate_selection"),
                    "output_rate_hz": diagnostics.get("output_rate_hz"),
                }
            )
        self.valid_pub.publish(self._bool_cls(data=False))
        self.status_pub.publish(self._json(status))

    def _point_from_payload(self, payload: dict[str, Any], stamp: Any) -> Any:
        """把 FLU 坐标填入 PointStamped；缺失坐标用 0 填充，不执行坐标变换。"""
        point = self._point_cls()
        point.header.stamp = stamp
        point.header.frame_id = self.frame_id
        point.point.x = float(payload.get("x_m") or 0.0)
        point.point.y = float(payload.get("y_m") or 0.0)
        point.point.z = float(payload.get("z_m") or 0.0)
        return point

    def _json(self, payload: dict[str, Any]) -> Any:
        """将字典序列化为紧凑 JSON，并封装成 std_msgs/String 消息。"""
        # 保留中文字符、去掉多余空格，并禁止输出非标准的 NaN/Infinity 字面值。
        return self._string_cls(
            data=json.dumps(
                json_safe(payload),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        )


def run_ros_node(ros_node: Any) -> None:
    """组织感知节点的准备、逐帧处理、定频输出和流水线资源释放。

    这是同步主循环：每轮主动读取并处理一帧，再发布其结果。
    相机输入由 pipeline 直接获取，不通过 ROS 图像订阅回调驱动。
    """

    # 第一步：构造运行配置，并按配置创建位置、有效性、状态及可选 JSON 发布器。
    config = config_from_ros_params(ros_node)
    publisher = RosBallStatePublisher(
        ros_node,
        frame_id=config.frame_id,
        position_topic=config.position_topic,
        valid_topic=config.valid_topic,
        status_topic=config.status_topic,
        json_topic=config.json_topic,
        publish_json=config.publish_json,
        publish_invalid_position=config.publish_invalid_position,
    )
    # 第二步：准备输出调度器，并组装相机输入源、YOLO 检测器和跟踪器。
    # create() 负责组装对象；实际打开硬件和加载模型发生在下面的 open()。
    scheduler = OutputScheduler(config.deploy_packet_rate_hz)
    pipeline = PipelineFactory(config).create()

    # frames 统计处理帧数；published 统计输出轮次，一轮可能发布多条 ROS 消息。
    frames = 0
    published = 0
    try:
        _log_info(
            ros_node,
            "soccer_perception_ros starting source=zed detector=yolo %s",
            _config_summary(
                config,
                frame_id=config.frame_id,
                position_topic=config.position_topic,
                valid_topic=config.valid_topic,
                status_topic=config.status_topic,
            ),
        )
        # 第三步：打开 ZED、加载模型、准备双目三角化和可选可视化。
        # 将初始化进度回调接入 ROS 日志，便于定位启动停在哪一步。
        pipeline.open(progress=lambda message: _log_info(ros_node, message))
        # 初始化完成后才开始计时，避免把模型加载耗时计入首个输出周期。
        scheduler.start()
        while _ros_should_continue(ros_node):
            # 第四步：采集左右目 → 检测候选 → 双目匹配/定位 → 跟踪，返回 FramePacket。
            packet = pipeline.next_packet()
            if packet is None:
                # None 表示输入结束；没有检测到球时仍会返回包含无效状态的数据包。
                _log_info(ros_node, "soccer_perception_ros input ended after %d frames", frames)
                break
            frames += 1
            # 分开整理控制端需要的位置数据与排查问题所需的详细诊断数据。
            payload = build_ball_position_camera_payload(packet)
            diagnostics = build_ball_camera_diagnostics(packet)
            # 按目标频率等待输出；处理速度不足时按实际速度输出，不补发旧结果。
            scheduler.wait()
            # 等待期间可能收到关闭请求，因此发布前再次确认 ROS 仍在运行。
            if not _ros_should_continue(ros_node):
                break
            # 记录实际输出频率，便于判断设备是否达到配置的目标频率。
            diagnostics["output_rate_hz"] = scheduler.record_publish()
            # 无效结果也明确通知下游；开关决定是否只发状态，或走完整发布流程。
            if not payload["valid"] and not config.deploy_send_invalid_state:
                publisher.publish_status_only(payload, diagnostics)
            else:
                publisher.publish(payload, diagnostics)
            published += 1
            # 可视化随每次 ROS 输出更新，展示与本轮发布相对应的处理结果。
            pipeline.update_visualization(packet)
    finally:
        # open() 或循环抛出异常、输入结束、ROS 关闭时，都尝试释放流水线资源。
        pipeline.close()
        _log_info(
            ros_node,
            "soccer_perception_ros stopped frames=%d published=%d",
            frames,
            published,
        )


def main(args: list[str] | None = None) -> None:
    """供入口脚本调用：初始化 ROS、创建节点，并管理节点的退出清理。

    这里是函数调用，不创建新的感知进程。args 为 None 时，rclpy 从当前进程的
    命令行读取 ROS 参数，包括 launch 传入的参数文件和节点名称等设置。
    """

    import rclpy

    # 初始化 ROS 通信上下文，再创建用于参数、日志和消息发布的节点。
    rclpy.init(args=args)
    ros_node = rclpy.create_node("soccer_perception_ros")
    context = ros_node.context
    try:
        # 阻塞执行主循环，直到 ROS 关闭、输入结束或发生异常。
        run_ros_node(ros_node)
    except Exception as exc:
        # 记录错误后继续抛出，让启动管理进程能够发现节点运行失败。
        _log_error(ros_node, "soccer_perception_ros failed: %s", exc)
        raise
    finally:
        # run_ros_node() 负责流水线资源；这里负责销毁节点并关闭其 ROS 上下文。
        ros_node.destroy_node()
        # 上下文可能已由退出信号关闭，仍有效时才执行 shutdown()。
        if rclpy.ok(context=context):
            rclpy.shutdown(context=context)

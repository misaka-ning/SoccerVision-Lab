"""Process-local scalar observation of the real ROS payload construction.

No tensor access, I/O, clock conversion, frame-age estimate or payload mutation.
``calls`` counts payloads successfully returned by the original builder.
"""

_ABSENT = object()
_NAME = "build_ball_position_camera_payload"
_MARKER = "_e04_packet_payload_observer"

FIELDS = (
    "frame_idx", "frame_timestamp_s", "measurement_valid", "tracking_valid",
    "track_initialized", "coasting", "frames_since_measurement",
)


class PacketPayloadObserver:
    def __init__(self, node):
        if getattr(node, _MARKER, None) is not None:
            raise RuntimeError("A packet payload observer is already installed")
        original = getattr(node, _NAME)
        if not callable(original):
            raise TypeError("The node payload builder must be callable")
        self._node = node
        self._previous_attribute = vars(node).get(_NAME, _ABSENT)
        self._original = original
        self.last_metrics = {}
        self.calls = 0
        self.restored = False

        def observed(packet, *args, **kwargs):
            payload = original(packet, *args, **kwargs)
            track = packet.camera_track_state
            # Replace the dictionary atomically; never retain packet, payload,
            # position arrays, tensors or another frame's mutable track state.
            self.last_metrics = {
                "frame_idx": int(packet.frame_idx),
                "frame_timestamp_s": float(packet.timestamp),
                "measurement_valid": int(bool(packet.ball_3d_measurement.valid)),
                "tracking_valid": int(bool(payload["valid"])),
                "track_initialized": int(bool(track.initialized)),
                "coasting": int(bool(track.coasting)),
                "frames_since_measurement": int(track.frames_since_measurement),
            }
            self.calls += 1
            return payload

        self._wrapper = observed
        setattr(node, _NAME, observed)
        setattr(node, _MARKER, self)

    def restore(self):
        if self.restored:
            return
        if vars(self._node).get(_NAME, _ABSENT) is not self._wrapper:
            raise RuntimeError("Payload builder changed after install; refusing to overwrite it")
        if self._previous_attribute is _ABSENT:
            delattr(self._node, _NAME)
        else:
            setattr(self._node, _NAME, self._previous_attribute)
        if getattr(self._node, _MARKER, None) is self:
            delattr(self._node, _MARKER)
        self.restored = True


def install_node_payload_observer(node):
    """Observe this node namespace only; restore before removing its owner."""
    return PacketPayloadObserver(node)

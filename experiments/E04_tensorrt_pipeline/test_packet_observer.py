import copy
import types
import unittest

from packet_observer import FIELDS, install_node_payload_observer


def packet(frame=123, timestamp=1.25, measured=True, initialized=True, coasting=False, age=0):
    return types.SimpleNamespace(
        frame_idx=frame, timestamp=timestamp,
        ball_3d_measurement=types.SimpleNamespace(valid=measured),
        camera_track_state=types.SimpleNamespace(initialized=initialized, coasting=coasting,
                                                frames_since_measurement=age),
    )


class PacketObserverTests(unittest.TestCase):
    def test_original_called_once_identity_and_input_are_preserved(self):
        value = packet()
        before = copy.deepcopy(value)
        payload = {"valid": True, "timestamp": 1.25, "x_m": 2.0}
        seen = []
        def build(p, *args, **kwargs):
            seen.append((p, args, kwargs))
            return payload
        node = types.SimpleNamespace(build_ball_position_camera_payload=build)
        handle = install_node_payload_observer(node)
        actual = node.build_ball_position_camera_payload(value, "extra", test=17)
        self.assertIs(actual, payload)
        self.assertEqual(payload, {"valid": True, "timestamp": 1.25, "x_m": 2.0})
        self.assertEqual(value, before)
        self.assertEqual(seen, [(value, ("extra",), {"test": 17})])
        self.assertEqual(handle.calls, 1)
        self.assertEqual(tuple(handle.last_metrics), FIELDS)
        self.assertEqual(handle.last_metrics, dict(frame_idx=123, frame_timestamp_s=1.25,
                         measurement_valid=1, tracking_valid=1, track_initialized=1,
                         coasting=0, frames_since_measurement=0))
        self.assertTrue(all(type(v) in (int, float) for v in handle.last_metrics.values()))
        handle.restore()
        handle.restore()
        self.assertIs(node.build_ball_position_camera_payload, build)

    def test_prediction_can_be_tracking_valid_without_measurement(self):
        node = types.SimpleNamespace(build_ball_position_camera_payload=lambda p: {"valid": True})
        handle = install_node_payload_observer(node)
        node.build_ball_position_camera_payload(packet(measured=False, coasting=True, age=3))
        self.assertEqual(handle.last_metrics["measurement_valid"], 0)
        self.assertEqual(handle.last_metrics["tracking_valid"], 1)
        self.assertEqual(handle.last_metrics["coasting"], 1)
        self.assertEqual(handle.last_metrics["frames_since_measurement"], 3)
        handle.restore()

    def test_lost_or_unusable_tracking_is_not_guessed_from_measurement(self):
        node = types.SimpleNamespace(build_ball_position_camera_payload=lambda p: {"valid": False})
        handle = install_node_payload_observer(node)
        node.build_ball_position_camera_payload(packet(measured=True, initialized=True))
        self.assertEqual(handle.last_metrics["measurement_valid"], 1)
        self.assertEqual(handle.last_metrics["track_initialized"], 1)
        self.assertEqual(handle.last_metrics["tracking_valid"], 0)
        handle.restore()

    def test_new_frame_replaces_scalar_snapshot_without_mutating_old_cache(self):
        payload = {"valid": True}
        node = types.SimpleNamespace(build_ball_position_camera_payload=lambda p: payload)
        handle = install_node_payload_observer(node)
        first = packet()
        node.build_ball_position_camera_payload(first)
        old = handle.last_metrics
        first.frame_idx = 999
        first.camera_track_state.coasting = True
        payload["valid"] = False
        self.assertEqual(old["frame_idx"], 123)
        self.assertEqual(old["coasting"], 0)
        self.assertEqual(old["tracking_valid"], 1)
        node.build_ball_position_camera_payload(packet(frame=124, timestamp=1.3, measured=False,
                                                       initialized=False, age=10))
        self.assertIsNot(handle.last_metrics, old)
        self.assertEqual(handle.calls, 2)
        self.assertEqual(handle.last_metrics["frame_idx"], 124)
        self.assertEqual(handle.last_metrics["tracking_valid"], 0)
        handle.restore()

    def test_original_exception_propagates_without_extra_call_or_stale_update(self):
        sentinel = RuntimeError("original error")
        calls = []
        def build(p):
            calls.append(p)
            raise sentinel
        node = types.SimpleNamespace(build_ball_position_camera_payload=build)
        handle = install_node_payload_observer(node)
        value = packet()
        with self.assertRaises(RuntimeError) as found:
            node.build_ball_position_camera_payload(value)
        self.assertIs(found.exception, sentinel)
        self.assertEqual(calls, [value])
        self.assertEqual(handle.calls, 0)
        self.assertEqual(handle.last_metrics, {})
        handle.restore()

    def test_inherited_builder_is_restored_by_removing_instance_attribute(self):
        class Node:
            def build_ball_position_camera_payload(self, p):
                return {"valid": False}
        node = Node()
        handle = install_node_payload_observer(node)
        node.build_ball_position_camera_payload(packet(initialized=False, measured=False))
        self.assertIn("build_ball_position_camera_payload", vars(node))
        handle.restore()
        self.assertNotIn("build_ball_position_camera_payload", vars(node))
        self.assertEqual(node.build_ball_position_camera_payload(packet()), {"valid": False})

    def test_duplicate_install_and_external_replacement_do_not_clobber_hooks(self):
        node = types.SimpleNamespace(build_ball_position_camera_payload=lambda p: {"valid": True})
        handle = install_node_payload_observer(node)
        with self.assertRaises(RuntimeError):
            install_node_payload_observer(node)
        replacement = lambda p: {"valid": False}
        node.build_ball_position_camera_payload = replacement
        with self.assertRaises(RuntimeError):
            handle.restore()
        self.assertIs(node.build_ball_position_camera_payload, replacement)
        self.assertFalse(handle.restored)
        # The owner can remove its outer wrapper and retry restoration safely.
        node.build_ball_position_camera_payload = handle._wrapper
        handle.restore()
        self.assertTrue(handle.restored)


if __name__ == "__main__":
    unittest.main()

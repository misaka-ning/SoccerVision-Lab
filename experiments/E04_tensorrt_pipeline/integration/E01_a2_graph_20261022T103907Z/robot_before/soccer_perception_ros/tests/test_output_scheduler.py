"""Publication timing under variable workloads and late wake-ups, without hardware."""
import unittest
from unittest.mock import patch

from soccer_perception.ros.output import OutputScheduler


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.wake_delay = 0.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds

    def sleep(self, seconds):
        self.advance(seconds + self.wake_delay)


class OutputSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        patches = (
            patch('soccer_perception.ros.output.time.monotonic', self.clock.monotonic),
            patch('soccer_perception.ros.output.time.sleep', self.clock.sleep),
        )
        for mocked in patches:
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_15_hz_workload_produces_10_hz_without_halving(self):
        scheduler = OutputScheduler(10.)
        scheduler.start()
        times = []
        for _ in range(100):
            self.clock.advance(1 / 15)
            scheduler.wait()
            times.append(self.clock.now)
            measured = scheduler.record_publish()
        self.assertAlmostEqual(times[-1] - times[0], 9.9)
        self.assertAlmostEqual(measured, 10.)
        for before, after in zip(times, times[1:]):
            self.assertAlmostEqual(after - before, .1)

    def test_processing_and_publish_cost_are_included_without_sleep_drift(self):
        scheduler = OutputScheduler(10.)
        scheduler.start()
        self.clock.wake_delay = .001
        for work in (.02, .075, .04, .06) * 50:
            self.clock.advance(work)
            scheduler.wait()
            measured = scheduler.record_publish()
            self.clock.advance(.005)
        self.assertAlmostEqual(self.clock.now, 20.006)
        self.assertAlmostEqual(measured, 10.)

    def test_overrun_skips_backlog_instead_of_catching_up(self):
        scheduler = OutputScheduler(10.)
        scheduler.start()
        self.clock.advance(.35)
        scheduler.wait()
        self.assertAlmostEqual(self.clock.now, .35)
        self.clock.advance(.01)
        scheduler.wait()
        self.assertAlmostEqual(self.clock.now, .45)

    def test_insufficient_compute_reports_actual_frequency(self):
        scheduler = OutputScheduler(10.)
        scheduler.start()
        for _ in range(50):
            self.clock.advance(.15)
            scheduler.wait()
            measured = scheduler.record_publish()
        self.assertAlmostEqual(self.clock.now, 7.5)
        self.assertAlmostEqual(measured, 1 / .15)

    def test_partial_period_overrun_does_not_compress_next_interval(self):
        scheduler = OutputScheduler(10.)
        scheduler.start()
        self.clock.advance(.19)
        scheduler.wait()
        self.clock.advance(.01)
        scheduler.wait()
        self.assertAlmostEqual(self.clock.now, .29)

    def test_early_sleep_return_still_waits_until_deadline(self):
        scheduler = OutputScheduler(10.)
        scheduler.start()
        def early_sleep(seconds):
            self.clock.advance(min(seconds, .025))
        with patch('soccer_perception.ros.output.time.sleep', early_sleep):
            scheduler.wait()
        self.assertAlmostEqual(self.clock.now, .1)

    def test_invalid_rates_are_rejected(self):
        for rate in (0., -1., float('nan'), float('inf')):
            with self.subTest(rate=rate):
                with self.assertRaises(ValueError):
                    OutputScheduler(rate)


if __name__ == '__main__':
    unittest.main()

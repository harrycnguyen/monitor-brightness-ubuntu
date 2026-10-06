import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from monitor_brightness import backlight, ddc, manager, proc, xrandr
from monitor_brightness.display import BrightnessError, Display
from monitor_brightness.writer import CoalescingWriter

DETECT = """\
Display 1
   I2C bus:             /dev/i2c-5
   DRM connector:       card1-DP-2
   EDID synopsis:
      Mfg id:           DEL - Dell Inc.
      Model:            DELL U2720Q
      Serial number:    ABC123
   VCP version:         2.1

Invalid display
   I2C bus:             /dev/i2c-3
   DRM connector:       card1-HDMI-A-1
   EDID synopsis:
      Mfg id:           XXX
      Model:            Broken

Display 2
   I2C bus:             /dev/i2c-7
   DRM connector:       card1-HDMI-A-2
   EDID synopsis:
      Model:            LG ULTRAGEAR
"""

XRANDR = """\
Screen 0: minimum 16 x 16, current 3840 x 1080
eDP-1 connected primary 1920x1080+0+0
\tBrightness: 1.0
\tGamma: 1.0:1.0:1.0
DP-2 connected 1920x1080+1920+0
\tBrightness: 0.6
HDMI-2 connected 1920x1080+3840+0
\tBrightness: 1.0
DP-3 connected 1920x1080+5760+0
\tBrightness: 0.8
HDMI-1 disconnected
\tBrightness: 0.3
"""


def fake_run(stdout="", returncode=0, stderr=""):
    calls = []

    def run(cmd, timeout=15.0):
        calls.append(cmd)
        return proc.Result(returncode, stdout, stderr)

    run.calls = calls
    return run


class DdcTests(unittest.TestCase):
    def test_parse_detect_skips_invalid(self):
        infos = ddc.parse_detect(DETECT)
        self.assertEqual([(i.number, i.name, i.drm_connector) for i in infos],
                         [(1, "DELL U2720Q", "card1-DP-2"), (2, "LG ULTRAGEAR", "card1-HDMI-A-2")])

    def test_parse_getvcp(self):
        self.assertEqual(ddc.parse_getvcp("VCP 10 C 45 100\n"), (45, 100))
        with self.assertRaises(BrightnessError):
            ddc.parse_getvcp("garbage")

    def test_get_and_set_scale_to_monitor_max(self):
        d = ddc.DdcDisplay(ddc.DdcInfo(1, "M", None))
        with mock.patch.object(proc, "run", fake_run("VCP 10 C 30 60\n")):
            self.assertEqual(d.get_percent(), 50)
        run = fake_run()
        with mock.patch.object(proc, "run", run):
            d.set_percent(100)
        self.assertEqual(run.calls[0], ["ddcutil", "setvcp", "10", "60", "--noverify", "--display", "1"])

    def test_failure_raises(self):
        d = ddc.DdcDisplay(ddc.DdcInfo(1, "M", None))
        with mock.patch.object(proc, "run", fake_run(returncode=1, stderr="no DDC")):
            with self.assertRaises(BrightnessError):
                d.get_percent()


class BacklightTests(unittest.TestCase):
    def test_sysfs_fallback_and_floor(self):
        with tempfile.TemporaryDirectory() as t:
            dev = Path(t) / "intel_backlight"
            dev.mkdir()
            (dev / "max_brightness").write_text("200")
            (dev / "brightness").write_text("100")
            d = backlight.BacklightDisplay("intel_backlight", Path(t))
            self.assertEqual(d.get_percent(), 50)
            with mock.patch.object(proc, "run", side_effect=FileNotFoundError):
                d.set_percent(25)
                self.assertEqual((dev / "brightness").read_text(), "50")
                d.set_percent(0)  # must not turn the panel off
                self.assertEqual((dev / "brightness").read_text(), "1")

    def test_prefers_logind(self):
        with tempfile.TemporaryDirectory() as t:
            dev = Path(t) / "bl"
            dev.mkdir()
            (dev / "max_brightness").write_text("100")
            (dev / "brightness").write_text("10")
            run = fake_run()
            with mock.patch.object(proc, "run", run):
                backlight.BacklightDisplay("bl", Path(t)).set_percent(40)
            self.assertEqual(run.calls[0][-3:], ["backlight", "bl", "40"])
            self.assertEqual((dev / "brightness").read_text(), "10")


class XrandrTests(unittest.TestCase):
    def test_parse_outputs(self):
        self.assertEqual(xrandr.parse_outputs(XRANDR), {"eDP-1": 1.0, "DP-2": 0.6, "HDMI-2": 1.0, "DP-3": 0.8})

    def test_normalize(self):
        self.assertEqual(xrandr.normalize_connector("card1-HDMI-A-2"), "HDMI-2")
        self.assertEqual(xrandr.normalize_connector("card0-DP-2"), "DP-2")

    def test_set_floor(self):
        run = fake_run()
        with mock.patch.object(proc, "run", run):
            xrandr.SoftwareDisplay("DP-2").set_percent(0)
        self.assertEqual(run.calls[0], ["xrandr", "--output", "DP-2", "--brightness", "0.10"])


class ManagerTests(unittest.TestCase):
    def _discover(self, env):
        def run(cmd, timeout=15.0):
            if cmd[0] == "ddcutil":
                return proc.Result(0, DETECT, "")
            return proc.Result(0, XRANDR, "")

        with mock.patch.object(proc, "run", run), \
                mock.patch.object(backlight, "detect", lambda: [backlight.BacklightDisplay("bl")]):
            return manager.discover(env)

    def test_x11_adds_only_unclaimed_outputs(self):
        found = self._discover({"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"})
        # DP-2 and HDMI-2 are the two DDC monitors and eDP-1 is the backlight panel,
        # so only DP-3 (no DDC) gets software dimming.
        self.assertEqual([d.id for d in found.displays],
                         ["backlight:bl", "ddc:1", "ddc:2", "software:DP-3"])

    def test_wayland_has_no_software(self):
        found = self._discover({"DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"})
        self.assertFalse([d for d in found.displays if d.kind == "software"])
        self.assertTrue(found.notes)

    def test_missing_ddcutil_is_a_note(self):
        with mock.patch.object(proc, "run", side_effect=FileNotFoundError), \
                mock.patch.object(backlight, "detect", lambda: []):
            found = manager.discover({})
        self.assertEqual(found.displays, [])
        self.assertIn("ddcutil is not installed", found.notes[0])

    def test_select(self):
        a, b = ddc.DdcDisplay(ddc.DdcInfo(1, "Dell", None)), ddc.DdcDisplay(ddc.DdcInfo(2, "LG", None))
        self.assertEqual(manager.select([a, b], "2"), [b])
        self.assertEqual(manager.select([a, b], "ddc:1"), [a])
        self.assertEqual(manager.select([a, b], "dell"), [a])
        self.assertEqual(manager.select([a, b], "9"), [])


class SlowDisplay(Display):
    id, name, kind = "slow", "Slow", "ddc"

    def __init__(self):
        self.written = []
        self.gate = threading.Event()

    def get_percent(self):
        return 0

    def set_percent(self, percent):
        self.gate.wait(2)
        self.written.append(percent)


class WriterTests(unittest.TestCase):
    def test_only_latest_value_is_written_while_busy(self):
        d = SlowDisplay()
        w = CoalescingWriter()
        for v in (10, 20, 30, 40, 50):
            w.request(d, v)
        d.gate.set()
        self.assertTrue(w.wait_idle())
        self.assertEqual(d.written[-1], 50)
        self.assertLessEqual(len(d.written), 2)  # the first value in flight, then the latest

    def test_errors_are_reported_not_raised(self):
        class Bad(SlowDisplay):
            def set_percent(self, percent):
                raise BrightnessError("boom")

        errors = []
        w = CoalescingWriter(on_error=lambda d, e: errors.append(str(e)))
        w.request(Bad(), 5)
        w.wait_idle()
        self.assertEqual(errors, ["boom"])


if __name__ == "__main__":
    unittest.main()

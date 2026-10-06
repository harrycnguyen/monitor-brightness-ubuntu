import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from monitor_brightness import cli, manager
from monitor_brightness.display import BrightnessError, Display


class Fake(Display):
    kind = "ddc"

    def __init__(self, n, level, fail=False):
        self.id, self.name, self.level, self.fail = f"ddc:{n}", f"Mon{n}", level, fail

    def get_percent(self):
        return self.level

    def set_percent(self, percent):
        if self.fail:
            raise BrightnessError("nope")
        self.level = percent


def run(argv, displays):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(manager, "discover", lambda: manager.Discovery(displays, ["a note"])), \
            redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_set_all_and_one(self):
        a, b = Fake(1, 10), Fake(2, 20)
        self.assertEqual(run(["set", "70"], [a, b])[0], 0)
        self.assertEqual((a.level, b.level), (70, 70))
        run(["set", "30", "-d", "2"], [a, b])
        self.assertEqual((a.level, b.level), (70, 30))

    def test_up_down_clamp(self):
        a = Fake(1, 95)
        run(["up", "10"], [a])
        self.assertEqual(a.level, 100)
        run(["down", "150"], [a])
        self.assertEqual(a.level, 0)

    def test_one_failure_does_not_stop_others(self):
        bad, good = Fake(1, 10, fail=True), Fake(2, 10)
        code, _, err = run(["set", "50"], [bad, good])
        self.assertEqual(code, 1)
        self.assertEqual(good.level, 50)
        self.assertIn("nope", err)

    def test_list_json(self):
        code, out, _ = run(["list", "--json"], [Fake(1, 42)])
        data = json.loads(out)
        self.assertEqual(data["displays"][0]["brightness"], 42)
        self.assertEqual(data["notes"], ["a note"])

    def test_unknown_display(self):
        code, _, err = run(["set", "5", "-d", "zzz"], [Fake(1, 1)])
        self.assertEqual(code, 1)
        self.assertIn("No display matches", err)


if __name__ == "__main__":
    unittest.main()

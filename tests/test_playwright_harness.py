import unittest

from toolcalltokenization.playwright_harness import (
    binding_map_from_args,
    fill_value_for_step,
    parse_canonical_step,
    primitive_name_for_step,
    stringify_args,
)


class PlaywrightHarnessParsingTest(unittest.TestCase):
    def test_parse_canonical_step(self) -> None:
        parsed = parse_canonical_step("TYPE|role=input|label=search|use=B01")
        self.assertEqual(parsed["action"], "TYPE")
        self.assertEqual(parsed["fields"]["role"], "input")
        self.assertEqual(parsed["fields"]["use"], "B01")

    def test_binding_map_from_args(self) -> None:
        bindings = binding_map_from_args(
            [{"name": "arg1", "binding_id": "B01"}, {"name": "arg2", "binding_id": "B02"}],
            {"arg1": "Chicago", "arg2": "London"},
        )
        self.assertEqual(bindings, {"B01": "Chicago", "B02": "London"})

    def test_fill_value_for_step(self) -> None:
        parsed = parse_canonical_step("TYPE|role=input|label=search|use=B01")
        self.assertEqual(fill_value_for_step(parsed, {"B01": "laptop"}), "laptop")

    def test_primitive_name_for_step(self) -> None:
        parsed = parse_canonical_step("CLICK|role=button|label=search")
        self.assertEqual(primitive_name_for_step(parsed), "click")

    def test_stringify_args(self) -> None:
        self.assertEqual(stringify_args(["arg1=Seattle", "arg2=Boston"]), {"arg1": "Seattle", "arg2": "Boston"})


if __name__ == "__main__":
    unittest.main()

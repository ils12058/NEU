"""Regression checks for the smoke verifier's firmware-independent contract."""

import unittest

from neuboot import inspect_console


class ConsoleTests(unittest.TestCase):
    version = "9.8.7"

    def console(self, graphics=None):
        if graphics is None:
            graphics = (
                "[INFO] GOP: available\n"
                "[INFO] GOP resolution: 1600x900\n"
                "[INFO] GOP pixel format: Bitmask\n"
                "[INFO] GOP framebuffer size: 5760000 bytes\n"
            )
        return (
            f"NEU\nNeuBoot v{self.version}\n\n"
            "[OK] UEFI environment initialized\n"
            "[OK] NeuBoot execution started\n"
            "[INFO] Firmware vendor: Example Firmware\n"
            "[INFO] UEFI specification revision: 2.99\n"
            "[INFO] Firmware revision: 0xdeadbeef\n"
            "[INFO] Memory map: 3 descriptors, 15 pages (4 KiB each)\n"
            "[INFO] Memory type 0 (RESERVED): 2 pages\n"
            "[INFO] Memory type 7 (CONVENTIONAL): 13 pages\n"
            f"{graphics}"
            "[OK] Firmware discovery completed\n"
            "[OK] Bootstrap milestone completed\n"
            "[OK] Returning to firmware\n"
            'BdsDxe: loading BootABCD "Some firmware target"\n'
        )

    def test_values_and_version_are_not_pinned_to_ovmf(self):
        output, resumed = inspect_console(self.console(), self.version)
        self.assertTrue(resumed)
        self.assertIn("[INFO] GOP resolution: 1600x900", output)
        self.assertIsNone(inspect_console(self.console(), "another-version"))

    def test_missing_protocol_is_successful(self):
        console = self.console("[INFO] GOP: unavailable (protocol not found)\n")
        self.assertTrue(inspect_console(console, self.version, no_graphics=True)[1])

    def test_graphics_present_scenario_cannot_pass_without_gop(self):
        self.assertTrue(inspect_console(self.console(), self.version, require_gop=True)[1])
        with self.assertRaisesRegex(RuntimeError, "GOP is required"):
            inspect_console(self.console("[INFO] GOP: unavailable (protocol not found)\n"),
                            self.version, require_gop=True)

    def test_optional_open_failure_can_be_reported(self):
        console = self.console("[WARN] GOP: unavailable (open failed: ACCESS_DENIED)\n")
        self.assertTrue(inspect_console(console, self.version)[1])
        with self.assertRaisesRegex(RuntimeError, "Expected missing GOP"):
            inspect_console(console, self.version, no_graphics=True)

    def test_no_graphics_requires_missing_protocol(self):
        with self.assertRaisesRegex(RuntimeError, "GOP was available"):
            inspect_console(self.console(), self.version, no_graphics=True)

    def test_blt_only_has_no_direct_framebuffer(self):
        console = self.console().replace("Bitmask", "BltOnly").replace(
            "5760000 bytes", "unavailable (BltOnly)"
        )
        self.assertTrue(inspect_console(console, self.version)[1])
        with self.assertRaisesRegex(RuntimeError, "BltOnly must not expose"):
            inspect_console(console.replace("unavailable (BltOnly)", "5760000 bytes"), self.version)

    def test_unknown_memory_type_is_counted_separately(self):
        console = self.console().replace("3 descriptors, 15 pages", "4 descriptors, 20 pages")
        console = console.replace(
            "[INFO] GOP: available",
            "[INFO] Memory type 2147483648 (MemoryType(2147483648)): 5 pages\n[INFO] GOP: available",
        )
        self.assertTrue(inspect_console(console, self.version)[1])

    def test_bad_totals_and_duplicate_types_fail(self):
        for console in (
            self.console().replace("15 pages (4 KiB each)", "16 pages (4 KiB each)"),
            self.console().replace("type 7 (CONVENTIONAL)", "type 0 (RESERVED)"),
        ):
            with self.subTest(console=console), self.assertRaises(RuntimeError):
                inspect_console(console, self.version)

    def test_return_marker_alone_does_not_prove_firmware_resumed(self):
        console = self.console().split("BdsDxe:")[0]
        self.assertFalse(inspect_console(console, self.version)[1])

    def test_incomplete_or_missing_discovery_cannot_pass(self):
        self.assertIsNone(inspect_console(self.console().split("[OK] Returning")[0], self.version))
        with self.assertRaisesRegex(RuntimeError, "Memory map"):
            inspect_console(self.console().replace("[INFO] Memory map: ", "missing: "), self.version)

    def test_panic_after_success_is_still_a_failure(self):
        with self.assertRaisesRegex(RuntimeError, "reported a failure"):
            inspect_console(self.console() + "[PANIC]: firmware problem\n", self.version)


if __name__ == "__main__":
    unittest.main()

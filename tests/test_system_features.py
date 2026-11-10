import ctypes
import os
import tempfile
import unittest
from ctypes import wintypes
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from app import client


class SystemFeatureTests(unittest.TestCase):
    def test_gateway_check_only_pings_the_resolved_local_gateway(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            results = [
                SimpleNamespace(returncode=0, stdout="192.168.1.1\r\n", stderr=""),
                SimpleNamespace(returncode=0, stdout="", stderr=""),
            ]
            with patch.dict(os.environ, {"SystemRoot": temp_dir}), patch.object(
                client.subprocess, "run", side_effect=results
            ) as run:
                status = client.varsayilan_ag_gecidi_kontrol_et()

        self.assertEqual(status["gecit"], "192.168.1.1")
        self.assertTrue(status["erisilebilir"])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].kwargs["timeout"], 15)
        ping_command = run.call_args_list[1].args[0]
        self.assertEqual(ping_command[-1], "192.168.1.1")
        self.assertNotIn("8.8.8.8", ping_command)

    def test_temperature_values_are_returned_without_reading_when_unsupported(self):
        readings = {
            "CPU": [
                SimpleNamespace(label="Package", current=63.7),
                SimpleNamespace(label="Core 1", current=65.2),
            ]
        }
        with patch.object(
            client.psutil, "sensors_temperatures", return_value=readings, create=True
        ):
            status = client.sicakliklari_topla()

        self.assertEqual(status[0]["etiket"], "Package")
        self.assertEqual(status[0]["celsius"], 64)

    def test_startup_apps_are_read_only_registry_names(self):
        fake_winreg = ModuleType("winreg")
        fake_winreg.HKEY_CURRENT_USER = object()
        fake_winreg.HKEY_LOCAL_MACHINE = object()

        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def enum_value(_key, index):
            if index == 0:
                return ("Updater", "C:\\private\\updater.exe --quiet", 0)
            raise OSError("no more values")

        fake_winreg.OpenKey = lambda *_args: FakeKey()
        fake_winreg.EnumValue = enum_value
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {"APPDATA": temp_dir, "PROGRAMDATA": temp_dir},
            ), patch.dict("sys.modules", {"winreg": fake_winreg}):
                names = client.baslangic_uygulamalarini_topla()

        self.assertEqual(names, ["Updater"])
        self.assertNotIn("C:\\private\\updater.exe --quiet", names)

    def test_power_operation_uses_the_selected_delay(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shutdown_exe = Path(temp_dir) / "System32" / "shutdown.exe"
            shutdown_exe.parent.mkdir()
            shutdown_exe.touch()
            with patch.dict(os.environ, {"SystemRoot": temp_dir}), patch.object(
                client.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ) as run, patch.object(client, "bekleyen_guc_islemi", None), patch.object(
                client, "bekleyen_islem_bitis_zamani", 0
            ):
                message = client.guc_islemi_yurut("restart", 300)

        self.assertIn("5 dakika", message)
        command = run.call_args.args[0]
        self.assertEqual(command[1:4], ["/r", "/t", "300"])

    def test_power_operation_rejects_delays_outside_supported_range(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shutdown_exe = Path(temp_dir) / "System32" / "shutdown.exe"
            shutdown_exe.parent.mkdir()
            shutdown_exe.touch()
            with patch.dict(os.environ, {"SystemRoot": temp_dir}), patch.object(
                client.subprocess, "run"
            ) as run:
                with self.assertRaises(ValueError):
                    client.guc_islemi_yurut("shutdown", 59)

        run.assert_not_called()

    def test_selected_application_window_is_restored_and_brought_forward(self):
        user32 = SimpleNamespace(
            EnumWindows=Mock(),
            IsWindowVisible=Mock(return_value=True),
            GetWindowTextLengthW=Mock(return_value=12),
            GetWindowThreadProcessId=Mock(),
            ShowWindow=Mock(),
            SetForegroundWindow=Mock(return_value=True),
            FlashWindowEx=Mock(),
        )

        def enumerate_windows(callback, _):
            callback(123, 0)
            return True

        def get_process_id(_, process_id_pointer):
            ctypes.cast(
                process_id_pointer, ctypes.POINTER(wintypes.DWORD)
            ).contents.value = 456
            return 1

        user32.EnumWindows.side_effect = enumerate_windows
        user32.GetWindowThreadProcessId.side_effect = get_process_id
        with patch.object(ctypes, "WinDLL", return_value=user32, create=True), patch.object(
            client.psutil,
            "Process",
            return_value=SimpleNamespace(name=lambda: "notepad.exe"),
        ):
            result, brought_to_front = client.uygulamayi_one_getir("notepad")

        self.assertIn("öne getirildi", result)
        self.assertTrue(brought_to_front)
        user32.ShowWindow.assert_called_once_with(123, 9)
        user32.SetForegroundWindow.assert_called_once_with(123)
        user32.FlashWindowEx.assert_not_called()

    def test_denied_foreground_activation_flashes_taskbar_instead_of_error(self):
        user32 = SimpleNamespace(
            EnumWindows=Mock(),
            IsWindowVisible=Mock(return_value=True),
            GetWindowTextLengthW=Mock(return_value=12),
            GetWindowThreadProcessId=Mock(),
            ShowWindow=Mock(),
            SetForegroundWindow=Mock(return_value=False),
            FlashWindowEx=Mock(),
        )

        def enumerate_windows(callback, _):
            callback(123, 0)
            return True

        def get_process_id(_, process_id_pointer):
            ctypes.cast(
                process_id_pointer, ctypes.POINTER(wintypes.DWORD)
            ).contents.value = 456
            return 1

        user32.EnumWindows.side_effect = enumerate_windows
        user32.GetWindowThreadProcessId.side_effect = get_process_id
        with patch.object(
            ctypes, "WinDLL", return_value=user32, create=True
        ), patch.object(
            client.psutil,
            "Process",
            return_value=SimpleNamespace(name=lambda: "notepad.exe"),
        ):
            result, brought_to_front = client.uygulamayi_one_getir("notepad")

        self.assertFalse(brought_to_front)
        self.assertIn("görev çubuğunda yanıp söndürüldü", result)
        user32.FlashWindowEx.assert_called_once()


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import Mock, patch

from app import reminders


class ReminderTests(unittest.TestCase):
    def test_calendar_date_and_time_are_parsed_as_future_local_time(self):
        due_at = reminders.hatirlatici_zamani_olustur("31.12.2099", "23:59")

        self.assertEqual(due_at.strftime("%d.%m.%Y %H:%M"), "31.12.2099 23:59")
        self.assertIsNotNone(due_at.tzinfo)

    def test_invalid_calendar_date_or_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "GG.AA.YYYY"):
            reminders.hatirlatici_zamani_olustur("31.02.2099", "23:59")
        with self.assertRaisesRegex(ValueError, "GG.AA.YYYY"):
            reminders.hatirlatici_zamani_olustur("31.12.2099", "24:00")

    def test_past_date_and_time_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "gelecekte"):
            reminders.hatirlatici_zamani_olustur("01.01.2000", "00:00")

    @patch.object(reminders.ctypes, "WinDLL")
    @patch.object(reminders.winsound, "MessageBeep")
    def test_desktop_alert_beeps_and_uses_topmost_windows_message_box(
        self, message_beep, win_dll
    ):
        message_box = Mock(return_value=1)
        win_dll.return_value.MessageBoxW = message_box

        reminders.masaustu_bildirimi_goster("Toplantı")

        message_beep.assert_called_once_with(reminders.winsound.MB_ICONEXCLAMATION)
        self.assertEqual(message_box.call_args.args[1], "Toplantı")
        self.assertEqual(
            message_box.call_args.args[3],
            0x00010000 | 0x00040000,
        )

    @patch.object(reminders.ctypes, "WinDLL")
    @patch.object(reminders.winsound, "MessageBeep", side_effect=RuntimeError)
    def test_desktop_alert_still_opens_if_beep_fails(self, _message_beep, win_dll):
        message_box = Mock(return_value=1)
        win_dll.return_value.MessageBoxW = message_box

        with self.assertLogs(reminders.logger, level="ERROR"):
            reminders.masaustu_bildirimi_goster("Toplantı")

        self.assertEqual(
            message_box.call_args.args[3],
            0x00010000 | 0x00040000 | 0x00000030,
        )


if __name__ == "__main__":
    unittest.main()

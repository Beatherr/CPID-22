import ctypes
from datetime import datetime
import logging
import winsound


logger = logging.getLogger(__name__)


def hatirlatici_zamani_olustur(date_value: str, time_value: str) -> datetime:
    try:
        due_at = datetime.strptime(
            f"{date_value.strip()} {time_value.strip()}", "%d.%m.%Y %H:%M"
        ).astimezone()
    except ValueError as exc:
        raise ValueError(
            "Tarihi GG.AA.YYYY, saati SS:DD biçiminde gir."
        ) from exc

    if due_at <= datetime.now().astimezone():
        raise ValueError("Hatırlatıcı zamanı gelecekte olmalıdır.")
    return due_at


def masaustu_bildirimi_goster(message: str) -> None:
    flags = 0x00010000 | 0x00040000
    try:
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except RuntimeError:
        logger.exception("Hatırlatıcı uyarı sesi çalınamadı; sesli pencere denenecek.")
        flags |= 0x00000030
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    message_box = user32.MessageBoxW
    message_box.argtypes = (
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
    )
    message_box.restype = ctypes.c_int
    result = message_box(
        None,
        message,
        "PCActivityMonitor - Hatırlatıcı",
        flags,
    )
    if result == 0:
        raise ctypes.WinError(ctypes.get_last_error())

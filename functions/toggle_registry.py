import time
import win32api


# (config-ключ настройки, подпись в GUI-попапе)
TOGGLE_FEATURES = [
    ("EnableESP", "ESP"),
    ("EnableTriggerbot", "Triggerbot"),
    ("EnableAimbot", "Aimbot"),
    ("EnableRecoilControl", "Контроль отдачи"),
    ("EnableBhop", "Бхоп"),
    ("EnableAntiFlashbang", "Антифлеш"),
    ("EnableAutoAccept", "Автопринятие"),
    ("EnableFovChanger", "Смена FOV"),
    ("EnableNoSmoke", "Удаление смоков"),
    ("EnableNoScopeOverlay", "Убрать скоуп"),
    ("EnableESPBombTimer", "Таймер бомбы"),
    ("EnableShowSpectators", "Наблюдатели"),
]


def toggle_key_name(config_key):
    """Имя config-ключа с клавишей тоггла для данной фичи."""
    return "ToggleKey_" + config_key


class HotkeyEngine:
    """Общий движок тоггл-хоткеев. Заменяет пер-фичевые опросы, которые
    жили в main-лупе (ESP) и в воркере триггера. Фронт нажатия
    (переход отпущена->нажата) инвертирует значение фичи в Options.
    Клавиши читаются из local_opts (кэш главного цикла, свежесть ~100 мс),
    запись идёт сквозь в Options (Manager + дебаунс сохранения) с
    зеркалированием в local_opts, чтобы следующее нажатие инвертировало
    актуальное значение, а не устаревшее."""

    def __init__(self):
        self._prev = {}
        self._flags_ts = 0.0
        self._capture_active = False

    def _capture_flag(self, Flags, now):
        """Флаг активного захвата клавиши (ставит GUI на время бинда).
        Кэш 10 Гц, не каждый кадр - Manager-чтения не на каждый poll."""
        if Flags is None:
            return False
        if now - self._flags_ts >= 0.1:
            self._flags_ts = now
            try:
                self._capture_active = bool(Flags.get("capture", False))
            except Exception:
                self._capture_active = False
        return self._capture_active

    def poll(self, local_opts, Options, Flags=None):
        now = time.time()
        if self._capture_flag(Flags, now):
            # Во время захвата клавиши бинда тоглы молчат: нажатие
            # биндимой клавиши не должно дёргать фичу. Сброс prev,
            # чтобы отпускание клавиши после бинда не дало фронт.
            self._prev.clear()
            return
        for key, _label in TOGGLE_FEATURES:
            try:
                code = int(local_opts.get(toggle_key_name(key), 0) or 0)
            except Exception:
                code = 0
            if code <= 0:
                self._prev[key] = False
                continue
            try:
                pressed = bool(win32api.GetAsyncKeyState(code) & 0x8000)
            except Exception:
                pressed = False
            was = self._prev.get(key, False)
            self._prev[key] = pressed
            if pressed and not was:
                try:
                    new_val = not bool(local_opts.get(key, False))
                except Exception:
                    new_val = True
                try:
                    Options[key] = new_val
                except Exception:
                    pass
                local_opts[key] = new_val
# markers: END functions/toggle_registry.py v2

import time
import win32api


# (config-ключ настройки, подпись в GUI-попапе)
# Мультипозиционные тумблеры (см. TOGGLE_CYCLE) хранят строку: хоткей
# переключает между "Выкл" и последним активным режимом, а не
# инвертирует bool и не ходит по кругу.
TOGGLE_FEATURES = [
    ("EnableESP", "ESP"),
    ("TriggerbotMode", "Triggerbot"),
    ("EnableAimbot", "Aimbot"),
    ("EnableRecoilControl", "Контроль отдачи"),
    ("EnableBhop", "Бхоп"),
    ("EnableAntiFlashbang", "Антифлеш"),
    ("EnableAutoAccept", "Автопринятие"),
    ("EnableFovChanger", "FOV Changer"),
    ("EnableNoSmoke", "Удаление смоков"),
    ("EnableNoScopeOverlay", "Удаление чёрноты скопа"),
    ("NoScopeCrosshairMode", "Noscope прицел"),
    ("EnableESPBombTimer", "Таймер бомбы"),
    ("EnableShowSpectators", "Наблюдатели"),
    ("EnableGlow", "Обводка (Glow)"),
]

# Мультипозиционные тогглы: хоткей переключает между "Выкл" (первое
# значение списка) и последним активным режимом, который юзер выбирал
# последним (из движка или в GUI). Ключ обязан быть в TOGGLE_FEATURES.
TOGGLE_CYCLE = {
    "TriggerbotMode": ["Выкл", "SadraKhorami", "Releotkamaza"],
    "NoScopeCrosshairMode": ["Выкл", "Кастомный", "Точка"],
}

# Описания для hover-попапа (ключ настройки -> текст). Показываются под
# заголовком. Сюда же попадают настройки БЕЗ хоткея - они регистрируются
# как «только описание» (без кнопок бинда).
DESCRIPTIONS = {
    "EnableESP": "Мастер-ключ: включает всю вкладку ESP целиком.",
    "TriggerbotMode": "SadraKhorami - классический тригер, не стреляет через стены, Releotkamaza - авол тригер",
    "EnableAimbot": "Наведение на противника по выбранной позиции.",
    "EnableRecoilControl": "Компенсация вертикальной отдачи при стрельбе.",
    "EnableBhop": "Автоматический прыжок при удержании пробела.",
    "EnableAntiFlashbang": "Антифлеш полностью гасит эффект ослепления флешбенга.",
    "EnableAutoAccept": "Автоматическое принятие готовности матча.",
    "EnableFovChanger": "Изменение угла обзора",
    "EnableNoSmoke": "Удаление дымов на карте.",
    "EnableNoScopeOverlay": "Удаляет скоп, заменяя его на кастомный, без черноты",
    "NoScopeCrosshairMode": "Настраиваемый прицел для ноускопов (AWP/SSG/SCAR-20/G3SG1)",
    "EnableESPBombTimer": "Таймер до взрыва бомбы, а также процесс её разминирования (дефьюза).",
    "EnableShowSpectators": "Список игроков, наблюдающих за вами в матче.",
    "EnableGlow": "Обводка персонажей, так называемый glow.",
    # --- настройки без хоткея (только описание) ---
    "EnableCustomCrosshair": "Кастомный прицел, стандартный прицел кс2 можно отключить через консольную команду crosshair 0",
    "Crosshair_Outline": "Обводка вокруг кастомного прицела",
    "TriggerbotRequireGround": "При включении triggerbot отключается в полёте",
}


def toggle_key_name(config_key):
    """Имя config-ключа с клавишей тоггла для данной фичи."""
    return "ToggleKey_" + config_key


def active_feature_labels(Options):
    """Список подписей АКТИВНЫХ функций (панель "Активные функции").
    Общий источник для GUI-панели и оверлея (features/active_list.py):
    bool-ключи активны при True; мультипозиционные (TOGGLE_CYCLE) - когда
    режим != "Выкл" (дефолт цикла - первое значение списка). Не показываются
    функции с ListShow_<ключ>=False (чекбоксы вкладки GUI)."""
    items = []
    for key, label in TOGGLE_FEATURES:
        try:
            shown = bool(Options.get("ListShow_" + key, True))
        except Exception:
            shown = True
        if not shown:
            continue
        cycle = TOGGLE_CYCLE.get(key)
        if cycle:
            try:
                active = str(Options.get(key, cycle[0]) or cycle[0]) != cycle[0]
            except Exception:
                active = False
        else:
            try:
                active = bool(Options.get(key, False))
            except Exception:
                active = False
        if active:
            items.append(label)
    return items


class HotkeyEngine:
    """Общий движок тоггл-хоткеев. Заменяет пер-фичевые опросы, которые
    жили в main-лупе (ESP) и в воркере триггера. Фронт нажатия
    (переход отпущена->нажата) переключает значение фичи в Options:
    для bool-тогглов инвертирует, для мультипозиционных (TOGGLE_CYCLE)
    переключает между "Выкл" и последним активным режимом. Клавиши
    читаются из local_opts (кэш главного цикла, свежесть ~100 мс),
    запись идёт сквозь в Options (Manager + дебаунс сохранения) с
    зеркалированием в local_opts, чтобы следующее нажатие переключало
    актуальное значение, а не устаревшее."""

    def __init__(self):
        self._prev = {}
        self._last_active = {}   # TOGGLE_CYCLE: режим до переключения в "Выкл"
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

    def _next_value(self, key, Options, local_opts):
        """Новое значение фичи при фронте нажатия хоткея.

        TOGGLE_CYCLE: не цикл по списку, а простое "вкл/выкл" -
        между "Выкл" и последним активным режимом (его юзер выбирал
        последним, неважно - хоткеем или в GUI). Переход из активного
        режима в "Выкл" запоминает этот режим как last_active; переход
        из "Выкл" возвращает его. Если активного ещё не было - первый
        не-"Выкл" режим из списка."""
        cycle = TOGGLE_CYCLE.get(key)
        if cycle:
            try:
                cur = str(Options.get(key, cycle[0]) or cycle[0])
            except Exception:
                cur = cycle[0]
            off = cycle[0]
            if cur == off:
                return self._last_active.get(key, cycle[1])
            self._last_active[key] = cur
            return off
        # База инверсии - актуальное значение из Options, а не из
        # local_opts (тот свежее ~100 мс): хоткей сразу после клика в GUI
        # не должен инвертировать устаревшее и затирать клик.
        try:
            return not bool(Options.get(key, False))
        except Exception:
            try:
                return not bool(local_opts.get(key, False))
            except Exception:
                return True

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
                new_val = self._next_value(key, Options, local_opts)
                try:
                    Options[key] = new_val
                except Exception:
                    pass
                local_opts[key] = new_val
        # Мастер-ключ панели активных функций (features/active_list.py):
        # не тумблер фичи, а переключение видимости окна списка. Фронт
        # нажатия инвертирует ActiveListVisible (в Options и local_opts).
        # Клавиша - стандартный toggle-ключ (ToggleKey_EnableActiveList,
        # биндится во всплывающем попапе на галочке "Включение активных
        # функций", как у остальных функций). Работает ТОЛЬКО при
        # включённой галочке: выключенная панель не копит переключения.
        try:
            al_enabled = bool(Options.get("EnableActiveList", False))
        except Exception:
            al_enabled = False
        try:
            al_code = int(local_opts.get(toggle_key_name("EnableActiveList"), 0) or 0)
        except Exception:
            al_code = 0
        if not al_enabled or al_code <= 0:
            self._prev["__active_list"] = False
        else:
            try:
                al_pressed = bool(win32api.GetAsyncKeyState(al_code) & 0x8000)
            except Exception:
                al_pressed = False
            al_was = self._prev.get("__active_list", False)
            self._prev["__active_list"] = al_pressed
            if al_pressed and not al_was:
                try:
                    al_new = not bool(Options.get("ActiveListVisible", False))
                except Exception:
                    al_new = True
                try:
                    Options["ActiveListVisible"] = al_new
                except Exception:
                    pass
                try:
                    local_opts["ActiveListVisible"] = al_new
                except Exception:
                    pass

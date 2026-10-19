import globals
import random
from functions import memfuncs
from functions import logutil
from functions import toggle_registry
from functions import config_manager
from features import aimbot
from features import rcs
from features import esp
from features import bombtimer
from features import fovchanger
from features import antiflash
from features import autoaccept
from features import triggerbot
from features import bhop
from features import spectator
from features import nosmoke
from features import glow
from GUI import gui_mainloop
from GUI import gui_util
from types import SimpleNamespace
import multiprocessing
import atexit
import time
import win32api
import keyboard, os, json
import gc
from functions.process_watcher import ProcessConnector

keyboard.add_hotkey("insert", callback=lambda: gui_util.hide_dpg())
keyboard.add_hotkey("home", callback=lambda: gui_util.streamproof_toggle())


class ManagedConfig:
    def __init__(self, managed_dict, save_function):
        self._dict = managed_dict
        self._save_function = save_function

    def update(self, *args, **kwargs):
        self._dict.update(*args, **kwargs)
        self._save_function(self._dict)

    def __setitem__(self, key, value):
        self._dict[key] = value
        self._save_function(self._dict)

    def __getitem__(self, key): return self._dict[key]

    def __delitem__(self, key):
        del self._dict[key]
        self._save_function(self._dict)

    def __contains__(self, key): return key in self._dict

    def get(self, key, default=None): return self._dict.get(key, default)

    def items(self): return self._dict.items()

    def keys(self): return self._dict.keys()

    def values(self): return self._dict.values()

    def __repr__(self): return repr(self._dict)


# ---------- Сохранение конфига с дебаунсом ----------
# Было: json.dump на КАЖДОЕ изменение галочки/слайдера - перетаскивание
# слайдера давало сотни записей файла в секунду через IPC.
_SAVE_MIN_INTERVAL = 0.5
_last_save_ts = 0.0
_save_pending = None


def _do_save(options):
    try:
        with open(globals.SAVE_FILE, 'w') as fp:
            json.dump(dict(options), fp, indent=4)
    except Exception:
        pass


def SaveConfig(options):
    """Не чаще раза в _SAVE_MIN_INTERVAL; промежуточное значение ждёт
    в _save_pending и сбрасывается главным циклом / _clean_exit."""
    global _last_save_ts, _save_pending
    now = time.time()
    if now - _last_save_ts >= _SAVE_MIN_INTERVAL:
        _do_save(options)
        _last_save_ts = now
        _save_pending = None
    else:
        _save_pending = dict(options)


def FlushPendingSave():
    global _save_pending, _last_save_ts
    if _save_pending is not None:
        _do_save(_save_pending)
        _save_pending = None
        _last_save_ts = time.time()


def LoadConfig():
    if not os.path.exists(globals.SAVE_FILE):
        with open(globals.SAVE_FILE, "w") as fp:
            json.dump(globals.CHEAT_SETTINGS, fp, indent=4)
    else:
        try:
            with open(globals.SAVE_FILE, "r") as fp:
                loaded = json.load(fp)
        except Exception:
            loaded = {}
        if not isinstance(loaded, dict):
            loaded = {}
        # Мерж с дефолтами: сохранённое поверх, недостающие ключи добираются.
        # settings.json от старой версии больше не даёт KeyError в воркерах.
        merged = dict(globals.CHEAT_SETTINGS)
        merged.update(loaded)
        # Однократная миграция: клавиша старого ESP-тогла переезжает
        # в общий движок. Новые бинды её перезаписывают, ключ-источник мёртв.
        if not merged.get("ToggleKey_EnableESP", 0) and merged.get("ESPMasterKey", 0):
            merged["ToggleKey_EnableESP"] = merged["ESPMasterKey"]
        # Миграция мультипозиционных тумблеров (v7): старые bool-галочки ->
        # строковый режим. Присутствие ключа проверяем в loaded, а не в
        # merged (иначе дефолт из CHEAT_SETTINGS маскирует старый конфиг).
        if "NoScopeCrosshairMode" not in loaded:
            if loaded.get("EnableNoScopeDot"):
                merged["NoScopeCrosshairMode"] = "Точка"
            elif loaded.get("EnableNoScopeDotSeparate"):
                merged["NoScopeCrosshairMode"] = "Кастомный"
        if "TriggerbotMode" not in loaded:
            if loaded.get("EnableTriggerbot", globals.CHEAT_SETTINGS.get("EnableTriggerbot", True)):
                merged["TriggerbotMode"] = ("Releotkamaza" if loaded.get("TriggerbotWallbang")
                                            else "SadraKhorami")
            else:
                merged["TriggerbotMode"] = "Выкл"
        # Хоткей-клавиши тогглов переносятся на новые ключи режимов.
        if not merged.get("ToggleKey_TriggerbotMode") and merged.get("ToggleKey_EnableTriggerbot"):
            merged["ToggleKey_TriggerbotMode"] = merged["ToggleKey_EnableTriggerbot"]
        if not merged.get("ToggleKey_NoScopeCrosshairMode") and merged.get("ToggleKey_EnableNoScopeDot"):
            merged["ToggleKey_NoScopeCrosshairMode"] = merged["ToggleKey_EnableNoScopeDot"]
        # v8.4.3: мастер-ключ панели "Активные функции" переименован
        # (ActiveListKey -> ToggleKey_EnableActiveList, бинд в hover-попапе).
        if not merged.get("ToggleKey_EnableActiveList") and merged.get("ActiveListKey"):
            merged["ToggleKey_EnableActiveList"] = merged["ActiveListKey"]
        # Производные bool-ключи: держим согласованными с режимами.
        _nsm = merged.get("NoScopeCrosshairMode", "Выкл")
        merged["EnableNoScopeDot"] = (_nsm == "Точка")
        merged["EnableNoScopeDotSeparate"] = _nsm in ("Кастомный", "Точка")
        _tbm = merged.get("TriggerbotMode", "SadraKhorami")
        merged["EnableTriggerbot"] = _tbm != "Выкл"
        merged["TriggerbotWallbang"] = _tbm == "Releotkamaza"
        globals.CHEAT_SETTINGS = merged


if __name__ == "__main__":
    kaomojis = [
        "(=^･ω･^=)",
        "(=^･^=)",
        "≽^•⩊•^≼",
        "(=^-ω-^=)",
        "(=˃ᆺ˂=)",
        "^._.^",
        "^>⩊<^",
        "(=^･ｪ･^=)",
        "≽^• ˕ •^≼",
        "ᓚ₍ ^. ̫ .^₎"
    ]

    print("       ::::    ::: :::::::::: :::::::::   ::::::::  ::::    :::            ::::::::      ::: ::::::::::: \n "
          "     :+:+:   :+: :+:        :+:    :+: :+:    :+: :+:+:   :+:           :+:    :+:   :+: :+:   :+:      \n "
          "    :+:+:+  +:+ +:+        +:+    +:+ +:+    +:+ :+:+:+  +:+           +:+         +:+   +:+  +:+       \n "
          "   +#+ +:+ +#+ +#++:++#   +#++:++#:  +#+    +:+ +#+ +:+ +#+           +#+        +#++:++#++: +#+        \n "
          "  +#+  +#+#+# +#+        +#+    +#+ +#+    +:+ +#+  +#+#+#           +#+        +#+     +#+ +#+         \n "
          " #+#   #+#+# #+#        #+#    #+# #+#    #+# #+#   #+#+#           #+#    #+# #+#     #+# #+#          \n "
          "###    #### ########## ###    ###  ########  ###    #### ########## ########  ###     ### ###           \n "

          "\n  "
          "             - NERON v0.10.8\n  "
          "             - https://github.com/Releotkamaza/cs2_neron_cat\n  "
          f"             - {random.choice(kaomojis)}  ")

    # SetPriorityClass(HIGH_PRIORITY_CLASS) убран: чит отъедал приоритет у CS2
    # и давал фреймтайм-спайки в игре. Если нужен - верни вызов.

    multiprocessing.freeze_support()

    # Дефолты клавиш тогглов из реестра - ДО LoadConfig, чтобы merge
    # видел их и свежий settings.json содержал все ключи.
    for _k, _lbl in toggle_registry.TOGGLE_FEATURES:
        globals.CHEAT_SETTINGS.setdefault(toggle_registry.toggle_key_name(_k), 0)

    # Process & module
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    ProcessObject = connector.ensure_process()
    ClientModuleAddress = connector.ensure_module("client.dll")

    def _restore_game_state():
        """Вернуть игре её значения: наш FOV -> 90, яркость вспышки -> 255.

        Вызывать ТОЛЬКО после остановки воркеров: fovchanger и antiflash
        крутятся в отдельных процессах и иначе снова перезапишут поля."""
        try:
            off = globals.GAME_OFFSETS.offset
            p = connector.ensure_process()
            c = connector.ensure_module("client.dll")
            if not (p and c):
                return
            lp = memfuncs.ProcMemHandler.ReadPointer(p, c + off.dwLocalPlayerPawn)
            if not lp:
                return
            try:
                cam = memfuncs.ProcMemHandler.ReadPointer(p, lp + off.m_pCameraServices)
                if cam:
                    memfuncs.ProcMemHandler.WriteInt(p, cam + off.m_iFOV, 90)
            except Exception:
                pass
            try:
                ctrl = memfuncs.ProcMemHandler.ReadPointer(p, c + off.dwLocalPlayerController)
                if ctrl:
                    memfuncs.ProcMemHandler.WriteInt(p, ctrl + off.m_iDesiredFOV, 90)
            except Exception:
                pass
            try:
                memfuncs.ProcMemHandler.WriteFloat(p, lp + off.m_flFlashMaxAlpha, 255.0)
            except Exception:
                pass
        except Exception:
            pass

    def _shutdown():
        """Остановить воркеры, вернуть память игры, сохранить конфиг.

        Порядок важен: сначала гасим воркеры (иначе они снова запишут FOV/
        вспышку), затем восстанавливаем поля, затем сохраняем и гасим
        Manager. Без этой очистки os._exit оставлял процессы-сироты, а игра
        оставалась с нашим FOV и выключенной вспышкой."""
        try:
            mgr_proc = getattr(Manager, "_process", None)
        except Exception:
            mgr_proc = None
        try:
            for _p in multiprocessing.active_children():
                if _p is mgr_proc:
                    continue
                try:
                    _p.terminate()
                except Exception:
                    pass
        except Exception:
            pass
        _restore_game_state()
        try:
            FlushPendingSave()
            _do_save(dict(SharedOptions))
        except Exception:
            pass
        try:
            Manager.shutdown()
        except Exception:
            pass

    def _clean_exit():
        _shutdown()
        os._exit(0)

    keyboard.add_hotkey("end", callback=_clean_exit)
    # Нормальный выход (закрытие окна оверлея, Ctrl+C, исключение) тоже
    # обязан вернуть FOV/вспышку и сохранить конфиг. os._exit эту регистрацию
    # не запускает, поэтому _clean_exit зовёт _shutdown() сам.
    atexit.register(_shutdown)

    # Config
    LoadConfig()
    Manager = multiprocessing.Manager()
    SharedOptions_M = Manager.dict(globals.CHEAT_SETTINGS)
    # Панель «Активные функции»: включённая галочка = видимая панель при старте.
    # Колбэк галочки при старте не вызывается, поэтому застрявший
    # ActiveListVisible=False (спрятано мастер-хоткеем - у юзера это Ctrl,
    # а Ctrl в CS2 = присед!) выглядел как «список перестал работать».
    # Пишем в память (Manager.dict), settings.json не трогаем.
    try:
        if bool(SharedOptions_M.get("EnableActiveList", False)):
            SharedOptions_M["ActiveListVisible"] = True
    except Exception:
        pass
    SharedOptions = ManagedConfig(SharedOptions_M, save_function=SaveConfig)

    # Служебные флаги процессов (не конфиг, в settings.json не пишется):
    # "capture"  - GUI ставит на время захвата клавиши бинда, движки молчат;
    # "config_ts"- метка применения профиля (main при хоткее, GUI при кнопке),
    #              GUI перерисовывает ВСЕ виджеты при смене значения.
    SharedFlags = Manager.dict()

    # Профили конфигов: cfg/ + бинды переключения
    cfgmgr = config_manager.ConfigManager()
    cfg_engine = config_manager.ConfigHotkeyEngine(cfgmgr, SharedFlags)

    # Offsets: обычный объект вместо Manager.Namespace. Прокси давал IPC
    # round-trip на КАЖДОЕ чтение .offset.* - в bhop это ~8 IPC каждую
    # миллисекунду, в ESP - несколько за кадр. Объект пиклится в воркеры
    # один раз, дальше все чтения локальные. Оффсеты статичны после старта.
    SharedOffsets = SimpleNamespace(offset=globals.GAME_OFFSETS)

    SharedRuntime = Manager.Namespace()
    SharedRuntime.spectators = []
    # (строка SharedOptions["EnableShowSpectators"] = True убрана: она
    #  затирала сохранённую галочку при каждом запуске; дефолт и так True)

    # Общий движок тоггл-хоткеев: реестр и логика в functions/toggle_registry.py.
    # Поглотил пер-фичевые опросы ESP (был здесь, в лупе) и триггера (был
    # в воркере). Тоглы работают и при закрытой игре.
    hotkey_engine = toggle_registry.HotkeyEngine()

    GUI_proc = multiprocessing.Process(target=gui_mainloop.run_gui, args=(SharedOptions, SharedRuntime, SharedFlags,))
    GUI_proc.start()

    # Overlay
    esp.pme.overlay_init(title="ESP-Overlay")
    fps = esp.pme.get_monitor_refresh_rate()
    try:
        target_fps = min(max(int(fps) * 2 + 30, 144), 360)
    except Exception:
        target_fps = 240
    esp.pme.set_fps(target_fps)

    # vsync оверлея: FLAG_VSYNC_HINT=0x40 (raylib -> glfwSwapInterval(1)).
    # set_window_flag - ТОГГЛ, поэтому вызов ровно один раз при старте.
    # Синхронизация с развёрткой убирает блоки end_drawing (9-65 мс: DWM
    # под нагрузкой игры в borderless), выравнивая кадр до ~1/refresh.
    esp.pme.set_window_flag(0x40)

    # FOV changer
    FOV_proc = multiprocessing.Process(target=fovchanger.FovChangerThreadFunction, args=(SharedOptions, SharedOffsets,))
    FOV_proc.daemon = True
    FOV_proc.start()

    # Anti-Flash (separate worker)
    AntiFlash_proc = multiprocessing.Process(target=antiflash.AntiFlashThreadFunction, args=(SharedOptions, SharedOffsets,))
    AntiFlash_proc.daemon = True
    AntiFlash_proc.start()

    # Автопринятие матча (отдельный воркер)
    AutoAccept_proc = multiprocessing.Process(target=autoaccept.AutoAcceptThreadFunction, args=(SharedOptions, SharedOffsets,))
    AutoAccept_proc.daemon = True
    AutoAccept_proc.start()

    # Triggerbot (separate worker)
    Trigger_proc = multiprocessing.Process(target=triggerbot.TriggerbotThreadFunction, args=(SharedOptions, SharedOffsets, SharedRuntime,))
    Trigger_proc.daemon = True
    Trigger_proc.start()

    # Bhop
    Bhop_proc = multiprocessing.Process(target=bhop.BhopThreadFunction, args=(SharedOptions, SharedOffsets,))
    Bhop_proc.daemon = True
    Bhop_proc.start()

    # Bomb timer
    SharedBombState = Manager.Namespace()
    SharedBombState.bombPlanted = False
    SharedBombState.bombTimeLeft = -1.0
    SharedBombState.bombTimeTotal = 40.0
    SharedBombState.bombBeingDefused = False
    SharedBombState.bombDefuseImpossible = False
    SharedBombState.bombTimerText = ""
    Bomb_proc = multiprocessing.Process(target=bombtimer.BombTimerThread, args=(SharedBombState, SharedOffsets,))
    Bomb_proc.daemon = True
    Bomb_proc.start()

    # No Smoke (separate worker)
    NoSmoke_proc = multiprocessing.Process(
        target=nosmoke.NoSmokeThreadFunction,
        args=(SharedOptions, SharedOffsets, SharedRuntime,)
    )
    NoSmoke_proc.daemon = True
    NoSmoke_proc.start()
    logutil.debug("[main] nosmoke worker: started")

    # Glow worker
    Glow_proc = multiprocessing.Process(
        target=glow.GlowThreadFunction,
        args=(SharedOptions, SharedOffsets)
    )
    Glow_proc.daemon = True
    Glow_proc.start()
    logutil.debug("[main] glow worker: started")

    # Spectator monitor
    Spectator_proc = multiprocessing.Process(
        target=spectator.SpectatorThreadFunction,
        args=(SharedOptions, SharedOffsets, SharedRuntime,)
    )
    Spectator_proc.daemon = True
    Spectator_proc.start()
    logutil.debug("[main] spectator monitor: started")

    overlay_logged_once = False
    _gc_counter = 0
    _gc_last_time = time.time()
    _opts_ts = 0.0
    _esp_err_ts = 0.0
    local_opts = dict(SharedOptions.items())

    while esp.pme.overlay_loop():
        _gc_now = time.time()

        # gc: только молодое поколение и реже. Полная сборка (collect())
        # морозила рендер на 5-20 мс каждые 3 секунды - это были периодические
        # фризы оверлея. Пороговые сборки старших поколений python делает сам.
        _gc_counter += 1
        if _gc_counter >= 120 or (_gc_now - _gc_last_time) >= 5.0:
            gc.collect(0)
            _gc_counter = 0
            _gc_last_time = _gc_now

        # Сброс отложенного сохранения конфига
        if _save_pending is not None and (_gc_now - _last_save_ts) >= _SAVE_MIN_INTERVAL:
            FlushPendingSave()

        # Локальная копия настроек раз в 100 мс (была каждый кадр - IPC round-trip)
        if _gc_now - _opts_ts >= 0.1:
            local_opts = dict(SharedOptions.items())
            _opts_ts = _gc_now

        # Движки хоткеев: тогглы функций + переключение профилей конфигов.
        # До ensure_process: работают и при закрытой/перезапускаемой игре.
        hotkey_engine.poll(local_opts, SharedOptions, SharedFlags)
        cfg_engine.poll(local_opts, SharedOptions)

        try:
            ProcessObject = connector.ensure_process()
            ClientModuleAddress = connector.ensure_module("client.dll")
        except Exception:
            connector.invalidate()
            # Игра закрыта/перезапускается -> рисовать нечем. Гасим оверлей
            # пустым кадром, иначе topmost-окно держит последний кадр на
            # экране (артефакт поверх чужих окон, v8.5).
            try:
                esp.clear_overlay()
            except Exception:
                pass
            time.sleep(0.5)
            continue

        if not overlay_logged_once:
            logutil.debug("[main] overlay loop entered; Spec List will be drawn from features/esp/static.py.")
            logutil.debug("[main] rendering Spec List on the game frame (inside ESP begin/end drawing)")
            overlay_logged_once = True

        try:
            esp.ESP_Update(ProcessObject, ClientModuleAddress, local_opts, SharedOffsets, SharedBombState, SharedRuntime)
            aimbot_key = int(local_opts.get("AimbotKey", 6) or 0)
            if local_opts.get("EnableAimbot", False) and aimbot_key > 0 and win32api.GetAsyncKeyState(aimbot_key) & 0x8000:
                aimbot.Aimbot_Update(ProcessObject, ClientModuleAddress, SharedOffsets, local_opts, SharedRuntime)
            rcs.RecoilControl_Update(ProcessObject, ClientModuleAddress, SharedOffsets, local_opts)
        except Exception as _e:
            # Не спамим в консоль на каждый кадр: устойчивая ошибка ESP иначе
            # забьёт вывод сотнями строк в секунду. Строка - не чаще 1 раза в
            # 2 с, полные детали - в debug (NERON_DEBUG=1).
            if _gc_now - _esp_err_ts >= 2.0:
                _esp_err_ts = _gc_now
                print("[MAIN] ESP/Aimbot error:", repr(_e), flush=True)
            logutil.debug(f"[MAIN] ESP/Aimbot error: {_e!r}")
            connector.invalidate()
            continue
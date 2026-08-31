from functions import memfuncs
from functions import logutil
from functions.process_watcher import ProcessConnector
import time

DEFAULT_FOV = 90
SCOPE_FOV_MAX = 89

# Сколько держим трубу перед снятием
# Сделал чуть позже, чем было
SCOPE_ENTER_GRACE_SEC = 1.45

# Сколько после выхода из скоупа не форсим FOV напрямую
# Увеличил на 0.1 сек, чтобы убрать одиночный передёрг
SCOPE_EXIT_GRACE_SEC = 0.40

# Дебаунс состояния скоупа
SCOPE_STATE_DEBOUNCE = 0.12

# Когда уже можно писать m_iDesiredFOV после выхода из скоупа
SCOPE_DESIRED_DELAY = 0.05

# Если FOV сам не вернулся, форсим его через этот таймаут
# Тоже чуть отодвинул, чтобы не влезал слишком рано
SCOPE_FORCE_FOV_AFTER = 0.75

# Насколько долго разрешаем считать сырой флаг m_bIsScoped началом скоупа,
# даже если FOV ещё не начал падать
RAW_SCOPE_ONLY_GRACE = 0.25

# Маленький мостик, чтобы не терять скоуп на единичных пропаданиях сигнала
ACTUAL_ZOOM_BRIDGE = 0.12

# Сколько времени после нажатия кнопки zoom считаем, что начался вход в скоуп
ZOOM_PRESS_GRACE = 0.35

# Сколько времени считаем, что FOV всё ещё уходит в зум
ZOOM_IN_BRIDGE = 0.12

# Сколько ждать перед принудительным выходом из "залипшего" скоупа.
# Увеличил, чтобы не убивать второй уровень скоупа из-за единичного глюка.
ZOOM_LOST_TIMEOUT = 0.80

FOV_RATE_EPS = 0.001

# из твоего buttons.json: client.dll -> zoom
ZOOM_BUTTON_OFFSET = 37604112


def FovChangerThreadFunction(Options, Offsets):
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])

    def _off(name, fallback):
        try:
            v = int(getattr(Offsets.offset, name, 0))
            return v if v != 0 else fallback
        except Exception:
            return fallback

    # Базовые оффсеты
    o_local_pawn = _off("dwLocalPlayerPawn", 37515880)
    o_local_controller = _off("dwLocalPlayerController", 37363504)
    o_entity_list = _off("dwEntityList", 39264816)

    # Pawn / services
    o_camera_services = _off("m_pCameraServices", 4672)
    o_weapon_services = _off("m_pWeaponServices", 4616)
    o_life_state = _off("m_lifeState", 852)

    # Camera FOV
    o_fov = _off("m_iFOV", 656)
    o_fov_start = _off("m_iFOVStart", 660)
    o_fov_rate = _off("m_flFOVRate", 668)
    o_desired_fov = _off("m_iDesiredFOV", 1932)

    # Scope flags
    o_scoped = _off("m_bIsScoped", 7288)
    o_resume_zoom = _off("m_bResumeZoom", 7289)
    o_old_scoped = _off("m_bOldIsScoped", 7348)

    # Weapon
    o_active_weapon = 96
    o_zoom_level = 7392

    def _clamp(v, lo, hi):
        try:
            return max(lo, min(hi, int(v)))
        except Exception:
            return lo

    def _set_noscope_active(v):
        try:
            if bool(Options.get("NoScopeActive", False)) != v:
                Options["NoScopeActive"] = v
        except Exception:
            pass

    def _read_bool(proc, addr):
        try:
            return bool(memfuncs.ProcMemHandler.ReadBool(proc, addr))
        except Exception:
            try:
                return bool(memfuncs.ProcMemHandler.ReadBytes(proc, addr, 1)[0])
            except Exception:
                return False

    def _write_bool(proc, addr, val):
        try:
            memfuncs.ProcMemHandler.WriteBool(proc, addr, bool(val))
            return True
        except Exception:
            try:
                memfuncs.ProcMemHandler.WriteBytes(proc, addr, b"\x01" if val else b"\x00")
                return True
            except Exception:
                return False

    def _read_fov_rate(proc, camera_services):
        if not o_fov_rate:
            return 0.0
        try:
            return float(memfuncs.ProcMemHandler.ReadFloat(proc, camera_services + o_fov_rate))
        except Exception:
            return 0.0

    def _read_zoom_button_down(proc, client_base):
        """
        Пытаемся прочитать кнопку zoom из buttons.json.
        Важно: я специально принимаю только маленькие/похожие на состояние значения,
        чтобы не словить ложный скоуп, если там вдруг лежит указатель или мусор.
        """
        try:
            val = int(memfuncs.ProcMemHandler.ReadInt(proc, client_base + ZOOM_BUTTON_OFFSET))

            # Самый частый вариант состояния кнопки - маленькое число.
            if 0 <= val <= 32:
                return val != 0

            # На всякий случай допускаем младший байт как битовую маску.
            if 0 <= val <= 0xFF:
                return (val & 1) != 0

            return False
        except Exception:
            return False

    weapon_cache = {"handle": -1, "entity": 0}

    def _entity_from_handle(proc, client_base, handle):
        try:
            handle = int(handle)
            if handle == 0:
                return 0

            index = handle & 0x1FFF
            if index == 0:
                return 0

            entity_list = memfuncs.ProcMemHandler.ReadPointer(proc, client_base + o_entity_list)
            if not entity_list:
                return 0

            list_entry = memfuncs.ProcMemHandler.ReadPointer(
                proc,
                entity_list + 0x10 + 8 * ((index >> 9) & 0x1FF)
            )
            if not list_entry:
                return 0

            entity = memfuncs.ProcMemHandler.ReadPointer(
                proc,
                list_entry + 0x78 * (index & 0x1FF)
            )
            return int(entity or 0)
        except Exception:
            return 0

    def _get_active_weapon(proc, client_base, local_pawn):
        try:
            if not o_weapon_services:
                return 0

            weapon_services = memfuncs.ProcMemHandler.ReadPointer(proc, local_pawn + o_weapon_services)
            if not weapon_services:
                return 0

            try:
                handle = int(memfuncs.ProcMemHandler.ReadUInt(proc, weapon_services + o_active_weapon))
            except Exception:
                handle = int(memfuncs.ProcMemHandler.ReadInt(proc, weapon_services + o_active_weapon)) & 0xFFFFFFFF

            if handle == weapon_cache["handle"]:
                return weapon_cache["entity"]

            ent = _entity_from_handle(proc, client_base, handle)
            weapon_cache["handle"] = handle
            weapon_cache["entity"] = ent
            return ent
        except Exception:
            return 0

    def _read_zoom_level(proc, client_base, local_pawn):
        try:
            ent = _get_active_weapon(proc, client_base, local_pawn)
            if not ent:
                return -1

            zl = int(memfuncs.ProcMemHandler.ReadInt(proc, ent + o_zoom_level))
            if 0 <= zl <= 2:
                return zl

            return -1
        except Exception:
            return -1

    in_scope = False
    scope_entered_at = 0.0
    last_scope_signal_time = 0.0

    noscope_removed = False
    locked_scope_fov = 0
    zoom_lost_since = 0.0

    prev_raw_scoped = False
    raw_scoped_true_since = 0.0

    last_actual_zoom_time = 0.0
    last_zoom_in_time = 0.0

    prev_zoom_button_down = False
    zoom_enter_press_at = 0.0

    next_debug_log = 0.0

    while True:
        try:
            process = connector.ensure_process()
            client = connector.ensure_module("client.dll")

            local_pawn = memfuncs.ProcMemHandler.ReadPointer(process, client + o_local_pawn) if o_local_pawn else 0
            if not local_pawn:
                time.sleep(0.01)
                continue

            # lifeState: 0 = жив
            try:
                life_state = int(memfuncs.ProcMemHandler.ReadBytes(process, local_pawn + o_life_state, 1)[0])
            except Exception:
                life_state = 0

            if life_state != 0:
                if in_scope or bool(Options.get("NoScopeActive", False)):
                    _set_noscope_active(False)

                in_scope = False
                noscope_removed = False
                locked_scope_fov = 0
                zoom_lost_since = 0.0
                last_scope_signal_time = 0.0
                last_actual_zoom_time = 0.0
                last_zoom_in_time = 0.0
                raw_scoped_true_since = 0.0
                prev_raw_scoped = False
                prev_zoom_button_down = False
                zoom_enter_press_at = 0.0

                time.sleep(0.02)
                continue

            camera_services = memfuncs.ProcMemHandler.ReadPointer(process, local_pawn + o_camera_services)
            if not camera_services:
                time.sleep(0.005)
                continue

            local_controller = 0
            if o_local_controller:
                try:
                    local_controller = memfuncs.ProcMemHandler.ReadPointer(process, client + o_local_controller)
                except Exception:
                    local_controller = 0

            fov_enabled = bool(Options.get("EnableFovChanger", False))
            noscope_enabled = bool(Options.get("EnableNoScopeOverlay", False))

            desired_fov = _clamp(Options.get("FovChangeSize", 90), 90, 170) if fov_enabled else DEFAULT_FOV

            raw_scoped = _read_bool(process, local_pawn + o_scoped) if o_scoped else False

            try:
                current_fov = int(memfuncs.ProcMemHandler.ReadInt(process, camera_services + o_fov))
            except Exception:
                current_fov = DEFAULT_FOV

            fov_rate = _read_fov_rate(process, camera_services)
            fov_moving = abs(fov_rate) > FOV_RATE_EPS

            zoom_level = -1
            if noscope_enabled or in_scope or raw_scoped or (0 < current_fov < SCOPE_FOV_MAX):
                zoom_level = _read_zoom_level(process, client, local_pawn)

            now = time.time()

            # Кнопка zoom.
            # Используем только как ранний сигнал входа.
            zoom_button_down = _read_zoom_button_down(process, client)

            if zoom_button_down and not prev_zoom_button_down and not in_scope:
                zoom_enter_press_at = now

            prev_zoom_button_down = zoom_button_down

            # Реальный зум определяем по FOV.
            actual_zoom = 0 < current_fov < SCOPE_FOV_MAX

            if actual_zoom:
                last_actual_zoom_time = now

            # Если FOV начал падать вниз, это тоже признак входа в зум.
            zooming_in = (fov_rate < -FOV_RATE_EPS) and (current_fov <= desired_fov)

            if zooming_in:
                last_zoom_in_time = now

            # Отслеживаем момент, когда m_bIsScoped только что стал true.
            if raw_scoped and not prev_raw_scoped:
                raw_scoped_true_since = now

            prev_raw_scoped = bool(raw_scoped)

            # Сырой флаг скоупа разрешаем как сигнал входа только короткое время.
            raw_scope_allowed = (
                bool(raw_scoped)
                and raw_scoped_true_since > 0.0
                and (now - raw_scoped_true_since) <= RAW_SCOPE_ONLY_GRACE
            )

            recent_actual_zoom = (
                last_actual_zoom_time > 0.0
                and (now - last_actual_zoom_time) <= ACTUAL_ZOOM_BRIDGE
            )

            recent_zoom_press = (
                zoom_enter_press_at > 0.0
                and (now - zoom_enter_press_at) <= ZOOM_PRESS_GRACE
            )

            recent_zooming_in = (
                last_zoom_in_time > 0.0
                and (now - last_zoom_in_time) <= ZOOM_IN_BRIDGE
            )

            raw_signal = (
                actual_zoom
                or recent_actual_zoom
                or raw_scope_allowed
                or recent_zoom_press
                or recent_zooming_in
            )

            if raw_signal:
                last_scope_signal_time = now

            # Вход/выход из состояния скоупа
            if not in_scope:
                if raw_signal:
                    in_scope = True
                    scope_entered_at = now
                    noscope_removed = False
                    locked_scope_fov = 0
                    zoom_lost_since = 0.0
                    _set_noscope_active(False)
            else:
                if (not raw_signal) and (now - last_scope_signal_time >= SCOPE_STATE_DEBOUNCE):
                    in_scope = False
                    noscope_removed = False
                    locked_scope_fov = 0
                    zoom_lost_since = 0.0
                    _set_noscope_active(False)

            if in_scope and actual_zoom:
                locked_scope_fov = current_fov

            # Отладка по желанию: включи "FovDebug": True
            if bool(Options.get("FovDebug", False)) and now >= next_debug_log:
                try:
                    logutil.debug(
                        f"[fovchanger] raw={raw_scoped} actual={actual_zoom} allowed={raw_scope_allowed} "
                        f"btn={zoom_button_down} press={recent_zoom_press} zin={recent_zooming_in} "
                        f"signal={raw_signal} fov={current_fov} rate={fov_rate:.4f} zoom={zoom_level} "
                        f"in_scope={in_scope} removed={noscope_removed} locked={locked_scope_fov} "
                        f"since_scope={(now - last_scope_signal_time):.3f}"
                    )
                except Exception:
                    pass
                next_debug_log = now + 1.0

            if in_scope:
                if noscope_enabled:
                    if not noscope_removed:
                        if (now - scope_entered_at) >= SCOPE_ENTER_GRACE_SEC:
                            noscope_removed = True
                            zoom_lost_since = 0.0
                            _set_noscope_active(True)
                    else:
                        _set_noscope_active(True)

                        # Снимаем скоуп нативным bool-ом
                        if o_scoped:
                            _write_bool(process, local_pawn + o_scoped, False)

                        # Дополнительно гасим то, что может заставлять игру возвращать zoom/scope
                        if o_resume_zoom:
                            _write_bool(process, local_pawn + o_resume_zoom, False)

                        if o_old_scoped:
                            _write_bool(process, local_pawn + o_old_scoped, False)

                        # Если игра вдруг пытается вытащить FOV из зума,
                        # а оружие всё ещё реально в zoom, удерживаем зум-FOV.
                        if zoom_level > 0 and locked_scope_fov > 0 and current_fov > SCOPE_FOV_MAX:
                            protect_fov = locked_scope_fov
                            try:
                                memfuncs.ProcMemHandler.WriteInt(process, camera_services + o_fov, protect_fov)
                                if o_fov_start:
                                    memfuncs.ProcMemHandler.WriteInt(process, camera_services + o_fov_start, protect_fov)
                                if local_controller and o_desired_fov:
                                    memfuncs.ProcMemHandler.WriteInt(process, local_controller + o_desired_fov, protect_fov)
                            except Exception:
                                pass

                        # Безопасный unstick.
                        # Раньше он мог сработать слишком быстро и случайно убить второй уровень скоупа.
                        # Теперь форсим выход только если:
                        # - оружие уже точно не в zoom
                        # - флага скоупа нет
                        # - FOV остался низким
                        # - и при этом FOV не двигается
                        if (
                            zoom_level == 0
                            and not raw_scoped
                            and current_fov < SCOPE_FOV_MAX
                            and abs(fov_rate) <= FOV_RATE_EPS
                        ):
                            if zoom_lost_since == 0.0:
                                zoom_lost_since = now
                            elif now - zoom_lost_since > ZOOM_LOST_TIMEOUT:
                                in_scope = False
                                noscope_removed = False
                                _set_noscope_active(False)
                                last_scope_signal_time = now
                                zoom_lost_since = 0.0

                                # Принудительно вытаскиваем FOV из застрявшего зума
                                try:
                                    if local_controller and o_desired_fov:
                                        memfuncs.ProcMemHandler.WriteInt(process, local_controller + o_desired_fov, desired_fov)

                                    if o_fov_rate:
                                        memfuncs.ProcMemHandler.WriteFloat(process, camera_services + o_fov_rate, 0.0)

                                    if o_fov_start:
                                        memfuncs.ProcMemHandler.WriteInt(process, camera_services + o_fov_start, desired_fov)

                                    memfuncs.ProcMemHandler.WriteInt(process, camera_services + o_fov, desired_fov)
                                except Exception:
                                    pass

                                time.sleep(0.001)
                                continue
                        else:
                            zoom_lost_since = 0.0
                else:
                    # Если NoScope выключили прямо во время скоупа, возвращаем нормальное поведение
                    if noscope_removed:
                        if o_scoped:
                            _write_bool(process, local_pawn + o_scoped, True)

                        if o_resume_zoom:
                            _write_bool(process, local_pawn + o_resume_zoom, True)

                        if o_old_scoped:
                            _write_bool(process, local_pawn + o_old_scoped, False)

                        noscope_removed = False
                        zoom_lost_since = 0.0
                        _set_noscope_active(False)

                time.sleep(0.001)
                continue

            # Вне скоупа
            time_since_scope = (now - last_scope_signal_time) if last_scope_signal_time > 0.0 else 9999.0
            hard_force_fov = time_since_scope >= SCOPE_FORCE_FOV_AFTER

            # desired FOV пишем быстро
            allow_desired = (
                time_since_scope >= SCOPE_DESIRED_DELAY
                and ((not fov_moving) or hard_force_fov)
            )

            # Прямой форс текущего FOV делаем после короткого хвоста анимации
            allow_direct_fov = (
                time_since_scope >= SCOPE_EXIT_GRACE_SEC
                and ((not fov_moving) or hard_force_fov)
            )

            if allow_desired:
                try:
                    if local_controller and o_desired_fov:
                        try:
                            cur_desired = int(memfuncs.ProcMemHandler.ReadInt(process, local_controller + o_desired_fov))
                        except Exception:
                            cur_desired = -1

                        if hard_force_fov or cur_desired != desired_fov:
                            memfuncs.ProcMemHandler.WriteInt(process, local_controller + o_desired_fov, desired_fov)
                except Exception:
                    pass

            if allow_direct_fov:
                try:
                    if current_fov != desired_fov or hard_force_fov:
                        # Останавливаем застрявшую интерполяцию
                        if o_fov_rate:
                            memfuncs.ProcMemHandler.WriteFloat(process, camera_services + o_fov_rate, 0.0)

                        if o_fov_start:
                            memfuncs.ProcMemHandler.WriteInt(process, camera_services + o_fov_start, desired_fov)

                        memfuncs.ProcMemHandler.WriteInt(process, camera_services + o_fov, desired_fov)
                except Exception:
                    pass

            time.sleep(0.001)

        except Exception as exc:
            logutil.debug(f"[fovchanger] loop exception: {exc}")
            connector.invalidate()
            time.sleep(0.01)
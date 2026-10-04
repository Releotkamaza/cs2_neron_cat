import gc
import json
import math
import os
import time
import ctypes
import struct

import win32api
import win32gui

from functions import memfuncs
from functions import gameinput
from functions import logutil
from functions.process_watcher import ProcessConnector


class Vector3:
    __slots__ = ("x", "y", "z")

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)


MIN_VALID_PTR = 0x1000
MAX_VALID_PTR = 0x7FFFFFFFFFFF

# ==================== Структурные константы entity-листа ====================
# Единая конвенция проекта (шапки features/esp/core.py, features/noscopedot.py).
# Магические числа 0x3FFF/прочие из старой копипасты выровнены на канон.
ENT_BUCKET_STEP = 0x8      # шаг бакетов entity list
ENT_IDENTITY = 0x10        # смещение CEntityIdentity в слоте
ENT_STRIDE = 112           # stride слота (контроллеры и павны)
HANDLE_SER_MASK = 0x7FFF   # серийно-индексные биты handle
HANDLE_IDX_MASK = 0x1FF    # индекс внутри бакета
BONE_STRIDE = 32           # размер записи кости в boneMatrix
BONE_ARRAY_OFF = 0x80      # boneArray внутри model state
BONE_SPAN = 27             # старший используемый индекс кости (eye_R=26) + 1


def valid_ptr(ptr):
    try:
        ptr = int(ptr)
    except:
        return False
    return MIN_VALID_PTR <= ptr <= MAX_VALID_PTR


def safe_read_ptr(process, address):
    if not valid_ptr(address):
        return 0
    try:
        ptr = memfuncs.ProcMemHandler.ReadPointer(process, address)
        return ptr if valid_ptr(ptr) else 0
    except:
        return 0


def safe_read_int(process, address, default=0):
    if not valid_ptr(address):
        return default
    try:
        return memfuncs.ProcMemHandler.ReadInt(process, address)
    except:
        return default


def safe_read_vec(process, address):
    if not valid_ptr(address):
        return None
    try:
        vec = memfuncs.ProcMemHandler.ReadVec(process, address)
        if vec is None:
            return None
        if not (math.isfinite(vec.x) and math.isfinite(vec.y) and math.isfinite(vec.z)):
            return None
        return Vector3(vec.x, vec.y, vec.z)
    except:
        return None


def read_head_center(process, boneMatrix):
    """Центр головы. Bulk-чтение костей ОДНИМ RPM (было 4 чтения по 12 байт
    на каждого кандидата автоволл-скана), семантика прежняя:
    глаза -> голова(7) -> шея(6). Фоллбек - старый поштучный путь."""
    buf = None
    try:
        buf = memfuncs.ProcMemHandler.ReadBytes(process, boneMatrix, BONE_STRIDE * BONE_SPAN)
    except Exception:
        buf = None
    if buf and len(buf) >= BONE_STRIDE * BONE_SPAN:
        def _v(i):
            x, y, z = struct.unpack_from('<3f', buf, i * BONE_STRIDE)
            if math.isfinite(x) and math.isfinite(y) and math.isfinite(z):
                return (x, y, z)
            return None

        le = _v(25)
        re_ = _v(26)
        if le is not None and re_ is not None:
            return Vector3(
                (le[0] + re_[0]) / 2.0,
                (le[1] + re_[1]) / 2.0,
                (le[2] + re_[2]) / 2.0
            )
        h = _v(7)
        if h is not None:
            return Vector3(h[0], h[1], h[2])
        n = _v(6)
        if n is not None:
            return Vector3(n[0], n[1], n[2])
        return None

    left_eye = safe_read_vec(process, boneMatrix + 25 * BONE_STRIDE)
    right_eye = safe_read_vec(process, boneMatrix + 26 * BONE_STRIDE)
    if left_eye is not None and right_eye is not None:
        return Vector3(
            (left_eye.x + right_eye.x) / 2.0,
            (left_eye.y + right_eye.y) / 2.0,
            (left_eye.z + right_eye.z) / 2.0
        )
    head = safe_read_vec(process, boneMatrix + 7 * BONE_STRIDE)
    if head is not None:
        return head
    return safe_read_vec(process, boneMatrix + 6 * BONE_STRIDE)


def to_float(value, default=0.0):
    try:
        return float(value)
    except:
        return default


def to_bool(value, default=False):
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "enabled")
        return bool(value)
    except:
        return default


def lerp_by_distance(d, points):
    if not points:
        return 0.1
    if d <= points[0][0]:
        return points[0][1]
    for i in range(len(points) - 1):
        d0, v0 = points[i]
        d1, v1 = points[i + 1]
        if d <= d1:
            if d1 == d0:
                return v1
            return v0 + (d - d0) * (v1 - v0) / (d1 - d0)
    return points[-1][1]


def calculate_angle(from_pos, to_pos):
    dx = to_pos.x - from_pos.x
    dy = to_pos.y - from_pos.y
    dz = to_pos.z - from_pos.z
    yaw = math.atan2(dy, dx) * 180.0 / math.pi
    dist = math.sqrt(dx * dx + dy * dy)
    pitch = -math.atan2(dz, dist) * 180.0 / math.pi
    return (yaw, pitch)


def angle_difference(angle1, angle2):
    yaw1, pitch1 = angle1
    yaw2, pitch2 = angle2
    diff_yaw = (yaw2 - yaw1 + 180) % 360 - 180
    diff_pitch = (pitch2 - pitch1 + 180) % 360 - 180
    return math.sqrt(diff_yaw * diff_yaw + diff_pitch * diff_pitch)


# ==================== Оффсеты из дампа (без хардкода) ====================
# ВНИМАНИЕ (флаг на будущее): плоский словарь "имя -> первое вхождение" -
# запрещённый проектом паттерн (C_Chicken/C_EconEntity). Сейчас не стреляет,
# потому что _need берёт значения из dataclass приоритетно, дамп - только
# фоллбек. Пины (класс, поле) - отдельной задачей, по свежему дампу.

_json_cache = {}


def _find_dump_dir():
    base = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(base, ".."))
    for c in (os.path.join(repo, "output"), repo, os.path.join(repo, "ext"), base):
        if os.path.exists(os.path.join(c, "client_dll.json")):
            return c
    return None


_DUMP_DIR = _find_dump_dir()


def _dump_json(filename):
    if filename in _json_cache:
        return _json_cache[filename]
    data = {}
    if _DUMP_DIR:
        try:
            with open(os.path.join(_DUMP_DIR, filename), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    _json_cache[filename] = data or {}
    return _json_cache[filename]


def _schema_fields_flat():
    jd = _dump_json("client_dll.json")
    out = {}
    try:
        classes = jd.get("client.dll", {}).get("classes", {})
        for cdata in classes.values():
            for fname, fval in (cdata.get("fields") or {}).items():
                out.setdefault(str(fname).strip(), int(fval))
    except Exception:
        pass
    return out


_SCHEMA = _schema_fields_flat()


def TriggerbotThreadFunction(Options, Offsets):
    # Точность sleep: без этого time.sleep(0.005) на деле 5-15.6 мс
    # (гранулярность системного таймера Windows). 1 мс делает каденцию
    # предсказуемой. Действует, пока процесс воркера жив, при выходе
    # снимается само.
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

    connector = ProcessConnector("cs2.exe", modules=["client.dll"])

    off = Offsets.offset

    def _need(name):
        try:
            v = int(getattr(off, name, 0) or 0)
        except Exception:
            v = 0
        return v if v else _SCHEMA.get(name, 0)

    # Ядро: без них триггер не работает вообще
    o_local_pawn = _need("dwLocalPlayerPawn")
    o_entity_list = _need("dwEntityList")
    o_health = _need("m_iHealth")
    o_id_ent_index = _need("m_iIDEntIndex")
    o_origin = _need("m_vOldOrigin")

    core_missing = [
        n for n, v in (
            ("dwLocalPlayerPawn", o_local_pawn),
            ("dwEntityList", o_entity_list),
            ("m_iHealth", o_health),
            ("m_iIDEntIndex", o_id_ent_index),
            ("m_vOldOrigin", o_origin),
        ) if not v
    ]
    if core_missing:
        msg = ("[triggerbot] OFF - нет оффсетов: " + ", ".join(core_missing) +
               ". Запусти CS2, потом 'cs2-dumper -f json' в папке чита, перезапусти чит.")
        print(msg)
        logutil.debug(msg)
        while True:
            time.sleep(5)
        return

    # Автоволл: нужны доп. поля
    o_view_angles = _need("dwViewAngles")
    o_eye_angles = _need("m_angEyeAngles")
    o_pawn_handle = _need("m_hPlayerPawn")
    o_scene_node = _need("m_pGameSceneNode")
    o_model_state = _need("m_modelState")
    o_view_offset = _need("m_vecViewOffset")

    wb_missing = []
    if not (o_view_angles or o_eye_angles):
        wb_missing.append("dwViewAngles/m_angEyeAngles")
    for n, v in (
        ("m_hPlayerPawn", o_pawn_handle),
        ("m_pGameSceneNode", o_scene_node),
        ("m_modelState", o_model_state),
        ("m_vecViewOffset", o_view_offset),
    ):
        if not v:
            wb_missing.append(n)

    # Деградирующие проверки: офсет нет -> проверка выключается, а не стреляет вслепую
    o_team = _need("m_iTeamNum")
    o_flags = _need("m_fFlags")
    o_velocity = _need("m_vecVelocity")

    if not o_team:
        print("[triggerbot] m_iTeamNum отсутствует - team check отключён (обнови output/)")
        logutil.debug("[triggerbot] m_iTeamNum missing - team check disabled")
    if not o_flags:
        print("[triggerbot] m_fFlags отсутствует - проверка 'на земле' отключена")
        logutil.debug("[triggerbot] m_fFlags missing - ground check disabled")
    if not o_velocity:
        print("[triggerbot] m_vecVelocity отсутствует - проверка скорости отключена")
        logutil.debug("[triggerbot] m_vecVelocity missing - speed check disabled")

    if wb_missing:
        msg = "[triggerbot] автоволл отключён, нет оффсетов: " + ", ".join(wb_missing)
        print(msg)
        logutil.debug(msg)

    # FOV автоволла - всегда адаптивный
    wallbang_fov_points = [
        (0.0, 2.1),
        (120.0, 1.5),
        (250.0, 1.2),
        (450.0, 0.7),
        (700.0, 0.45),
        (1000.0, 0.3),
        (1500.0, 0.15),
        (3000.0, 0.1),
    ]

    # 5 мс каденция: средняя задержка реакции на появление цели ~2.5 мс.
    # Чтений в цикле - единицы, CPU-цена нулевая (timeBeginPeriod выше).
    LOOP_SLEEP = 0.005
    WALLBANG_EXTRA_SLEEP = 0.004

    last_exception_time = 0.0
    last_gc_time = 0.0
    last_shot_time = 0.0

    # IPC-кэш настроек: Options (Manager.dict) - RPC на каждый .get(),
    # до 6 get за цикл хоронили каденцию. Перечитывается одним .items()
    # раз в 100 мс (правило проекта: в мс-циклах только локальные копии).
    opts_cache = {}
    opts_ts = 0.0

    # Кэш фокуса окна: GetWindowText - оконное сообщение, до ~1 мс.
    focus_ts = 0.0
    focus_ok = False

    while True:
        try:
            now = time.time()

            if now - opts_ts >= 0.1:
                try:
                    opts_cache = dict(Options.items())
                except Exception:
                    pass
                opts_ts = now
            opts = opts_cache

            if now - last_gc_time >= 5.0:
                # Только молодое поколение: полный collect морозил цикл
                # на несколько мс (тот же урок, что в main-лупе).
                gc.collect(0)
                last_gc_time = now

            if not to_bool(opts.get("EnableTriggerbot", False), False):
                time.sleep(0.05)
                continue

            process = connector.ensure_process()
            client = connector.ensure_module("client.dll")
            if not process or not client:
                time.sleep(0.05)
                continue

            if now - focus_ts >= 0.25:
                focus_ts = now
                try:
                    focus_ok = (win32gui.GetWindowText(
                        win32gui.GetForegroundWindow()) == "Counter-Strike 2")
                except Exception:
                    focus_ok = False
            if not focus_ok:
                time.sleep(0.02)
                continue

            local_pawn = safe_read_ptr(process, client + o_local_pawn)
            if not valid_ptr(local_pawn):
                time.sleep(0.02)
                continue

            local_hp = safe_read_int(process, local_pawn + o_health, 0)
            if local_hp <= 0:
                time.sleep(0.01)
                continue

            local_origin = safe_read_vec(process, local_pawn + o_origin)
            if local_origin is None:
                time.sleep(LOOP_SLEEP)
                continue

            team_check = to_bool(opts.get("EnableTriggerbotTeamCheck", False), False) and bool(o_team)
            require_ground = to_bool(opts.get("TriggerbotRequireGround", True), True) and bool(o_flags)
            speed_threshold = to_float(opts.get("TriggerbotSpeedThreshold", 5.0), 5.0) if o_velocity else 0.0

            # eye_pos нужен ТОЛЬКО автоволлу: view_offset читаем только когда
            # wallbang реально включен (раньше читался каждый цикл всегда).
            wallbang_mode = False
            eye_pos = None
            if not wb_missing and to_bool(opts.get("TriggerbotWallbang", False), False):
                view_offset = safe_read_vec(process, local_pawn + o_view_offset)
                if view_offset is None:
                    time.sleep(LOOP_SLEEP)
                    continue
                eye_pos = Vector3(
                    local_origin.x + view_offset.x,
                    local_origin.y + view_offset.y,
                    local_origin.z + view_offset.z
                )
                wallbang_mode = True

            shot_delay = to_float(opts.get("TriggerbotShotDelay", 0.4), 0.4)

            target = None
            target_hp = 0
            target_dist = 0.0

            if not wallbang_mode:
                # ОБЫЧНЫЙ режим: через m_iIDEntIndex
                local_id = safe_read_int(process, local_pawn + o_id_ent_index, 0)
                if local_id > 0:
                    entlist = safe_read_ptr(process, client + o_entity_list)
                    if valid_ptr(entlist):
                        entry = safe_read_ptr(
                            process,
                            entlist + ENT_BUCKET_STEP * (local_id >> 9) + ENT_IDENTITY)
                        if valid_ptr(entry):
                            maybe_target = safe_read_ptr(
                                process, entry + ENT_STRIDE * (local_id & HANDLE_IDX_MASK))
                            if valid_ptr(maybe_target) and maybe_target != local_pawn:
                                hp = safe_read_int(process, maybe_target + o_health, 0)
                                if 0 < hp <= 100:
                                    target = maybe_target
                                    target_hp = hp
                                    t_origin = safe_read_vec(process, maybe_target + o_origin)
                                    if t_origin is not None:
                                        target_dist = math.sqrt(
                                            (t_origin.x - local_origin.x) ** 2 +
                                            (t_origin.y - local_origin.y) ** 2 +
                                            (t_origin.z - local_origin.z) ** 2
                                        )
            else:
                # АВТОВОЛЛ: скан по углам, адаптивный FOV
                view_angles_vec = None
                if o_view_angles:
                    view_angles_vec = safe_read_vec(process, client + o_view_angles)
                if view_angles_vec is None and o_eye_angles:
                    view_angles_vec = safe_read_vec(process, local_pawn + o_eye_angles)
                if view_angles_vec is None:
                    time.sleep(LOOP_SLEEP)
                    continue
                view_angles = (view_angles_vec.y, view_angles_vec.x)

                entity_list = safe_read_ptr(process, client + o_entity_list)
                if not valid_ptr(entity_list):
                    time.sleep(LOOP_SLEEP)
                    continue

                # Команда локального - ОДИН раз на скан, не на каждого кандидата
                me_team = safe_read_int(process, local_pawn + o_team, 0) if team_check else 0

                # Слоты 1..63 живут в бакете 0: list_entry один на весь скан,
                # контроллеры - одним bulk-куском (фоллбек - поштучно).
                entry0 = safe_read_ptr(process, entity_list + ENT_IDENTITY)
                ctrl_buf = None
                if valid_ptr(entry0):
                    try:
                        ctrl_buf = memfuncs.ProcMemHandler.ReadBytes(
                            process, entry0, ENT_STRIDE * 64)
                        if not ctrl_buf or len(ctrl_buf) < ENT_STRIDE * 64:
                            ctrl_buf = None
                    except Exception:
                        ctrl_buf = None

                best_angle = 360.0
                best_target = 0
                best_hp = 0
                best_dist = 0.0
                le2_cache = {}

                for i in range(1, 64):
                    if ctrl_buf is not None:
                        controller = struct.unpack_from('<Q', ctrl_buf, i * ENT_STRIDE)[0]
                    else:
                        controller = safe_read_ptr(process, entry0 + ENT_STRIDE * i)
                    if not valid_ptr(controller):
                        continue

                    pawn_handle = safe_read_int(process, controller + o_pawn_handle, 0)
                    if pawn_handle <= 0 or pawn_handle == 0xFFFFFFFF or pawn_handle == -1:
                        continue

                    pawn_index = pawn_handle & HANDLE_SER_MASK
                    if pawn_index <= 0:
                        continue

                    bucket = pawn_index >> 9
                    list_entry2 = le2_cache.get(bucket, 0)
                    if not valid_ptr(list_entry2):
                        list_entry2 = safe_read_ptr(
                            process, entity_list + ENT_BUCKET_STEP * bucket + ENT_IDENTITY)
                        if valid_ptr(list_entry2):
                            le2_cache[bucket] = list_entry2
                        else:
                            le2_cache[bucket] = 0
                            continue

                    pawn = safe_read_ptr(
                        process, list_entry2 + ENT_STRIDE * (pawn_index & HANDLE_IDX_MASK))
                    if not valid_ptr(pawn) or pawn == local_pawn:
                        continue

                    hp = safe_read_int(process, pawn + o_health, 0)
                    if hp <= 0 or hp > 100:
                        continue

                    if team_check:
                        tgt_team = safe_read_int(process, pawn + o_team, 0)
                        if tgt_team not in (2, 3) or tgt_team == me_team:
                            continue

                    sceneNode = safe_read_ptr(process, pawn + o_scene_node)
                    if not valid_ptr(sceneNode):
                        continue

                    boneMatrix = safe_read_ptr(process, sceneNode + o_model_state + BONE_ARRAY_OFF)
                    if not valid_ptr(boneMatrix):
                        continue

                    head_pos = read_head_center(process, boneMatrix)
                    if head_pos is None:
                        continue

                    angle_to_target = calculate_angle(eye_pos, head_pos)
                    diff = angle_difference(view_angles, angle_to_target)

                    dist = math.sqrt(
                        (head_pos.x - eye_pos.x) ** 2 +
                        (head_pos.y - eye_pos.y) ** 2 +
                        (head_pos.z - eye_pos.z) ** 2
                    )

                    if not math.isfinite(dist) or not math.isfinite(diff):
                        continue

                    if diff < best_angle:
                        best_angle = diff
                        best_target = pawn
                        best_hp = hp
                        best_dist = dist

                if valid_ptr(best_target) and best_hp > 0:
                    threshold = max(0.05, lerp_by_distance(best_dist, wallbang_fov_points))
                    if best_angle < threshold:
                        target = best_target
                        target_hp = best_hp
                        target_dist = best_dist

                time.sleep(WALLBANG_EXTRA_SLEEP)

            if target and team_check:
                tgt_team = safe_read_int(process, target + o_team, 0)
                me_team = safe_read_int(process, local_pawn + o_team, 0)
                if tgt_team not in (2, 3) or tgt_team == me_team:
                    target = None
                    target_hp = 0

            if not valid_ptr(target) or target_hp <= 0:
                time.sleep(LOOP_SLEEP)
                continue

            if require_ground:
                flags = safe_read_int(process, local_pawn + o_flags, 1)
                if not (flags & 1):
                    time.sleep(LOOP_SLEEP)
                    continue

            if speed_threshold > 0.0:
                velocity = safe_read_vec(process, local_pawn + o_velocity)
                if velocity is None:
                    velocity = Vector3(0.0, 0.0, 0.0)
                speed = math.sqrt(
                    velocity.x * velocity.x +
                    velocity.y * velocity.y +
                    velocity.z * velocity.z
                )
                if math.isfinite(speed) and speed > speed_threshold:
                    time.sleep(LOOP_SLEEP)
                    continue

            if shot_delay > 0.0 and (now - last_shot_time) < shot_delay:
                time.sleep(0.01)
                continue

            if not win32api.GetAsyncKeyState(0x01):
                # Реакция (адаптивная по дистанции + рандом) живёт в gameinput
                gameinput.LeftClick(target_dist)
                last_shot_time = time.time()

            time.sleep(LOOP_SLEEP)

        except Exception as exc:
            now = time.time()
            if now - last_exception_time >= 1.0:
                logutil.debug(f"[triggerbot] loop exception: {exc}")
                last_exception_time = now
                connector.invalidate()
            time.sleep(0.05)

import gc
import json
import math
import os
import time
import ctypes
import random
import struct

import win32api
import win32gui

from functions import memfuncs
from functions import gameinput
from functions import logutil
from functions import calculations
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
    """Центр головы как в ESP (_head_from): по глазам (25/26) + шее (6),
    проекция вперёд по вектору neck->eye_mid, +3.0 по Z. Фоллбек на кость 7."""
    buf = None
    try:
        buf = memfuncs.ProcMemHandler.ReadBytes(process, boneMatrix, BONE_STRIDE * BONE_SPAN)
    except Exception:
        buf = None
    if buf and len(buf) >= BONE_STRIDE * BONE_SPAN:
        def _v(i):
            x, y, z = struct.unpack_from('<3f', buf, i * BONE_STRIDE)
            if math.isfinite(x) and math.isfinite(y) and math.isfinite(z):
                return Vector3(x, y, z)
            return None
        eye_l = _v(25); eye_r = _v(26); neck = _v(6); fb = _v(7)
        if eye_l and eye_r and neck:
            mx, my, mz = (eye_l.x + eye_r.x)/2.0, (eye_l.y + eye_r.y)/2.0, (eye_l.z + eye_r.z)/2.0
            vx, vy, vz = mx - neck.x, my - neck.y, mz - neck.z
            length = math.sqrt(vx*vx + vy*vy + vz*vz)
            if length > 0.01:
                return Vector3(mx - (vx/length)*4.0, my - (vy/length)*4.0, mz - (vz/length)*4.0 + 3.0)
            if fb: return Vector3(fb.x, fb.y, fb.z)
            return Vector3(mx, my, mz + 5.0)
        if fb: return Vector3(fb.x, fb.y, fb.z)
        if neck: return neck
        return None
    eye_l = safe_read_vec(process, boneMatrix + 25 * BONE_STRIDE)
    eye_r = safe_read_vec(process, boneMatrix + 26 * BONE_STRIDE)
    neck  = safe_read_vec(process, boneMatrix + 6  * BONE_STRIDE)
    fb    = safe_read_vec(process, boneMatrix + 7  * BONE_STRIDE)
    if eye_l and eye_r and neck:
        mx,my,mz = (eye_l.x+eye_r.x)/2.0,(eye_l.y+eye_r.y)/2.0,(eye_l.z+eye_r.z)/2.0
        vx,vy,vz = mx-neck.x,my-neck.y,mz-neck.z
        length = math.sqrt(vx*vx+vy*vy+vz*vz)
        if length > 0.01:
            return Vector3(mx-(vx/length)*4.0, my-(vy/length)*4.0, mz-(vz/length)*4.0 + 3.0)
        if fb: return fb
        return Vector3(mx,my,mz+5.0)
    if fb: return fb
    if neck: return neck
    return None


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


# ==================== Реакция триггера (TriggerbotDelay*) ====================
# Раньше это жило в functions/gameinput.py и там же была жёсткая таблица
# TRIGGER_DELAY_STEPS. Убрано: gameinput отвечает только за импуты, режим и
# таблицу задержки читает триггер. Никаких "запасных" кривых по дистанции -
# если настроек нет, работает безопасный откат LEGACY (битые/неизвестные
# данные не должны выглядеть как настройка пользователя).
#
# Внутренние id режимов пишет GUI (_config_combo_map): в конфиге строки,
# в списке - русские подписи.
DELAY_MODE_STATIC = "static"
DELAY_MODE_RANGE = "range"
DELAY_MODE_DISTANCE = "distance"

# Верхняя граница полей задержки/таблицы в GUI, мс.
DELAY_MS_MAX = 500.0

# Откат (нет режима / пустая таблица / неизвестная дистанция).
LEGACY_DELAY_MIN_MS = 1.0
LEGACY_DELAY_MAX_MS = 17.0


def _clamp_delay_ms(value, default=0.0):
    """Мс с клампом в [0, DELAY_MS_MAX]. Мусор/None -> default."""
    v = to_float(value, default)
    if v < 0.0:
        return 0.0
    if v > DELAY_MS_MAX:
        return DELAY_MS_MAX
    return v


def _norm_delay_range(lo, hi):
    """(мин, макс) мс: переставленные границы меняются местами, обе
    зажимаются в [0, DELAY_MS_MAX]."""
    a = _clamp_delay_ms(lo, 0.0)
    b = _clamp_delay_ms(hi, 0.0)
    return (a, b) if a <= b else (b, a)


def _table_row(row):
    """Строка таблицы -> (даль,от,даль,от) или None, если строка битая.
    Границы диапазонов и задержек упорядочиваются."""
    try:
        d0 = max(0.0, to_float(row[0], 0.0))
        d1 = max(0.0, to_float(row[1], 0.0))
        ms0, ms1 = _norm_delay_range(row[2], row[3])
    except (TypeError, IndexError, KeyError):
        return None
    if d0 > d1:
        d0, d1 = d1, d0
    return (d0, d1, ms0, ms1)


def _table_row_for_distance(table, distance):
    """Строка таблицы для дистанции (юниты).

    Правило: точное попадание в [от, до), иначе - БЛИЖАЙШИЙ по расстоянию
    промежуток: дистанция ниже первой строки -> первая, выше последней ->
    последняя, дно в дыру -> ближайший край. Так дальность всегда даёт
    строку, пока таблица не пуста.
    """
    rows = []
    for row in table:
        r = _table_row(row) if isinstance(row, (list, tuple)) else None
        if r is not None:
            rows.append(r)
    if not rows:
        return None
    try:
        d = max(0.0, float(distance))
    except (TypeError, ValueError):
        return None
    for r in rows:
        if r[0] <= d < r[1]:
            return r
    best = rows[0]
    best_gap = None
    for r in rows:
        if d < r[0]:
            gap = r[0] - d
        elif d > r[1]:
            gap = d - r[1]
        else:
            gap = 0.0
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best = r
    return best


def resolve_trigger_delay(opts, distance=None):
    """Задержка (мс) перед выстрелом: чтобы реакция была точной.

    Режимы конфига TriggerbotDelayMode:
      "static"   - постоянная TriggerbotDelayStatic, мс;
      "range"    - случайная из [TriggerbotDelayMin, TriggerbotDelayMax], мс;
      "distance" - случайная из строки TriggerbotDelayTable по дистанции.
    Откат (неизвестный режим, пустая/битая таблица, нет дистанции) -
    LEGACY_DELAY_MIN_MS..LEGACY_DELAY_MAX_MS.
    """
    try:
        mode = str(opts.get("TriggerbotDelayMode", DELAY_MODE_DISTANCE) or "")
    except Exception:
        mode = ""

    if mode == DELAY_MODE_STATIC:
        return _clamp_delay_ms(opts.get("TriggerbotDelayStatic", 50.0), 50.0)

    if mode == DELAY_MODE_RANGE:
        lo, hi = _norm_delay_range(
            opts.get("TriggerbotDelayMin", LEGACY_DELAY_MIN_MS),
            opts.get("TriggerbotDelayMax", LEGACY_DELAY_MAX_MS),
        )
        return random.uniform(lo, hi)

    if mode == DELAY_MODE_DISTANCE and distance is not None:
        try:
            table = opts.get("TriggerbotDelayTable") or []
        except Exception:
            table = []
        if isinstance(table, (list, tuple)) and len(table) > 0:
            row = _table_row_for_distance(table, distance)
            if row is not None:
                return random.uniform(row[2], row[3])

    return random.uniform(LEGACY_DELAY_MIN_MS, LEGACY_DELAY_MAX_MS)


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


def TriggerbotThreadFunction(Options, Offsets, Runtime=None):
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

            # Проверка команды: при наличии оффсета блокируем тиммейта.
            # Опция EnableTriggerbotTeamCheck используется если задана в конфиге.
            team_check = to_bool(opts.get("EnableTriggerbotTeamCheck", True), True) and bool(o_team)
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

            # TriggerbotShotDelayMs - минимальный интервал между выстрелами
            # в МС (ползунок «Задержка между выстрелами» в субвкладке).
            shot_ms = max(0.0, to_float(opts.get("TriggerbotShotDelayMs", 400.0), 400.0))

            target = None
            target_hp = 0
            target_dist = 0.0
            # Точка цели для проверки видимости через дым: у обычного режима
            # это m_vOldOrigin, у автоволла - центр головы.
            target_pos = None

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
                                        target_pos = t_origin
                                        target_dist = math.sqrt(
                                            (t_origin.x - local_origin.x) ** 2 +
                                            (t_origin.y - local_origin.y) ** 2 +
                                            (t_origin.z - local_origin.z) ** 2
                                        )
            else:
                # АВТОВОЛЛ: скан по углам, выбор по пересечению луча со сферой головы
                view_angles_vec = None
                if o_view_angles:
                    view_angles_vec = safe_read_vec(process, client + o_view_angles)
                if view_angles_vec is None and o_eye_angles:
                    view_angles_vec = safe_read_vec(process, local_pawn + o_eye_angles)
                if view_angles_vec is None:
                    time.sleep(LOOP_SLEEP)
                    continue
                # view_angles_vec: x=pitch, y=yaw, z=roll

                entity_list = safe_read_ptr(process, client + o_entity_list)
                if not valid_ptr(entity_list):
                    time.sleep(LOOP_SLEEP)
                    continue

                # Команда локального - ОДИН раз на скан
                me_team = safe_read_int(process, local_pawn + o_team, 0) if o_team else 0

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

                best_t = 10e12
                best_target = 0
                best_hp = 0
                best_dist = 0.0
                le2_cache = {}

                # forward из view angles
                pitch = math.radians(view_angles_vec.x)
                yaw = math.radians(view_angles_vec.y)
                cos_p = math.cos(pitch); sin_p = math.sin(pitch)
                cos_y = math.cos(yaw); sin_y = math.sin(yaw)
                fx, fy, fz = cos_p * cos_y, cos_p * sin_y, -sin_p
                D = (fx, fy, fz)

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

                    if o_team and me_team != 0:
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
                    if not (math.isfinite(head_pos.x) and math.isfinite(head_pos.y) and math.isfinite(head_pos.z)):
                        continue
                    def ray_sphere(Cx,Cy,Cz, r):
                        OCx,OCy,OCz = Cx-eye_pos.x, Cy-eye_pos.y, Cz-eye_pos.z
                        b = OCx*fx+OCy*fy+OCz*fz
                        if b < 0.1: return None
                        c = OCx*OCx+OCy*OCy+OCz*OCz - r*r
                        d = b*b - c
                        if d < 0: return None
                        t = b - math.sqrt(d)
                        if t < 0.1 or t > 8192: return None
                        return t
                    t = None
                    if head_pos is not None:
                        # try larger sphere to catch top/front
                        for r,dz in ((4.6,1.4),(4.4,1.2),(4.2,1.0),(4.0,0.8),(3.8,0.6),(3.6,0)):
                            t = ray_sphere(head_pos.x, head_pos.y, head_pos.z+dz, r)
                            if t is not None: break
                        if t is None:
                            t = ray_sphere(head_pos.x+fx*0.25, head_pos.y+fy*0.25, head_pos.z+1.2, 4.2)
                    else:
                        t = None
                    if t is None: continue

                    dist = math.sqrt((head_pos.x-eye_pos.x)**2 + (head_pos.y-eye_pos.y)**2 + (head_pos.z-eye_pos.z)**2)
                    if not math.isfinite(t) or not math.isfinite(dist): continue
                    if t > dist + 5.0: continue  # sanity check

                    if t < best_t:
                        best_t = t
                        best_target = pawn
                        best_hp = hp
                        best_dist = dist

                if valid_ptr(best_target) and best_hp > 0:
                    target = best_target
                    target_hp = best_hp
                    target_dist = best_dist
                    target_pos = head_pos

                time.sleep(WALLBANG_EXTRA_SLEEP)

            if target and o_team:
                tgt_team = safe_read_int(process, target + o_team, 0)
                me_team_local = safe_read_int(process, local_pawn + o_team, 0)
                if tgt_team not in (2, 3) or (me_team_local != 0 and tgt_team == me_team_local):
                    target = None
                    target_hp = 0

            if not valid_ptr(target) or target_hp <= 0:
                time.sleep(LOOP_SLEEP)
                continue

            # Проверка видимости через дым (аналог ESP/аимбота).
            # Запускается только когда включена галочка "Проверка на видимости"
            # в субвкладке триггербота (ключ EnableTriggerbotVisibilityCheck).
            # При включённом NoSmoke дым визуально убран - враг для игрока
            # видим, поэтому в этом случае смок не учитываем.
            if (to_bool(opts.get("EnableTriggerbotVisibilityCheck", False), False)
                    and not to_bool(opts.get("EnableNoSmoke", False), False)
                    and target_pos is not None
                    and Runtime is not None):
                try:
                    smokes = getattr(Runtime, "smokes", None)
                    if smokes:
                        # local_eye = local_origin + view_offset
                        view_offset = safe_read_vec(process, local_pawn + o_view_offset)
                        if view_offset is not None:
                            local_eye = Vector3(
                                local_origin.x + view_offset.x,
                                local_origin.y + view_offset.y,
                                local_origin.z + view_offset.z
                            )
                            if calculations.smoke_blocks_segment(
                                    local_eye, target_pos, smokes,
                                    calculations.SMOKE_RADIUS,
                                    now=time.time()):
                                target = None
                                target_hp = 0
                except Exception:
                    pass

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

            if shot_ms > 0.0 and (now - last_shot_time) < (shot_ms / 1000.0):
                time.sleep(0.01)
                continue

            if not win32api.GetAsyncKeyState(0x01):
                # Реакция перед кликом: режим и числа задаёт GUI
                # (TriggerbotDelay*, вкладка Triggerbot), сама формула -
                # resolve_trigger_delay() в этом же файле (по дистанции).
                delay_ms = resolve_trigger_delay(opts, target_dist)
                gameinput.LeftClick(delay_ms=delay_ms)
                last_shot_time = time.time()

            time.sleep(LOOP_SLEEP)

        except Exception as exc:
            now = time.time()
            if now - last_exception_time >= 1.0:
                logutil.debug(f"[triggerbot] loop exception: {exc}")
                last_exception_time = now
                connector.invalidate()
            time.sleep(0.05)

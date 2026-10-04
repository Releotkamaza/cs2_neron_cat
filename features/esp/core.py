from ext.datatypes import *
from functions import memfuncs
from functions import calculations
import globals
import pyMeow as pme
from features import nosmoke as _ns_mod
from features import noscopedot
from . import static as static_layer   # v5.9: статичный слой (зрители, прицел)
from .draw import (draw_box, draw_skeleton, draw_distance, draw_health_text,
                   draw_name, draw_health_bar, draw_weapon, draw_bomb_status_card)
from .colors import resolve_color, health_color_hex
from .visibility import resolve_local_index, is_visible_to_local
import threading
import time
import struct
import win32api, win32gui, win32process, win32con, os
from collections import namedtuple
import math as _m

# ==================== Кэши цветов ====================
# Парсинг hex убран из покадровых вызовов
_col_cache = {}
_health_hex_cache = {}
_health_col_cache = {}


def _col(hexstr):
    c = _col_cache.get(hexstr)
    if c is None:
        c = resolve_color(hexstr)
        _col_cache[hexstr] = c
    return c


def _health_hex(hp):
    h = _health_hex_cache.get(hp)
    if h is None:
        h = health_color_hex(hp)
        _health_hex_cache[hp] = h
    return h


def _health_col(hp):
    c = _health_col_cache.get(hp)
    if c is None:
        c = _col(_health_hex(hp))
        _health_col_cache[hp] = c
    return c


# pawn/scene_node - адреса для перечитки свежих данных прямо в кадре
# рендера (снапшот стареет на время скана - на быстрых целях скелеты
# отставали от моделек).
CachedEntity = namedtuple('CachedEntity',
                          ['team', 'is_enemy', 'health', 'origin', 'head', 'bones',
                           'pelvis', 'name', 'visible', 'dist', 'weapon',
                           'pawn', 'scene_node'])

# ==================== Структурные константы ====================
# В дампах cs2-dumper их нет по определению (дамп отдаёт только поля схем
# и кнопки). Те же значения использует вся кодовая база
# (aimbot/triggerbot/nosmoke/bhop); после обновления игры правятся здесь.
ENT_BUCKET_STEP = 0x8      # шаг бакетов entity list
ENT_IDENTITY = 0x10        # смещение CEntityIdentity в слоте
ENT_STRIDE = 112           # stride слота (контроллеры и павны)
HANDLE_SER_MASK = 0x7FFF   # серийно-индексные биты handle
HANDLE_IDX_MASK = 0x1FF    # индекс внутри бакета
BONE_STRIDE = 32           # размер записи кости в boneMatrix
BONE_ARRAY_OFF = 0x80      # boneArray внутри model state
BONE_SPAN = 27             # старший используемый индекс кости (eye_R=26) + 1
LIFESTATE_ALIVE = 256
BOX_TOP_OFFSET = 70.0      # верх коробки над origin
MIN_TARGET_DIST = 35.0     # отсечка по дистанции до локального игрока
TRACER_BONE_INDEX = 0      # кость 0: таз, низ-центр модели - крепление трейсеров

# Опорные кости bulk-ридера: eye/neck деривятся из PLAYER_BONES (единый
# источник индексов - ext/datatypes, смена там подхватывается здесь
# автоматически). Fallback-кость головы - отдельная калибровочная
# константа (кросс-ссылки в PLAYER_BONES нет).
BONE_EYE_L = PLAYER_BONES.get("eye_L", 25)
BONE_EYE_R = PLAYER_BONES.get("eye_R", 26)
BONE_NECK = PLAYER_BONES.get("neck", 6)
BONE_HEAD_FALLBACK = 7

# Окно кластера полей: если поля сидят ближе этого разброса - одно bulk
# чтение вместо чтения на каждое поле. НЕ оффсет, порог эвристики.
CLUSTER_MAX_SPREAD = 1024

# TTL перечитки КОСТЕЙ: игра обновляет анимацию со своей частотой, кости
# дорогие (bulk). Позиция (origin) в кэш не попадает - читается каждый
# кадр синхронно с view matrix (см. _fresh_draw_data). v6.2: 0.007 -> 0.005
# - голова/скелет свежее, меньше визуальное отставание от модели.
FRESH_TTL_SEC = 0.005

_fresh_cache = {}   # pawn -> (origin, head, bones, pelvis, ts)


def _vec3_zero(v):
    """Сигнатура сбоя чтения при семантике memfuncs v2.1 (ноль вместо
    ошибки). Реальный игрок в точном (0,0,0) карты не стоит."""
    return v.x == 0.0 and v.y == 0.0 and v.z == 0.0


# ==================== Кэш имён ====================
# Валидное имя кэшируется на NAME_TTL_OK, неудачное ("?") перечитывается
# каждые NAME_TTL_RETRY секунд.
NAME_TTL_OK = 10.0
NAME_TTL_RETRY = 1.5

_ELLIPSE_STEPS = 14
_ELLIPSE_UNIT = [
    (_m.cos(2.0 * _m.pi * k / _ELLIPSE_STEPS), _m.sin(2.0 * _m.pi * k / _ELLIPSE_STEPS))
    for k in range(_ELLIPSE_STEPS)
]

boneConnections = [
    ('neck', 'head'),
    ('neck', 'chest'),
    ('chest', 'pelvis'),
    ('chest', 'arm_upper_L'), ('arm_upper_L', 'arm_lower_L'), ('arm_lower_L', 'hand_L'),
    ('chest', 'arm_upper_R'), ('arm_upper_R', 'arm_lower_R'), ('arm_lower_R', 'hand_R'),
    ('pelvis', 'leg_upper_L'), ('leg_upper_L', 'leg_lower_L'), ('leg_lower_L', 'ankle_L'),
    ('pelvis', 'leg_upper_R'), ('leg_upper_R', 'leg_lower_R'), ('leg_lower_R', 'ankle_R'),
]

# Только кости, реально участвующие в отрисовке скелета: всё остальное из
# PLAYER_BONES (spine/lower_spine/clavicle_*) не распаковывается в словарь
# bones и не идёт дальше (фильтр в _read_bones_bulk). Само чтение памяти -
# единый сплошной блок 27*32 байт одной операцией ReadBytes (дешевле, чем
# читать по одной кости; неиспользуемые индексы сидят внутри блока между
# используемыми и их выкинуть из чтения физически нельзя).
_CONNECTED_BONES = {n for pair in boneConnections for n in pair}


def _head_from(eye_l, eye_r, neck, fallback):
    """Центр головы из костей - чистая математика, без чтений памяти."""
    if eye_l and eye_r and neck:
        mx = (eye_l.x + eye_r.x) / 2.0
        my = (eye_l.y + eye_r.y) / 2.0
        mz = (eye_l.z + eye_r.z) / 2.0
        vx = mx - neck.x
        vy = my - neck.y
        vz = mz - neck.z
        length = (vx * vx + vy * vy + vz * vz) ** 0.5
        if length > 0.01:
            return Vector3(mx - (vx / length) * 4.0,
                           my - (vy / length) * 4.0,
                           mz - (vz / length) * 4.0 + 3.0)
        if fallback:
            return fallback
        return Vector3(mx, my, mz + 5.0)
    if fallback:
        return fallback
    if neck:
        return neck
    return Vector3(0.0, 0.0, 0.0)


def _read_bones_bulk(processHandle, bone_matrix):
    """Атомарный слепок костей: ОДНО чтение BONE_SPAN*32 байт вместо ~21
    ReadVec. Кость 0 (таз) возвращается третьим значением - крепление
    трейсеров, нужна даже при выключенном скелете."""
    span = BONE_SPAN * BONE_STRIDE
    try:
        buf = memfuncs.ProcMemHandler.ReadBytes(processHandle, bone_matrix, span)
    except Exception:
        return None, None, None
    if not buf or len(buf) < span:
        return None, None, None

    def bone(i):
        x, y, z = struct.unpack_from('<3f', buf, i * BONE_STRIDE)
        return Vector3(x, y, z)

    eye_l = bone(BONE_EYE_L)
    eye_r = bone(BONE_EYE_R)
    neck = bone(BONE_NECK)
    fb = bone(BONE_HEAD_FALLBACK)
    head = _head_from(eye_l, eye_r, neck, fb)
    pelvis = bone(TRACER_BONE_INDEX)
    bones = {}
    for bname, bidx in PLAYER_BONES.items():
        if bname == "eye_L" or bname == "eye_R":
            continue
        if bname not in _CONNECTED_BONES:
            # неиспользуемые кости скелета (spine/lower_spine/clavicle_*)
            # не распаковываем - не идут в отрисовку и в кэш
            continue
        bones[bname] = bone(bidx)
    return head, bones, pelvis


def _filter_skeleton(bones, origin, head):
    """Отсев мусорных костей (далеко от origin - разъехавшаяся анимация)
    + подмена head. >= 2 валидных костей, иначе None."""
    if not bones:
        return None
    filtered = {}
    for bname, wp in bones.items():
        if (abs(wp.x - origin.x) > 200 or abs(wp.y - origin.y) > 200
                or abs(wp.z - origin.z) > 200):
            continue
        filtered[bname] = wp
    if len(filtered) >= 2:
        filtered["head"] = head
        return filtered
    return None


def _read_origin(processHandle, pawn, scene_node, o):
    """Позиция для отрисовки: интерполированная клиентом m_vecAbsOrigin
    (scene_node) - совпадает с моделью в кадре, а не с сырым тиком
    сервера. Фоллбэк на m_vOldOrigin (сырая серверная позиция) при
    нуле/сбое: энтити не мигает, отставание не растёт."""
    if scene_node and o.m_vecAbsOrigin:
        try:
            origin = memfuncs.ProcMemHandler.ReadVec(processHandle, scene_node + o.m_vecAbsOrigin)
            if origin is not None and not _vec3_zero(origin):
                return origin
        except Exception:
            pass
    try:
        origin = memfuncs.ProcMemHandler.ReadVec(processHandle, pawn + o.m_vOldOrigin)
        if origin is not None and not _vec3_zero(origin):
            return origin
    except Exception:
        pass
    return None


# Экстраполяция рисуемой геометрии вперёд по скорости: even интерполиро-
# ванный абсОриджин обновляется тиками (64 Гц -> ~15.6 мс) + сетевая
# задержка клиента, поэтому бокс/скелет визуально отстают от модели.
# Кламп по модулю: на резких остановках не улетаем сквозь стены.
# v6.2: период настраивается из GUI ("ESP_ExtrapolateMs", мс) - глобал
# перевыставляется каждый кадр до цикла отрисовки (см. ESP_Update).
# v6.4: сдвиг сглаживается EMA (SHIFT_SMOOTH_TAU ~1 тик): m_vecVelocity
# тиковая (64 Гц) - сырое vel*ms давало ступеньки-рывки ESP на каждом
# тике и «ушла плавность» (жалоба живого теста v6.3, 80 мс).
# v6.5: ДЕФОЛТ 0 (выключено). Живой тест: экстраполяция даёт перелёт
# в упоре (60 мс * 250 ю/с = 15 ю при дистанции 50-100 ю = треть экрана:
# «скелет улетает вперёд на модельку при стрейфе») и НЕ убирает хвост
# вдали. Отличия от стабильной были «незначительны и негативны» ->
# возврат к поведению стабильной (без сдвига), польза остаётся только
# от свежего чтения origin/костей в кадре. Слайдер оставлен (0..200).
EXTRAPOLATE_SEC = 0.05           # исторический дефолт (документация)
EXTRAPOLATE_MAX_SHIFT = 32.0     # потолок сдвига в юнитах
SHIFT_SMOOTH_TAU = 0.016         # постоянная времени EMA (~1 тик 64 Гц)
_EXTRAPOLATE_MS = 0              # текущее значение из Options (кадр)
_shift_smooth_cache = {}         # pawn -> (сглаженный сдвиг, ts)


def _extrapolate_shift(processHandle, pawn, o):
    """Vector3-сдвиг (или None), который надо прибавить КО ВСЕМ точкам
    геометрии (origin/кости/голова/таз), чтобы ESP совпал с моделью
    на экране. Сдвиг - суммарно, чтобы бокс и скелет не разъезжались.
    v6.4: результат пропускается через EMA - даже нулевая скорость
    плавно схлопывает сдвиг (цель остановилась), а не дёргает бокс."""
    if not o.m_vecVelocity:
        return None
    try:
        vel = memfuncs.ProcMemHandler.ReadVec(processHandle, pawn + o.m_vecVelocity)
    except Exception:
        return None
    if vel is None:
        return None
    raw = vel * (_EXTRAPOLATE_MS / 1000.0)
    length = (raw.x * raw.x + raw.y * raw.y + raw.z * raw.z) ** 0.5
    if length > EXTRAPOLATE_MAX_SHIFT and length > 0.0:
        k = EXTRAPOLATE_MAX_SHIFT / length
        raw = Vector3(raw.x * k, raw.y * k, raw.z * k)
    now = time.time()
    if len(_shift_smooth_cache) > 256:
        _shift_smooth_cache.clear()
    prev = _shift_smooth_cache.get(pawn)
    if prev is None:
        _shift_smooth_cache[pawn] = (raw, now)
        return raw
    pshift, pts = prev
    dt = now - pts
    if dt <= 0.0 or dt > 0.5:  # сбой времени/долгая пауза: пересоздать
        _shift_smooth_cache[pawn] = (raw, now)
        return raw
    alpha = 1.0 - _m.exp(-dt / SHIFT_SMOOTH_TAU)
    s = Vector3(pshift.x + (raw.x - pshift.x) * alpha,
                pshift.y + (raw.y - pshift.y) * alpha,
                pshift.z + (raw.z - pshift.z) * alpha)
    _shift_smooth_cache[pawn] = (s, now)
    return s


def _shift_pt(pt, shift):
    if pt is None or shift is None:
        return pt
    return pt + shift


def _shift_bones(bones, shift):
    if not bones or shift is None:
        return bones
    return {k: v + shift for k, v in bones.items()}


def _fresh_draw_data(processHandle, ent, o, want_bones):
    """Свежие origin/кости ПРЯМО в кадре рендера. origin читается КАЖДЫЙ
    кадр (одно дешёвое чтение, кэш ему только мешал бы), дорогие кости -
    по TTL-кэшу (рендер не чаще игры перечитывает анимацию). Сбой
    чтения -> None-поля: рисуем по снапшоту, энтити не мигает.
    want_bones=False - только origin (кости не рисуем)."""
    now = time.time()
    origin = _read_origin(processHandle, ent.pawn, ent.scene_node, o)
    if origin is None:
        return None, None, None, None
    raw_origin = origin
    shift = _extrapolate_shift(processHandle, ent.pawn, o)
    origin = _shift_pt(origin, shift)
    if not want_bones or not ent.scene_node:
        return origin, None, None, None
    cached = _fresh_cache.get(ent.pawn)
    if cached is not None:
        c_origin, c_head, c_bones, c_pelvis, ts = cached
        if now - ts < FRESH_TTL_SEC:
            # origin свежий из только что прочитанного (со сдвигом),
            # кости из кэша сырые - сдвигаем и их тоже (тот же shift).
            return origin, _shift_pt(c_head, shift), _shift_bones(c_bones, shift), _shift_pt(c_pelvis, shift)
    try:
        bm = memfuncs.ProcMemHandler.ReadPointer(
            processHandle, ent.scene_node + o.m_modelState + BONE_ARRAY_OFF)
        if not bm:
            return origin, None, None, None
        head, bones, pelvis = _read_bones_bulk(processHandle, bm)
        if len(_fresh_cache) > 128:
            _fresh_cache.clear()
        # Кэш храним СЫРЫМ (без сдвига): сдвиг зависит от текущей скорости
        # кадра, а не от момента чтения костей.
        _fresh_cache[ent.pawn] = (raw_origin, head, bones, pelvis, now)
        head = _shift_pt(head, shift)
        pelvis = _shift_pt(pelvis, shift)
        bones = _shift_bones(bones, shift)
        return origin, head, bones, pelvis
    except Exception:
        return origin, None, None, None

_last_focus_check = 0.0
_last_focus_result = False


def _neron_has_focus():
    global _last_focus_check, _last_focus_result
    now = time.time()
    if now - _last_focus_check < 0.5:
        return _last_focus_result
    _last_focus_check = now
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            _last_focus_result = False
            return False
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        h = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid)
        try:
            exe = win32process.GetModuleFileNameEx(h, 0)
            _last_focus_result = os.path.basename(exe).lower() == "cs2.exe"
            return _last_focus_result
        except Exception:
            title = (win32gui.GetWindowText(hwnd) or "").lower()
            _last_focus_result = ("counter-strike 2" in title) or ("counter-strike" in title)
            return _last_focus_result
        finally:
            try:
                win32api.CloseHandle(h)
            except Exception:
                pass
    except Exception:
        _last_focus_result = False
        return False


# ==================== Поток-ридер ====================
# Сканер строит снапшот валидности (кто жив/враг/дистанция) + адреса
# pawn/scene_node. Свежую геометрию перечитывает сам рендер-кадр
# (_fresh_draw_data) - скелеты не отстают от моделек. Проход сканера
# ускорен bulk-чтениями: массив контроллеров одним куском + кластеры
# полей (см. _scan_once).

_reader_state = {
    "proc": None,
    "client": 0,
    "offsets": None,      # объект Offsets целиком (нужен .offset и visibility)
    "opts": {},
}
_snapshot = []
_snap_lock = threading.Lock()
_name_cache = {}          # controller addr -> (name, read_ts)
_reader_thread = None


def _get_player_name(proc, controller, o):
    """Имя игрока с TTL-кэшем. '?' и пустые читаются заново каждые
    NAME_TTL_RETRY секунд, валидные держатся NAME_TTL_OK."""
    now = time.time()
    entry = _name_cache.get(controller)
    if entry is not None:
        name, ts = entry
        ttl = NAME_TTL_OK if (name and name != "?") else NAME_TTL_RETRY
        if now - ts < ttl:
            return name
    try:
        addr = memfuncs.ProcMemHandler.ReadPointer(proc, controller + o.m_sSanitizedPlayerName)
        name = memfuncs.ProcMemHandler.ReadString(proc, addr, 64) if addr else "?"
    except Exception:
        name = "?"
    if not name or not name.strip():
        name = "?"
    if len(_name_cache) > 512:
        _name_cache.clear()
    _name_cache[controller] = (name, now)
    return name


# ==================== Оружие в руках (Weapon Text) ====================
# Индекс активного оружия - по калиброванной композиции noscopedot:
#   pawn + m_pWeaponServices -> ws + m_hActiveWeapon -> entity по handle
#   (конвенция entity-листа) -> ent + m_AttributeManager(C_EconEntity)
#   + m_Item(C_AttributeContainer) + m_iItemDefinitionIndex
#   (C_EconItemView), uint16.
# Схема - единый источник noscopedot._get_schema(): те же (класс, поле)
# из дампа, никакого копипаста пар. Кэш по handle: индекс оружейной
# энтити постоянен, handle меняется только при смене оружия.
_wpn_idx_cache = {}    # weapon handle -> item definition index

# Item definition index -> имя. Игровые константы (не оффсеты, в дампах
# их нет по определению). Нет в таблице -> текст не рисуется.
WEAPON_NAMES = {
    1: "Deagle", 2: "Dualies", 3: "Five-Seven", 4: "Glock-18",
    7: "AK-47", 8: "AUG", 9: "AWP", 10: "FAMAS", 11: "G3SG1",
    13: "Galil AR", 14: "M249", 16: "M4A4", 17: "MAC-10", 19: "P90",
    23: "MP5-SD", 24: "UMP-45", 25: "XM1014", 26: "PP-Bizon",
    27: "MAG-7", 28: "Negev", 29: "Sawed-Off", 30: "Tec-9",
    32: "P2000", 33: "MP7", 34: "MP9", 35: "Nova", 36: "P250",
    38: "SCAR-20", 39: "SG 553", 40: "SSG 08", 42: "Knife", 59: "Knife",
    60: "M4A1-S", 61: "USP-S", 63: "CZ75-Auto", 64: "R8 Revolver",
    43: "Flash", 44: "HE", 45: "Smoke", 46: "Molotov", 47: "Decoy",
    48: "Incendiary", 49: "C4", 68: "Zeus",
}


def _weapon_display_name(idx):
    if idx in WEAPON_NAMES:
        return WEAPON_NAMES[idx]
    if 500 <= idx <= 560:
        return "Knife"   # скиновые ножи, item def range
    return None


def _read_active_weapon_idx(proc, entity_list, pawn, o, sch):
    """Индекс активного оружия павна. Ошибка чтения / неполная схема -
    None (текст просто не рисуется)."""
    ws_off = sch.get("m_pWeaponServices", 0)
    aw_off = sch.get("m_hActiveWeapon", 0)
    am_off = sch.get("m_AttributeManager", 0)
    item_off = sch.get("m_Item", 0)
    idx_off = sch.get("m_iItemDefinitionIndex", 0)
    if not (ws_off and aw_off and am_off and item_off and idx_off):
        return None
    try:
        ws = memfuncs.ProcMemHandler.ReadPointer(proc, pawn + ws_off)
        if not ws:
            return None
        try:
            handle = int(memfuncs.ProcMemHandler.ReadUInt(proc, ws + aw_off))
        except Exception:
            handle = int(memfuncs.ProcMemHandler.ReadInt(proc, ws + aw_off)) & 0xFFFFFFFF
        if not handle:
            return None
        idx = _wpn_idx_cache.get(handle)
        if idx is not None:
            return idx
        index = handle & HANDLE_SER_MASK
        le = memfuncs.ProcMemHandler.ReadPointer(
            proc, entity_list + ENT_BUCKET_STEP * (index >> 9) + ENT_IDENTITY)
        if not le:
            return None
        ent = memfuncs.ProcMemHandler.ReadPointer(
            proc, le + ENT_STRIDE * (index & HANDLE_IDX_MASK))
        if not ent:
            return None
        idx = int(memfuncs.ProcMemHandler.ReadUShort(proc, ent + am_off + item_off + idx_off))
        if len(_wpn_idx_cache) > 512:
            _wpn_idx_cache.clear()
        _wpn_idx_cache[handle] = idx
        return idx
    except Exception:
        return None


def _scan_once(st):
    proc = st["proc"]
    client = st["client"]
    offsets_obj = st["offsets"]
    opts = st["opts"]
    if offsets_obj is None:
        return None
    o = offsets_obj.offset

    opt_team_check = bool(opts.get("EnableESPTeamCheck", False))
    opt_skeleton = bool(opts.get("EnableESPSkeletonRendering", False))
    opt_name = bool(opts.get("EnableESPNameText", False))
    opt_visible = bool(opts.get("ESP_VisibleCheckBox", False))
    opt_weapon = bool(opts.get("EnableESPWeaponText", False))

    render_required = bool(opts.get("EnableESP", True)) and any((
        opts.get("EnableESPBoxRendering", False),
        opts.get("EnableESPNameText", False),
        opts.get("EnableESPDistanceText", False),
        opts.get("EnableESPHealthText", False),
        opts.get("EnableESPHealthBarRendering", False),
        opts.get("EnableESPTracerRendering", False),
        opts.get("EnableESPSkeletonRendering", False),
        opts.get("EnableESPWeaponText", False),
    ))
    if not render_required:
        return []

    # Локальные данные:
    #   нет павна (меню/лобби/загрузка) или исключение -> [] - гасим ESP.
    #   Нулевой origin - НЕ сбой: мёртвый/спектирующий павн отдаёт (0,0,0),
    #   скан обязан продолжаться (живые враги видны, умершие исчезают).
    #   Отсечка MIN_TARGET_DIST при нулевом origin самонейтрализуется:
    #   мировые координаты далеки от нуля, dist заведомо > порога.
    #   (История: гейт нулей из v5.7 замораживал снапшот призраками,
    #   затем [] глушил ESP после смерти - оба регресса отсюда.)
    try:
        local_pawn = memfuncs.ProcMemHandler.ReadPointer(proc, client + o.dwLocalPlayerPawn)
        if not local_pawn:
            return []
        local_controller = memfuncs.ProcMemHandler.ReadPointer(proc, client + o.dwLocalPlayerController)
        local_team = memfuncs.ProcMemHandler.ReadInt(proc, local_pawn + o.m_iTeamNum)
        local_origin = memfuncs.ProcMemHandler.ReadVec(proc, local_pawn + o.m_vOldOrigin)
        entity_list = memfuncs.ProcMemHandler.ReadPointer(proc, client + o.dwEntityList)
    except Exception:
        return []
    if not entity_list:
        return []

    # ---- Кластеры: одно bulk-чтение вместо чтения на каждое поле ----
    # Окно считается из реальных оффсетов датаclass-а, ноль хардкода.
    # Разброс > CLUSTER_MAX_SPREAD или поле недоступно - индивидуальные
    # чтения (старый путь).
    try:
        pawn_lo = min(int(o.m_iHealth), int(o.m_lifeState), int(o.m_pGameSceneNode))
        pawn_hi = max(int(o.m_iHealth), int(o.m_lifeState), int(o.m_pGameSceneNode)) + 8
        pawn_cluster_ok = (pawn_hi - pawn_lo) <= CLUSTER_MAX_SPREAD
        _off_health = int(o.m_iHealth) - pawn_lo
        _off_life = int(o.m_lifeState) - pawn_lo
        _off_gsn = int(o.m_pGameSceneNode) - pawn_lo
    except Exception:
        pawn_cluster_ok = False
        pawn_lo = pawn_hi = 0
        _off_health = _off_life = _off_gsn = 0

    try:
        ctrl_lo = min(int(o.m_hPlayerPawn), int(o.m_iTeamNum))
        ctrl_hi = max(int(o.m_hPlayerPawn), int(o.m_iTeamNum)) + 4
        ctrl_cluster_ok = (ctrl_hi - ctrl_lo) <= CLUSTER_MAX_SPREAD
        _off_hpawn = int(o.m_hPlayerPawn) - ctrl_lo
        _off_team = int(o.m_iTeamNum) - ctrl_lo
    except Exception:
        ctrl_cluster_ok = False
        ctrl_lo = ctrl_hi = 0
        _off_hpawn = _off_team = 0

    # ---- Bulk-подготовка прохода ----
    # Контроллеры слотов 0..63 живут в бакете 0 (i >> 9 == 0 для i < 64):
    # list_entry - 1 чтение за проход вместо 64, массив указателей
    # контроллеров - одним куском 64*112 байт. Сбой/короткое чтение -
    # fallback на поштучные (старый путь).
    list_entry = 0
    ctrl_buf = None
    try:
        list_entry = memfuncs.ProcMemHandler.ReadPointer(proc, entity_list + ENT_IDENTITY)
        if list_entry:
            ctrl_buf = memfuncs.ProcMemHandler.ReadBytes(proc, list_entry, ENT_STRIDE * 64)
            if not ctrl_buf or len(ctrl_buf) < ENT_STRIDE * 64:
                ctrl_buf = None
    except Exception:
        ctrl_buf = None

    local_index = 0
    if opt_visible:
        try:
            local_index = resolve_local_index(proc, entity_list, local_controller)
        except Exception:
            local_index = 0

    out = []
    _le2_cache = {}   # бакет -> list_entry павнов, кэш на проход
    for i in range(64):
        try:
            # Контроллер: из bulk-массива прохода или поштучно (fallback)
            if ctrl_buf is not None:
                controller = struct.unpack_from('<Q', ctrl_buf, i * ENT_STRIDE)[0]
            else:
                if not list_entry:
                    list_entry = memfuncs.ProcMemHandler.ReadPointer(
                        proc, entity_list + ENT_IDENTITY)
                    if not list_entry:
                        continue
                controller = memfuncs.ProcMemHandler.ReadPointer(
                    proc, list_entry + ENT_STRIDE * i)
            if not controller or controller == local_controller:
                continue

            # pawn_handle + team: кластер одним чтением
            if ctrl_cluster_ok:
                try:
                    cbuf = memfuncs.ProcMemHandler.ReadBytes(proc, controller + ctrl_lo, ctrl_hi - ctrl_lo)
                    pawn_handle = struct.unpack_from('<I', cbuf, _off_hpawn)[0]
                    team = struct.unpack_from('<i', cbuf, _off_team)[0]
                except Exception:
                    pawn_handle = memfuncs.ProcMemHandler.ReadInt(proc, controller + o.m_hPlayerPawn)
                    team = memfuncs.ProcMemHandler.ReadInt(proc, controller + o.m_iTeamNum)
            else:
                pawn_handle = memfuncs.ProcMemHandler.ReadInt(proc, controller + o.m_hPlayerPawn)
                team = memfuncs.ProcMemHandler.ReadInt(proc, controller + o.m_iTeamNum)
            if not pawn_handle:
                continue

            # Павн по handle: list_entry бакета кэшируется на проход
            pidx = pawn_handle & HANDLE_SER_MASK
            bucket = pidx >> 9
            le2 = _le2_cache.get(bucket, 0)
            if not le2:
                le2 = memfuncs.ProcMemHandler.ReadPointer(
                    proc, entity_list + ENT_BUCKET_STEP * bucket + ENT_IDENTITY)
                _le2_cache[bucket] = le2 or 0
            if not le2:
                continue
            pawn = memfuncs.ProcMemHandler.ReadPointer(
                proc, le2 + ENT_STRIDE * (pidx & HANDLE_IDX_MASK))
            if not pawn or pawn == local_pawn:
                continue

            # health / lifeState / sceneNode: кластер одним чтением
            if pawn_cluster_ok:
                try:
                    pbuf = memfuncs.ProcMemHandler.ReadBytes(proc, pawn + pawn_lo, pawn_hi - pawn_lo)
                    health = struct.unpack_from('<i', pbuf, _off_health)[0]
                    life_state = struct.unpack_from('<i', pbuf, _off_life)[0]
                    scene_node = struct.unpack_from('<Q', pbuf, _off_gsn)[0]
                except Exception:
                    health = memfuncs.ProcMemHandler.ReadInt(proc, pawn + o.m_iHealth)
                    life_state = memfuncs.ProcMemHandler.ReadInt(proc, pawn + o.m_lifeState)
                    scene_node = memfuncs.ProcMemHandler.ReadPointer(proc, pawn + o.m_pGameSceneNode)
            else:
                health = memfuncs.ProcMemHandler.ReadInt(proc, pawn + o.m_iHealth)
                life_state = memfuncs.ProcMemHandler.ReadInt(proc, pawn + o.m_lifeState)
                scene_node = memfuncs.ProcMemHandler.ReadPointer(proc, pawn + o.m_pGameSceneNode)

            if health <= 0:
                continue
            if life_state != LIFESTATE_ALIVE or (opt_team_check and team == local_team):
                continue
            if not scene_node:
                continue

            bone_matrix = memfuncs.ProcMemHandler.ReadPointer(
                proc, scene_node + o.m_modelState + BONE_ARRAY_OFF)
            if not bone_matrix:
                continue

            origin = _read_origin(proc, pawn, scene_node, o)
            if origin is None:
                continue

            dist = calculations.distance_vec3(origin, local_origin)
            if dist < MIN_TARGET_DIST:
                continue

            # Bulk-кости: и head, и скелет, и кость-крепление трейсера - одним чтением
            head, bones, pelvis = _read_bones_bulk(proc, bone_matrix)
            if head is None or _vec3_zero(head):
                continue
            if opt_skeleton:
                bones = _filter_skeleton(bones, origin, head)
            else:
                bones = None

            name = _get_player_name(proc, controller, o) if opt_name else None

            # Активное оружие: только когда текст включен, кэш по handle
            weapon = None
            if opt_weapon:
                sch = noscopedot._get_schema()
                widx = _read_active_weapon_idx(proc, entity_list, pawn, o, sch)
                if widx is not None:
                    weapon = _weapon_display_name(widx)

            visible = False
            if opt_visible:
                try:
                    visible = is_visible_to_local(proc, pawn, offsets_obj, local_index)
                except Exception:
                    visible = False

            out.append(CachedEntity(
                team=team,
                is_enemy=(team != local_team),
                health=health,
                origin=origin,
                head=head,
                bones=bones,
                pelvis=pelvis,
                name=name,
                visible=visible,
                dist=dist,
                weapon=weapon,
                pawn=pawn,
                scene_node=scene_node,
            ))
        except Exception:
            continue
    return out


def _reader_loop():
    global _snapshot
    while True:
        st = _reader_state
        if st["proc"] is None or not st["client"] or st["offsets"] is None:
            time.sleep(0.02)
            continue
        try:
            snap = _scan_once(st)
        except Exception:
            snap = None
        if snap is not None:
            with _snap_lock:
                _snapshot = snap
        time.sleep(0.001)


def _ensure_reader():
    global _reader_thread
    if _reader_thread is None or not _reader_thread.is_alive():
        _reader_thread = threading.Thread(target=_reader_loop, daemon=True)
        _reader_thread.start()


def ESP_Update(processHandle, clientBaseAddress, Options, Offsets, SharedBombState, SharedRuntime=None):
    _ensure_reader()

    if not _neron_has_focus():
        # Намеренный одиночный end_drawing без пары begin: продаёт бэкбуфер
        # и качает PollInputEvents, пока окно без фокуса. Проверено
        # рантаймом; не "чинить" на begin+end без прямой причины.
        try:
            pme.end_drawing()
        except Exception:
            pass
        return

    # Обновляем состояние для ридера; смена процесса - сброс кэшей
    # (имена, оружие, кости: после рестарта игры хэндлы переиспользуются).
    if (_reader_state["proc"] is not processHandle
            or _reader_state["client"] != clientBaseAddress):
        _reader_state["proc"] = processHandle
        _reader_state["client"] = clientBaseAddress
        _reader_state["offsets"] = Offsets
        _name_cache.clear()
        _wpn_idx_cache.clear()
        _fresh_cache.clear()
    _reader_state["opts"] = Options

    opt_box = Options.get("EnableESPBoxRendering", False)
    opt_name = Options.get("EnableESPNameText", False)
    opt_distance = Options.get("EnableESPDistanceText", False)
    opt_health_text = Options.get("EnableESPHealthText", False)
    opt_health_bar = Options.get("EnableESPHealthBarRendering", False)
    opt_tracer = Options.get("EnableESPTracerRendering", False)
    opt_skeleton = Options.get("EnableESPSkeletonRendering", False)
    opt_visible_box = Options.get("ESP_VisibleCheckBox", False)
    opt_weapon = Options.get("EnableESPWeaponText", False)

    if not bool(Options.get("EnableESP", True)):
        opt_box = opt_name = opt_distance = opt_health_text = False
        opt_health_bar = opt_tracer = opt_skeleton = opt_visible_box = False
        opt_weapon = False

    # Свежие кости в кадре нужны только когда их реально рисуем
    need_fresh_bones = bool(opt_skeleton or opt_tracer)

    sync_skel = bool(Options.get("ESP_HealthSyncSkeleton", True))
    sync_bar = bool(Options.get("ESP_HealthSyncBar", True))
    skel_scale = float(Options.get("ESP_SkeletonThicknessScale", 1.0) or 1.0)
    box_scale = float(Options.get("ESP_BoxThicknessScale", 1.0) or 1.0)
    bar_scale = float(Options.get("ESP_HealthBarThicknessScale", 1.0) or 1.0)

    # Цвета: базовая окраска по отношению к локальному игроку + кастомы
    enemy_col = _col(Options.get("Enemy_color", "#FF6A5A"))
    teammate_col = _col(Options.get("Teammate_color", "#4DA2FF"))
    box_custom = bool(Options.get("EnableBoxCustomColor", False))
    box_custom_col = _col(Options.get("Box_color", "#FF6A5A"))
    tracer_custom = bool(Options.get("EnableTracerCustomColor", False))
    tracer_custom_col = _col(Options.get("Tracer_color", "#FFD24D"))
    hpbar_custom = bool(Options.get("EnableHPBarCustomColor", False))
    hpbar_custom_col = _col(Options.get("HPBar_color", "#FF6A5A"))

    try:
        tracer_thick = float(Options.get("ESP_TracerThickness", 1.5) or 1.5)
    except Exception:
        tracer_thick = 1.5
    tracer_thick = max(0.5, min(4.0, tracer_thick))

    # v6.2: период экстраполяции ESP из GUI (мс), кламп 0..150. Глобал
    # читается _extrapolate_shift уже внутри кадра. 0 = выключено.
    # v6.3: дефолт 50 -> 80 и кламп 0..200. Живой тест в матче: бокс и
    # скелет отставали от моделей (~тик 15.6мс + пинг + кадр), 50 мс
    # не хватало; трейсеры отставали меньше (менее чувствительны).
    # v6.5: дефолт 0 - экстраполяция выключена (см. константы выше).
    # Живой тест показал перелёт в упоре и «отличия незначительны и
    # негативны»; слайдер оставлен для ручной подстройки (0..200).
    global _EXTRAPOLATE_MS
    try:
        _EXTRAPOLATE_MS = int(float(Options.get("ESP_ExtrapolateMs", 0) or 0))
    except Exception:
        _EXTRAPOLATE_MS = 0
    _EXTRAPOLATE_MS = max(0, min(200, _EXTRAPOLATE_MS))

    with _snap_lock:
        ents = _snapshot

    try:
        pme.begin_drawing()
    except Exception:
        return

    # ===== Панель зрителей (статично: Runtime читается раз в 0.2 c) =====
    # v5.9: вынесено в features/esp/static.py.
    try:
        static_layer.render_spectators(pme, Options, SharedRuntime)
    except Exception:
        pass

    # ===== NoScope-оверлей (крест при снятом скопе): ТОЛЬКО рисование =====
    # Снятие скопа - целиком в fovchanger (там же гейт снайперок на снятие).
    # zoomed: m_bIsScoped ИЛИ 0<FOV<89.
    try:
        if bool(Options.get("EnableNoScopeOverlay", False)):
            off = Offsets.offset
            o_sc = getattr(off, "m_bIsScoped", 0)
            zoomed = False
            lp = 0
            try:
                lp = memfuncs.ProcMemHandler.ReadPointer(
                    processHandle, clientBaseAddress + off.dwLocalPlayerPawn)
            except Exception:
                lp = 0

            if lp:
                if o_sc:
                    try:
                        zoomed = memfuncs.ProcMemHandler.ReadInt(processHandle, lp + o_sc) == 1
                    except Exception:
                        zoomed = False

                if not zoomed:
                    try:
                        cam = memfuncs.ProcMemHandler.ReadPointer(processHandle, lp + off.m_pCameraServices)
                        if cam:
                            cf = memfuncs.ProcMemHandler.ReadInt(processHandle, cam + off.m_iFOV)
                            if 0 < cf < 89:
                                zoomed = True
                    except Exception:
                        pass

            # Гейт снайперок: крест - только с AWP/SSG08/SCAR-20/G3SG1 в
            # руках. AUG/SG553 держат нативный скоуп - крест поверх него
            # не нужен. Схема/список - единые источники (noscopedot), чтение
            # - та же калиброванная композиция, что у Weapon Text. Сбой
            # чтения -> крест off, нативный прицел остаётся чистым.
            if zoomed:
                try:
                    _entlist = memfuncs.ProcMemHandler.ReadPointer(
                        processHandle, clientBaseAddress + off.dwEntityList)
                    _widx = None
                    if _entlist:
                        _widx = _read_active_weapon_idx(
                            processHandle, _entlist, lp, off, noscopedot._get_schema())
                    if _widx is None or _widx not in noscopedot.SNIPER_ITEM_IDS:
                        zoomed = False
                except Exception:
                    zoomed = False

            if zoomed:
                sw2, sh2 = globals.SCREEN_WIDTH, globals.SCREEN_HEIGHT
                col = _col("#000000")
                pme.draw_line(sw2 // 2, 0, sw2 // 2, sh2, color=col, thick=1.0)
                pme.draw_line(0, sh2 // 2, sw2, sh2 // 2, color=col, thick=1.0)
    except Exception:
        pass

    # Точка ноускопа: статичный слой (features/esp/static.py): параметры
    # (цвет/радиус/прозрачность) кэшируются, только наличие по таймеру.
    try:
        static_layer.render_noscopedot(pme, processHandle, clientBaseAddress, Offsets, Options)
    except Exception:
        pass

    # v5.9: кастомный прицел - статичный слой (features/esp/static.py):
    # геометрия кэшируется и читается только при открытом окне чита.
    # Живые гейты (зум/алив) draw_cfg проверяет каждый кадр сам.
    try:
        static_layer.render_crosshair(pme, processHandle, clientBaseAddress, Offsets, Options)
    except Exception:
        pass

    try:
        view_matrix = memfuncs.ProcMemHandler.ReadMatrix(
            processHandle, clientBaseAddress + Offsets.offset.dwViewMatrix)
    except Exception:
        view_matrix = None

    if view_matrix is None:
        try:
            pme.end_drawing()
        except Exception:
            pass
        return
        
    screen_w, screen_h = globals.SCREEN_WIDTH, globals.SCREEN_HEIGHT

    try:
        if bool(Options.get("EnableNoSmoke", False)) and SharedRuntime is not None:
            smokes_snapshot = getattr(SharedRuntime, "smokes", None)
            if smokes_snapshot:
                _ns_mod.render_smoke_markers(
                    pme, processHandle, clientBaseAddress, Offsets.offset,
                    list(smokes_snapshot), screen_w, screen_h)
    except Exception:
        pass

    o_fresh = Offsets.offset

    for ent in ents:
        try:
            # Свежие данные прямо в кадре; сбой -> снапшот (не мигаем)
            origin = ent.origin
            head = ent.head
            bones = ent.bones
            pelvis = ent.pelvis
            f_origin, f_head, f_bones, f_pelvis = _fresh_draw_data(
                processHandle, ent, o_fresh, need_fresh_bones)
            if f_origin is not None:
                origin = f_origin
            if f_head is not None:
                head = f_head
            if f_bones is not None:
                bones = f_bones
            if f_pelvis is not None:
                pelvis = f_pelvis

            sh = calculations.world_to_screen(view_matrix, head)
            sf = calculations.world_to_screen(view_matrix, origin)
            bt = calculations.world_to_screen(
                view_matrix, Vector3(origin.x, origin.y, origin.z + BOX_TOP_OFFSET))

            # Базовая окраска: противник/тиммейт (не T/CT)
            color_team = enemy_col if ent.is_enemy else teammate_col

            # Трейсер ДО гейт-проверок границ: линия живёт и у заэкранных
            # противников. Крепление - кость 0 (таз).
            if opt_tracer:
                tracer_w = pelvis if pelvis is not None else origin
                tp = calculations.world_to_screen(view_matrix, tracer_w)
                if tp is not None:
                    tcol = tracer_custom_col if tracer_custom else color_team
                    pme.draw_line(screen_w // 2, screen_h, tp.x, tp.y,
                                  color=tcol, thick=tracer_thick)

            if sh is None or sf is None or bt is None:
                continue
            if sh.x <= -1 or sf.y <= -1 or sh.x >= screen_w or sh.y >= screen_h:
                continue

            box_h = sf.y - bt.y
            rect_left = sf.x - box_h / 4
            rect_top = bt.y
            rect_w = box_h / 2
            rect_h = box_h
            rect_right = rect_left + rect_w

            info_x = rect_right + 12
            info_y = rect_top + 4

            # Белая окраска невидимых - только для командного варианта:
            # явно заданный "свой цвет" бокса сильнее.
            if opt_visible_box and not ent.visible:
                color_team = _col("#FFFFFF")

            hp_int = int(ent.health)
            health_col = _health_col(hp_int)
            hp_hex = _health_hex(hp_int)

            if opt_box:
                draw_box(rect_left, rect_top, rect_w, rect_h,
                         color=(box_custom_col if box_custom else color_team),
                         thickness_scale=box_scale)

            info_cursor = info_y

            if opt_name and ent.name:
                draw_name(ent.name.strip(), info_x, info_cursor, color="#E8F1FF")
                info_cursor += 14

            if opt_weapon and ent.weapon:
                draw_weapon(ent.weapon, info_x, info_cursor, color="#D9C9FF")
                info_cursor += 14

            if opt_distance:
                draw_distance(info_x, info_cursor, ent.dist, color="#A4B0C3")
                info_cursor += 14

            if opt_health_text:
                draw_health_text(info_x, info_cursor, ent.health, color="#82FFAE")

            if opt_health_bar:
                # Иерархия: sync_bar (по HP) > свой цвет > командная окраска
                bar_team = hpbar_custom_col if (hpbar_custom and not sync_bar) else color_team
                draw_health_bar(ent.health, rect_left, rect_top, rect_h,
                                thickness_scale=bar_scale, use_health_color=sync_bar,
                                team_color=bar_team,
                                color_from_hex=hp_hex)

            if opt_skeleton and bones:
                # Свежие кости проходят тот же фильтр мусора, что и снапшот
                bones = _filter_skeleton(bones, origin, head)
                if not bones:
                    continue
                bones2d = {}
                for bn, wp in bones.items():
                    b2d = calculations.world_to_screen(view_matrix, wp)
                    if b2d is None:
                        continue
                    bones2d[bn] = b2d
                if not bones2d:
                    continue
                sk_thick = max(0.9, min(1.8, rect_h * 0.012)) * skel_scale
                sk_radius = int(max(1.0, min(3.0, rect_h * 0.02)))
                skel_col = health_col if sync_skel else color_team
                draw_skeleton(bones2d, boneConnections, color=skel_col,
                              thickness=sk_thick, joint_radius=sk_radius)

                if "head" in bones2d:
                    hp2d = bones2d["head"]
                    if hp2d.x >= 0 and hp2d.y >= 0:
                        head_r = max(2.0, rect_h * 0.085)
                        hw = head_r * 0.75
                        pts = [(hp2d.x + cx * hw, hp2d.y + cy * head_r)
                               for (cx, cy) in _ELLIPSE_UNIT]
                        for k in range(_ELLIPSE_STEPS):
                            a = pts[k]
                            b = pts[(k + 1) % _ELLIPSE_STEPS]
                            pme.draw_line(a[0], a[1], b[0], b[1],
                                          color=skel_col, thick=sk_thick)
        except Exception:
            continue

    try:
        if Options.get("EnableESPBombTimer", False) and SharedBombState is not None:
            draw_bomb_status_card(
                planted=getattr(SharedBombState, "bombPlanted", False),
                time_left=getattr(SharedBombState, "bombTimeLeft", -1),
                total_time=getattr(SharedBombState, "bombTimeTotal", 40) or 40,
                defusing=bool(getattr(SharedBombState, "bombBeingDefused", False)),
                defuse_left=getattr(SharedBombState, "bombDefuseLeft", None),
                defuse_total=getattr(SharedBombState, "bombDefuseTotal", None),
                defuse_impossible=bool(getattr(SharedBombState, "bombDefuseImpossible", False)),
            )
    except Exception:
        pass

    try:
        pme.end_drawing()
    except Exception:
        pass

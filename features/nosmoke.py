import json
import math
import os
import struct
import time
from functions import memfuncs
from functions.process_watcher import ProcessConnector

SCAN_INTERVAL_SEC = 0.10
MAX_ENTITIES_CAP = 2048

MASK64   = 0xFFFFFFFFFFFFFFFF
USER_LOW  = 0x0000000000100000
USER_HIGH = 0x00007FFFFFFFFFFF

# Структурные константы entity-листа (в дампе их нет,
# те же числа, что и в spectator.py: страйд 112, identity на +0x10)
ENTITY_LIST_STRIDE     = 112
ENTITY_IDENTITY_OFFSET = 0x10

SMOKE_CLASS_NAME = "smokegrenade_projectile"

# --- Маркер смока на оверлее (дизайн-константы, не оффсеты) ---
SMOKE_RADIUS    = 128.0          # радиус смока в юнитах CS2
RING_POINTS     = 16             # точек на нижней окружности
TOP_ELEV_DEG    = 45.0           # высота боковых верхних точек
TOP_AZIMUTH_DEG = (45.0, 135.0, 225.0, 315.0)
MARKER_COLOR    = "#9FB6DE"

def _find_dump_path():
    """Ищет дамп client_dll.json: сначала известные пути, потом любой json
    в output/, содержащий класс смока."""
    base = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(base, ".."))
    candidates = [
        os.path.join(repo, "output", "client_dll.json"),
        os.path.join(repo, "client_dll.json"),
        os.path.join(repo, "ext", "client_dll.json"),
        os.path.join(base, "client_dll.json"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    out_dir = os.path.join(repo, "output")
    try:
        for fn in sorted(os.listdir(out_dir)):
            if not fn.lower().endswith(".json"):
                continue
            p = os.path.join(out_dir, fn)
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    if "C_SmokeGrenadeProjectile" in f.read():
                        return p
            except Exception:
                continue
    except Exception:
        pass
    return None

_DUMP_PATH = _find_dump_path()

def _load_dump_fields(path):
    """Достаёт нужные оффсеты напрямую из дампа, чтобы модуль не зависел
    от того, что решил выставить ext/offsets."""
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        def strip_keys(d):
            if isinstance(d, dict):
                return {str(k).strip(): strip_keys(v) for k, v in d.items()}
            return d

        data = strip_keys(raw)
        classes = data.get("client.dll", {}).get("classes", {})
        wanted = ("CEntityIdentity", "C_BaseEntity", "CGameSceneNode", "C_SmokeGrenadeProjectile")
        out = {}
        for cls in wanted:
            fields = classes.get(cls, {}).get("fields", {})
            for k, v in fields.items():
                out.setdefault(k, v)
        return out
    except Exception:
        return {}

_DUMP_FIELDS = _load_dump_fields(_DUMP_PATH)

def _off(off, name):
    """Оффсет берём из Offsets.offset; если его там нет - из дампа."""
    val = 0
    try:
        val = getattr(off, name, 0) or 0
    except Exception:
        val = 0
    if not val:
        val = _DUMP_FIELDS.get(name, 0) or 0
    return val

def _build_marker_segments():
    """Каркас 'купола': пары точек на единичной сфере (радиус 1)."""
    segs = []
    # Нижняя окружность: точки соединяются с соседними
    ring = []
    for i in range(RING_POINTS):
        a = 2.0 * math.pi * i / RING_POINTS
        ring.append((math.cos(a), math.sin(a), 0.0))
    for i in range(RING_POINTS):
        segs.append((ring[i], ring[(i + 1) % RING_POINTS]))
    # Верх: 4 боковые точки + центральная (вершина), все на том же радиусе
    elev = math.radians(TOP_ELEV_DEG)
    h  = math.sin(elev)
    r2 = math.cos(elev)
    top = []
    for az in TOP_AZIMUTH_DEG:
        a = math.radians(az)
        top.append((math.cos(a) * r2, math.sin(a) * r2, h))
    apex = (0.0, 0.0, 1.0)
    for i in range(len(top)):
        segs.append((top[i], top[(i + 1) % len(top)]))  # соседние боковые между собой
        segs.append((top[i], apex))                     # каждая с центральной
    return segs

_MARKER_SEGMENTS = _build_marker_segments()

def to_u64(x):
    try:
        return int(x) & MASK64
    except Exception:
        return 0

def is_valid_ptr(p):
    p = to_u64(p)
    return USER_LOW <= p <= USER_HIGH

def rd_ptr(h, addr):
    try:
        p = memfuncs.ProcMemHandler.ReadPointer(h, addr)
        p = to_u64(p)
        return p if is_valid_ptr(p) else 0
    except Exception:
        return 0

def rd_bool(h, addr):
    try:
        return bool(memfuncs.ProcMemHandler.ReadBool(h, addr))
    except Exception:
        return False

def rd_int(h, addr):
    try:
        return memfuncs.ProcMemHandler.ReadInt(h, addr) & 0xFFFFFFFF
    except Exception:
        return 0

def rd_bytes(h, addr, n):
    try:
        return memfuncs.ProcMemHandler.ReadBytes(h, addr, n)
    except Exception:
        return b""

def read_cstr_utf8(h, addr, maxlen=64):
    if not addr:
        return ""
    bs = rd_bytes(h, addr, maxlen)
    if not bs:
        return ""
    try:
        return bs.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
    except Exception:
        return ""

def ent_by_index(h, entlist_ptr, i):
    """Получить entity по индексу (та же логика, что в spectator.py)"""
    entry2 = rd_ptr(h, entlist_ptr + 0x8 * (i >> 9) + 0x10)
    if not entry2:
        return 0
    e = rd_ptr(h, entry2 + ENTITY_LIST_STRIDE * (i & 0x1FF))
    return e if is_valid_ptr(e) else 0

def get_class_name(h, entity_ptr, name_off):
    """Имя класса entity через CEntityIdentity::m_designerName (оффсет из дампа)"""
    if not name_off:
        return ""
    identity = rd_ptr(h, entity_ptr + ENTITY_IDENTITY_OFFSET)
    if not identity:
        return ""
    name_ptr = rd_ptr(h, identity + name_off)
    if not name_ptr:
        return ""
    return read_cstr_utf8(h, name_ptr, 48)

def NoSmokeThreadFunction(Options, Offsets, Runtime=None):
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    off = Offsets.offset

    did_off  = _off(off, "m_bDidSmokeEffect")
    pos_off  = _off(off, "m_vSmokeDetonationPos")
    name_off = _off(off, "m_designerName")

    while True:
        try:
            hproc = connector.ensure_process()
            client = connector.ensure_module("client.dll")

            if not bool(Options.get("EnableNoSmoke", False)):
                if Runtime is not None:
                    try:
                        Runtime.smokes = []
                    except Exception:
                        pass
                time.sleep(0.25)
                continue

            entlist_ptr = rd_ptr(hproc, client + off.dwEntityList)
            if not entlist_ptr:
                time.sleep(SCAN_INTERVAL_SEC)
                continue

            # До какого индекса сканировать: highestEntityIndex из дампа, с ограничителем
            hi_off = getattr(off, "dwGameEntitySystem_highestEntityIndex", 0) or 0
            highest = rd_int(hproc, entlist_ptr + hi_off) if hi_off else 0
            if highest < 64:
                highest = 1024
            max_idx = min(highest + 1, MAX_ENTITIES_CAP)

            smokes = []
            for i in range(1, max_idx):
                entity = ent_by_index(hproc, entlist_ptr, i)
                if not entity:
                    continue
                if get_class_name(hproc, entity, name_off) != SMOKE_CLASS_NAME:
                    continue

                # Подавление смока - всегда и для всех
                if did_off and not rd_bool(hproc, entity + did_off):
                    try:
                        memfuncs.ProcMemHandler.WriteBool(hproc, entity + did_off, True)
                    except Exception:
                        pass

                # Центр для маркера
                if not pos_off:
                    continue
                try:
                    pos = memfuncs.ProcMemHandler.ReadVec(hproc, entity + pos_off)
                except Exception:
                    pos = None
                if pos is None or (abs(pos.x) <= 1.0 and abs(pos.y) <= 1.0):
                    continue
                smokes.append([float(pos.x), float(pos.y), float(pos.z)])

            if Runtime is not None:
                try:
                    Runtime.smokes = smokes
                except Exception:
                    pass

            time.sleep(SCAN_INTERVAL_SEC)

        except Exception:
            connector.invalidate()
            time.sleep(0.5)

def render_smoke_markers(pme, processHandle, clientBase, off, smokes, screen_w, screen_h):
    """Рисует каркас-купол на месте каждого удалённого смока."""
    vm_off = getattr(off, "dwViewMatrix", 0) or 0
    if not vm_off:
        return
    try:
        vm_bytes = memfuncs.ProcMemHandler.ReadBytes(processHandle, clientBase + vm_off, 64)
    except Exception:
        return
    vm = struct.unpack("16f", vm_bytes)

    col_near = pme.fade_color(pme.get_color(MARKER_COLOR), 0.90)  # ближняя половина ярче
    col_far  = pme.fade_color(pme.get_color(MARKER_COLOR), 0.35)  # дальняя - тусклее

    def _proj(x, y, z):
        """Мировые координаты -> пиксели экрана (NDC -> pixels)."""
        w = vm[12]*x + vm[13]*y + vm[14]*z + vm[15]
        if w < 0.01:
            return None  # точка за камерой
        nx = (vm[0]*x + vm[1]*y + vm[2]*z + vm[3]) / w
        ny = (vm[4]*x + vm[5]*y + vm[6]*z + vm[7]) / w
        sx = (nx + 1.0) * 0.5 * screen_w
        sy = (1.0 - ny) * 0.5 * screen_h
        return (sx, sy, w)

    R = SMOKE_RADIUS
    for s in smokes:
        try:
            cx, cy, cz = float(s[0]), float(s[1]), float(s[2])
        except Exception:
            continue

        # Глубина центра - для разделения ближней/дальней половины
        wc = vm[12]*cx + vm[13]*cy + vm[14]*cz + vm[15]

        for (p0, p1) in _MARKER_SEGMENTS:
            a = _proj(cx + p0[0]*R, cy + p0[1]*R, cz + p0[2]*R)
            b = _proj(cx + p1[0]*R, cy + p1[1]*R, cz + p1[2]*R)
            if not a or not b:
                continue
            (x0, y0, w0), (x1, y1, w1) = a, b
            # Полностью за экраном - не рисуем
            if max(x0, x1) < -64 or min(x0, x1) > screen_w + 64:
                continue
            if max(y0, y1) < -64 or min(y0, y1) > screen_h + 64:
                continue
            col = col_near if (w0 + w1) * 0.5 < wc else col_far
            pme.draw_line(int(x0), int(y0), int(x1), int(y1), color=col, thick=1.5)

        # Точка в центре
        c = _proj(cx, cy, cz)
        if c and 0 <= c[0] <= screen_w and 0 <= c[1] <= screen_h:
            pme.draw_circle(int(c[0]), int(c[1]), 3, color=col_far)
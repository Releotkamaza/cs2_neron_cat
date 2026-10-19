import json
import math
import os
import struct
import time

from functions import memfuncs
from functions import logutil
from functions.process_watcher import ProcessConnector

# ==================== Периодика и лимиты (не оффсеты) ====================
SCAN_INTERVAL_SEC = 0.10
MAX_ENTITIES_CAP = 2048
# Фоллбек-верхняя граница скана: если highestEntityIndex не читается,
# сканируем не больше этого количества слотов
FALLBACK_MAX_INDEX = 1024

# ==================== Валидация указателей ====================
MASK64   = 0xFFFFFFFFFFFFFFFF
USER_LOW  = 0x0000000000100000
USER_HIGH = 0x00007FFFFFFFFFFF

# ==================== Структурные константы entity-листа ====================
# В дампах cs2-dumper их нет по определению. Те же значения использует
# вся кодовая база (esp/core, spectator, aimbot, triggerbot, bhop).
ENT_BUCKET_STEP = 0x8
ENT_IDENTITY = 0x10
ENT_STRIDE = 112
HANDLE_SER_MASK = 0x7FFF
HANDLE_IDX_MASK = 0x1FF

SMOKE_CLASS_NAME = "smokegrenade_projectile"

# --- Маркер смока на оверлее (дизайн-константы, не оффсеты) ---
# SMOKE_RADIUS обязан совпадать с одноимённой константой в
# functions/calculations.py (она участвует в проверке видимости):
# правки делать в обоих файлах одной парой.
SMOKE_RADIUS    = 128.0          # радиус смока в юнитах CS2
RING_POINTS     = 16             # точек на нижней окружности
TOP_ELEV_DEG    = 45.0           # высота боковых верхних точек
TOP_AZIMUTH_DEG = (45.0, 135.0, 225.0, 315.0)
MARKER_COLOR    = "#9FB6DE"

# Время от детонации до НАЧАЛА рассеивания (конец плотной фазы дыма) -
# решение юзера 2026-10-07: таймер показывает время до рассеивания,
# значение 18.0 оставлено, т.к. подтверждено другими данными:
# - источники: Liquipedia ("full effect lasts 18 seconds"), Fandom,
#   scope.gg, swap.gg ("CS2 kept the same 18-second duration") = 18;
#   миноритарные ~20 (reddit/CSDB) считали с учётом рассеивания;
# - живой замер юзера согласуется: маркер ESP пропадает через 22.15 с
#   от детонации (остаток после "0.0" = 4.17/4.14 с - точные замеры;
#   4.69/4.7 завышены, юзер нажал раньше нуля), т.е. плотная фаза 18 +
#   рассеивание ~4 с = полное время жизни сущности 22.15.
# Поведение (осознанно принятый компромисс): "0.0" = дым начал
# рассеиваться, маркер ESP живёт ещё ~4 с до полного исчезновения
# (юзер: "ЕСП смока пропадает лишь когда смок пропадает полностью").
# Рандомизации длительности нет - замер детерминированный.
SMOKE_LIFETIME_SEC = 18.0

# Как часто обновлять локальную копию настройки (Options - IPC-прокси)
OPTS_REFRESH = 0.5

# ==================== Дамп client_dll.json ====================
# Единый конвейер известных путей (как в fovchanger/bombtimer):
# батник жёстко кладёт client_dll.json в output/, альтернативные имена
# и поисковый проход по всем json не нужны.
#
# ПРИМЕЧАНИЕ ПО КОНВЕНЦИИ: _SCHEMA - плоский словарь "первое вхождение".
# Это допустимый ФОЛЛБЕК под dataclass-приоритетом (_off ниже): поля
# смока читаются от entity НАПРЯМУЮ, композиций (AM/Item/idx) здесь нет,
# потому классоспецифичные пары не обязательны. Если поле в дампе
# неуникально и первое вхождение когда-нибудь станет чужим - перевести
# на pinned-классы по образцу noscopedot._get_schema().

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


_SCHEMA = {}
_jd = _dump_json("client_dll.json")
try:
    for _cdata in _jd.get("client.dll", {}).get("classes", {}).values():
        for _fname, _fval in (_cdata.get("fields") or {}).items():
            _SCHEMA.setdefault(str(_fname).strip(), int(_fval))
except Exception:
    pass


def _sf(name):
    """Оффсет поля схемы из дампа; 0 если дампа нет или поля нет."""
    return _SCHEMA.get(name, 0)


def _off(off, name):
    """dataclass -> дамп. Ноль = под-фича отключается (не fallback-число)."""
    val = 0
    try:
        val = int(getattr(off, name, 0) or 0)
    except Exception:
        val = 0
    if not val:
        val = _sf(name)
    return val


def _build_marker_segments():
    """Каркас 'купола': пары точек на единичной сфере (радиус 1)."""
    segs = []
    ring = []
    for i in range(RING_POINTS):
        a = 2.0 * math.pi * i / RING_POINTS
        ring.append((math.cos(a), math.sin(a), 0.0))
    for i in range(RING_POINTS):
        segs.append((ring[i], ring[(i + 1) % RING_POINTS]))
    elev = math.radians(TOP_ELEV_DEG)
    h  = math.sin(elev)
    r2 = math.cos(elev)
    top = []
    for az in TOP_AZIMUTH_DEG:
        a = math.radians(az)
        top.append((math.cos(a) * r2, math.sin(a) * r2, h))
    apex = (0.0, 0.0, 1.0)
    for i in range(len(top)):
        segs.append((top[i], top[(i + 1) % len(top)]))
        segs.append((top[i], apex))
    return segs


_MARKER_SEGMENTS = _build_marker_segments()

# Кэш цветов маркера: константы, собираются один раз (аналог _panel_colors
# у spectator). Значения - списки (контракт pme).
_MARKER_COLORS = None


def _marker_colors(pme):
    global _MARKER_COLORS
    if _MARKER_COLORS is None:
        base = pme.get_color(MARKER_COLOR)
        _MARKER_COLORS = (pme.fade_color(base, 0.90), pme.fade_color(base, 0.35))
    return _MARKER_COLORS


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


def rd_float(h, addr):
    try:
        v = float(memfuncs.ProcMemHandler.ReadFloat(h, addr))
        if v != v:  # NaN - мусор чтения
            return 0.0
        return v
    except Exception:
        return 0.0


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
    """Entity по индексу: bucket по (i >> 9), слот по страйду 112."""
    entry2 = rd_ptr(h, entlist_ptr + ENT_BUCKET_STEP * (i >> 9) + ENT_IDENTITY)
    if not entry2:
        return 0
    e = rd_ptr(h, entry2 + ENT_STRIDE * (i & HANDLE_IDX_MASK))
    return e if is_valid_ptr(e) else 0


def get_class_name(h, entity_ptr, name_off):
    """Имя класса entity через CEntityIdentity::m_designerName (оффсет из дампа)."""
    if not name_off:
        return ""
    identity = rd_ptr(h, entity_ptr + ENT_IDENTITY)
    if not identity:
        return ""
    name_ptr = rd_ptr(h, identity + name_off)
    if not name_ptr:
        return ""
    return read_cstr_utf8(h, name_ptr, 48)


def _confirm_smoke(hproc, entlist_ptr, i, entity, name_off):
    """Повторная перепроверка энтити ПЕРЕД записью: тот же слот вернул ТОТ ЖЕ
    указатель и класс всё ещё smokegrenade_projectile. Аналог _pawn_alive из
    antiflash: между чтением entity и записью объект может освободиться
    (деспавн смока, загрузка/выход матча), запись тогда уходит в
    переиспользованную/полупостроенную память и может ронять игру."""
    try:
        if ent_by_index(hproc, entlist_ptr, i) != entity:
            return False
        return get_class_name(hproc, entity, name_off) == SMOKE_CLASS_NAME
    except Exception:
        return False


def NoSmokeThreadFunction(Options, Offsets, Runtime=None):
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    off = Offsets.offset

    did_off  = _off(off, "m_bDidSmokeEffect")
    pos_off  = _off(off, "m_vSmokeDetonationPos")
    name_off = _off(off, "m_designerName")
    # Временные поля для компенсации полёта гранаты: детонация =
    # спаун + (m_flDetonateTime - m_flSpawnTime); оба есть в дампе
    # (наследуются: m_flDetonateTime от C_BaseGrenade, m_flSpawnTime
    # от C_BaseCSGrenadeProjectile). Нет полей -> таймер без компенсации.
    det_off   = _off(off, "m_flDetonateTime")
    spawn_off = _off(off, "m_flSpawnTime")

    # Деградация: нет полей смока в дампе - модуль фактически не работает
    if not did_off or not pos_off or not name_off:
        print("[nosmoke] поля смока отсутствуют в дампе - модуль отключён. "
              "Обнови output/ (запусти CS2, потом cs2-dumper -f json)", flush=True)

    enable_local = bool(Options.get("EnableNoSmoke", False))
    # Список смоков нужен ещё и проверке видимости (ESP_VisibleCheckBox /
    # EnableAimbotVisibilityCheck): она считает врага за дымом невидимым.
    vis_check = (bool(Options.get("ESP_VisibleCheckBox", False))
                 or bool(Options.get("EnableAimbotVisibilityCheck", False)))
    opts_ts = time.time()

    # Отсчёт до деспавна смока: ключ - центр детонации (округлённый;
    # константен всю жизнь сущности), значение - наше время time.time(),
    # когда купол исчезнет = детонация + SMOKE_LIFETIME_SEC.
    # Детонация в наших часах = первый_скан_сущности + полёт
    # (см. блок расчёта t_end ниже): позиция m_vSmokeDetonationPos может
    # быть валидна уже С БРОСКА (гипотеза, проверена симптомом юзера:
    # таймер истекал раньше деспавна на время полёта гранаты).
    t_end_by_pos = {}
    # entity addr -> наш time.time() первого обнаружения (спаун-якорь
    # для формулы детонации; погрешность <= SCAN_INTERVAL_SEC).
    ent_first = {}

    while True:
        try:
            now = time.time()
            if now - opts_ts >= OPTS_REFRESH:
                enable_local = bool(Options.get("EnableNoSmoke", False))
                vis_check = (bool(Options.get("ESP_VisibleCheckBox", False))
                             or bool(Options.get("EnableAimbotVisibilityCheck", False)))
                opts_ts = now

            if not enable_local and not vis_check:
                if Runtime is not None:
                    try:
                        Runtime.smokes = []
                    except Exception:
                        pass
                # Ни подавление дыма, ни проверка видимости не нужны -
                # накопленные ключи протухли бы (смоки деспавнились за время
                # паузы); при повторном включении отсчёт начнётся заново.
                t_end_by_pos.clear()
                ent_first.clear()
                time.sleep(0.25)
                continue

            hproc = connector.ensure_process()
            client = connector.ensure_module("client.dll")

            entlist_ptr = rd_ptr(hproc, client + off.dwEntityList)
            if not entlist_ptr:
                time.sleep(SCAN_INTERVAL_SEC)
                continue

            # До какого индекса сканировать: highestEntityIndex из дампа, с ограничителем
            hi_off = int(getattr(off, "dwGameEntitySystem_highestEntityIndex", 0) or 0)
            highest = rd_int(hproc, entlist_ptr + hi_off) if hi_off else 0
            if highest < 64:
                highest = FALLBACK_MAX_INDEX
            max_idx = min(highest + 1, MAX_ENTITIES_CAP)

            smokes = []
            alive_keys = set()
            alive_ents = set()
            for i in range(1, max_idx):
                entity = ent_by_index(hproc, entlist_ptr, i)
                if not entity:
                    continue
                if get_class_name(hproc, entity, name_off) != SMOKE_CLASS_NAME:
                    continue

                # Спаун-якорь: первый наш скан этой сущности (для формулы
                # детонации). Адрес живой сущности константен; при
                # переиспользовании слота прошлый якорь безвреден:
                # условие t0+flight > now отсекает устаревший якорь.
                if entity not in ent_first:
                    ent_first[entity] = now
                alive_ents.add(entity)

                # Подавление смока - ТОЛЬКО когда NoSmoke включён. При
                # скане ради проверки видимости (vis_check без enable_local)
                # смоки лишь собираются в Runtime.smokes, памяти не трогаем.
                # Запись только после повторной перепроверки: в момент массового
                # деспавна (загрузка/выход матча) слот entity-листа может
                # отдать освобождённую или переиспользованную энтити - запись
                # в неё роняет игру.
                if enable_local and did_off and not rd_bool(hproc, entity + did_off):
                    if _confirm_smoke(hproc, entlist_ptr, i, entity, name_off):
                        try:
                            memfuncs.ProcMemHandler.WriteBool(hproc, entity + did_off, True)
                        except Exception:
                            pass

                # Центр для маркера + отсчёт до деспавна
                if not pos_off:
                    continue
                try:
                    pos = memfuncs.ProcMemHandler.ReadVec(hproc, entity + pos_off)
                except Exception:
                    pos = None
                if pos is None or (abs(pos.x) <= 1.0 and abs(pos.y) <= 1.0):
                    continue
                key = (round(float(pos.x), 1), round(float(pos.y), 1),
                       round(float(pos.z), 1))
                if key not in t_end_by_pos:
                    # Детонация в НАШИХ часах = спаун-якорь + полёт
                    # (m_flDetonateTime - m_flSpawnTime). Формула max()
                    # покрывает три случая: позиция валидна с броска
                    # (t0+flight > now -> берём детонацию), позиция
                    # появилась уже после детонации (t0+flight < now ->
                    # берём now), фича включена посреди жизни смока
                    # (тоже now). flight вне (0, 30) - мусор чтения,
                    # отсчёт без компенсации (старое поведение).
                    t_end = now + SMOKE_LIFETIME_SEC
                    if det_off and spawn_off:
                        flight = (rd_float(hproc, entity + det_off)
                                  - rd_float(hproc, entity + spawn_off))
                        t0 = ent_first.get(entity, now)
                        if 0.0 < flight < 30.0 and t0 + flight > now:
                            t_end = t0 + flight + SMOKE_LIFETIME_SEC
                    t_end_by_pos[key] = t_end
                alive_keys.add(key)
                # 5-й элемент - время детонации в НАШИХ часах. Нужен
                # проверке видимости: пока смок в полёте, купола нет, и
                # линию видимости он перекрывать не должен.
                smokes.append([float(pos.x), float(pos.y), float(pos.z),
                               t_end_by_pos[key],
                               t_end_by_pos[key] - SMOKE_LIFETIME_SEC])

            # Чистка: сущности, не замеченные в этом цикле, деспавнились
            # (или entity-лист пересоздан) - их ключи протухли.
            for k in list(t_end_by_pos):
                if k not in alive_keys:
                    del t_end_by_pos[k]
            for a in list(ent_first):
                if a not in alive_ents:
                    del ent_first[a]

            if Runtime is not None:
                try:
                    Runtime.smokes = smokes
                except Exception:
                    pass

            time.sleep(SCAN_INTERVAL_SEC)

        except Exception as exc:
            try:
                _last_exc_ts
            except NameError:
                _last_exc_ts = 0.0
            now = time.time()
            if now - _last_exc_ts >= 1.0:
                logutil.debug(f"[nosmoke] loop exception: {exc}")
                connector.invalidate()
                _last_exc_ts = now
            time.sleep(0.5)


def render_smoke_markers(pme, processHandle, clientBase, off, smokes, screen_w, screen_h):
    """Рисует каркас-купол на месте каждого удалённого смока."""
    vm_off = int(getattr(off, "dwViewMatrix", 0) or 0)
    if not vm_off:
        return
    try:
        vm_bytes = memfuncs.ProcMemHandler.ReadBytes(processHandle, clientBase + vm_off, 64)
    except Exception:
        return
    if not vm_bytes or len(vm_bytes) < 64:
        return
    # Сырой кортеж, НЕ Matrix (без субскриптов); vm[12..15] - w-строка,
    # индексация согласована с calculations.world_to_screen
    vm = struct.unpack("16f", vm_bytes)

    # Цвета маркера - кэш, один раз за жизнь процесса
    col_near, col_far = _marker_colors(pme)

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

    # Ленивый импорт (вне пакета esp): draw_shadowed_label даёт обводку
    # текста - единый с ESP рендер (plate/shadow по TEXT_OUTLINE_MODE).
    _label = None
    try:
        from features.esp.draw import draw_shadowed_label as _label
    except Exception:
        _label = None

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

            # Таймер до деспавна смока - НАД центральной точкой, с обводкой
            # (s[3] = t_end, ставит сканер в NoSmokeThreadFunction).
            # Остаток <= 0 не показываем: сущность уходит из списка в
            # течение SCAN_INTERVAL, мелькание "0.0" не нужно.
            t_end = None
            try:
                t_end = float(s[3])
            except Exception:
                t_end = None
            if t_end is not None and _label is not None:
                remain = t_end - time.time()
                # Верх: полёт компенсируется в t_end (до +30 с), остаток
                # на старте = полёт + LIFETIME; >50 - точно мусор.
                if 0.0 < remain <= SMOKE_LIFETIME_SEC + 32.0:
                    txt = "%.1f" % remain
                    # Центрирование по точке: ширина - зеркало формулы
                    # plate-подложки из draw.py (int(len*size*0.62)+4).
                    w = int(len(txt) * 12 * 0.62) + 4
                    _label(txt, c[0] - w * 0.5, c[1] - 12 - 6,
                           size=12, color="#FFFFFF")
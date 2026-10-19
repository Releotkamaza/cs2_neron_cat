# Обводка персонажей (glow) в CS2: внешняя запись в CGlowProperty павна.
#
# Оффсеты берутся из дампа (output/client_dll.json, фоллбек: repo, ext):
#   * m_Glow        -> класс C_BaseModelEntity: АБСОЛЮТНЫЙ оффсет
#                      glow-структуры внутри павна;
#   * поля свечения -> класс CGlowProperty: оффсеты ОТНОСИТЕЛЬНО начала
#                      glow-структуры (m_fGlowColor=8, m_iGlowType=48,
#                      m_bGlowing=81 и т.д.). Плоского "имя -> оффсет" тут
#                      быть не может: у C_CSPlayerPawn этих полей нет.
#
# Пишем ТОЧЕЧНО (не блоком 128 байт, как было в первой версии: блок
# read-modify-write затирал соседние поля, которые игра переписывает сама):
#   m_iGlowType = 3 (светится постоянно), m_bGlowing = 1, m_iGlowTeam = 0,
#   m_glowColorOverride + m_fGlowColor = цвет.
# При выключении фичи — разовый проход очистки: свечение не «залипает»
# на игроках до конца раунда.
#
# ПОЧЕМУ ЦИКЛ ТАКОЙ СЛОЖНЫЙ (борьба с мерцанием): CS2 гасит m_bGlowing=false
# КАЖДЫЙ кадр своим glow-апдейтом, а рисует обводку позже в том же кадре.
# Внешнему читу остаётся успеть переписать 1 обратно в окно «сброс → отрисовка»,
# поэтому горячий путь максимально дешёвый:
#   * список павнов пересобирается редко (REPAWN_REFRESH): полный обход — это
#     ~148 чтений = 0.54 мс на ЭТОЙ машине, каждый пасс так нельзя;
#   * hp/team читаются раз в HP_REFRESH и кэшируются;
#   * в установившемся режиме на павна уходит ОДНА запись 1 байта (флаг),
#     остальные поля переписываются только при смене цвета/типа.
# Замеры (та же машина): ReadPointer 3.7 мкс, WriteBytes 8.1 мкс (сырой
# WriteProcessMemory 5.3 мкс), sleep(0.0002) при таймере 0.5 мс -> ~0.6 мс.
import ctypes
import json
import os
import struct
import time

from functions import logutil
from functions import memfuncs
from functions.process_watcher import ProcessConnector

# ===== структурные константы (синхронно с features/esp/core.py) =====
ENT_BUCKET_STEP = 0x8      # шаг бакетов entity list
ENT_IDENTITY = 0x10        # смещение CEntityIdentity в слоте
ENT_STRIDE = 112           # stride слота (контроллеры и павны)
HANDLE_SER_MASK = 0x7FFF   # серийно-индексные биты handle
HANDLE_IDX_MASK = 0x1FF    # индекс внутри бакета
SCAN_MAX = 128             # столько же слотов контроллеров сканирует ESP

MIN_VALID_PTR = 0x10000
MAX_VALID_PTR = 0x7FFFFFFFFFFF

GLOW_TYPE = 3              # CS2: 3 = светится ПОСТОЯННО (0=никогда, 1=когда
                           # используется, 2=когда на него смотрят)
LIFESTATE_ALIVE = 256      # m_lifeState живого павна (константа из esp/core.py)
# Сна в горячем цикле НЕТ (v8.11, решение юзера): цикл упирается только в работу
# пасса (замер: 0.08 мс на 11 павнов => десятки тысяч пассов/с, одно ядро CPU).
# Темп здесь критичен: CS2 сам гасит m_iGlowType/m_bGlowing ~5 раз/с, и длина
# «тёмного окна» (мерцание) = задержка до следующей перезаписи; sleep(0.0005)
# на деле спит 1-2 мс и при 5 противниках мерцание было видно (живой тест 14.10).
REPAWN_REFRESH = 0.25      # пересбор/перевалидация списка павнов (обход ~150
                           # чтений): заодно ловит переиспользованные слоты
HP_REFRESH = 0.15          # кэш hp/team/lifeState на павна
TEAM_T = 2                 # m_iTeamNum: Т
TEAM_CT = 3                # m_iTeamNum: КТ
T_COLOR = "#FF6A1A"        # режим Team: Т - оранжевый
CT_COLOR = "#4DA2FF"       # режим Team: КТ - синий
OPTS_REFRESH = 0.1         # кэш настроек: Manager-IPC в мс-цикле запрещён

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _valid_ptr(ptr):
    try:
        ptr = int(ptr)
    except Exception:
        return False
    return MIN_VALID_PTR <= ptr <= MAX_VALID_PTR


def _read_ptr(process, address):
    if not _valid_ptr(address):
        return 0
    try:
        v = memfuncs.ProcMemHandler.ReadPointer(process, address)
        return v if _valid_ptr(v) else 0
    except Exception:
        return 0


def _read_int(process, address, default=0):
    if not _valid_ptr(address):
        return default
    try:
        return int(memfuncs.ProcMemHandler.ReadInt(process, address))
    except Exception:
        return default


def _read_int_stable(process, address, default=0, suspect=(0,)):
    """Чтение int с перечиткой «подозрительного» значения.

    memfuncs при сбое ReadProcessMemory отдаёт НУЛИ (см. memfuncs.py), поэтому
    один транзиентный сбой выглядел бы как реальные данные: hp=0 -> «павн мёртв»
    (снятие обводки + выброс из списка до REPAWN_REFRESH), team=0 -> «все
    союзники» (при выключенных союзниках гасится ВСЁ). Перечитываем один раз:
    сбой обычно разовый, а реально мёртвый павн/освобождённый слот отдают ноль
    и во второй раз."""
    v = _read_int(process, address, default)
    if v in suspect:
        v2 = _read_int(process, address, default)
        if v2 not in suspect:
            return v2
    return v


def _write(process, address, raw):
    if not _valid_ptr(address):
        return False
    try:
        memfuncs.ProcMemHandler.WriteBytes(process, address, raw)
        return True
    except Exception:
        return False


def _read_bytes(process, address, count):
    """Сырые байты (для диагностики: одно чтение 40 байт дешевле двух)."""
    if not _valid_ptr(address):
        return b""
    try:
        raw = memfuncs.ProcMemHandler.ReadBytes(process, address, count)
        if isinstance(raw, (bytes, bytearray)) and len(raw) == count:
            return bytes(raw)
        return b""
    except Exception:
        return b""


# Быстрая запись через WriteProcessMemory напрямую - самый частый вызов в
# воркере. Замер на этой машине: 5.3 мкс против 8.1 мкс у pymem.WriteBytes.
#
# ЗАМЕРЫ 13.10 (живой CS2, bench_cs2_hotwrite.py, идемпотентно): холодная своя
# страница 4 мкс за запись, а ГОРЯЧАЯ страница павна (её игра трогает сама)
# 14-18 мкс за вызов; пять точечных полей = 84 мкс, блок-RMW (1 чтение + 1
# запись диапазона) = 20 мкс, чтение того же блока = 2.8 мкс. В живой игре на
# реальной карте те же записи дороже ещё в разы (в логах воркера пасс с 45
# записей стоил 100-190 мс против 10 мс на аим-карте). Отсюда правило горячего
# пути: ОДНО чтение на павна за пасс и запись ТОЛЬКО тех диапазонов, которые
# игра реально погасила (обычно - ни одной записи).
# Буфер один: воркер однопоточный. False -> вызывающий пишет через memfuncs.
_WPM = ctypes.windll.kernel32.WriteProcessMemory
_WPM.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                 ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
_WPM.restype = ctypes.c_int
_WPM_DONE = ctypes.c_size_t(0)
_WBUF_SIZE = 256
_WBUF = ctypes.create_string_buffer(_WBUF_SIZE)
_WBUF_PTR = ctypes.cast(_WBUF, ctypes.c_void_p)


def _write_raw(handle, address, payload):
    if not handle or len(payload) > _WBUF_SIZE or not _valid_ptr(address):
        return False
    try:
        ctypes.memmove(_WBUF, payload, len(payload))
        return bool(_WPM(handle, ctypes.c_void_p(address), _WBUF_PTR,
                         len(payload), ctypes.byref(_WPM_DONE)))
    except Exception:
        return False


def _desired_map(r, g, b, rel):
    """Желаемое состояние свечения как {относительный оффсет: байты}.

    Набор полей свечения словарём: по нему горячий путь сравнивает
    прочитанный блок с желаемым и пишет только разошедшееся."""
    want = {}
    for name, raw in (
        ("m_iGlowType", struct.pack("<i", GLOW_TYPE)),
        ("m_iGlowTeam", struct.pack("<i", 0)),
        ("m_glowColorOverride", struct.pack("<I", _rgba_u32(r, g, b))),
        ("m_fGlowColor", struct.pack("<fff", float(r), float(g), float(b))),
        ("m_bGlowing", b"\x01"),
    ):
        off = rel.get(name, -1)
        if off is not None and off >= 0:
            want[int(off)] = raw
    return want


def _merge_ranges(patch):
    """[(оффсет, байты)] -> соседние диапазоны склеены (меньше вызовов WPM)."""
    out = []
    for off, payload in sorted(patch, key=lambda kv: kv[0]):
        if out and off == out[-1][0] + len(out[-1][1]):
            out[-1][1] += payload
        else:
            out.append([off, payload])
    return [(off, payload) for off, payload in out]


def _put(process, handle, address, payload):
    """Один вызов записи: сырой WPM, иначе путь через memfuncs."""
    if handle and _write_raw(handle, address, payload):
        return True
    return _write(process, address, payload)


def _sync_glow(process, handle, base, lo, raw, want, drift=None, anchor=None):
    """Привести прочитанный блок CGlowProperty к желаемому состоянию.

    `raw` - байты блока, начинающегося с `base + lo`; `want` - {оффсет: байты}
    (оффсеты те же, что в `raw`). Пишем ТОЛЬКО разошедшиеся поля: одно поле -
    один вызов, несколько - один блок-вызов на общий диапазон. Отсутствие
    расхождений = ни одной записи (обычный случай: игра наше свечение не гасит).
    Необязательный `drift` (словарь) считает, какие поля и сколько раз пришлось
    чинить - им пользуются пробы; в рабочем цикле он не нужен. Необязательный
    `anchor` - (slot_addr, pawn): список павнов пересобирается раз в
    REPAWN_REFRESH, за это время слот мог освободиться/переиспользоваться, и
    запись ушла бы в чужую память (тот самый вылет 13.10), поэтому ПЕРЕД записью
    перечитываем ячейку списка и пишем только если там всё ещё наш павн. Сверка
    стоит одно чтение указателя и только когда есть что писать. Возвращает число
    сделанных вызовов записи или None, если запись не прошла (павн отвалился)."""
    patch = []
    for off, payload in sorted(want.items()):
        cur = raw[off - lo:off - lo + len(payload)]
        if cur != payload:
            patch.append((off, payload))
            if drift is not None:
                drift[off] = drift.get(off, 0) + 1
    if not patch:
        return 0
    if anchor is not None and _read_ptr(process, anchor[0]) != anchor[1]:
        return None
    if len(patch) > 1:
        patch = _merge_ranges(patch)
    if len(patch) == 1:
        off, payload = patch[0]
        return 1 if _put(process, handle, base + off, payload) else None
    first = patch[0][0]
    last = patch[-1][0] + len(patch[-1][1])
    buf = bytearray(raw[first - lo:last - lo])
    for off, payload in patch:
        pos = off - first
        buf[pos:pos + len(payload)] = payload
    return 1 if _put(process, handle, base + first, bytes(buf)) else None


def _color_hex_to_rgbf(hexstr):
    try:
        h = str(hexstr).lstrip("#")
        if len(h) == 3:
            h = h[0] * 2 + h[1] * 2 + h[2] * 2
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return r, g, b
    except Exception:
        return 1.0, 0.0, 0.0


def _health_color(hp):
    try:
        hp = max(0, min(100, int(hp)))
    except Exception:
        hp = 100
    if hp > 50:
        r = (100 - hp) / 50.0
        g = 1.0
        b = 0.0
    else:
        r = 1.0
        g = hp / 50.0
        b = 0.0
    return r, g, b


def _glow_color(mode, hp, team, is_enemy, c_enemy, c_ally):
    """Цвет для режима.

    ВАЖНО про режим Team: цвет выбирается ЖЁСТКО по номеру команды
    (Т=2 -> оранжевый, КТ=3 -> синий), а НЕ по «враг/союзник». Прошлая версия
    брала оранжевый для врага и синий для союзника, поэтому у играющего за Т
    цвета менялись местами: свои (Т) светились синим, враги (КТ) - оранжевым.
    """
    if mode == "Health":
        return _health_color(hp)
    if mode == "Custom":
        return _color_hex_to_rgbf(c_enemy if is_enemy else c_ally)
    if team == TEAM_CT:
        return _color_hex_to_rgbf(CT_COLOR)
    if team == TEAM_T:
        return _color_hex_to_rgbf(T_COLOR)
    # team 0/1 (наблюдатель/не назначен) - старая логика «враг/союзник»
    return _color_hex_to_rgbf(T_COLOR if is_enemy else CT_COLOR)


def _rgba_u32(r, g, b, a=1.0):
    """Source-2 Color: в памяти байты [R, G, B, A], т.е. u32 = A<<24|B<<16|G<<8|R.

    ВАЖНО про байт-порядок: прошлая версия собирала A<<24|R<<16|G<<8|B, т.е.
    в памяти лежало [B, G, R, A] - красный и синий менялись местами."""
    try:
        r = max(0, min(255, int(round(float(r) * 255))))
        g = max(0, min(255, int(round(float(g) * 255))))
        b = max(0, min(255, int(round(float(b) * 255))))
        a = max(0, min(255, int(round(float(a) * 255))))
        return (a << 24) | (b << 16) | (g << 8) | r
    except Exception:
        return 0xFF0000FF


def _find_dump_dir():
    """Папка с client_dll.json: как в triggerbot/nosmoke (output -> repo -> ext)."""
    base = os.path.dirname(os.path.abspath(__file__))
    for c in (os.path.join(_REPO, "output"), _REPO, os.path.join(_REPO, "ext"), base):
        if os.path.exists(os.path.join(c, "client_dll.json")):
            return c
    return None


def _load_glow_offsets():
    """(m_Glow, {поле CGlowProperty: относительный оффсет}).

    m_Glow лежит в C_BaseModelEntity (базовый класс павна), сами поля
    свечения — в CGlowProperty. Оба класса есть в любом свежем дампе
    cs2-dumper, так что хардкод не нужен и не может протухнуть."""
    d = _find_dump_dir()
    if not d:
        return 0, {}
    try:
        with open(os.path.join(d, "client_dll.json"), "r", encoding="utf-8") as f:
            jd = json.load(f)
        classes = jd.get("client.dll", {}).get("classes", {})
        m_glow = int(((classes.get("C_BaseModelEntity", {}).get("fields") or {})
                      .get("m_Glow")) or 0)
        props = (classes.get("CGlowProperty", {}).get("fields") or {})
        return m_glow, {str(k): int(v) for k, v in props.items()}
    except Exception:
        return 0, {}


def _iter_pawns(process, entity_list, local_pawn, o_m_glow, o_h_player_pawn,
                o_life=0, o_scene=0, o_health=0):
    """[(pawn, glow_base, slot_addr)] по списку контроллеров - тот же проход,
    что в ESP.

    Павн ВАЛИДИРУЕТСЯ до попадания в список: пишем мы по `pawn + m_Glow`, а
    `m_hPlayerPawn` есть у любой сущности, поэтому сам по себе разбор handle
    гарантией не является. Слот может быть освобождён или переиспользован -
    тогда запись glow-полей уходит в чужую память (порча, вылет CS2; именно
    это случилось на живом тесте 13.10). Фильтр - как в features/esp/core.py
    (проверен на живых картах): жив (life_state == 256), есть модель
    (m_pGameSceneNode != 0), hp > 0.

    `slot_addr` - адрес ячейки списка сущностей, где лежит сам павн. Обход
    дорогой (кэш живёт REPAWN_REFRESH), за это время слот может освободиться/
    переиспользоваться, поэтому ПЕРЕД записью воркер перечитывает этот адрес и
    сверяет с павном (`anchor` у `_sync_glow`/`_clear_glow`), а не пишет вслепую.

    Вынесено на уровень модуля, чтобы проверялось пробой без игры
    (подменой ProcMemHandler на фейковую память)."""
    out = []
    list_entry = _read_ptr(process, entity_list + ENT_IDENTITY)
    if not list_entry:
        return out
    le_cache = {}
    for i in range(1, SCAN_MAX):
        controller = _read_ptr(process, list_entry + ENT_STRIDE * i)
        if not controller:
            continue
        handle = _read_int(process, controller + o_h_player_pawn, 0)
        if handle <= 0 or handle == 0xFFFFFFFF:
            continue
        idx = handle & HANDLE_SER_MASK
        if idx <= 0:
            continue
        bucket = idx >> 9
        le2 = le_cache.get(bucket, 0)
        if not le2:
            le2 = _read_ptr(process, entity_list + ENT_BUCKET_STEP * bucket + ENT_IDENTITY)
            le_cache[bucket] = le2 or 0
        if not le2:
            continue
        slot = le2 + ENT_STRIDE * (idx & HANDLE_IDX_MASK)
        pawn = _read_ptr(process, slot)
        if not pawn or pawn == local_pawn:
            continue
        if o_life and _read_int_stable(process, pawn + o_life, -1) != LIFESTATE_ALIVE:
            continue
        if o_health and _read_int_stable(process, pawn + o_health, 0) <= 0:
            continue
        if o_scene and not _read_ptr(process, pawn + o_scene):
            continue
        # m_Glow - ВСТРОЕННАЯ CGlowProperty (88 байт; в дампе следующее поле
        # C_BaseModelEntity - m_flGlowBackfaceMult = 3560+88). Разыменовывать
        # НЕЛЬЗЯ: раньше тут читался указатель из первых 8 байт структуры
        # (обычно 0) -> павн молча отбрасывался и обводки не было вообще.
        base = pawn + o_m_glow
        if not _valid_ptr(base):
            continue
        out.append((pawn, base, slot))
    return out


def _clear_glow(process, base, rel, anchor=None):
    """Снять свечение (при выключении фичи и на мёртвых).

    `anchor` - (slot_addr, pawn): та же защита, что в `_sync_glow` (перед
    записью проверяем, что слот всё ещё наш); по устаревшему списку в чужой
    освобождённый объект не пишем. Возвращает False, если проверка не прошла."""
    if anchor is not None and _read_ptr(process, anchor[0]) != anchor[1]:
        return False

    def w(off, raw):
        if off is not None and off >= 0:
            _write(process, base + off, raw)

    w(rel.get("m_bGlowing", -1), b"\x00")
    w(rel.get("m_iGlowType", -1), struct.pack("<i", 0))
    return True


def GlowThreadFunction(Options, Offsets):
    # Раньше здесь поднималась гранулярность системного таймера Windows
    # (timeBeginPeriod(1) + NtSetTimerResolution(0.5 мс)) - под sleep(0.0005) в
    # горячем цикле. С v8.11 сна в цикле нет (турбо безусловно), поэтому блок
    # удалён: он опускал разрешение таймера во всём процессе, а пользы не давал.

    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    off = Offsets.offset

    def _need(n):
        try:
            return int(getattr(off, n, 0) or 0)
        except Exception:
            return 0

    o_entity_list = _need("dwEntityList")
    o_local_pawn = _need("dwLocalPlayerPawn")
    o_team = _need("m_iTeamNum")
    o_health = _need("m_iHealth")
    o_h_player_pawn = _need("m_hPlayerPawn")
    o_life = _need("m_lifeState")
    o_scene = _need("m_pGameSceneNode")

    o_m_glow, props = _load_glow_offsets()
    R_FGC = props.get("m_fGlowColor", -1)
    R_GOV = props.get("m_glowColorOverride", -1)
    R_IGT = props.get("m_iGlowTeam", -1)
    R_IGL = props.get("m_iGlowType", -1)
    R_BGL = props.get("m_bGlowing", -1)

    # Один диапазон CGlowProperty, с которым работает горячий путь: от младшего
    # нашего поля (m_fGlowColor) до КОНЦА старшего (m_bGlowing, 1 байт). Размеры
    # задаём по типам: m_fGlowColor - три float (12 байт), остальное int/byte,
    # иначе граница блока уезжает на 3 байта в соседнее поле CGlowProperty.
    _sizes = {"m_fGlowColor": 12, "m_glowColorOverride": 4, "m_iGlowTeam": 4,
              "m_iGlowType": 4, "m_bGlowing": 1}
    _span = [(props[n], _sizes[n]) for n in _sizes if n in props]
    R_LO = min(o for o, _ in _span) if _span else 0
    R_HI = max(o + s for o, s in _span) if _span else 0
    R_SPAN = R_HI - R_LO

    core_missing = [
        n for n, v in (
            ("dwEntityList", o_entity_list),
            ("dwLocalPlayerPawn", o_local_pawn),
            ("m_iTeamNum", o_team),
            ("m_iHealth", o_health),
            ("m_hPlayerPawn", o_h_player_pawn),
            ("m_lifeState", o_life),
            ("m_pGameSceneNode", o_scene),
            ("m_Glow (C_BaseModelEntity)", o_m_glow),
        ) if not v
    ]
    if R_IGL < 0 or R_BGL < 0:
        core_missing.append("CGlowProperty (m_iGlowType/m_bGlowing)")
    if R_SPAN <= 0 or R_SPAN > _WBUF_SIZE:
        core_missing.append("CGlowProperty (диапазон полей)")
    if core_missing:
        msg = ("[glow] OFF - нет оффсетов: " + ", ".join(core_missing) +
               ". Запусти CS2, потом 'cs2-dumper -f json' в папке чита, "
               "перезапусти чит.")
        print(msg)
        logutil.debug(msg)
        while True:
            time.sleep(5)

    opt_enabled = False
    opt_mode = "Team"
    opt_show_en = True
    opt_show_al = True
    opt_c_enemy = "#FF5555"
    opt_c_ally = "#55AAFF"
    opts_ts = 0.0

    was_enabled = False
    want_cache = {}            # упакованный цвет -> готовый {оффсет: байты}
    pawn_info = {}             # pawn -> [ts, hp, team, life, shown]
    pawns = []                 # кэш [(pawn, glow_base, slot_addr)]: обход дорогой
    pawns_ts = 0.0
    local_team = 0
    while True:
        try:
            now = time.time()
            if now - opts_ts >= OPTS_REFRESH:
                try:
                    opt_enabled = bool(Options.get("EnableGlow", False))
                    opt_mode = str(Options.get("GlowMode", "Team") or "Team")
                    opt_show_en = bool(Options.get("GlowShowEnemies", True))
                    opt_show_al = bool(Options.get("GlowShowAllies", True))
                    opt_c_enemy = Options.get("GlowEnemyColor", "#FF5555") or "#FF5555"
                    opt_c_ally = Options.get("GlowAllyColor", "#55AAFF") or "#55AAFF"
                except Exception:
                    pass
                opts_ts = now

            process = connector.ensure_process()
            client = connector.ensure_module("client.dll")
            if not process or not client:
                time.sleep(0.5)
                continue

            # Выключено и чистить нечего - не читаем память зря.
            if not opt_enabled and not was_enabled:
                time.sleep(0.1)
                continue

            local_pawn = _read_ptr(process, client + o_local_pawn)
            entity_list = _read_ptr(process, client + o_entity_list)
            if not local_pawn or not entity_list:
                was_enabled = opt_enabled
                time.sleep(0.05)
                continue

            if not opt_enabled:
                # Разово снимаем свечение после выключения фичи.
                if not pawns:
                    pawns = _iter_pawns(process, entity_list, local_pawn,
                                        o_m_glow, o_h_player_pawn,
                                        o_life, o_scene, o_health)
                for _pawn, base, _slot in pawns:
                    _clear_glow(process, base, props, (_slot, _pawn))
                pawn_info.clear()
                pawns = []
                pawns_ts = 0.0
                was_enabled = False
                time.sleep(0.05)
                continue

            was_enabled = True

            # Список павнов пересобираем/перевалидируем раз в REPAWN_REFRESH:
            # обход ~150 чтений (доли миллисекунды), а он ещё и отсеивает
            # мёртвые и переиспользованные слоты - писать в них нельзя.
            if not pawns or (now - pawns_ts) >= REPAWN_REFRESH:
                pawns = _iter_pawns(process, entity_list, local_pawn,
                                    o_m_glow, o_h_player_pawn,
                                    o_life, o_scene, o_health)
                pawns_ts = now
                # team=0 приходит и при сбое чтения (memfuncs отдаёт нули), а
                # это трактуется как «все союзники» -> при выключенных союзниках
                # обводка гасла бы у ВСЕХ сразу. Ноль не принимаем: оставляем
                # прежнюю команду и пробуем снова на следующей пересборке.
                _t = _read_int(process, local_pawn + o_team, 0)
                if _t:
                    local_team = _t
                if not pawns:
                    time.sleep(0.05)
                    continue

            handle = getattr(process, "process_handle", None)

            bad = []
            for pawn, base, slot_addr in pawns:
                info = pawn_info.get(pawn)
                if info is None:
                    info = [0.0, 0, 0, LIFESTATE_ALIVE, False]
                    pawn_info[pawn] = info
                if (now - info[0]) > HP_REFRESH:
                    # Валидация перед записью - тот же фильтр, что в ESP:
                    # живой павн (life_state), hp в норме. Запись в слот,
                    # который игра уже освободила/переиспользовала, уходит в
                    # чужую память - это порча и вылет CS2 (живой тест 13.10).
                    # Перечитка «нулей» (_read_int_stable): memfuncs при сбое
                    # чтения отдаёт нули, поэтому один сбой выглядел бы как
                    # смерть павна - обводка гасла бы на каждый транзиентный сбой.
                    info[0] = now
                    info[1] = _read_int_stable(process, pawn + o_health, 0, suspect=(0,))
                    info[2] = _read_int_stable(process, pawn + o_team, 0, suspect=(0,))
                    info[3] = _read_int_stable(process, pawn + o_life, LIFESTATE_ALIVE, suspect=(0, -1))
                hp, team, life, shown = info[1], info[2], info[3], info[4]

                if hp <= 0 or life != LIFESTATE_ALIVE:
                    # Мёртвый/невалидный: разово снять свечение и убрать из
                    # списка (пересбор вернёт его, если слот оживёт). Снятие -
                    # с проверкой якоря: кэш павнов может уже указывать на
                    # освобождённый/переиспользованный слот.
                    if shown:
                        _clear_glow(process, base, props, (slot_addr, pawn))
                        info[4] = False
                    bad.append(pawn)
                    continue

                is_enemy = (team != 0 and local_team != 0 and team != local_team)
                if not (opt_show_en if is_enemy else opt_show_al):
                    # Группа отключена: снять обводку, если уже ставили.
                    if shown:
                        _clear_glow(process, base, props, (slot_addr, pawn))
                        info[4] = False
                    continue

                r, g, b = _glow_color(opt_mode, hp, team, is_enemy,
                                      opt_c_enemy, opt_c_ally)
                sig = _rgba_u32(r, g, b)
                want = want_cache.get(sig)
                if want is None:
                    if len(want_cache) > 512:
                        want_cache.clear()
                    want = _desired_map(r, g, b, props)
                    want_cache[sig] = want

                # ГОРЯЧИЙ ПУТЬ: одно чтение блока CGlowProperty и запись только
                # тех полей, которые игра погасила (обычно - ни одной записи).
                raw = _read_bytes(process, base + R_LO, R_SPAN)
                if len(raw) != R_SPAN:
                    info[4] = False
                    bad.append(pawn)
                    continue
                if _sync_glow(process, handle, base, R_LO, raw, want,
                              anchor=(slot_addr, pawn)) is None:
                    info[4] = False
                    bad.append(pawn)
                    continue
                info[4] = True

            if bad:
                # Отвалившиеся павны (смерть/выход игрока/свободный слот)
                # выкидываем: игра переиспользует эти адреса.
                _dead = set(bad)
                pawns = [(p, b, s) for p, b, s in pawns if p not in _dead]
                for _p in _dead:
                    pawn_info.pop(_p, None)

            # Сна нет сознательно (гонка с игрой): чем чаще перезапись, тем
            # выше шанс попасть в окно «игра погасила -> отрисовала». Цена -
            # загрузка одного ядра (см. комментарий у констант выше).
            time.sleep(0)

        except Exception as exc:
            now = time.time()
            try:
                if now - last_exc_ts >= 1.0:
                    try:
                        logutil.debug(f"[glow] loop exception: {exc}")
                    except Exception:
                        pass
                    try:
                        connector.invalidate()
                    except Exception:
                        pass
                    last_exc_ts = now
            except Exception:
                last_exc_ts = now
            time.sleep(0.3)

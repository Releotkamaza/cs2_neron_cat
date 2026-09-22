from functions import memfuncs
from functions import logutil
from functions.process_watcher import ProcessConnector
import json
import os
import time

# ==================== Игровые константы (не оффсеты) ====================
FALLBACK_BOMB_TIME = 40.0   # стандартный таймер C4; реальное значение читаем из m_flTimerLength
KIT_DEFUSE_MAX = 7.0        # дефьюз <= 7с считаем "с китом" (5с), дольше - "без кита" (10с)
DEFUSE_EPS = 0.05           # допуск в сравнении "дефьюз дольше бомбы"
SCAN_INTERVAL = 0.05        # период воркера

# ==================== Структурные константы ====================
# CGlobalVarsBase::curtime - не schema-класс, в дампы cs2-dumper не попадает.
# Смещение калибруется перебором известных кандидатов; 0x30 подтверждён
# на актуальном билде (curtime=347.55, blow=387.55, left=40.00), остальные -
# страховка на будущие обновления. Найденный кандидат фиксируется до конца
# процесса (см. curtime_off в BombTimerThread).
CURTIME_CANDIDATES = (0x30, 0x2C, 0x10, 0x14)

# Границы санити-гейтов (игровые величины, не оффсеты)
BLOW_IS_ABSOLUTE_MIN = 50.0   # m_flC4Blow больше этого -> абсолютное время, иначе остаток
LEFT_MAX = 50.0               # максимум правдоподобного остатка бомбы
TIMER_LEN_RANGE = (10.0, 120.0)
DEFUSE_LEN_RANGE = (1.0, 30.0)

# ==================== Оффсеты из дампа (хардкода нет) ====================
# dwGlobalVars / dwPlantedC4 - из output/offsets.json
# Поля C_PlantedC4 - из output/client_dll.json
#
# ПРИМЕЧАНИЕ ПО КОНВЕНЦИИ (зеркально nosmoke): _field над плоским
# _SCHEMA - "первое вхождение". Это легально: поля C_PlantedC4 читаются
# от entity НАПРЯМУЮ, композиций нет, имена в дампе уникальны. Полей
# C_PlantedC4 в dataclass ext/offsets.py нет - дамп здесь единственный
# источник, это соответствует канону "оффсеты - из output/*.json".
# Если какое-то имя когда-нибудь станет неуникальным - перевести на
# pinned-классы по образцу noscopedot._get_schema().

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

_OFFSETS = {}
try:
    _OFFSETS = _dump_json("offsets.json").get("client.dll", {}) or {}
except Exception:
    _OFFSETS = {}


def _field(*names):
    """Первое существующее поле из списка кандидатов; 0 если ничего нет."""
    for n in names:
        v = _SCHEMA.get(n, 0)
        if v:
            return v
    return 0


def _reset_state(s):
    s.bombPlanted = False
    s.bombTimeLeft = -1
    s.bombTimeTotal = FALLBACK_BOMB_TIME
    s.bombBeingDefused = False
    s.bombDefuseLeft = None
    s.bombDefuseTotal = None
    s.bombDefuseImpossible = False


def BombTimerThread(SharedBombState, SharedOffsets):
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    off = SharedOffsets.offset

    # --- Разрешение оффсетов из дампа ---
    o_c4_blow = _field("m_flC4Blow")
    o_timer_len = _field("m_flTimerLength")
    o_being_defused = _field("m_bBeingDefused")
    o_defuse_len = _field("m_flDefuseLength")
    o_defuse_cd = _field("m_flDefuseCountDown")
    o_gv = int(_OFFSETS.get("dwGlobalVars", 0) or 0)
    o_c4 = int(_OFFSETS.get("dwPlantedC4", 0) or 0)

    real_ok = bool(o_gv and o_c4 and o_c4_blow)
    defuse_ok = real_ok and bool(o_being_defused and o_defuse_cd and o_defuse_len)
    # Единственный легальный консольный вывод - деградация (не штатный режим).
    if not real_ok:
        print("[bombtimer] нет dwGlobalVars/dwPlantedC4/m_flC4Blow в дампе - "
              "запасной счётчик по секундам, дефьюз скрыт. Обнови output/", flush=True)
    elif not defuse_ok:
        print("[bombtimer] поля дефюза отсутствуют в дампе - таймер бомбы точный, "
              "дефьюз скрыт. Обнови output/", flush=True)

    # Состояние семантики/калибровки (живёт между раундами)
    curtime_off = 0            # найденное смещение curtime; 0 = не найдено / не нужно
    blow_is_absolute = None    # None = неизвестно, True = абсолютное время, False = остаток

    while True:
        try:
            proc = connector.ensure_process()
            client = connector.ensure_module("client.dll")

            game_rule = memfuncs.ProcMemHandler.ReadPointer(proc, client + off.dwGameRules)
            planted = bool(game_rule) and bool(
                memfuncs.ProcMemHandler.ReadBool(proc, game_rule + off.m_bBombPlanted))
            if not planted:
                _reset_state(SharedBombState)
                time.sleep(0.1)
                continue

            # Бомба заложена - сообщаем об этом НЕМЕДЛЕННО. Точное время
            # доедет следующими тактами, карточка покажет "Syncing timer..."
            SharedBombState.bombPlanted = True

            if not real_ok:
                # Запасной путь: прежний счётчик по секундам
                SharedBombState.bombTimeTotal = FALLBACK_BOMB_TIME
                for elapsed in range(int(FALLBACK_BOMB_TIME)):
                    try:
                        gr = memfuncs.ProcMemHandler.ReadPointer(proc, client + off.dwGameRules)
                        if not gr or not memfuncs.ProcMemHandler.ReadBool(proc, gr + off.m_bBombPlanted):
                            break
                    except Exception:
                        break
                    SharedBombState.bombTimeLeft = FALLBACK_BOMB_TIME - elapsed
                    time.sleep(1)
                _reset_state(SharedBombState)
                continue

            c4 = memfuncs.ProcMemHandler.ReadPointer(proc, client + o_c4) if o_c4 else 0
            if not c4:
                time.sleep(SCAN_INTERVAL)
                continue

            # --- Время взрыва ---
            try:
                blow = float(memfuncs.ProcMemHandler.ReadFloat(proc, c4 + o_c4_blow))
            except Exception:
                blow = 0.0
            if blow <= 0.0:
                time.sleep(SCAN_INTERVAL)
                continue

            # --- Семантика m_flC4Blow и калибровка curtime ---
            left = -1.0
            curtime = 0.0

            if blow_is_absolute is None:
                # Первая встреча с заложенной бомбой: определяем семантику поля
                blow_is_absolute = blow > BLOW_IS_ABSOLUTE_MIN

            if not blow_is_absolute:
                # Поле хранит остаток напрямую
                left = blow if blow <= LEFT_MAX else -1.0
            else:
                # Абсолютное время: нужен curtime
                if curtime_off:
                    try:
                        gv = memfuncs.ProcMemHandler.ReadPointer(proc, client + o_gv)
                        if gv:
                            curtime = float(memfuncs.ProcMemHandler.ReadFloat(proc, gv + curtime_off))
                    except Exception:
                        curtime = 0.0
                else:
                    # Калибровка: первое смещение, при котором blow - t даёт
                    # правдоподобный остаток. Неудача - только в debug-лог.
                    gv = 0
                    try:
                        gv = memfuncs.ProcMemHandler.ReadPointer(proc, client + o_gv)
                    except Exception:
                        gv = 0
                    if gv:
                        for cand in CURTIME_CANDIDATES:
                            try:
                                t = float(memfuncs.ProcMemHandler.ReadFloat(proc, gv + cand))
                            except Exception:
                                t = 0.0
                            rem = blow - t
                            if 0.0 <= rem <= LEFT_MAX:
                                curtime_off = cand
                                curtime = t
                                logutil.debug(f"[bombtimer] curtime calibrated: "
                                              f"offset=0x{cand:X} left={rem:.2f}")
                                break
                    if not curtime_off:
                        logutil.debug(f"[bombtimer] curtime calibration failed, blow={blow:.2f}")

                if curtime > 0.0:
                    rem = blow - curtime
                    if 0.0 <= rem <= LEFT_MAX:
                        left = rem
                    elif -1.0 <= rem < 0.0:
                        # чуть за гранью - бомба уже взорвалась/уходит
                        left = 0.0

            total = FALLBACK_BOMB_TIME
            if o_timer_len:
                try:
                    t = float(memfuncs.ProcMemHandler.ReadFloat(proc, c4 + o_timer_len))
                    if TIMER_LEN_RANGE[0] <= t <= TIMER_LEN_RANGE[1]:
                        total = t
                except Exception:
                    pass

            if left < 0.0:
                # Точное время пока не считается - карточка покажет
                # PLANTED + "Syncing timer...", НЕ SAFE
                time.sleep(SCAN_INTERVAL)
                continue
            if left > total + 1.0:
                left = total
            left = max(0.0, left)

            SharedBombState.bombTimeTotal = total
            SharedBombState.bombTimeLeft = left

            # --- Дефьюз: m_flDefuseCountDown - та же семантика, что и blow;
            # m_flDefuseLength уже учитывает наличие кита у дефьюзера ---
            defusing = False
            defuse_left = None
            defuse_total = None
            impossible = False
            if defuse_ok:
                try:
                    if memfuncs.ProcMemHandler.ReadBool(proc, c4 + o_being_defused):
                        d_total = float(memfuncs.ProcMemHandler.ReadFloat(proc, c4 + o_defuse_len))
                        if DEFUSE_LEN_RANGE[0] <= d_total <= DEFUSE_LEN_RANGE[1]:
                            cd = float(memfuncs.ProcMemHandler.ReadFloat(proc, c4 + o_defuse_cd))
                            dl = None
                            if blow_is_absolute and curtime > 0.0:
                                cand = cd - curtime
                                if 0.0 <= cand <= d_total + 1.0:
                                    dl = cand
                            elif cd <= d_total + 1.0:
                                # поле хранит остаток
                                dl = cd
                            if dl is not None:
                                defusing = True
                                defuse_left = max(0.0, dl)
                                defuse_total = d_total
                                impossible = defuse_left > (left + DEFUSE_EPS)
                except Exception:
                    pass

            SharedBombState.bombBeingDefused = defusing
            SharedBombState.bombDefuseLeft = defuse_left
            SharedBombState.bombDefuseTotal = defuse_total
            SharedBombState.bombDefuseImpossible = impossible

            time.sleep(SCAN_INTERVAL)

        except Exception as exc:
            logutil.debug(f"[bombtimer] loop exception: {exc}")
            _reset_state(SharedBombState)
            connector.invalidate()
            time.sleep(1)
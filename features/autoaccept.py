# markers: START functions/autoaccept.py v2.4
import time
import json
import os
import ctypes

import win32gui
import win32api
import win32con

from functions import memfuncs
from functions import logutil
from functions.process_watcher import ProcessConnector

# --- зоны поиска (доли ширины/высоты окна) ---
SEARCH_X0, SEARCH_X1 = 0.36, 0.64
SEARCH_Y0, SEARCH_Y1 = 0.30, 0.52

MIN_RUN_W, MAX_RUN_W = 0.07, 0.16   # ширина прогонов кнопки
RUN_CENTER_X0, RUN_CENTER_X1 = 0.42, 0.58
MIN_BTN_HEIGHT = 0.045              # верт. покрытие хитов

# кубики принятых игроков
SLOT_RUN_MIN, SLOT_RUN_MAX = 0.012, 0.045
SLOT_MIN_COUNT = 4
SLOT_ROWS_FY = (0.375, 0.395, 0.415, 0.435)
SLOT_MIN_ROWS = 2

# --- относительные пороги зелени ---
GREEN_MIN_G = 30
GREEN_ADV_MIN = 22
GREEN_RATIO_R = 1.35
GREEN_RATIO_B = 1.15

_SCAN_SLEEP = 0.4
_IDLE_SLEEP = 0.5
_IN_MATCH_SLEEP = 1.0
_COOLDOWN_ACCEPTED = 15.0
_COOLDOWN_FAIL = 3.0
_VERIFY_DELAY = 1.0
_WARN_STREAK = 20

# структурные константы Win32 (не оффсеты)
BI_RGB = 0
DIB_RGB_COLORS = 0
SRCCOPY = 0x00CC0020
PW_RENDERFULLCONTENT = 0x00000002
ERROR_ALREADY_EXISTS = 183


class _BMIH(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_int32),
        ("biClrImportant", ctypes.c_int32),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

_kernel32.CreateMutexW.restype = ctypes.c_void_p
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
_user32.PrintWindow.restype = ctypes.c_int
_user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
_gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
_gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
_gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_gdi32.SelectObject.restype = ctypes.c_void_p
_gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_gdi32.DeleteObject.restype = ctypes.c_int
_gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
_gdi32.DeleteDC.restype = ctypes.c_int
_gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
_gdi32.BitBlt.restype = ctypes.c_int
_gdi32.BitBlt.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint32,
]
_gdi32.GetDIBits.restype = ctypes.c_int
_gdi32.GetDIBits.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
    ctypes.c_void_p, ctypes.POINTER(_BMIH), ctypes.c_uint,
]
_gdi32.GetBitmapBits.restype = ctypes.c_long
_gdi32.GetBitmapBits.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p]

_SINGLE_MUTEX = None


def _dbg(msg):
    logutil.debug(f"[autoaccept] {msg}")


# ==================== гейт "в матче" (C_CSGameRules) ====================
# Павн-гейт (dwLocalPlayerPawn + hp) сломан по построению: после выхода из
# матча клиент держит "тёплую" сессию, павн читается живым -> гейт держал
# скан в меню и матч игнорился. GameRules привязан к ЗАГРУЖЕННОЙ карте:
# в меню/лобби/поиске карты нет -> dwGameRules = 0 или чтение по
# выгруженному адресу даёт нули (memfuncs v2.1) -> скан жив. GameRules
# "тёплым" не бывает по построению. Консольного вывода нет: деградация
# (нет поля в дампе) - только debug-лог, скан ведёт себя как без гейта.

def _resolve_has_match_started():
    """C_CSGameRules::m_bHasMatchStarted из output/client_dll.json.
    0 = поля нет (гейт off, тихо)."""
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        repo = os.path.abspath(os.path.join(base, ".."))
        for c in (os.path.join(repo, "output"), repo, os.path.join(repo, "ext"), base):
            p = os.path.join(c, "client_dll.json")
            if not os.path.exists(p):
                continue
            with open(p, "r", encoding="utf-8") as f:
                jd = json.load(f)
            fields = (jd.get("client.dll", {}).get("classes", {})
                        .get("C_CSGameRules", {}).get("fields") or {})
            v = fields.get("m_bHasMatchStarted")
            return int(v) if v else 0
    except Exception:
        pass
    return 0


def _in_live_match(process, client, off, o_has_started):
    """True = активный матч (скан глушится). False = меню/поиск/лобби."""
    try:
        gr = memfuncs.ProcMemHandler.ReadPointer(process, client + off.dwGameRules)
        if not gr:
            return False
        return bool(memfuncs.ProcMemHandler.ReadBool(process, gr + o_has_started))
    except Exception:
        return False


# ==================== цвет / геометрия ====================

def _is_green(px):
    r = px & 0xFF
    g = (px >> 8) & 0xFF
    b = (px >> 16) & 0xFF
    if g < GREEN_MIN_G:
        return False
    if g - (r if r > b else b) < GREEN_ADV_MIN:
        return False
    if g < r * GREEN_RATIO_R:
        return False
    if g < b * GREEN_RATIO_B:
        return False
    return True


def _green_runs(gp, y, x0, x1, step):
    runs = []
    s = None
    x = x0
    while x <= x1:
        if _is_green(gp(x, y)):
            if s is None:
                s = x
            e_last = x
        else:
            if s is not None:
                runs.append((s, e_last))
                s = None
        x += step
    if s is not None:
        runs.append((s, e_last))
    return runs


def _find_button(gp, w, h):
    x0, x1 = int(w * SEARCH_X0), int(w * SEARCH_X1)
    y0, y1 = int(h * SEARCH_Y0), int(h * SEARCH_Y1)
    step_x = max(1, w // 480)
    step_y = max(1, h // 360)
    min_r = w * MIN_RUN_W
    max_r = w * MAX_RUN_W

    hit_rows = 0
    cx_sum = 0.0
    y = y0
    while y <= y1:
        for s, e in _green_runs(gp, y, x0, x1, step_x):
            run_w = (e - s) + step_x
            if not (min_r <= run_w <= max_r):
                continue
            c = (s + e) / 2.0
            if RUN_CENTER_X0 * w <= c <= RUN_CENTER_X1 * w:
                hit_rows += 1
                cx_sum += c
                break
        y += step_y

    if hit_rows == 0 or hit_rows * step_y < h * MIN_BTN_HEIGHT:
        return None
    return int(cx_sum / hit_rows), int((y0 + y1) / 2 + h * 0.0)


def _accepted_rows(gp, w, h):
    """Число валидных рядов кубиков (>= SLOT_MIN_ROWS = принято).
    ВНИМАНИЕ (диагноз 'игнорит матч'): зелёный ФОН за попапом (мох,
    трава) проходит _is_green и может давать ложные 'кубы' - ряды.
    Поэтому эта проверка ВЫЗЫВАЕТСЯ только когда кнопки на экране НЕТ
    (см. главный цикл): кнопка присутствует на попапе всегда, её
    детект - истина в последней инстанции."""
    x0, x1 = int(w * 0.30), int(w * 0.70)
    step_x = max(1, w // 480)
    btn_min = w * MIN_RUN_W
    rows_ok = 0
    row_detail = []
    for fy in SLOT_ROWS_FY:
        y = int(h * fy)
        runs = _green_runs(gp, y, x0, x1, step_x)
        # строка с кнопочным прогоном - это кнопка, не кубики
        if any((e - s) + step_x >= btn_min for s, e in runs):
            row_detail.append("btn")
            continue
        slots = [r for r in runs
                 if w * SLOT_RUN_MIN <= (r[1] - r[0]) + step_x <= w * SLOT_RUN_MAX]
        row_detail.append(len(slots))
        if len(slots) >= SLOT_MIN_COUNT:
            rows_ok += 1
    return rows_ok, row_detail


def _capture_valid(gp, w, h):
    non_black = 0
    for fy in (0.2, 0.35, 0.5, 0.65, 0.8):
        for fx in (0.2, 0.35, 0.5, 0.65, 0.8):
            px = gp(int(w * fx), int(h * fy))
            if (px & 0xFF) + ((px >> 8) & 0xFF) + ((px >> 16) & 0xFF) > 36:
                non_black += 1
    return non_black >= 5


# ==================== захват (конвейер v5, reader починен) ====================

def _make_reader(raw, w, h, top_down):
    # raw - bytes: индексация дает int. create_string_buffer давал бы
    # однобайтовые bytes - источник TypeError v5.
    if top_down:
        def gp(x, y):
            i = (y * w + x) * 4
            return raw[i + 2] | (raw[i + 1] << 8) | (raw[i] << 16)
    else:
        def gp(x, y):
            i = ((h - 1 - y) * w + x) * 4
            return raw[i + 2] | (raw[i + 1] << 8) | (raw[i] << 16)
    return gp


def _extract_bits(mem_dc, bmp, w, h, label):
    """Требование MSDN: битмап НЕ выбран в DC (вызывающий код снял SelectObject)."""
    bmi = _BMIH()
    bmi.biSize = ctypes.sizeof(_BMIH)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = BI_RGB
    buf = ctypes.create_string_buffer(w * h * 4)
    if _gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS):
        return bytes(buf), True
    _dbg(f"{label}: GetDIBits=0 err={ctypes.get_last_error()}, фоллбек GetBitmapBits")

    size = _gdi32.GetBitmapBits(bmp, 0, None)
    if size == w * h * 4:
        buf2 = ctypes.create_string_buffer(size)
        if _gdi32.GetBitmapBits(bmp, size, buf2) == size:
            return bytes(buf2), False
        _dbg(f"{label}: GetBitmapBits недочитал, err={ctypes.get_last_error()}")
        return None, None
    _dbg(f"{label}: GetBitmapBits размер {size}, ожидалось {w * h * 4}")
    return None, None


def _capture_gdi(hwnd, mode):
    label = mode
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = right - left, bottom - top
        if w <= 0 or h <= 0:
            _dbg(f"{label}: пустой размер окна {w}x{h}")
            return None
        src_dc = win32gui.GetWindowDC(hwnd) if mode == "window" else win32gui.GetDC(0)
        if not src_dc:
            _dbg(f"{label}: GetDC=0 err={ctypes.get_last_error()}")
            return None
        mem_dc = bmp = None
        try:
            mem_dc = _gdi32.CreateCompatibleDC(src_dc)
            if not mem_dc:
                _dbg(f"{label}: CreateCompatibleDC=0")
                return None
            bmp = _gdi32.CreateCompatibleBitmap(src_dc, w, h)
            if not bmp:
                _dbg(f"{label}: CreateCompatibleBitmap=0")
                return None
            old = _gdi32.SelectObject(mem_dc, bmp)

            drew = False
            if mode == "window":
                for flag in (PW_RENDERFULLCONTENT, 0):
                    if _user32.PrintWindow(hwnd, mem_dc, flag):
                        drew = True
                        break
                if not drew:
                    _dbg(f"{label}: PrintWindow=0")
            else:
                drew = bool(_gdi32.BitBlt(mem_dc, 0, 0, w, h, src_dc,
                                          left, top, SRCCOPY))
                if not drew:
                    _dbg(f"{label}: BitBlt=0")

            # критично: снять выбор битмапа ДО чтения бит
            if old:
                _gdi32.SelectObject(mem_dc, old)
            if not drew:
                return None

            raw, top_down = _extract_bits(mem_dc, bmp, w, h, label)
            if raw is None:
                return None
            return _make_reader(raw, w, h, top_down), w, h
        finally:
            if bmp:
                _gdi32.DeleteObject(bmp)
            if mem_dc:
                _gdi32.DeleteDC(mem_dc)
            if mode == "window":
                win32gui.ReleaseDC(hwnd, src_dc)
            else:
                win32gui.ReleaseDC(0, src_dc)
    except Exception as e:
        _dbg(f"{label}: исключение {e!r}")
        return None


def _grab(hwnd):
    # активное окно -> экран (BitBlt) с фоллбеком на PrintWindow;
    # фоновое -> ТОЛЬКО PrintWindow. Фоллбек "screen" в фоне убран: BitBlt
    # экранного DC захватывает ЧУЖОЕ окно поверх игры (анализ и клик по
    # чужим пикселям). PrintWindow дал чёрный/невалидный кадр в фоне -
    # честный отказ, ретрай следующим циклом (_SCAN_SLEEP).
    fg = win32gui.GetForegroundWindow() == hwnd
    if fg:
        order = ("screen", "window")
    else:
        order = ("window",)
    for mode in order:
        cap = _capture_gdi(hwnd, mode)
        if cap and _capture_valid(cap[0], cap[1], cap[2]):
            return cap
        if cap:
            _dbg(f"{mode}: снимок получен, но выглядит черным - отброшен")
    return None


# ==================== служебное ====================

def _force_foreground(hwnd):
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32api.keybd_event(0x12, 0, 0, 0)
        win32api.keybd_event(0x12, 0, 2, 0)
        win32gui.SetForegroundWindow(hwnd)
        for _ in range(20):
            if win32gui.GetForegroundWindow() == hwnd:
                return True
            time.sleep(0.05)
    except Exception:
        pass
    return win32gui.GetForegroundWindow() == hwnd


def _real_click(x, y):
    win32api.SetCursorPos((int(x), int(y)))
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.03)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def _is_in_match(process, client, off):
    """Пост-клик верификация (НЕ гейт скана): после клика по accept
    матч грузится, павн оживает. Здесь "тёплый павн" безвреден."""
    try:
        lp = memfuncs.ProcMemHandler.ReadPointer(process, client + off.dwLocalPlayerPawn)
        if not lp:
            return False
        # memfuncs v2.1: сбой RPM -> 0 без исключения. Здоровье должно быть
        # > 0: переходное состояние (павн жив, страница не читается) раньше
        # классифицировалось как "в матче" и пропускло скан.
        hp = memfuncs.ProcMemHandler.ReadInt(process, lp + off.m_iHealth)
        return hp > 0
    except Exception:
        return False


def AutoAcceptThreadFunction(Options, Offsets):
    global _SINGLE_MUTEX

    handle = _kernel32.CreateMutexW(None, False, "NERON_AUTOACCEPT_SINGLE")
    if not handle or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        print("[autoaccept] второй экземпляр воркера - модуль отключён")
        return
    _SINGLE_MUTEX = handle

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

    # --- Резолв гейта: dataclass dwGameRules + дамп C_CSGameRules ---
    o_gamerules = 0
    try:
        o_gamerules = int(getattr(Offsets.offset, "dwGameRules", 0) or 0)
    except Exception:
        o_gamerules = 0
    o_has_started = _resolve_has_match_started()
    gate_on = bool(o_gamerules and o_has_started)
    if not gate_on:
        # Без консольного вывода: деградация видна только в debug-логе.
        _dbg("гейт матча off: нет dwGameRules/m_bHasMatchStarted - скан всегда активен")

    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    last_state = None
    cooldown_until = 0.0
    fail_streak = 0
    iconic_misses = 0
    diag_cycle = 0

    while True:
        try:
            enabled = bool(Options.get("EnableAutoAccept", False))
            if not enabled:
                last_state = None
                time.sleep(_IDLE_SLEEP)
                continue

            hwnd = win32gui.FindWindow(None, "Counter-Strike 2") or \
                   win32gui.FindWindow("SDL_app", None)
            if not hwnd:
                last_state = None
                time.sleep(_IDLE_SLEEP)
                continue

            # Гейт матча: активный матч (карта загружена) -> скан спит.
            # В меню/поиске/лобби карты нет -> скан жив (ре-кью работает).
            if gate_on:
                try:
                    process = connector.ensure_process()
                    client = connector.ensure_module("client.dll")
                    if _in_live_match(process, client, Offsets.offset, o_has_started):
                        time.sleep(_IN_MATCH_SLEEP)
                        continue
                except Exception:
                    pass

            if time.time() < cooldown_until:
                time.sleep(0.2)
                continue

            iconic = False
            try:
                iconic = bool(win32gui.IsIconic(hwnd))
            except Exception:
                pass
            if iconic:
                # свернутое окно не рендерится
                iconic_misses += 1
                if iconic_misses >= 2:
                    iconic_misses = 0
                    try:
                        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
                        _dbg("окно свернуто - развернуто без фокуса")
                    except Exception:
                        pass
                time.sleep(_SCAN_SLEEP)
                continue
            iconic_misses = 0

            cap = _grab(hwnd)
            if not cap:
                fail_streak += 1
                if fail_streak == _WARN_STREAK:
                    _dbg("WARN: много циклов без валидного снимка. Если игра в "
                         "полноэкранном эксклюзиве - включи 'Оконный без рамки'")
                time.sleep(_SCAN_SLEEP)
                continue
            fail_streak = 0
            gp, w, h = cap

            # Приоритет КНОПКИ. Пока кнопка на экране - мы НЕ приняли,
            # сколько бы 'кубов' ни нашлось: это может быть зелёный ФОН
            # за попапом (мох/трава проходят _is_green). Прежний порядок
            # (accepted-state первым) глотал матч: ложные кубы от фона ->
            # кулдаун 10с -> фон не меняется -> цикл кулдаунов до конца
            # окна приёма. Проявлялось как "иногда игнорит в тех же
            # условиях": фон зависит от карты/спавна/освещения.
            center = _find_button(gp, w, h)
            if center is None:
                rows, detail = _accepted_rows(gp, w, h)
                if rows >= SLOT_MIN_ROWS:
                    _dbg(f"accepted-state (кнопки нет) rows={rows}/{len(SLOT_ROWS_FY)} "
                         f"детали={detail} - кулдаун 10с")
                    cooldown_until = time.time() + 10.0
                    continue
                diag_cycle += 1
                if diag_cycle % 5 == 1:
                    pts = []
                    for fx, fy in ((0.44, 0.39), (0.56, 0.39),
                                   (0.44, 0.455), (0.56, 0.455), (0.50, 0.39)):
                        px = gp(int(w * fx), int(h * fy))
                        pts.append(f"{px & 0xFF},{(px >> 8) & 0xFF},{(px >> 16) & 0xFF}")
                    _dbg(f"кнопка не найдена; окно={w}x{h}; RGB углов кнопки={pts}")
                time.sleep(_SCAN_SLEEP)
                continue

            # дебаунс: кнопка должна устоять на втором снимке
            time.sleep(0.15)
            if not bool(Options.get("EnableAutoAccept", False)):
                continue
            cap = _grab(hwnd)
            if not cap:
                continue
            gp, w, h = cap
            center2 = _find_button(gp, w, h)
            if center2 is None:
                continue

            # клик по активному/после перевода фокуса
            if win32gui.GetForegroundWindow() != hwnd and not _force_foreground(hwnd):
                _dbg("не удалось получить фокус окна")
                cooldown_until = time.time() + _COOLDOWN_FAIL
                continue

            accepted = False
            for attempt in range(3):
                cx, cy = center2
                left, top, _, _ = win32gui.GetWindowRect(hwnd)
                _real_click(left + cx, top + cy)
                _dbg(f"клик #{attempt + 1} по ({left + cx}, {top + cy})")
                time.sleep(_VERIFY_DELAY)

                try:
                    process = connector.ensure_process()
                    client = connector.ensure_module("client.dll")
                    if _is_in_match(process, client, Offsets.offset):
                        accepted = True
                        break
                except Exception:
                    pass

                cap = _grab(hwnd)
                if not cap:
                    _dbg("после клика снимок не удался - проверка отложена")
                    break
                gp, w, h = cap
                rows, detail = _accepted_rows(gp, w, h)
                if rows >= SLOT_MIN_ROWS:
                    accepted = True
                    break
                center2 = _find_button(gp, w, h)
                if center2 is None:
                    # валидный снимок, кнопки нет - принято
                    accepted = True
                    break

            if accepted:
                _dbg("матч принят")
                cooldown_until = time.time() + _COOLDOWN_ACCEPTED
            else:
                _dbg("кнопка не подтверждена")
                cooldown_until = time.time() + _COOLDOWN_FAIL

            time.sleep(0.5)

        except Exception as e:
            _dbg(f"исключение: {e!r}")
            time.sleep(0.5)
# markers: END functions/autoaccept.py v2.4
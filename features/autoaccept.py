import time
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


def _is_accepted_state(gp, w, h):
    x0, x1 = int(w * 0.30), int(w * 0.70)
    step_x = max(1, w // 480)
    btn_min = w * MIN_RUN_W
    rows_ok = 0
    for fy in SLOT_ROWS_FY:
        y = int(h * fy)
        runs = _green_runs(gp, y, x0, x1, step_x)
        # строка с кнопочным прогоном - это кнопка, не кубики
        if any((e - s) + step_x >= btn_min for s, e in runs):
            continue
        slots = [r for r in runs
                 if w * SLOT_RUN_MIN <= (r[1] - r[0]) + step_x <= w * SLOT_RUN_MAX]
        if len(slots) >= SLOT_MIN_COUNT:
            rows_ok += 1
    return rows_ok >= SLOT_MIN_ROWS


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
    # активное окно -> экран (BitBlt); фоновое -> PrintWindow; фоллбеки в обе стороны
    fg = win32gui.GetForegroundWindow() == hwnd
    order = (("screen", "window"), ("window", "screen"))[not fg]
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
    try:
        lp = memfuncs.ProcMemHandler.ReadPointer(process, client + off.dwLocalPlayerPawn)
        if not lp:
            return False
        memfuncs.ProcMemHandler.ReadInt(process, lp + off.m_iHealth)
        return True
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

            try:
                process = connector.ensure_process()
                client = connector.ensure_module("client.dll")
                in_match = _is_in_match(process, client, Offsets.offset)
            except Exception:
                in_match = False

            state = in_match
            if state != last_state:
                last_state = state
                _dbg(f"статус: в_матче={in_match}")

            if in_match:
                # вошли в матч. кто-то не принял -> поиск заново -> павн
                # исчезнет -> ловля продолжится сама
                time.sleep(_IN_MATCH_SLEEP)
                continue

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

            if _is_accepted_state(gp, w, h):
                cooldown_until = time.time() + 10.0
                continue
            center = _find_button(gp, w, h)
            if center is None:
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
                if _is_accepted_state(gp, w, h):
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
import time
import ctypes
import win32gui
import win32api
import win32con
from functions import memfuncs
from functions import logutil
from functions.process_watcher import ProcessConnector

_SINGLE_MUTEX = None
DEBUG_MODE = True  # Включи True для подробного логирования

def _ensure_single_instance():
    """Только один экземпляр автопринятия на всю систему."""
    global _SINGLE_MUTEX
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        _SINGLE_MUTEX = kernel32.CreateMutexW(None, False, "NERON_AUTOACCEPT_SINGLE")
        return ctypes.GetLastError() != 183  # 183 = ERROR_ALREADY_EXISTS
    except Exception:
        return True

def _is_button_green(rgb):
    """Проверка на зеленый цвет кнопки ПРИНЯТЬ."""
    r = rgb & 0xFF
    g = (rgb >> 8) & 0xFF
    b = (rgb >> 16) & 0xFF
    
    # Возвращаемся к простой логике, но с пониженными порогами
    # Это должно работать и на 60%, и на 33% яркости
    if g > 80:  # Было 130
        if (g - r) > 10 and (g - b) > 10:  # Было 20
            return True
    
    return False

def _button_present(get_pixel_rel, w, h):
    """
    Поиск кнопки ПРИНЯТЬ по вертикальному зеленому блоку.
    """
    need = int(h * 0.05)
    y0, y1 = int(h * 0.36), int(h * 0.47)
    step = max(1, h // 720)
    
    green_pixels_found = 0
    sample_pixels = []
    
    for fx in (0.46, 0.54):
        x = int(w * fx)
        run = 0
        y = y0
        while y <= y1:
            try:
                px = get_pixel_rel(x, y)
            except Exception:
                px = 0
            
            # Собираем статистику для отладки
            if DEBUG_MODE and y == y0:
                r = px & 0xFF
                g = (px >> 8) & 0xFF
                b = (px >> 16) & 0xFF
                sample_pixels.append((x, y, r, g, b))
            
            if _is_button_green(px):
                run += step
                green_pixels_found += 1
                if run >= need:
                    if DEBUG_MODE:
                        logutil.debug(f"[autoaccept] Кнопка найдена! Зеленых пикселей: {green_pixels_found}, нужно: {need}")
                    return True
            else:
                run = 0
            y += step
    
    if DEBUG_MODE:
        logutil.debug(f"[autoaccept] Кнопка НЕ найдена. Зеленых пикселей: {green_pixels_found}, нужно: {need}")
        if sample_pixels:
            logutil.debug(f"[autoaccept] Примеры пикселей (x, y, R, G, B):")
            for px_data in sample_pixels[:5]:  # Первые 5 пикселей
                logutil.debug(f"  ({px_data[0]}, {px_data[1]}) -> R={px_data[2]}, G={px_data[3]}, B={px_data[4]}")
    
    return False

def _capture_valid(get_pixel_rel, w, h):
    non_black = 0
    for fy in (0.25, 0.5, 0.75):
        for fx in (0.25, 0.5, 0.75):
            try:
                px = get_pixel_rel(int(w * fx), int(h * fy))
            except Exception:
                px = 0
            if (px & 0xFF) + ((px >> 8) & 0xFF) + ((px >> 16) & 0xFF) > 30:
                non_black += 1
    return non_black >= 3

def _capture_window(hwnd):
    try:
        import win32ui
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w = right - left
        h = bottom - top
        if w <= 0 or h <= 0:
            return None
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        ok = False
        for flag in (2, 0):
            try:
                win32gui.PrintWindow(hwnd, save_dc.GetSafeHdc(), flag)
                ok = True
                break
            except Exception:
                continue
        if not ok:
            raise Exception("PrintWindow failed")

        def get_pixel_rel(x, y):
            return save_dc.GetPixel((x, y))

        def cleanup():
            for fn in (
                lambda: win32gui.DeleteObject(bmp.GetHandle()),
                save_dc.DeleteDC,
                mfc_dc.DeleteDC,
                lambda: win32gui.ReleaseDC(hwnd, hwnd_dc),
            ):
                try:
                    fn()
                except Exception:
                    pass

        return get_pixel_rel, w, h, cleanup
    except Exception as e:
        if DEBUG_MODE:
            logutil.debug(f"[autoaccept] _capture_window failed: {e}")
        return None

def _capture_screen(hwnd):
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w = right - left
        h = bottom - top
        if w <= 0 or h <= 0:
            return None
        dc = win32gui.GetDC(0)

        def get_pixel_rel(x, y):
            return win32gui.GetPixel(dc, left + x, top + y)

        def cleanup():
            try:
                win32gui.ReleaseDC(0, dc)
            except Exception:
                pass

        return get_pixel_rel, w, h, cleanup
    except Exception as e:
        if DEBUG_MODE:
            logutil.debug(f"[autoaccept] _capture_screen failed: {e}")
        return None

def _grab(hwnd):
    if win32gui.GetForegroundWindow() == hwnd:
        if DEBUG_MODE:
            logutil.debug("[autoaccept] Окно в фокусе, используем _capture_screen")
        return _capture_screen(hwnd) or _capture_window(hwnd)
    cap = _capture_window(hwnd)
    if cap and not _capture_valid(cap[0], cap[1], cap[2]):
        if DEBUG_MODE:
            logutil.debug("[autoaccept] _capture_window вернул невалидные данные, пробуем _capture_screen")
        cap[3]()
        cap = None
    if not cap:
        cap = _capture_screen(hwnd)
    return cap

def _force_foreground(hwnd):
    try:
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        except Exception:
            pass
        win32api.keybd_event(0x12, 0, 0, 0)
        win32api.keybd_event(0x12, 0, 2, 0)
        win32gui.SetForegroundWindow(hwnd)
        for _ in range(20):
            if win32gui.GetForegroundWindow() == hwnd:
                return True
            time.sleep(0.05)
    except Exception as e:
        if DEBUG_MODE:
            logutil.debug(f"[autoaccept] _force_foreground failed: {e}")
    return win32gui.GetForegroundWindow() == hwnd

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
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    if not _ensure_single_instance():
        if DEBUG_MODE:
            logutil.debug("[autoaccept] Уже запущен другой экземпляр, спим")
        while True:
            time.sleep(5)

    cooldown_until = 0.0
    while True:
        try:
            if not bool(Options.get("EnableAutoAccept", False)):
                time.sleep(0.5)
                continue

            hwnd = win32gui.FindWindow(None, "Counter-Strike 2")
            if not hwnd:
                time.sleep(0.5)
                continue

            process = connector.ensure_process()
            client = connector.ensure_module("client.dll")
            if not process or not client:
                time.sleep(0.3)
                continue

            # Спячка на время матча
            if _is_in_match(process, client, Offsets.offset):
                if DEBUG_MODE:
                    logutil.debug("[autoaccept] В матче, спим")
                time.sleep(0.3)
                if _is_in_match(process, client, Offsets.offset):
                    time.sleep(0.5)
                    continue

            if time.time() < cooldown_until:
                time.sleep(0.3)
                continue

            if DEBUG_MODE:
                logutil.debug("[autoaccept] Делаем снимок экрана...")
            
            cap = _grab(hwnd)
            if not cap:
                if DEBUG_MODE:
                    logutil.debug("[autoaccept] Не удалось сделать снимок")
                time.sleep(0.3)
                continue

            gp, w, h, cl = cap
            if DEBUG_MODE:
                logutil.debug(f"[autoaccept] Снимок получен: {w}x{h}")
            
            try:
                found = _button_present(gp, w, h)
            finally:
                cl()

            if not found:
                time.sleep(0.25)
                continue

            # Дебаунс: подтверждаем кнопку повторным снимком
            if DEBUG_MODE:
                logutil.debug("[autoaccept] Кнопка найдена, делаем повторную проверку...")
            time.sleep(0.3)
            cap = _grab(hwnd)
            if not cap:
                continue
            gp, w, h, cl = cap
            try:
                confirmed = _button_present(gp, w, h)
            finally:
                cl()

            if not confirmed:
                if DEBUG_MODE:
                    logutil.debug("[autoaccept] Кнопка не подтверждена")
                continue

            if not _force_foreground(hwnd):
                if DEBUG_MODE:
                    logutil.debug("[autoaccept] Не удалось перевести окно в фокус")
                time.sleep(0.3)
                continue

            if DEBUG_MODE:
                logutil.debug("[autoaccept] Окно в фокусе, кликаем...")
            
            for attempt in range(5):
                left, top, _, _ = win32gui.GetWindowRect(hwnd)
                win32api.SetCursorPos((left + int(w * 0.50), top + int(h * 0.42)))
                time.sleep(0.05)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                
                if DEBUG_MODE:
                    logutil.debug(f"[autoaccept] Клик выполнен (попытка {attempt + 1})")
                
                time.sleep(1.0)

                # Кнопка исчезла / стали слотами => приняли
                cap2 = _grab(hwnd)
                if cap2:
                    gp2, w2, h2, cl2 = cap2
                    try:
                        still = _button_present(gp2, w2, h2)
                    finally:
                        cl2()
                    if not still:
                        if DEBUG_MODE:
                            logutil.debug("[autoaccept] Кнопка исчезла - принято!")
                        cooldown_until = time.time() + 10
                        break
                else:
                    cooldown_until = time.time() + 10
                    break

                # Матч реально грузится
                if _is_in_match(process, client, Offsets.offset):
                    if DEBUG_MODE:
                        logutil.debug("[autoaccept] Матч загружается - принято!")
                    cooldown_until = time.time() + 10
                    break

            time.sleep(2.0)
        except Exception as e:
            logutil.debug(f"[autoaccept] {e}")
            time.sleep(0.5)
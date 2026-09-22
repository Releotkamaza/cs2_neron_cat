import ctypes
import ctypes.wintypes  # ОБЯЗАТЕЛЬНО явно: ctypes.wintypes не подгружается
                        # сам с ctypes - раньше работало только случайно,
                        # пока какой-то из импортов main тянул подмодуль
import win32api, win32gui, win32con

from functions import logutil

user32 = ctypes.WinDLL('user32', use_last_error=True)
SetWindowDisplayAffinity = user32.SetWindowDisplayAffinity
SetWindowDisplayAffinity.argtypes = ctypes.wintypes.HWND, ctypes.wintypes.DWORD
SetWindowDisplayAffinity.restype = ctypes.wintypes.BOOL
WDA_EXCLUDEFROMCAPTURE = 0x00000011
WDA_NONE = 0x00000000

HIDDEN = False
STREAMPROOF = False

def hide_dpg():
    global HIDDEN
    global STREAMPROOF
    hwnd = win32gui.FindWindow(None, "NERON")
    if not hwnd:
        return
    if HIDDEN:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        if STREAMPROOF:
            SetWindowDisplayAffinity(hwnd, WDA_NONE)
            SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        HIDDEN = False
    elif not HIDDEN:
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        HIDDEN = True

def streamproof_toggle():
    global STREAMPROOF
    hwnd1 = win32gui.FindWindow(None, "NERON")
    hwnd2 = win32gui.FindWindow(None, "ESP-Overlay")
    # Окно может быть не создано/уже закрыто (хоткей до старта или после
    # выхода): без guard'а pywintypes.error летел в поток keyboard.
    if not hwnd1 and not hwnd2:
        return
    if STREAMPROOF:
        logutil.info("STREAMPROOF OFF")
        if hwnd1:
            SetWindowDisplayAffinity(hwnd1, WDA_NONE)
        if hwnd2:
            SetWindowDisplayAffinity(hwnd2, WDA_NONE)
        STREAMPROOF = False
    elif not STREAMPROOF:
        logutil.info("STREAMPROOF ON")
        if hwnd1:
            SetWindowDisplayAffinity(hwnd1, WDA_EXCLUDEFROMCAPTURE)
        if hwnd2:
            SetWindowDisplayAffinity(hwnd2, WDA_EXCLUDEFROMCAPTURE)
        STREAMPROOF = True
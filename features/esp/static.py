
"""Статичный слой рендера: элементы, чьи данные НЕ критичны к частоте
кадров и обновляются редко (по таймеру), а не опрашиваются каждый кадр.

  * Панель зрителей: список перечитывается раз в 0.2 c (SharedRuntime),
    рисование - по кэшу (спектатор-воркер всё равно пишет раз в 0.5 c).
  * Кастомный прицел: геометрия (длина/цвет/обводка/стиль/толщина/зазор/
    прозрачность) читается ТОЛЬКО пока открыто окно чита (NERON) - вне
    него эти значения физически не могут измениться. Наличие прицела
    (enabled) и флаги координации с точкой ноускопа перечитываются по
    таймеру 0.2 c: их могут дёргать хоткеи вне GUI.

Живые гейты отрисовки прицела (зум/алив) остаются покадровыми - это
игровое состояние, а не настройки; при входе в зум прицел обязан
исчезать сразу. Динамический слой (ESP-примитивы, точка ноускопа, крест
NoScope, бомб-кард, смоки) живёт в core.py.
"""

import time

import win32gui

import globals
from features import spectator
from features import customcrosshair
from features import noscopedot
from .fonts import _find_overlay_font, _ensure_raylib_font, _get_overlay_font_handle

# ==================== Тайминги обновления ====================
SPEC_UPDATE_SEC = 0.2         # список зрителей: раз в 0.2 c
CROSS_FLAGS_SEC = 0.2         # наличие прицела + геометрия (по тому же таймеру,
                              # но геометрия читается только при открытом GUI)
GUI_VISIBLE_CHECK_SEC = 0.25  # кэш проверки видимости окна чита (WinAPI не спамим)

# ==================== Кэш зрителей ====================
_spec_cache = []
_spec_last_read = 0.0
_spec_enabled = True


def render_spectators(pme, Options, SharedRuntime=None):
    """Панель зрителей. Список и флаг читаются раз в SPEC_UPDATE_SEC,
    дальше рисуем по кэшу. Шапка/тексты панели - render_spectator_block."""
    global _spec_cache, _spec_last_read, _spec_enabled
    now = time.time()
    if now - _spec_last_read >= SPEC_UPDATE_SEC:
        _spec_last_read = now
        try:
            _spec_enabled = bool(Options.get("EnableShowSpectators", True))
        except Exception:
            _spec_enabled = True
        try:
            _spec_cache = list(SharedRuntime.spectators) if SharedRuntime is not None else []
        except Exception:
            _spec_cache = []
    try:
        spectator.render_spectator_block(
            pme,
            _spec_cache,
            enabled=_spec_enabled,
            screen_size=(globals.SCREEN_WIDTH, globals.SCREEN_HEIGHT),
            font_path=_find_overlay_font(),
            font_id=_ensure_raylib_font(),
            font_handle=_get_overlay_font_handle(16),
            font_size=16,
        )
    except Exception:
        pass


# ==================== Кэш кастомного прицела ====================
_gui_checked_ts = 0.0
_gui_visible = False

_cross_cfg = None
_cross_cfg_ts = 0.0


def _gui_is_visible():
    """Окно чита (NERON) видимо сейчас? Кэш GUI_VISIBLE_CHECK_SEC.
    Геометрия прицела меняется только из этого окна: скрыто - не читаем."""
    global _gui_checked_ts, _gui_visible
    now = time.time()
    if now - _gui_checked_ts < GUI_VISIBLE_CHECK_SEC:
        return _gui_visible
    _gui_checked_ts = now
    try:
        hwnd = win32gui.FindWindow(None, "NERON")
        _gui_visible = bool(hwnd) and bool(win32gui.IsWindowVisible(hwnd))
    except Exception:
        _gui_visible = False
    return _gui_visible


def render_crosshair(pme, processHandle, clientBaseAddress, Offsets, Options):
    """Кастомный прицел. Геометрия кэшируется и перечитывается только при
    открытом GUI; наличие/флаги - по таймеру CROSS_FLAGS_SEC (хоткеи).
    Живые гейты зум/алив и самое рисование - draw_cfg в customcrosshair."""
    global _cross_cfg, _cross_cfg_ts
    now = time.time()
    if _cross_cfg is None:
        # Первый кадр: читаем всё, даже если GUI скрыт (кэша ещё нет)
        _cross_cfg = customcrosshair.build_cfg(Options)
        _cross_cfg_ts = now
    elif now - _cross_cfg_ts >= CROSS_FLAGS_SEC:
        _cross_cfg_ts = now
        if _gui_is_visible():
            _cross_cfg = customcrosshair.build_cfg(Options)
        else:
            customcrosshair.refresh_flags(_cross_cfg, Options)
    try:
        customcrosshair.draw_cfg(pme, processHandle, clientBaseAddress, Offsets, _cross_cfg)
    except Exception:
        pass


# ==================== Кэш точки ноускопа ====================
_dot_cfg = None
_dot_cfg_ts = 0.0


def render_noscopedot(pme, processHandle, clientBaseAddress, Offsets, Options):
    """Точка ноускопа: параметры (цвет/радиус/прозрачность) кэшируются и
    перечитываются только при открытом GUI (те же гейты, что у прицела);
    наличие (enabled) - по таймеру (хоткеи). Живые гейты зум/жив/оружие
    и самое рисование - draw_cfg в noscopedot."""
    global _dot_cfg, _dot_cfg_ts
    now = time.time()
    if _dot_cfg is None:
        # Первый кадр: читаем всё, даже если GUI скрыт (кэша ещё нет)
        _dot_cfg = noscopedot.build_cfg(Options)
        _dot_cfg_ts = now
    elif now - _dot_cfg_ts >= CROSS_FLAGS_SEC:
        _dot_cfg_ts = now
        if _gui_is_visible():
            _dot_cfg = noscopedot.build_cfg(Options)
        else:
            noscopedot.refresh_flags(_dot_cfg, Options)
    noscopedot.draw_cfg(pme, processHandle, clientBaseAddress, Offsets, _dot_cfg)


def render_static(pme, processHandle, clientBaseAddress, Offsets, Options, SharedRuntime=None):
    """Единая точка входа статичного слоя для ESP_Update."""
    render_spectators(pme, Options, SharedRuntime)
    render_crosshair(pme, processHandle, clientBaseAddress, Offsets, Options)
    render_noscopedot(pme, processHandle, clientBaseAddress, Offsets, Options)



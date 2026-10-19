import ctypes
import time
import random
import win32api
from ext.datatypes import *
from globals import *

# ============================================================================
# МОДУЛЬ ИМПУТОВ (только ввод в игру)
# ============================================================================
# Здесь только низкоуровневые вводы: ЛКМ и перемещение курсора.
# Политики задержек тут нет: задержку реакции триггера считает
# features/triggerbot.py по настройкам TriggerbotDelay* и отдаёт в
# LeftClick готовое число. Так скрытая константа не может незаметно
# подменить настройку пользователя.

# Время удержания ЛКМ (нажатие -> отпускание), мс, случайно.
CLICK_HOLD_MIN_MS = 8.0
CLICK_HOLD_MAX_MS = 30.0


def LeftClick(delay_ms=0.0):
    """Клик ЛКМ: пауза delay_ms -> LEFTDOWN -> удержание -> LEFTUP.

    delay_ms - ГОТОВОЕ время в мс (снимает features/triggerbot.py по
    конфигу). None/мусор -> клик без паузы.
    """
    try:
        pause_ms = float(delay_ms)
    except (TypeError, ValueError):
        pause_ms = 0.0
    if pause_ms > 0.0:
        time.sleep(pause_ms / 1000.0)
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
    time.sleep(random.uniform(CLICK_HOLD_MIN_MS, CLICK_HOLD_MAX_MS) / 1000.0)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP


def moveMouseToLocation(pos: Vector2):
    """Сдвинуть курсор к экранным координатам pos (относительно центра)."""
    if pos.x < 0.0 and pos.y < 0.0:
        return
    center_of_screen = Vector2(SCREEN_WIDTH / 2.0, SCREEN_HEIGHT / 2.0)
    dx = int(pos.x - center_of_screen.x)
    dy = int(pos.y - center_of_screen.y)
    ctypes.windll.user32.mouse_event(0x0001, dx, dy, 0, 0)


def getCurrentMousePosition():
    """Текущая позиция курсора."""
    pos = win32api.GetCursorPos()
    if pos:
        return Vector2(pos[0], pos[1])
    return Vector2(0, 0)

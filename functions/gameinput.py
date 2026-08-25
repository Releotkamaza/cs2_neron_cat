import ctypes
import time
import random
import win32api
from ext.datatypes import *
from globals import *

# ============================================================================
# НАСТРОЙКИ СКОРОСТИ ТРИГГЕРА (РЕДАКТИРУЙ ЗДЕСЬ)
# ============================================================================
# Таблица реакции по ПРОМЕЖУТКАМ дистанции.
# Формат строки: (от_дист, до_дист, мин_задержка_мс, макс_задержка_мс)
#   - дистанция в юнитах (1 метр ~ 39 юнитов);
#   - задержка в миллисекундах ПЕРЕД нажатием (1 сек = 1000 мс).
# Берётся строка, в которую попала дистанция, и задержка выбирается
# СЛУЧАЙНО между мин и макс. Дальше цель -> меньше мс (быстрее).
TRIGGER_DELAY_STEPS = [
    (0.0,     250.0,   90.0, 140.0),   # вплотную: медленно, по-человечески
    (250.0,   500.0,   60.0,  90.0),   # ближняя
    (500.0,   800.0,   35.0,  60.0),   # средняя
    (800.0,  1200.0,   20.0,  35.0),   # дальняя
    (1200.0, 2000.0,   10.0,  20.0),   # очень дальняя
    (2000.0, 99999.0,   5.0,  12.0),   # экстремально далеко
]

# Задержка, если дистанция неизвестна (LeftClick() без аргумента).
LEGACY_DELAY_MIN_MS = 1.0
LEGACY_DELAY_MAX_MS = 17.0

# Время удержания кнопки (нажатие->отпускание), мс, случайно.
CLICK_HOLD_MIN_MS = 8.0
CLICK_HOLD_MAX_MS = 30.0


def _pick_delay_ms(distance):
    """Случайная задержка в мс внутри своего промежутка дистанции."""
    if distance is None:
        return random.uniform(LEGACY_DELAY_MIN_MS, LEGACY_DELAY_MAX_MS)
    d = max(0.0, float(distance))
    for (d0, d1, ms_min, ms_max) in TRIGGER_DELAY_STEPS:
        if d0 <= d < d1:
            return random.uniform(ms_min, ms_max)
    return random.uniform(TRIGGER_DELAY_STEPS[-1][2], TRIGGER_DELAY_STEPS[-1][3])


def LeftClick(distance=None):
    """
    Эмуляция клика ЛКМ.
    distance - дистанция до цели в юнитах (передаёт триггер).
    distance=None - старое поведение для прочих модулей.
    """
    time.sleep(_pick_delay_ms(distance) / 1000.0)          # реакция
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
    time.sleep(random.uniform(CLICK_HOLD_MIN_MS, CLICK_HOLD_MAX_MS) / 1000.0)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP


def LeftClickArduino(handle):
    """Клик через Arduino (внешний эмулятор)."""
    time.sleep(random.randint(10, 30) / 1000.0)
    handle.write(f"down\n".encode())
    time.sleep(random.randint(10, 50) / 1000.0)
    handle.write(f"up\n".encode())


def moveMouseToLocation(pos: Vector2):
    """Сдвинуть курсор к экранным координатам pos (относительно центра)."""
    if pos.x < 0.0 and pos.y < 0.0:
        return
    center_of_screen = Vector2(SCREEN_WIDTH / 2.0, SCREEN_HEIGHT / 2.0)
    dx = int(pos.x - center_of_screen.x)
    dy = int(pos.y - center_of_screen.y)
    ctypes.windll.user32.mouse_event(0x0001, dx, dy, 0, 0)  # MOUSEEVENTF_MOVE


def getCurrentMousePosition():
    """Текущая позиция курсора."""
    pos = win32api.GetCursorPos()
    if pos:
        return Vector2(pos[0], pos[1])
    return Vector2(0, 0)


def moveMouseToLocationArdunio(pos: Vector2, handle=None):
    """То же, что moveMouseToLocation, но через Arduino."""
    if pos.x < 0.0 and pos.y < 0.0:
        return
    center_of_screen = Vector2(SCREEN_WIDTH / 2.0, SCREEN_HEIGHT / 2.0)
    dx = int(pos.x - center_of_screen.x)
    dy = int(pos.y - center_of_screen.y)
    handle.write(f"move {dx},{dy}\n".encode())
import math
import time

import win32gui

from ext.datatypes import Vector2, Vector3, Matrix
from globals import SCREEN_WIDTH, SCREEN_HEIGHT

def distance_vec3(v: Vector3, other: Vector3) -> float:
    dx = float(v.x) - float(other.x)
    dy = float(v.y) - float(other.y)
    dz = float(v.z) - float(other.z)
    return math.sqrt(dx * dx + dy * dy + dz * dz)

def distance_vec2(v: Vector2, other: Vector2) -> float:
    dx = float(v.x) - float(other.x)
    dy = float(v.y) - float(other.y)
    return math.sqrt(dx * dx + dy * dy)


# Радиус сферического купола дыма в юнитах CS2. Та же величина, что
# SMOKE_RADIUS в features/nosmoke.py (там она нужна для маркера на
# оверлее); здесь - для проверки перекрытия линии видимости.
SMOKE_RADIUS = 128.0


def smoke_blocks_segment(eye, target, smokes, radius=SMOKE_RADIUS, now=None) -> bool:
    """True, если отрезок eye->target упирается в сферу любого смока.

    smokes - список позиций вида [x, y, z, t_end, det_time] (хвост не
    обязателен). Если передан now: позиции с det_time > now (смок ещё
    летит - купола дыма в мире нет) и с t_end < now (купол уже рассеялся)
    пропускаются - иначе остывший/мёртвый смок продолжал бы ложно
    перекрывать обзор.
    Геометрия: расстояние от центра сферы до ОТРЕЗКА (а не до прямой) -
    иначе смок за спиной или за целью давал бы ложное перекрытие.
    Чистая функция без чтений памяти: её зовут и ESP-сканер (в отдельном
    потоке), и аимбот (в кадре рендера)."""
    if not smokes or eye is None or target is None:
        return False
    try:
        ex, ey, ez = float(eye.x), float(eye.y), float(eye.z)
        tx, ty, tz = float(target.x), float(target.y), float(target.z)
    except Exception:
        return False
    dx = tx - ex
    dy = ty - ey
    dz = tz - ez
    seg_len2 = dx * dx + dy * dy + dz * dz
    if not math.isfinite(seg_len2) or seg_len2 <= 1e-6:
        return False
    r2 = float(radius) * float(radius)
    for s in smokes:
        try:
            cx = float(s[0]); cy = float(s[1]); cz = float(s[2])
        except Exception:
            continue
        if now is not None and len(s) >= 5:
            try:
                if float(s[4]) > float(now):
                    continue
                if float(s[3]) < float(now):
                    continue
            except Exception:
                pass
        # Параметр ближайшей к центру точки отрезка (кламп в [0, 1]).
        t = -(((ex - cx) * dx) + ((ey - cy) * dy) + ((ez - cz) * dz)) / seg_len2
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        px = ex + dx * t
        py = ey + dy * t
        pz = ez + dz * t
        qx = px - cx
        qy = py - cy
        qz = pz - cz
        if qx * qx + qy * qy + qz * qz <= r2:
            return True
    return False

def _isfinite_matrix(mat):
    try:
        for r in mat:
            for v in r:
                if not math.isfinite(v):
                    return False
        return True
    except Exception:
        return False

def world_to_screen(view_matrix: Matrix, position: Vector3):
    """Мировые координаты -> экран. Возвращает None, если точка за камерой
    (w < 0.01); раньше за-камерой и любой краевой случай возвращали (-1, -1),
    что ложилось на границу фильтра 'x <= -1' у потребителя."""
    try:
        if not view_matrix or not getattr(view_matrix, "matrix", None):
            return None
        mat = view_matrix.matrix
        if not _isfinite_matrix(mat):
            return None
    except Exception:
        return None
    x = position.x
    y = position.y
    z = position.z
    try:
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            return None
    except Exception:
        return None
    screen_x = mat[0][0] * x + mat[0][1] * y + mat[0][2] * z + mat[0][3]
    screen_y = mat[1][0] * x + mat[1][1] * y + mat[1][2] * z + mat[1][3]
    w = mat[3][0] * x + mat[3][1] * y + mat[3][2] * z + mat[3][3]
    if not math.isfinite(w) or w < 0.01:
        return None
    invw = 1.0 / w
    screen_x *= invw
    screen_y *= invw
    width_float = float(SCREEN_WIDTH)
    height_float = float(SCREEN_HEIGHT)
    px = (width_float / 2.0) + (0.5 * screen_x * width_float) + 0.5
    py = (height_float / 2.0) - (0.5 * screen_y * height_float) + 0.5
    return Vector2(px, py)

def calculate_angles(from_: Vector3, to: Vector3) -> Vector2:
    deltaX = to.x - from_.x
    deltaY = to.y - from_.y
    deltaZ = to.z - from_.z
    yaw = math.atan2(deltaY, deltaX) * 180.0 / math.pi
    distance = math.sqrt(deltaX * deltaX + deltaY * deltaY)
    pitch = -(math.atan2(deltaZ, distance) * 180.0 / math.pi)
    return Vector2(yaw, pitch)

_CS2_WINDOW_TITLE = "Counter-Strike 2"      # канон rcs.py GetWindowText
_OVERLAY_WINDOW_TITLE = "ESP-Overlay"       # title из esp.pme.overlay_init (main.py)
_CENTER_TTL = 0.25
_center_cache = {"ts": 0.0, "x": 0, "y": 0}


def native_crosshair_center():
    """(cx, cy) - куда рисовать прицел, чтобы совпасть с нативным крестом,
    в координатах draw-слоя оверлея."""
    now = time.time()
    c = _center_cache
    if now - c["ts"] < _CENTER_TTL:
        return c["x"], c["y"]
    c["ts"] = now

    # Цель: центр клиентской области окна игры, экранные координаты
    x = int(SCREEN_WIDTH // 2)
    y = int(SCREEN_HEIGHT // 2)
    try:
        hwnd = win32gui.FindWindow(None, _CS2_WINDOW_TITLE)
        if hwnd:
            l, t, r, b = win32gui.GetClientRect(hwnd)
            sx, sy = win32gui.ClientToScreen(hwnd, (0, 0))
            w = int(r) - int(l)
            h = int(b) - int(t)
            if w > 0 and h > 0:
                x = int(sx) + w // 2
                y = int(sy) + h // 2
    except Exception:
        pass

    # Компенсация оверлея: минус экранный origin его клиентской области
    try:
        ohwnd = win32gui.FindWindow(None, _OVERLAY_WINDOW_TITLE)
        if ohwnd:
            osx, osy = win32gui.ClientToScreen(ohwnd, (0, 0))
            x -= int(osx)
            y -= int(osy)
    except Exception:
        pass

    c["x"], c["y"] = x, y
    return x, y

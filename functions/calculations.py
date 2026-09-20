import math

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


def world_to_screen(view_matrix: Matrix, position: Vector3):
    """Мировые координаты -> экран. Возвращает None, если точка за камерой
    (w < 0.01); раньше за-камерой и любой краевой случай возвращали (-1, -1),
    что ложилось на границу фильтра 'x <= -1' у потребителя."""
    mat = view_matrix.matrix
    x = position.x
    y = position.y
    z = position.z

    screen_x = mat[0][0] * x + mat[0][1] * y + mat[0][2] * z + mat[0][3]
    screen_y = mat[1][0] * x + mat[1][1] * y + mat[1][2] * z + mat[1][3]
    w = mat[3][0] * x + mat[3][1] * y + mat[3][2] * z + mat[3][3]

    if w < 0.01:
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
import pyMeow as pme
import globals
from .colors import clamp, resolve_color
from .fonts import draw_text as _draw_text

# Режим обводки текста:
#   "shadow4" - 4 тени + текст (5 вызовов draw_text, максимальная обводка)
#   "shadow1" - одна тень +1,+1 (2 вызова; на 12-15px выглядит как обводка)
#   "plate"   - тёмная полупрозрачная подложка (2 вызова; максимальная читаемость)
TEXT_OUTLINE_MODE = "plate"

_SHADOW_COLOR = None
_PLATE_COLOR = None

# Кэш pme.get_color: парсинг hex убран из покадровых вызовов
_pme_col_cache = {}


def _pcol(hexstr):
    c = _pme_col_cache.get(hexstr)
    if c is None:
        c = pme.get_color(hexstr)
        _pme_col_cache[hexstr] = c
    return c


# Кэш resolve_color ТОЛЬКО для хэшируемых входов (константные hex-строки
# из core). Уже-резолвнутые объекты идут напрямую, без кэша: попытка
# использовать их ключом = TypeError (нехэшируемое), регресс v3 -
# исключение на каждой энтити глоталось per-entity except, живы были
# только трейсеры. v2-поведение для них сохранено 1:1.
_rcol_cache = {}


def _rcol(color):
    try:
        c = _rcol_cache.get(color)
    except TypeError:
        return resolve_color(color)
    if c is None:
        c = resolve_color(color)
        try:
            _rcol_cache[color] = c
        except TypeError:
            pass
    return c


def draw_shadowed_label(text, x, y, size=12, color="#FFFFFF"):
    global _SHADOW_COLOR, _PLATE_COLOR
    base = _rcol(color)

    if TEXT_OUTLINE_MODE == "shadow4":
        if _SHADOW_COLOR is None:
            _SHADOW_COLOR = pme.fade_color(resolve_color("#000000"), 0.65)
        for ox, oy in ((-1, 0), (1, 0), (0, 1), (0, -1)):
            _draw_text(text, x + ox, y + oy, size=size, color=_SHADOW_COLOR)
        _draw_text(text, x, y, size=size, color=base)
        return

    if TEXT_OUTLINE_MODE == "plate":
        if _PLATE_COLOR is None:
            _PLATE_COLOR = pme.fade_color(resolve_color("#000000"), 0.55)
        w = int(len(text) * size * 0.62) + 4
        h = size + 4
        pme.draw_rectangle(int(x) - 2, int(y) - 2, w, h, color=_PLATE_COLOR)
        _draw_text(text, x, y, size=size, color=base)
        return

    # shadow1 (по умолчанию)
    if _SHADOW_COLOR is None:
        _SHADOW_COLOR = pme.fade_color(resolve_color("#000000"), 0.8)
    _draw_text(text, x + 1, y + 1, size=size, color=_SHADOW_COLOR)
    _draw_text(text, x, y, size=size, color=base)


def draw_name(player_name, x, y, color="#FFFFFF", font_size=12):
    if player_name:
        draw_shadowed_label(player_name, x, y, size=font_size, color=color)


def draw_weapon(weapon_name, x, y, color="#D9C9FF", font_size=12):
    """Название активного оружия - тот же путь рендера, что Имя/Дистанция."""
    if weapon_name:
        draw_shadowed_label(weapon_name, x, y, size=font_size, color=color)


def draw_distance(x, y, distance, color="#FFFFFF", font_size=12):
    draw_shadowed_label(f"{distance:.1f}m", x, y, size=font_size, color=color)


def draw_health_text(x, y, health, color="#FFFFFF", font_size=12):
    draw_shadowed_label(f"HP: {int(health)}", x, y, size=font_size, color=color)


def draw_health_bar(health, x, y, height, bar_width=None, thickness_scale=1.0,
                    use_health_color=True, team_color=None, color_from_hex=None):
    hp = int(max(0, min(100, health or 0)))
    if bar_width is None:
        bw = clamp(height * 0.02, 2.0, 6.0)
    else:
        bw = float(bar_width)
    try:
        bw *= float(thickness_scale or 1.0)
    except Exception:
        pass
    bw = clamp(bw, 1.0, 8.0)
    track_x = int(round(x)) - (int(round(bw)) + 6)
    track_y = int(round(y))
    track_h = int(round(height))
    track_w = int(round(bw))
    if track_h <= 0 or track_w <= 0:
        return
    col_bg = _pcol("#111418")
    col_border = _pcol("#3A4652")
    if use_health_color and color_from_hex:
        col_fill = _pcol(color_from_hex)
    else:
        col_fill = team_color if isinstance(team_color, (tuple, list)) else _pcol("#22C55E")
    pme.draw_rectangle(track_x - 1, track_y - 1, track_w + 2, track_h + 2, color=col_border)
    pme.draw_rectangle(track_x, track_y, track_w, track_h, color=col_bg)
    filled = int(round(track_h * hp / 100.0))
    if filled > 0:
        pme.draw_rectangle(track_x, track_y + (track_h - filled), track_w, filled, color=col_fill)
    _draw_text(str(hp), track_x - 6, track_y - 16, size=12, color=col_fill)


def draw_box(rect_left, rect_top, rect_width, rect_height, color, thickness_scale=1.0):
    base = _rcol(color)
    x1, y1 = int(rect_left), int(rect_top)
    x2, y2 = int(rect_left + rect_width), int(rect_top + rect_height)
    size = max(1.0, float(min(rect_width, rect_height)))
    L = int(max(4.0, min(24.0, size * 0.22)))
    T = max(1.3, min(2.6, size * 0.018))
    try:
        T *= float(thickness_scale or 1.0)
    except Exception:
        pass
    T = max(0.8, min(3.2, T))
    fade = max(0.65, min(1.0, size / 120.0))
    col = pme.fade_color(base, 0.9 * fade + 0.1)
    pme.draw_line(x1, y1, x1 + L, y1, color=col, thick=T)
    pme.draw_line(x1, y1, x1, y1 + L, color=col, thick=T)
    pme.draw_line(x2, y1, x2 - L, y1, color=col, thick=T)
    pme.draw_line(x2, y1, x2, y1 + L, color=col, thick=T)
    pme.draw_line(x1, y2, x1 + L, y2, color=col, thick=T)
    pme.draw_line(x1, y2, x1, y2 - L, color=col, thick=T)
    pme.draw_line(x2, y2, x2 - L, y2, color=col, thick=T)
    pme.draw_line(x2, y2, x2, y2 - L, color=col, thick=T)


def draw_skeleton(bones, bone_connections, color, thickness=None, joint_radius=None):
    col = _rcol(color)
    if thickness is None or joint_radius is None:
        try:
            xs = [pt.x for pt in bones.values() if pt.x >= 0 and pt.y >= 0]
            ys = [pt.y for pt in bones.values() if pt.x >= 0 and pt.y >= 0]
            scale = max(max(xs) - min(xs), max(ys) - min(ys)) if xs and ys else 50.0
        except Exception:
            scale = 50.0
        if thickness is None:
            thickness = clamp(scale * 0.02, 1.0, 2.2)
        if joint_radius is None:
            joint_radius = int(round(clamp(scale * 0.03, 1.0, 3.0)))
    for s_name, e_name in bone_connections:
        if s_name in bones and e_name in bones:
            s = bones[s_name]
            e = bones[e_name]
            if s.x < 0 or s.y < 0 or e.x < 0 or e.y < 0:
                continue
            pme.draw_line(s.x, s.y, e.x, e.y, color=col, thick=thickness)
    try:
        conn_bones = set()
        for s_name, e_name in bone_connections:
            conn_bones.add(s_name)
            conn_bones.add(e_name)
        for bname, pt in bones.items():
            if bname in conn_bones and pt.x >= 0 and pt.y >= 0:
                pme.draw_circle(int(pt.x), int(pt.y), int(joint_radius), color=col)
    except Exception:
        pass


# Длительность <= этого порога считаем дефюзом "с китом"
_KIT_DEFUSE_MAX = 7.0


def draw_bomb_status_card(*, planted, time_left, total_time=40.0,
                          defusing=False, defuse_left=None, defuse_total=None,
                          defuse_impossible=False):
    try:
        screen_h = globals.SCREEN_HEIGHT
        card_w = 236
        show_defuse = bool(planted and defusing and defuse_left is not None)
        card_h = 134 if show_defuse else (118 if planted else 104)
        pad_x = 16
        pad_y = 12
        title_size = 16
        status_size = 18
        detail_size = 13
        x = 28
        y = (screen_h - card_h) // 3
        # фиолетовая палитра GUI v5.x: акцент #965CFF, приглушённый #583896
        base_accent = _pcol("#965CFF")
        status_accent = _pcol("#ec4058") if planted else _pcol("#34d399")
        col_shadow = pme.fade_color(_pcol("#000000"), 0.28)
        col_border = pme.fade_color(base_accent, 0.48)
        col_bg = pme.fade_color(_pcol("#150B1A"), 0.92)
        col_title = _pcol("#F5F2FC")
        col_muted = pme.fade_color(_pcol("#B0A4D0"), 0.9)
        col_bar_bg = pme.fade_color(_pcol("#1A0F2E"), 0.95)
        pme.draw_rectangle(x + 3, y + 5, card_w, card_h, col_shadow)
        pme.draw_rectangle(x, y, card_w, card_h, col_border)
        inner_x = x + 1
        inner_y = y + 1
        inner_w = card_w - 2
        inner_h = card_h - 2
        pme.draw_rectangle(inner_x, inner_y, inner_w, inner_h, col_bg)
        pme.draw_rectangle(inner_x, inner_y, 3, inner_h, base_accent)
        title_y = inner_y + pad_y
        status_y = title_y + title_size + 6
        detail_y = status_y + status_size + 6
        detail2_y = detail_y + detail_size + 4

        status_text = "PLANTED" if planted else "SAFE"
        detail_text = ""
        detail2_text = ""
        show_progress = False
        remaining = 0.0
        bar_total = max(0.01, float(total_time or 40.0))

        if planted:
            if show_defuse:
                d_left = max(0.0, float(defuse_left))
                b_left = max(0.0, float(time_left) if (time_left is not None and time_left >= 0) else 0.0)
                kit = bool(defuse_total is not None and float(defuse_total) <= _KIT_DEFUSE_MAX)
                if defuse_impossible:
                    # Дефюз не успевает закончиться до взрыва
                    status_text = "WON'T FINISH"
                    status_accent = _pcol("#ec4058")
                    detail_text = f"defuse {d_left:.1f}s > bomb {b_left:.1f}s"
                    detail2_text = "bomb detonates first"
                else:
                    status_text = "DEFUSING"
                    status_accent = _pcol("#fbbf24")
                    detail_text = f"{d_left:.1f}s to defuse ({'kit' if kit else 'no kit'})"
                    detail2_text = f"bomb: {b_left:.1f}s"
                # Прогресс-бар показывает остаток дефюза
                remaining = d_left
                bar_total = max(0.01, float(defuse_total) if defuse_total else 5.0)
                show_progress = True
            elif time_left < 0:
                detail_text = "Syncing timer..."
                show_progress = False
                remaining = 0.0
            else:
                remaining = max(0.0, float(time_left))
                detail_text = f"{int(round(remaining))}s until detonation"
                show_progress = True
        else:
            detail_text = "No active bomb detected."
            show_progress = False
            remaining = 0.0

        _draw_text("BOMB STATUS", inner_x + pad_x, title_y, size=title_size, color=col_title)
        _draw_text(status_text, inner_x + pad_x, status_y, size=status_size, color=status_accent)
        _draw_text(detail_text, inner_x + pad_x, detail_y, size=detail_size, color=col_muted)
        if show_defuse and detail2_text:
            _draw_text(detail2_text, inner_x + pad_x, detail2_y, size=detail_size, color=col_muted)
        if show_progress:
            total = bar_total
            ratio = max(0.0, min(1.0, remaining / total))
            bar_width = inner_w - pad_x * 2
            bar_height = 12
            bar_x = inner_x + pad_x
            bar_y = inner_y + inner_h - pad_y - bar_height
            pme.draw_rectangle(bar_x, bar_y, bar_width, bar_height, col_bar_bg)
            fill_width = int(round(bar_width * ratio))
            if fill_width > 0:
                pme.draw_rectangle(bar_x, bar_y, fill_width, bar_height, pme.fade_color(status_accent, 0.82))
            pme.draw_rectangle_lines(bar_x, bar_y, bar_width, bar_height, pme.fade_color(status_accent, 0.65), lineThick=1.0)
    except Exception:
        # Фича подтверждена: молча не рвём кадр оверлея
        pass
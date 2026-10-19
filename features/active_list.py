"""Окно "Активные функции" в оверлее: список включённых функций.

Паттерн — панель зрителей (features/spectator.py + features/esp/static.py):
читает настройки из Options (SharedOptions, кэш 100 мс в main-лупе),
рисует в оверлее pyMeow поверх игры. Видимость окна переключает
мастер-ключ ToggleKey_EnableActiveList (обработка в HotkeyEngine.poll в
functions/toggle_registry.py), позиция окна — ActiveListPosX/ActiveListPosY
в %% экрана (ползунки во вкладке GUI "Активные функции"), набор
показываемых функций — ListShow_<ключ> (чекбоксы там же).
"""

from functions import toggle_registry
from features import spectator  # _panel_colors: единый стиль панелей оверлея


def render_active_list(pme, Options, screen_size=None):
    try:
        if not (bool(Options.get("EnableActiveList", False))
                and bool(Options.get("ActiveListVisible", False))):
            return
    except Exception:
        return
    try:
        if isinstance(screen_size, (tuple, list)) and len(screen_size) >= 2:
            sw, sh = int(screen_size[0]), int(screen_size[1])
        else:
            try:
                sw, sh = pme.get_screen_size()
            except Exception:
                sw, sh = 1920, 1080

        # Собираем активные функции с учётом настройки показа
        items = toggle_registry.active_feature_labels(Options)

        pad_x, pad_y = 14, 10
        title_size, name_size = 16, 15
        line_height = name_size + 6
        title = "Активные функции"

        max_chars = len(title)
        for it in items:
            max_chars = max(max_chars, len(it))
        block_w = max(220, pad_x * 2 + max_chars * 8)
        rows = max(1, len(items))
        block_h = pad_y * 2 + title_size + 6 + rows * line_height

        # Позиция окна: ползунки X/Y в % — окно ЦЕЛИКОМ от левого/верхнего
        # края (0%) до правого/нижнего (100%). Раньше было x = sw*px/100
        # (левый край окна на px) и "or 70": 0 в Python falsy, поэтому 0%
        # превращался в дефолтные 70% (окно «на четверть правее середины»),
        # а 100% улетал в клип к правому краю. Исправлено v8.4.6.
        try:
            _vx = Options.get("ActiveListPosX", 70)
            px = int(_vx) if _vx is not None else 70
        except Exception:
            px = 70
        try:
            _vy = Options.get("ActiveListPosY", 4)
            py = int(_vy) if _vy is not None else 4
        except Exception:
            py = 4
        px = max(0, min(100, px))
        py = max(0, min(100, py))
        x = int((sw - block_w) * px / 100.0)
        y = int((sh - block_h) * py / 100.0)
        # Страховка за края (если вычисленный размер неточен)
        if x + block_w > sw:
            x = max(0, sw - block_w)
        if y + block_h > sh:
            y = max(0, sh - block_h)

        cols = spectator._panel_colors(pme)
        pme.draw_rectangle(x, y, block_w, block_h, cols["bg"])
        pme.draw_rectangle_lines(x, y, block_w, block_h, cols["border"], lineThick=1)
        pme.draw_rectangle(x, y, 3, block_h, cols["accent"])

        from features.esp.fonts import draw_text as _fd
        _fd(title, x + pad_x, y + pad_y, size=title_size, color=cols["title"])
        cur_y = y + pad_y + title_size + 6
        if items:
            for it in items:
                _fd(it, x + pad_x, cur_y, size=name_size, color=cols["name"])
                cur_y += line_height
        else:
            _fd("Нет активных функций", x + pad_x, cur_y, size=name_size, color=cols["name"])
    except Exception:
        pass
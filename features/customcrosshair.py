import json
import os
import time

import globals
from functions import memfuncs
from functions import calculations
from features import noscopedot

try:
    from features.esp.colors import resolve_color
except Exception:
    resolve_color = None

# ==================== Границы клампа настроек (слайдеры GUI
# имеют те же диапазоны; это настройки, не оффсеты) ====================
THICKNESS_MIN, THICKNESS_MAX = 1.0, 10.0
LENGTH_MIN, LENGTH_MAX = 1.0, 30.0
GAP_MIN, GAP_MAX = 0.0, 20.0
OPACITY_MIN, OPACITY_MAX = 10, 100

# Стили (строки - их хранит комбо GUI, vtype "combo")
STYLE_NORMAL = "Обычный"
STYLE_TSHAPE = "T-образный"

# Цвет обводки и её паддинг (дизайн-константы, не оффсеты)
OUTLINE_COLOR = "#000000"
OUTLINE_PAD = 1

# Игровая константа (канон fovchanger.SCOPE_FOV_MAX): FOV ниже - зум.
ZOOM_FOV_MAX = 89

# Рейтлимит печати ошибок: новая фича до подтверждения НЕ глушится
# глухим except, но и не спамит консоль 240 раз/сек.
_ERR_INTERVAL = 5.0
_err_last = 0.0

# Кэш фейдов: ключ (hex, opacity), значения - списки (контракт pme)
_fade_cache = {}


def _clampf(value, lo, hi):
    try:
        return max(lo, min(hi, float(value)))
    except Exception:
        return lo


def _is_tshape(Options):
    try:
        return str(Options.get("Crosshair_Style", STYLE_NORMAL) or STYLE_NORMAL) == STYLE_TSHAPE
    except Exception:
        return False


def _hex(Options, key, default):
    try:
        h = str(Options.get(key, default) or default).lstrip("#").strip()
        if len(h) >= 6:
            return "#" + h[:6].upper()
    except Exception:
        pass
    return default


def _opacity01(Options):
    try:
        v = int(Options.get("Crosshair_Opacity", 100))
    except Exception:
        v = 100
    v = max(OPACITY_MIN, min(OPACITY_MAX, v))
    return v / 100.0


def _fade(pme, hexstr, op01):
    """hex -> непрозрачный список цвета. resolve_color - путь всего
    рендера проекта (контракт списков), фоллбек pme.get_color."""
    key = (hexstr, round(op01, 2))
    c = _fade_cache.get(key)
    if c is None:
        try:
            base = resolve_color(hexstr) if resolve_color is not None else pme.get_color(hexstr)
        except Exception:
            base = pme.get_color("#FFFFFF")
        try:
            c = pme.fade_color(base, op01)
        except Exception:
            c = base
        _fade_cache[key] = c
    return c


def _in_lobby_or_not_live(proc, client, off):
    """Возвращает True если НЕ в активном матче (лобби/меню/поиск)"""
    try:
        # читаем m_bHasMatchStarted из схемы как в autoaccept
        o_has_started = _resolve_has_match_started()
        if not o_has_started or not getattr(off, 'dwGameRules', 0):
            return False  # не можем определить - не блокируем
        try:
            gr = memfuncs.ProcMemHandler.ReadPointer(proc, client + off.dwGameRules)
            if not gr:
                return True  # нет правил - вероятно лобби
            started = bool(memfuncs.ProcMemHandler.ReadBool(proc, gr + o_has_started))
            return not started
        except:
            return False
    except:
        return False


def _resolve_has_match_started():
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        repo = os.path.abspath(os.path.join(base, ".."))
        for c in (os.path.join(repo, "output"), repo, os.path.join(repo, "ext"), base):
            p = os.path.join(c, "client_dll.json")
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        jd = json.load(f)
                    fields = (jd.get("client.dll", {}).get("classes", {})
                              .get("C_CSGameRules", {}).get("fields") or {})
                    v = fields.get("m_bHasMatchStarted")
                    return int(v) if v else 0
                except:
                    pass
    except:
        pass
    return 0


def _is_zoomed(proc, lp, o):
    """Зум: m_bIsScoped ИЛИ 0<FOV<89. Логика зеркальна noscopedot.draw
    (fovchanger пишет m_bIsScoped=0 в зуме при 'Убрать чёрный скоуп',
    FOV-чек обязателен). При изменении там - синхронизировать здесь."""
    try:
        if hasattr(o, 'm_bIsScoped') and getattr(o, 'm_bIsScoped'):
            try:
                if memfuncs.ProcMemHandler.ReadInt(proc, lp + o.m_bIsScoped) == 1:
                    return True
            except Exception:
                pass
    except:
        pass
    try:
        if hasattr(o, 'm_pCameraServices') and hasattr(o, 'm_iFOV'):
            cam = memfuncs.ProcMemHandler.ReadPointer(proc, lp + o.m_pCameraServices)
            if cam:
                cf = memfuncs.ProcMemHandler.ReadInt(proc, cam + o.m_iFOV)
                if 0 < cf < ZOOM_FOV_MAX:
                    return True
    except Exception:
        pass
    return False


def _alive(proc, lp, o):
    """Жив? (байт lifestate, 0 = жив; та же семантика, что noscopedot)"""
    try:
        if hasattr(o, 'm_lifeState') and getattr(o, 'm_lifeState'):
            try:
                return int(memfuncs.ProcMemHandler.ReadBytes(proc, lp + o.m_lifeState, 1)[0]) == 0
            except:
                pass
        # fallback: health > 0
        if hasattr(o, 'm_iHealth') and getattr(o, 'm_iHealth'):
            try:
                hp = memfuncs.ProcMemHandler.ReadInt(proc, lp + o.m_iHealth)
                return hp > 0
            except:
                pass
    except Exception:
        pass
    return False


def _dot_takes_priority(cfg, proc, client, lp, o):
    """True - сейчас рисуется точка noscopedot, кастомный молчит.
    Зум/жив уже проверены вызывающим (у точки те же гейты), осталось
    'swap включен И точка включена И снайперка в руках'. Резолв оружия
    - единый источник noscopedot (_get_schema/_weapon_index), кэш
    по handle общий, двойных чтений нет. Нет схемы -> 'не снайперка'
    -> кастомный рисует (точка при этом честно молчит). Флаги приходят
    из cfg-кэша (features/esp/static.py перечитывает их по таймеру)."""
    if not cfg.get("dot_sep"):
        return False
    if not cfg.get("dot_on"):
        return False
    res = noscopedot._weapon_index(proc, client, lp, o, noscopedot._get_schema())
    if res is None:
        return False
    return res[0] in noscopedot.SNIPER_ITEM_IDS


def _draw_segments(pme, cx, cy, th, ln, gap, tshape, col, out_col, outline):
    """Крест из прямоугольников. Точки входа линий отстоят от центра
    на gap, длина ln, толщина th. Обводка: чёрный rect с паддингом
    OUTLINE_PAD под каждой линией. T-образный - без верхней линии
    (не перекрывает хедбокс)."""
    half = th / 2.0
    segs = [
        (cx - gap - ln, cy - half, ln, th),   # левая
        (cx + gap,      cy - half, ln, th),   # правая
        (cx - half,     cy + gap,  th, ln),   # нижняя
    ]
    if not tshape:
        segs.append((cx - half, cy - gap - ln, th, ln))  # верхняя
    if outline:
        for (x, y, w, h) in segs:
            pme.draw_rectangle(
                int(round(x)) - OUTLINE_PAD, int(round(y)) - OUTLINE_PAD,
                int(round(w)) + 2 * OUTLINE_PAD, int(round(h)) + 2 * OUTLINE_PAD,
                color=out_col)
    for (x, y, w, h) in segs:
        pme.draw_rectangle(
            int(round(x)), int(round(y)),
            max(1, int(round(w))), max(1, int(round(h))),
            color=col)


def build_cfg(Options):
    """Кэшируемая геометрия прицела + флаги. Вызывается РЕДКО (см.
    features/esp/static.py), не каждый кадр: вне открытого окна чита
    эти значения не могут измениться."""
    return {
        "th": _clampf(Options.get("Crosshair_Thickness", 2.0), THICKNESS_MIN, THICKNESS_MAX),
        "ln": _clampf(Options.get("Crosshair_Length", 8.0), LENGTH_MIN, LENGTH_MAX),
        "gap": _clampf(Options.get("Crosshair_Gap", 4.0), GAP_MIN, GAP_MAX),
        "op01": _opacity01(Options),
        "hexc": _hex(Options, "Crosshair_color", "#00FF00"),
        "outline": bool(Options.get("Crosshair_Outline", True)),
        "tshape": _is_tshape(Options),
        "enabled": bool(Options.get("EnableCustomCrosshair", False)),
        "dot_sep": bool(Options.get("EnableNoScopeDotSeparate", False)),
        "dot_on": bool(Options.get("EnableNoScopeDot", False)),
    }


def refresh_flags(cfg, Options):
    """Обновить в cfg только 'наличие' (enabled прицела + координация с
    точкой): эти флаги могут дёргаться хоткеями вне GUI. Геометрия не
    трогается - вне открытого окна она не меняется."""
    try:
        cfg["enabled"] = bool(Options.get("EnableCustomCrosshair", False))
    except Exception:
        pass
    try:
        cfg["dot_sep"] = bool(Options.get("EnableNoScopeDotSeparate", False))
    except Exception:
        pass
    try:
        cfg["dot_on"] = bool(Options.get("EnableNoScopeDot", False))
    except Exception:
        pass
    return cfg


def draw_cfg(pme, processHandle, clientBaseAddress, Offsets, cfg):
    """Рисование кастомного прицела по КЭШИРОВАННОЙ геометрии (cfg).
    Живые гейты (зум/жив/активное оружие) проверяются здесь каждый кадр:
    это игровое состояние, а не настройки - прицел обязан исчезать сразу
    при входе в зум. Выключен -> нулевая цена (один выход)."""
    global _err_last
    try:
        if not cfg.get("enabled"):
            return
        o = Offsets.offset

        lp = 0
        try:
            lp = memfuncs.ProcMemHandler.ReadPointer(
                processHandle, clientBaseAddress + o.dwLocalPlayerPawn)
        except Exception:
            lp = 0
        if not lp:
            return

        # Рисование: только вне зума, жив, и точка не имеет приоритета
        # Не рисуем в лобби, рисуем только в матче (живы или нет - проверяем отдельно по жизни)
        try:
            if _in_lobby_or_not_live(processHandle, clientBaseAddress, Offsets):
                return
        except Exception:
            pass
        # Если живы - не рисуем в зуме
        if _is_zoomed(processHandle, lp, o) and _alive(processHandle, lp, o):
            return
        if _dot_takes_priority(cfg, processHandle, clientBaseAddress, lp, o):
            return

        col = _fade(pme, cfg["hexc"], cfg["op01"])
        out_col = _fade(pme, OUTLINE_COLOR, min(1.0, cfg["op01"] + 0.25)) if cfg["outline"] else None
        cx, cy = calculations.native_crosshair_center()
        _draw_segments(pme, cx, cy, cfg["th"], cfg["ln"], cfg["gap"], cfg["tshape"],
                       col, out_col, cfg["outline"])
    except Exception as exc:
        now = time.time()
        if now - _err_last >= _ERR_INTERVAL:
            _err_last = now
            try:
                print("[customcrosshair] draw_cfg error:", repr(exc), flush=True)
            except Exception:
                pass


def update(processHandle, clientBaseAddress, Offsets, Options, pme):
    """Обратная совместимость: полное чтение настроек + рисование за кадр.
    Рендер-цикл больше не вызывает (статичный слой кэширует через
    build_cfg/refresh_flags/draw_cfg); сохранено для внешних вызовов."""
    draw_cfg(pme, processHandle, clientBaseAddress, Offsets, build_cfg(Options))

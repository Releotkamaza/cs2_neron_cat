import os
import json

import globals
from functions import memfuncs
from functions import calculations

try:
    from features.esp.colors import resolve_color
except Exception:
    resolve_color = None

# Definition index'ы снайперских винтовок
SNIPER_ITEM_IDS = frozenset({9, 40, 38, 11})   # AWP, SSG08, SCAR-20, G3SG1

# Границы клампа настроек (слайдеры в GUI имеют те же диапазоны)
RADIUS_MIN, RADIUS_MAX = 1.0, 12.0
OPACITY_MIN, OPACITY_MAX = 10, 100

# ==================== Структурные константы entity-листа ====================
ENT_BUCKET_STEP = 0x8
ENT_IDENTITY = 0x10
ENT_STRIDE = 112
HANDLE_SER_MASK = 0x7FFF
HANDLE_IDX_MASK = 0x1FF

# Поля схемы: каждое ИЗ СВОЕГО КЛАССА
_SCHEMA_NEEDS = (
    ("C_BasePlayerPawn", "m_pWeaponServices"),
    ("CPlayer_WeaponServices", "m_hActiveWeapon"),
    ("C_EconEntity", "m_AttributeManager"),
    ("C_AttributeContainer", "m_Item"),
    ("C_EconItemView", "m_iItemDefinitionIndex"),
    ("C_CSWeaponBaseGun", "m_zoomLevel"),
)

_REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_schema = None
_col_cache = {}
_wpn_cache = {"h": -1, "idx": -1, "zl": -1}


def _get_schema():
    """Словарь поле -> оффсет, каждое поле из своего класса. Один раз
    за жизнь процесса."""
    global _schema
    if _schema is not None:
        return _schema
    data = {}
    try:
        with open(os.path.join(_REPO, "output", "client_dll.json"), "r", encoding="utf-8") as f:
            jd = json.load(f)
        classes = jd.get("client.dll", {}).get("classes", {})
        for cname, fname in _SCHEMA_NEEDS:
            cdata = classes.get(cname)
            if not cdata:
                continue
            val = (cdata.get("fields") or {}).get(fname)
            if val is not None:
                data[fname] = int(val)
    except Exception:
        pass
    _schema = data
    return data


def _dot_color(hexstr):
    """Цвет точки: resolve_color - путь всего рендера проекта. Кэш по
    входной строке."""
    c = _col_cache.get(hexstr)
    if c is not None:
        return c
    try:
        h = (hexstr or "FFFFFF").lstrip("#").strip()
        h = h[:6].upper() if len(h) >= 6 else "FFFFFF"
    except Exception:
        h = "FFFFFF"
    result = "#" + h
    if resolve_color is not None:
        try:
            result = resolve_color("#" + h)
        except Exception:
            result = "#" + h
    _col_cache[hexstr] = result
    return result


def _weapon_index(proc, client_base, local_pawn, o, sch):
    """(idx, zl) активного оружия. ent по handle-пути (конвенция
    ESP-сканера), индекс - uint16 по каноничной вложенной композиции
    (ent + AM + Item + idx). uint16 ОБЯЗАТЕЛЬНО: int32 затягивает
    соседнее m_iEntityQuality в старшую половину (0x40000-мусор).
    Кэш по handle."""
    ws_off = sch.get("m_pWeaponServices", 0)
    aw_off = sch.get("m_hActiveWeapon", 0)
    am_off = sch.get("m_AttributeManager", 0)
    item_off = sch.get("m_Item", 0)
    idx_off = sch.get("m_iItemDefinitionIndex", 0)
    zl_off = sch.get("m_zoomLevel", 0)
    if not (ws_off and aw_off and am_off and item_off and idx_off):
        return None
    try:
        ws = memfuncs.ProcMemHandler.ReadPointer(proc, local_pawn + ws_off)
        if not ws:
            return None
        try:
            handle = int(memfuncs.ProcMemHandler.ReadUInt(proc, ws + aw_off))
        except Exception:
            handle = int(memfuncs.ProcMemHandler.ReadInt(proc, ws + aw_off)) & 0xFFFFFFFF
        if handle and handle == _wpn_cache["h"]:
            return (_wpn_cache["idx"], _wpn_cache["zl"])
        if not handle:
            # Нет оружия (смерть/межраунд) - кэш сбрасываем
            _wpn_cache.update(h=-1, idx=-1, zl=-1)
            return None
        index = handle & HANDLE_SER_MASK
        el = memfuncs.ProcMemHandler.ReadPointer(proc, client_base + o.dwEntityList)
        if not el:
            return None
        le = memfuncs.ProcMemHandler.ReadPointer(
            proc, el + ENT_BUCKET_STEP * (index >> 9) + ENT_IDENTITY)
        if not le:
            return None
        ent = memfuncs.ProcMemHandler.ReadPointer(
            proc, le + ENT_STRIDE * (index & HANDLE_IDX_MASK))
        if not ent:
            return None
        # Индекс: uint16 по вложенной композиции атрибутов (калибровка)
        widx = int(memfuncs.ProcMemHandler.ReadUShort(proc, ent + am_off + item_off + idx_off))
        zl = -1
        if zl_off:
            try:
                zl = int(memfuncs.ProcMemHandler.ReadInt(proc, ent + zl_off))
            except Exception:
                pass
        _wpn_cache.update(h=handle, idx=widx, zl=zl)
        return (widx, zl)
    except Exception:
        return None


def build_cfg(Options):
    """Кэшируемые параметры точки (цвет/прозрачность/радиус/наличие).
    Как и у кастомного прицела: эти значения меняются ТОЛЬКО из окна чита,
    поэтому читаются редко (static.py) — не каждый кадр. Наличие может
    дёргаться хоткеем вне GUI — оно обновляется по таймеру отдельно."""
    try:
        radius = float(Options.get("NoScopeDot_radius", 5.0))
    except Exception:
        radius = 5.0
    radius = max(RADIUS_MIN, min(RADIUS_MAX, radius))
    try:
        opacity = int(Options.get("NoScopeDot_opacity", 80))
    except Exception:
        opacity = 80
    opacity = max(OPACITY_MIN, min(OPACITY_MAX, opacity)) / 100.0
    try:
        color = Options.get("NoScopeDot_color", "#FFFFFF") or "#FFFFFF"
    except Exception:
        color = "#FFFFFF"
    return {
        "enabled": bool(Options.get("EnableNoScopeDot", False)),
        "radius": radius,
        "opacity": opacity,
        "color": _dot_color(color),
    }


def refresh_flags(cfg, Options):
    """Обновить в cfg только наличие (enabled) — его могут дёргать хоткеи
    вне GUI. Геометрия (цвет/радиус/прозрачность) не трогается: вне
    открытого окна она не меняется."""
    try:
        cfg["enabled"] = bool(Options.get("EnableNoScopeDot", False))
    except Exception:
        pass
    return cfg


def draw(processHandle, clientBaseAddress, Offsets, Options, pme):
    """Обратная совместимость: чтение настроек каждый кадр + рисование.
    Рендер-цикл больше не зовёт (статичный слой кэширует через
    build_cfg/refresh_flags/draw_cfg); сохранено для внешних вызовов."""
    draw_cfg(pme, processHandle, clientBaseAddress, Offsets, build_cfg(Options))


def draw_cfg(pme, processHandle, clientBaseAddress, Offsets, cfg):
    """Точка ноускопа по КЭШИРОВАННОЙ конфигурации (cfg). Живые гейты
    (зум/жив/оружие) проверяются здесь каждый кадр: это игровое состояние,
    а не настройки. Выключен -> нулевая цена (один выход)."""
    try:
        if not cfg.get("enabled"):
            return
        o = Offsets.offset

        # Локальный павн
        lp = 0
        try:
            lp = memfuncs.ProcMemHandler.ReadPointer(
                processHandle, clientBaseAddress + o.dwLocalPlayerPawn)
        except Exception:
            pass

        # Зум: m_bIsScoped ИЛИ 0<FOV<89 (fovchanger пишет m_bIsScoped=0
        # в зуме при "Убрать чёрный скоуп" - FOV-чек обязателен)
        zoomed = False
        if lp:
            try:
                zoomed = memfuncs.ProcMemHandler.ReadInt(
                    processHandle, lp + o.m_bIsScoped) == 1
            except Exception:
                pass
            if not zoomed:
                try:
                    cam = memfuncs.ProcMemHandler.ReadPointer(
                        processHandle, lp + o.m_pCameraServices)
                    if cam:
                        cf = memfuncs.ProcMemHandler.ReadInt(processHandle, cam + o.m_iFOV)
                        if 0 < cf < 89:
                            zoomed = True
                except Exception:
                    pass

        # Жив? (байт, 0 = жив)
        alive = False
        if lp:
            try:
                alive = int(memfuncs.ProcMemHandler.ReadBytes(
                    processHandle, lp + o.m_lifeState, 1)[0]) == 0
            except Exception:
                pass

        if lp and not zoomed and alive:
            sch = _get_schema()
            res = _weapon_index(processHandle, clientBaseAddress, lp, o, sch)
            if res is not None:
                widx, _zl = res
                if widx in SNIPER_ITEM_IDS:
                    try:
                        col = pme.fade_color(cfg["color"], cfg["opacity"])
                    except Exception:
                        col = cfg["color"]
                    _ncx, _ncy = calculations.native_crosshair_center()
                    pme.draw_circle(int(_ncx), int(_ncy),
                                    int(round(cfg["radius"])), color=col)

    except Exception:
        # Фича подтверждена: молча не рвём кадр оверлея
        pass

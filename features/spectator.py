import time
import os
from functions import memfuncs
from functions import fontpaths
from functions import logutil
from functions.process_watcher import ProcessConnector

_SPEC_LOG_LEVEL = 0

def set_spec_log_level(level: int):
    global _SPEC_LOG_LEVEL
    try:
        _SPEC_LOG_LEVEL = max(0, min(2, int(level)))
    except Exception:
        _SPEC_LOG_LEVEL = 0

if logutil.is_debug_enabled():
    _SPEC_LOG_LEVEL = 2

def _log(level: int, msg: str):
    if _SPEC_LOG_LEVEL >= level:
        logutil.debug(msg)

# Кэш цветов панели (создаётся один раз, а не каждый кадр)
_PANEL_COLORS = None

def _panel_colors(pme):
    global _PANEL_COLORS
    if _PANEL_COLORS is None:
        _PANEL_COLORS = {
            "border": pme.fade_color(pme.get_color("#588bc4"), 0.45),
            "bg":     pme.fade_color(pme.get_color("#101726"), 0.92),
            "accent": pme.fade_color(pme.get_color("#588bc4"), 0.85),
            "title":  pme.get_color("#f0f4ff"),
            "name":   pme.get_color("#e3e9f7"),
        }
    return _PANEL_COLORS

OBS_MODE_NONE      = 0
OBS_MODE_DEATHCAM  = 1
OBS_MODE_FREEZECAM = 2
OBS_MODE_FIXED     = 3
OBS_MODE_IN_EYE    = 4
OBS_MODE_CHASE     = 5
OBS_MODE_ROAMING   = 6

MODE_NAMES = {
    OBS_MODE_NONE:      "NONE",
    OBS_MODE_DEATHCAM:  "DEATHCAM",
    OBS_MODE_FREEZECAM: "FREEZECAM",
    OBS_MODE_FIXED:     "FIXED",
    OBS_MODE_IN_EYE:    "IN_EYE",
    OBS_MODE_CHASE:     "CHASE",
    OBS_MODE_ROAMING:   "ROAMING",
}

SCAN_INTERVAL_SEC = 0.50
MAX_ENTITIES      = 128

MASK64   = 0xFFFFFFFFFFFFFFFF
USER_LOW  = 0x0000000000100000
USER_HIGH = 0x00007FFFFFFFFFFF

def to_u64(x):
    try:
        return int(x) & MASK64
    except Exception:
        return 0

def is_valid_ptr(p):
    p = to_u64(p)
    return USER_LOW <= p <= USER_HIGH

def rd_ptr(h, addr):
    try:
        p = memfuncs.ProcMemHandler.ReadPointer(h, addr)
        p = to_u64(p)
        return p if is_valid_ptr(p) else 0
    except Exception:
        return 0

def rd_int(h, addr):
    try:
        return memfuncs.ProcMemHandler.ReadInt(h, addr) & 0xFFFFFFFF
    except Exception:
        return 0

def rd_bool(h, addr):
    try:
        return bool(memfuncs.ProcMemHandler.ReadBool(h, addr))
    except Exception:
        return False

def rd_bytes(h, addr, n):
    try:
        return memfuncs.ProcMemHandler.ReadBytes(h, addr, n)
    except Exception:
        return b""

def read_cstr_utf8(h, addr, maxlen=64):
    if not addr:
        return ""
    bs = rd_bytes(h, addr, maxlen)
    if not bs:
        return ""
    try:
        return bs.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
    except Exception:
        return ""

def read_controller_name(h, ctrl, off):
    p = rd_ptr(h, ctrl + off.m_sSanitizedPlayerName)
    s = read_cstr_utf8(h, p, 64) if p else ""
    if s:
        return s
    return read_cstr_utf8(h, ctrl + off.m_sSanitizedPlayerName, 64) or "UNKNOWN"

def ent_by_index_112(h, entlist_ptr, i):
    entry2 = rd_ptr(h, entlist_ptr + 0x8 * (i >> 9) + 0x10)
    if not entry2:
        return 0
    e = rd_ptr(h, entry2 + 112 * (i & 0x1FF))
    return e if is_valid_ptr(e) else 0

def handle_to_ent_stride(h, entlist_ptr, handle, stride):
    h32 = handle & 0xFFFFFFFF
    if h32 == 0 or h32 == 0xFFFFFFFF:
        return 0
    bucket = (h32 & 0x7FFF) >> 9
    idx    = (h32 & 0x1FF)
    entry2 = rd_ptr(h, entlist_ptr + 0x8 * bucket + 0x10)
    if not entry2:
        return 0
    e = rd_ptr(h, entry2 + stride * idx)
    return e if is_valid_ptr(e) else 0

def handle_to_ent_adaptive(h, entlist_ptr, handle):
    e = handle_to_ent_stride(h, entlist_ptr, handle, 112)
    if e:
        return e, 112
    e = handle_to_ent_stride(h, entlist_ptr, handle, 120)
    if e:
        return e, 120
    return 0, 0

def is_dead(h, pawn, off):
    """Мёртв ли игрок. Живой игрок в этой кодовой базе имеет m_lifeState == 256."""
    if not pawn:
        return False
    hp_off = getattr(off, "m_iHealth", 0)
    if hp_off:
        hp = rd_int(h, pawn + hp_off)
        if hp <= 0:
            return True
    life_off = getattr(off, "m_lifeState", 0)
    if life_off:
        life = rd_int(h, pawn + life_off)
        if life != 256:
            return True
    return False

def resolve_local_pawn(h, client, off, entlist_ptr):
    local_ctrl = rd_ptr(h, client + off.dwLocalPlayerController)
    if local_ctrl:
        hLocalPawn = rd_int(h, local_ctrl + off.m_hPlayerPawn)
        lp1, s1 = handle_to_ent_adaptive(h, entlist_ptr, hLocalPawn)
        if is_valid_ptr(lp1):
            return lp1, "A"
    lp2 = rd_ptr(h, client + off.dwLocalPlayerPawn)
    if is_valid_ptr(lp2):
        return lp2, "B(ptr)"
    return 0, "FAIL"

def SpectatorThreadFunction(Options, Offsets, Runtime):
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    try:
        set_spec_log_level(int(Options.get("SpectatorLogLevel", 0)))
    except Exception:
        set_spec_log_level(0)

    off = Offsets.offset
    _log(1, "[spectator] thread started.")

    try:
        allow_fixed = bool(Options.get("SpectatorAllowFixed", True))
    except Exception:
        allow_fixed = True
    ALLOWED_MODES = {OBS_MODE_IN_EYE, OBS_MODE_CHASE, OBS_MODE_FREEZECAM} | ({OBS_MODE_FIXED} if allow_fixed else set())

    last_sig = None

    while True:
        try:
            hproc = connector.ensure_process()
            client = connector.ensure_module("client.dll")

            try:
                if not bool(Options.get("EnableShowSpectators", False)):
                    Runtime.spectators = []
                    time.sleep(SCAN_INTERVAL_SEC)
                    continue
            except Exception:
                pass

            entlist_ptr = rd_ptr(hproc, client + off.dwEntityList)
            if not entlist_ptr:
                Runtime.spectators = []
                time.sleep(SCAN_INTERVAL_SEC)
                continue

            game_rules = rd_ptr(hproc, client + getattr(off, "dwGameRules", 0))
            if game_rules:
                mw = rd_bool(hproc, game_rules + getattr(off, "m_bMatchWaitingForResume", 0)) if getattr(off, "m_bMatchWaitingForResume", 0) else False
                mr = rd_bool(hproc, game_rules + getattr(off, "m_bGameRestart", 0)) if getattr(off, "m_bGameRestart", 0) else False
                if mw or mr:
                    Runtime.spectators = []
                    time.sleep(SCAN_INTERVAL_SEC)
                    continue

            local_pawn, route = resolve_local_pawn(hproc, client, off, entlist_ptr)
            local_ctrl_ptr = rd_ptr(hproc, client + off.dwLocalPlayerController)
            local_hpawn_handle = rd_int(hproc, local_ctrl_ptr + off.m_hPlayerPawn) if local_ctrl_ptr else 0
            local_handle_idx = (local_hpawn_handle & 0x7FFF) if local_hpawn_handle not in (0, 0xFFFFFFFF) else 0

            local_ctrl_idx = 0
            if local_ctrl_ptr:
                for i2 in range(1, MAX_ENTITIES):
                    if ent_by_index_112(hproc, entlist_ptr, i2) == local_ctrl_ptr:
                        local_ctrl_idx = i2
                        break

            if not is_valid_ptr(local_pawn):
                Runtime.spectators = []
                time.sleep(SCAN_INTERVAL_SEC)
                continue

            spectators = []

            for i in range(1, MAX_ENTITIES):
                ctrl = ent_by_index_112(hproc, entlist_ptr, i)
                if not ctrl:
                    continue
                if ctrl == local_ctrl_ptr:
                    continue

                name     = read_controller_name(hproc, ctrl, off)
                hObsPawn = rd_int(hproc, ctrl + off.m_hObserverPawn)
                hPawn    = rd_int(hproc, ctrl + off.m_hPlayerPawn)

                has_obs  = hObsPawn not in (0, 0xFFFFFFFF)
                has_pawn = hPawn not in (0, 0xFFFFFFFF)
                if not has_obs and not has_pawn:
                    continue

                player_pawn = 0
                if has_pawn:
                    player_pawn, _ = handle_to_ent_adaptive(hproc, entlist_ptr, hPawn)

                # Живой игрок никогда не наблюдатель (чинит "висящих" после респауна)
                if player_pawn and not is_dead(hproc, player_pawn, off):
                    continue

                observer_pawn = 0
                if has_obs:
                    observer_pawn, _ = handle_to_ent_adaptive(hproc, entlist_ptr, hObsPawn)

                if not observer_pawn:
                    if not player_pawn or not is_dead(hproc, player_pawn, off):
                        continue
                    observer_pawn = player_pawn

                obs_services = rd_ptr(hproc, observer_pawn + off.m_pObserverServices)
                if not obs_services and player_pawn and player_pawn != observer_pawn:
                    obs_services = rd_ptr(hproc, player_pawn + off.m_pObserverServices)

                mode = rd_int(hproc, obs_services + off.m_iObserverMode) if obs_services else 0

                hTarget = 0
                target_ent = 0
                target_idx = 0
                if obs_services:
                    hTarget = rd_int(hproc, obs_services + off.m_hObserverTarget)
                    if hTarget not in (0, 0xFFFFFFFF):
                        target_ent, _ = handle_to_ent_adaptive(hproc, entlist_ptr, hTarget)
                        target_idx = hTarget & 0x7FFF

                view_entity = 0
                view_idx = 0
                if not target_ent and observer_pawn:
                    cam = rd_ptr(hproc, observer_pawn + off.m_pCameraServices)
                    if cam:
                        hView = rd_int(hproc, cam + off.m_hViewEntity)
                        if hView not in (0, 0xFFFFFFFF):
                            view_entity, _ = handle_to_ent_adaptive(hproc, entlist_ptr, hView)
                            view_idx = hView & 0x7FFF

                match = bool(
                    (target_ent and (target_ent == local_pawn or target_ent == local_ctrl_ptr)) or
                    (view_entity and (view_entity == local_pawn or view_entity == local_ctrl_ptr)) or
                    (target_idx and (target_idx == local_handle_idx or target_idx == local_ctrl_idx)) or
                    (view_idx and (view_idx == local_handle_idx or view_idx == local_ctrl_idx))
                )

                if match and (mode in ALLOWED_MODES):
                    spectators.append({
                        "pawn": observer_pawn,
                        "mode": mode,
                        "mode_name": MODE_NAMES.get(mode, f"MODE_{mode}"),
                        "name": name or "UNKNOWN",
                    })

            Runtime.spectators = spectators

            sig = tuple(sorted((s["name"], s["pawn"], s["mode"]) for s in spectators))
            if sig != last_sig:
                if _SPEC_LOG_LEVEL >= 1:
                    if spectators:
                        names = ", ".join(s.get("name", "UNKNOWN") for s in spectators)
                        _log(1, f"[spectator] {len(spectators)} spectator(s): {names}")
                    else:
                        _log(1, "[spectator] no spectators")
                last_sig = sig

            time.sleep(SCAN_INTERVAL_SEC)

        except Exception as e:
            try:
                Runtime.spectators = []
            except Exception:
                pass
            logutil.debug(f"[spectator] exception: {e}")
            connector.invalidate()
            time.sleep(0.5)

def render_spectator_block(
    pme,
    spectators,
    enabled=True,
    screen_size=None,
    font_path=None,
    font_handle=None,
    font_size=16,
    font_id=None
):
    """
    Постоянная табличка, но рисуются ТОЛЬКО "ESP-безопасные" вызовы:
    draw_rectangle / draw_rectangle_lines / draw_font (raylib).
    Никакого measure_text, push/pop шрифтов и ImGui-шрифта - именно они текли.
    """
    try:
        if not enabled or not spectators:
            return

        sw = sh = 0
        if isinstance(screen_size, (tuple, list)) and len(screen_size) >= 2:
            sw, sh = int(screen_size[0]), int(screen_size[1])
        else:
            try:
                sw, sh = pme.get_screen_size()
            except Exception:
                sw, sh = 1920, 1080

        names = []
        for s in spectators:
            names.append((s.get("name") or "UNKNOWN").strip())
        if not names:
            return

        shown = names[:4]
        extra = len(names) - len(shown)
        line = ", ".join(shown)
        if extra > 0:
            line += " +{}".format(extra)
        title = "Spectators ({}):".format(len(names))

        cols = _panel_colors(pme)

        pad_x = 14
        pad_y = 10
        title_size = 16
        name_size = 15
        # Ширина без measure_text - оценка по длине строки
        max_chars = max(len(title), len(line))
        block_w = max(220, pad_x * 2 + max_chars * 8)
        block_h = pad_y * 2 + title_size + 6 + name_size
        x = sw - block_w - 24
        y = sh // 2 - block_h // 2

        pme.draw_rectangle(x, y, block_w, block_h, cols["bg"])
        pme.draw_rectangle_lines(x, y, block_w, block_h, cols["border"], lineThick=1)
        pme.draw_rectangle(x, y, 3, block_h, cols["accent"])

        if font_id is not None and hasattr(pme, "draw_font"):
            pme.draw_font(fontId=font_id, text=title, posX=x + pad_x, posY=y + pad_y,
                          fontSize=title_size, spacing=0, tint=cols["title"])
            pme.draw_font(fontId=font_id, text=line, posX=x + pad_x, posY=y + pad_y + title_size + 6,
                          fontSize=name_size, spacing=0, tint=cols["name"])
        else:
            def _safe(t):
                try:
                    t.encode("ascii")
                    return t
                except Exception:
                    return "".join(ch if ord(ch) < 128 else "?" for ch in t)
            pme.draw_text(_safe(title), x + pad_x, y + pad_y, fontSize=title_size, color=cols["title"])
            pme.draw_text(_safe(line), x + pad_x, y + pad_y + title_size + 6, fontSize=name_size, color=cols["name"])
    except Exception as e:
        try:
            _log(1, f"[overlay/spec] draw error: {e}")
        except Exception:
            pass
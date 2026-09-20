from functions import memfuncs
from functions import logutil
from functions.process_watcher import ProcessConnector
import win32api
import win32gui
import time
import random
import math
import ctypes

VK_A = 0x41
VK_D = 0x44
VK_SPACE = 0x20
KEYEVENTF_KEYUP = 0x0002

AIRACCEL = 12.0          # sv_airaccelerate
TICK = 1.0 / 64.0        # тик сервера
STRAFE_INVERT_KEYS = False  # True, если разгонит назад/вбок (зеркалит пару)

# Значения кнопки прыжка. Игра видит прыжок как ПЕРЕХОД 256 -> 65537 между
# соседними usercmd (edge), постоянное значение эджей не даёт.
JUMP_PRESS = 65537
JUMP_IDLE = 256

# ==================== ТАЙМИНГ ПРЫЖКА ====================
# Главный путь: эдж на переходе air->ground по m_fFlags, живёт один тик.
# Страховка: если эдж потрачен впустую (сервер сэмплировал usercmd с эджем
# до СВОЕГО приземления), через TICK включается волна пересоздания.
# ПОЛУПЕРИОД ВОЛНЫ ОБЯЗАН БЫТЬ БОЛЬШЕ ТИКА: эдж живёт полупериод, и если
# окно короче тика, эдж может пикнуть между сборками usercmd и сервер его
# вообще не увидит (дефект прошлой версии: 8 мс окно при тике 15.6 мс).
# 17 мс = тик + запас на джиттер цикла: эдж гарантированно накрывает
# хотя бы одну сборку usercmd.
EDGE_HOLD = 0.016        # главный эдж живёт один тик
REEDGE_HALF = 0.017      # полупериод волны страховки (> тика!)

# Структурные константы entity-листа (в дампах их нет по определению)
ENT_BUCKET_STEP = 0x8
ENT_IDENTITY = 0x10
ENT_STRIDE = 112
HANDLE_SER_MASK = 0x7FFF
HANDLE_IDX_MASK = 0x1FF

DEG_PER_COUNT = 0.022     # градусов поворота на один каунт мыши

# IPC-копия настроек раз в 25 мс (сталл IPC не должен ронять окно прыжка)
OPTS_REFRESH = 0.025

CURSOR_SHOWING = 0x0001
CURSOR_SUPPRESSED = 0x0002


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("hCursor", ctypes.c_void_p),
        ("ptScreenPos", _POINT),
    ]


def _cursor_visible():
    """True, если системный курсор ВИДЕН (чат/консоль/меню CS2).
    Любой сбой чтения = False: сбой никогда не блокирует бхоп."""
    ci = _CURSORINFO()
    ci.cbSize = ctypes.sizeof(_CURSORINFO)
    try:
        if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(ci)):
            return False
    except Exception:
        return False
    if ci.flags & CURSOR_SUPPRESSED:
        return False
    return bool(ci.flags & CURSOR_SHOWING)


def _move_mouse(dx):
    if dx != 0:
        ctypes.windll.user32.mouse_event(0x0001, int(dx), 0, 0, 0)


def _bezier_emit(counts, intensity):
    """Дробит поворот на подшаги вдоль квадратичной Безье во времени.
    P0=(0,0), P2=(1,1), P1=(c,c): c=0.5 -> тождественно линейно,
    intensity 0..1 -> c 0.5..1.0 -> всё более выраженная S-кривая."""
    counts = int(counts)
    if counts == 0:
        return
    intensity = max(0.0, min(1.0, float(intensity)))
    if intensity <= 0.02:
        _move_mouse(counts)
        return
    steps = 4
    c = 0.5 + 0.5 * intensity
    emitted = 0
    for i in range(1, steps + 1):
        t = i / steps
        y = 2.0 * t * (1.0 - t) * c + t * t
        target = int(round(counts * y))
        d = target - emitted
        if d:
            _move_mouse(d)
            emitted += d
        if i < steps:
            time.sleep(0.001)
    if emitted != counts:
        _move_mouse(counts - emitted)


def _key_down(vk):
    win32api.keybd_event(vk, win32api.MapVirtualKey(vk, 0), 0, 0)


def _key_up(vk):
    win32api.keybd_event(vk, win32api.MapVirtualKey(vk, 0), KEYEVENTF_KEYUP, 0)


def _norm_angle(a):
    while a > 180.0:
        a -= 360.0
    while a < -180.0:
        a += 360.0
    return a


class StrafeEngine:
    def __init__(self):
        self.side = 1
        self.key_vk = 0
        self.state = "idle"      # idle | hold
        self.release_time = 0.0

    def reset(self):
        if self.key_vk:
            _key_up(self.key_vk)
            self.key_vk = 0
        self.state = "idle"

    def update(self, opts, now, vel, view_yaw, sens):
        """Один вызов = один шаг. Возвращает каунты мыши для этого шага."""
        speed = math.hypot(vel.x, vel.y)

        # Слишком медленно или камера смотрит не туда, куда летим - не стрейфим
        if speed < 50.0:
            self.reset()
            return 0
        vel_yaw = math.degrees(math.atan2(vel.y, vel.x))
        if abs(_norm_angle(vel_yaw - view_yaw)) > 60.0:
            self.reset()
            return 0

        if self.state == "hold":
            if now >= self.release_time:
                if self.key_vk:
                    _key_up(self.key_vk)
                    self.key_vk = 0
                self.state = "idle"
            return 0

        # --- новый стрейф-тик ---
        self.side = -self.side
        s = self.side * (-1 if STRAFE_INVERT_KEYS else 1)

        # идеальный угол: окно, где Source даёт ускорение
        a = AIRACCEL * 30.0 * TICK
        ratio = min(1.0, a / max(speed, 1.0))
        theta = math.degrees(math.asin(ratio))
        theta = max(0.5, min(theta, float(opts.get("BhopStrafeMaxAngle", 4.0))))
        # лёгкий человеческий шум: ползунок Безье управляет формой хода мыши
        theta += random.uniform(-0.08, 0.08) * theta

        # камера на theta впереди вектора скорости со стороны стрейфа
        desired = _norm_angle(vel_yaw - s * theta)
        delta_yaw = _norm_angle(view_yaw - desired)
        delta_yaw = max(-3.0, min(3.0, delta_yaw))   # защита от снапов
        counts = int(round(delta_yaw / (DEG_PER_COUNT * sens)))

        vk = VK_D if s == 1 else VK_A
        _key_down(vk)
        self.key_vk = vk

        speed_mult = max(0.3, min(3.0, float(opts.get("BhopStrafeSpeed", 1.0))))
        self.release_time = now + (TICK / speed_mult)
        self.state = "hold"
        return counts


def _read_sensitivity(processHandle, clientBaseAddress, Offsets):
    try:
        sens_ptr = memfuncs.ProcMemHandler.ReadPointer(
            processHandle, clientBaseAddress + Offsets.offset.dwSensitivity)
        if sens_ptr:
            val = memfuncs.ProcMemHandler.ReadFloat(
                processHandle, sens_ptr + Offsets.offset.dwSensitivity_sensitivity)
            if 0.05 <= val <= 10.0:
                return val
    except Exception:
        pass
    return 1.0


class JumpTiming:
    """Главный эдж на приземлении (один тик) + волна пересоздания эджа
    с полупериодом > тика, если провисели на земле дольше тика."""

    def __init__(self):
        self.was_ground = False
        self.landed_ts = 0.0
        self.mode = "idle"
        self.prev_mode = ""
        # Счётчики для дебага: сколько эджей главных/страховочных за серию
        self.cnt_edge = 0
        self.cnt_reedge = 0
        self.cnt_air = 0

    def reset(self, processHandle, jump_addr):
        self.was_ground = False
        self.landed_ts = 0.0
        self.mode = "idle"
        try:
            memfuncs.ProcMemHandler.WriteInt(processHandle, jump_addr, JUMP_IDLE)
        except Exception:
            pass

    def reset_counters(self):
        self.cnt_edge = 0
        self.cnt_reedge = 0
        self.cnt_air = 0

    def update(self, processHandle, jump_addr, space_held, on_ground, now):
        """Возвращает записанное значение. mode - для дебага."""
        self.prev_mode = self.mode

        if not space_held:
            self.was_ground = False
            self.landed_ts = 0.0
            self.mode = "idle"
            memfuncs.ProcMemHandler.WriteInt(processHandle, jump_addr, JUMP_IDLE)
            return JUMP_IDLE

        if not on_ground:
            self.was_ground = False
            self.landed_ts = 0.0
            self.mode = "air"
            self.cnt_air += 1
            memfuncs.ProcMemHandler.WriteInt(processHandle, jump_addr, JUMP_IDLE)
            return JUMP_IDLE

        # На земле, пробел зажат
        if not self.was_ground:
            # Переход air->ground (или зажали пробел стоя на земле):
            # главный эдж немедленно, живёт один тик
            self.landed_ts = now
            self.was_ground = True
            self.mode = "edge"
            self.cnt_edge += 1
            memfuncs.ProcMemHandler.WriteInt(processHandle, jump_addr, JUMP_PRESS)
            return JUMP_PRESS

        dt = now - self.landed_ts
        if dt < EDGE_HOLD:
            # Держим главный эдж до конца тика
            self.mode = "edge"
            memfuncs.ProcMemHandler.WriteInt(processHandle, jump_addr, JUMP_PRESS)
            return JUMP_PRESS

        # Страховка: волна с полупериодом > тика. Фаза от момента приземления.
        # k нечётный -> 65537 (эдж живёт REEDGE_HALF > тик - гарантированно
        # попадает в сборку usercmd), k чётный -> 256 (сброс между эджами).
        k = int((dt - EDGE_HOLD) / REEDGE_HALF)
        if k % 2 == 1:
            self.mode = "reedge"
            self.cnt_reedge += 1
            memfuncs.ProcMemHandler.WriteInt(processHandle, jump_addr, JUMP_PRESS)
            return JUMP_PRESS
        else:
            self.mode = "reedge_low"
            memfuncs.ProcMemHandler.WriteInt(processHandle, jump_addr, JUMP_IDLE)
            return JUMP_IDLE


def Bhop_Update(processHandle, clientBaseAddress, Offsets, opts, engine,
                timing, dbg):
    try:
        hwnd = win32gui.GetForegroundWindow()
        try:
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            title = ""

        dbg["fg"] = title

        if title != "Counter-Strike 2":
            engine.reset()
            return

        # Чат/консоль/меню: курсор виден - идёт ввод текста, пробел это
        # пробел. До любых записей в кнопку прыжка. Fail-open.
        if _cursor_visible():
            engine.reset()
            timing.reset(processHandle, clientBaseAddress + Offsets.offset.ButtonJump)
            dbg["blocked"] = "cursor"
            return

        jump_addr = clientBaseAddress + Offsets.offset.ButtonJump

        localPlayer = memfuncs.ProcMemHandler.ReadPointer(
            processHandle,
            clientBaseAddress + Offsets.offset.dwLocalPlayerController)
        if not localPlayer:
            return

        localPawn = memfuncs.ProcMemHandler.ReadInt(
            processHandle, localPlayer + Offsets.offset.m_hPlayerPawn)
        if not localPawn:
            return

        entityList = memfuncs.ProcMemHandler.ReadPointer(
            processHandle, clientBaseAddress + Offsets.offset.dwEntityList)
        listEntry = memfuncs.ProcMemHandler.ReadPointer(
            processHandle,
            entityList + (ENT_BUCKET_STEP * ((localPawn & HANDLE_SER_MASK) >> 9) + ENT_IDENTITY))
        localPawn = memfuncs.ProcMemHandler.ReadPointer(
            processHandle, listEntry + (ENT_STRIDE * (localPawn & HANDLE_IDX_MASK)))
        if not localPawn:
            return

        flags = memfuncs.ProcMemHandler.ReadInt(
            processHandle, localPawn + Offsets.offset.m_fFlags)
        on_ground = bool(flags & (1 << 0))
        space_held = bool(win32api.GetAsyncKeyState(VK_SPACE) & 0x8000)

        dbg["space"] = int(space_held)
        dbg["ground"] = int(on_ground)

        # === БХОП: главный эдж на приземлении + видимая страховка ===
        w = timing.update(processHandle, jump_addr, space_held, on_ground,
                          time.perf_counter())
        dbg["w"] = w
        dbg["mode"] = timing.mode
        dbg["mode_changed"] = timing.mode != timing.prev_mode
        dbg["cnt_e"] = timing.cnt_edge
        dbg["cnt_r"] = timing.cnt_reedge

        # === АВТОСТРЕЙФ ===
        if not opts.get("EnableBhopAutoStrafe", False):
            engine.reset()
            return

        if not space_held or on_ground:
            engine.reset()
            return

        vel = memfuncs.ProcMemHandler.ReadVec(
            processHandle, localPawn + Offsets.offset.m_vecVelocity)
        view_yaw = memfuncs.ProcMemHandler.ReadFloat(
            processHandle,
            clientBaseAddress + Offsets.offset.dwViewAngles + 4)
        sens = _read_sensitivity(processHandle, clientBaseAddress, Offsets)

        counts = engine.update(opts, time.perf_counter(), vel, view_yaw, sens)
        if counts:
            _bezier_emit(counts, opts.get("BhopBezierIntensity", 0.5))

    except Exception as e:
        dbg["err"] = repr(e)
        logutil.debug(f"Bhop error: {e}")


def BhopThreadFunction(Options, Offsets):
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    engine = StrafeEngine()
    timing = JumpTiming()

    local_opts = dict(Options.items())
    opts_ts = time.time()

    dbg = {}
    dbg_ts = 0.0

    while True:
        try:
            now = time.time()
            if now - opts_ts >= OPTS_REFRESH:
                local_opts = dict(Options.items())
                opts_ts = now

            if not local_opts.get("EnableBhop", False):
                engine.reset()
                time.sleep(0.01)
                continue

            h = connector.ensure_process()
            client = connector.ensure_module("client.dll")

            dbg.clear()
            Bhop_Update(h, client, Offsets, local_opts, engine, timing, dbg)

            if local_opts.get("BhopDebug", False):
                now2 = time.time()
                active = dbg.get("space") == 1 or dbg.get("mode") in ("edge", "reedge", "reedge_low")
                # Пока прыгаем: печать на каждую смену режима (реальная
                # хронология тайминга) и не реже раза в 100 мс.
                # Вне прыжков - раз в секунду (пульс).
                if active:
                    if dbg.get("mode_changed") or (now2 - dbg_ts) >= 0.1:
                        dbg_ts = now2
                        print(
                            f"[bhop] space={dbg.get('space','-')} ground={dbg.get('ground','-')} "
                            f"w={dbg.get('w','-')} mode={dbg.get('mode','-')} "
                            f"edges={dbg.get('cnt_e',0)}/{dbg.get('cnt_r',0)}",
                            flush=True,
                        )
                elif (now2 - dbg_ts) >= 1.0:
                    dbg_ts = now2
                    fg = dbg.get("fg", "?")
                    fg_short = fg if len(fg) <= 24 else fg[:21] + "..."
                    print(
                        f"[bhop] fg='{fg_short}' blocked={dbg.get('blocked','-')} "
                        f"space={dbg.get('space','-')} ground={dbg.get('ground','-')}",
                        flush=True,
                    )

            time.sleep(0.001)
        except Exception as exc:
            logutil.debug(f"Bhop thread exception: {exc}")
            connector.invalidate()
            time.sleep(0.01)
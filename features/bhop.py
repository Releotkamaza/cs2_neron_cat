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
KEYEVENTF_KEYUP = 0x0002

AIRACCEL = 12.0          # sv_airaccelerate
TICK = 1.0 / 64.0        # тик сервера
STRAFE_INVERT_KEYS = False  # True, если разгонит назад/вбок (зеркалит пару)


def _move_mouse(dx):
    if dx != 0:
        ctypes.windll.user32.mouse_event(0x0001, int(dx), 0, 0, 0)


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
        # "человеческий" шум
        theta += random.uniform(-0.15, 0.15) * theta * float(opts.get("BhopBezierIntensity", 0.5))

        # камера на theta впереди вектора скорости со стороны стрейфа
        desired = _norm_angle(vel_yaw - s * theta)
        delta_yaw = _norm_angle(view_yaw - desired)
        delta_yaw = max(-3.0, min(3.0, delta_yaw))   # защита от снапов
        counts = int(round(delta_yaw / (0.022 * sens)))

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


def Bhop_Update(processHandle, clientBaseAddress, Offsets, opts, engine):
    try:
        hwnd = win32gui.GetForegroundWindow()
        try:
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            title = ""

        jump_addr = clientBaseAddress + Offsets.offset.ButtonJump

        if title != "Counter-Strike 2":
            engine.reset()
            memfuncs.ProcMemHandler.WriteInt(processHandle, jump_addr, 256)
            return

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
            entityList + (0x8 * ((localPawn & 0x7FFF) >> 9) + 0x10))
        localPawn = memfuncs.ProcMemHandler.ReadPointer(
            processHandle, listEntry + (112 * (localPawn & 0x1FF)))
        if not localPawn:
            return

        flags = memfuncs.ProcMemHandler.ReadInt(
            processHandle, localPawn + Offsets.offset.m_fFlags)
        on_ground = bool(flags & (1 << 0))
        space_held = bool(win32api.GetAsyncKeyState(0x20) & 0x8000)

        # === БХОП ===
        if space_held:
            if on_ground:
                memfuncs.ProcMemHandler.WriteInt(processHandle, jump_addr, 65537)
            else:
                memfuncs.ProcMemHandler.WriteInt(processHandle, jump_addr, 256)
        else:
            memfuncs.ProcMemHandler.WriteInt(processHandle, jump_addr, 256)

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
            _move_mouse(counts)

    except Exception as e:
        logutil.debug(f"Bhop error: {e}")


def BhopThreadFunction(Options, Offsets):
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    engine = StrafeEngine()

    while True:
        try:
            if not Options.get("EnableBhop", False):
                engine.reset()
                time.sleep(0.01)
                continue

            h = connector.ensure_process()
            client = connector.ensure_module("client.dll")
            local_opts = dict(Options.items())
            Bhop_Update(h, client, Offsets, local_opts, engine)
            time.sleep(0.001)
        except Exception as exc:
            logutil.debug(f"Bhop thread exception: {exc}")
            connector.invalidate()
            time.sleep(0.01)
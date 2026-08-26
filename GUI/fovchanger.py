from functions import memfuncs
from functions import logutil
from functions.process_watcher import ProcessConnector
import time

DEFAULT_FOV = 90
# После последнего скоупа не трогаем FOV ещё ~секунду, чтобы не бороться
# с анимацией отдачи прицела (игра сама дёргает m_iFOV к 90 после выстрела).
SCOPE_GRACE_SEC = 1.3


def FovChangerThreadFunction(Options, Offsets):
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    last_fov_written = None
    last_scoped_time = 0.0

    def _clamp(v, lo, hi):
        try:
            return max(lo, min(hi, int(v)))
        except Exception:
            return lo

    while True:
        try:
            process = connector.ensure_process()
            client = connector.ensure_module("client.dll")

            enabled = bool(Options.get("EnableFovChanger", False))

            local_pawn = memfuncs.ProcMemHandler.ReadPointer(process, client + Offsets.offset.dwLocalPlayerPawn)
            if not local_pawn:
                last_fov_written = None
                last_scoped_time = 0.0
                time.sleep(0.05)
                continue

            camera_services = memfuncs.ProcMemHandler.ReadPointer(process, local_pawn + Offsets.offset.m_pCameraServices)
            if not camera_services:
                time.sleep(0.01)
                continue

            now = time.time()

            if not enabled:
                # Выключено: один раз возвращаем дефолт и не трогаем
                if last_fov_written is not None:
                    try:
                        memfuncs.ProcMemHandler.WriteInt(process, camera_services + Offsets.offset.m_iFOV, DEFAULT_FOV)
                    except Exception:
                        pass
                    last_fov_written = None
                time.sleep(0.05)
                continue

            desired_fov = _clamp(Options.get("FovChangeSize", 90), 50, 170)

            try:
                current_fov = memfuncs.ProcMemHandler.ReadInt(process, camera_services + Offsets.offset.m_iFOV)
            except Exception:
                current_fov = desired_fov

            # Реальный скоуп = значение 1..89, не равное нашему
            scoped_now = (1 <= current_fov < 90) and (current_fov != desired_fov)
            if scoped_now:
                last_scoped_time = now

            # В скоупе ИЛИ сразу после него (анимация выстрела) - НЕ пишем,
            # чтобы не мигать. В простое - держим свой FOV.
            in_scope_window = (now - last_scoped_time) < SCOPE_GRACE_SEC

            if not in_scope_window:
                try:
                    memfuncs.ProcMemHandler.WriteInt(process, camera_services + Offsets.offset.m_iFOV, desired_fov)
                    last_fov_written = desired_fov
                except Exception:
                    pass

            time.sleep(0.01)
        except Exception as exc:
            logutil.debug(f"[fovchanger] loop exception: {exc}")
            connector.invalidate()
            time.sleep(0.01)
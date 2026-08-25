from functions import memfuncs
from functions import logutil
from functions.process_watcher import ProcessConnector
import time

# Максимальная яркость вспышки: 255 = как обычно, 0 = вспышка не видна
FLASH_ALPHA_NORMAL = 255.0
FLASH_ALPHA_BLOCKED = 0.0


def AntiFlashThreadFunction(Options, Offsets):
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    # Помним предыдущее состояние, чтобы один раз вернуть яркость при выключении
    last_enabled = None

    while True:
        try:
            process = connector.ensure_process()
            client = connector.ensure_module("client.dll")

            enabled = bool(Options.get("EnableAntiFlashbang", False))

            local_pawn = memfuncs.ProcMemHandler.ReadPointer(
                process, client + Offsets.offset.dwLocalPlayerPawn
            )
            if not local_pawn:
                last_enabled = None
                time.sleep(0.01)
                continue

            addr = local_pawn + Offsets.offset.m_flFlashMaxAlpha

            if enabled:
                # Постоянно держим 0: игра каждый тик пытается вернуть 255,
                # поэтому разовая запись (как было раньше) не работала.
                try:
                    memfuncs.ProcMemHandler.WriteFloat(process, addr, FLASH_ALPHA_BLOCKED)
                except Exception:
                    pass
                last_enabled = True
            else:
                # После выключения один раз возвращаем нормальную яркость
                if last_enabled is not False:
                    try:
                        memfuncs.ProcMemHandler.WriteFloat(process, addr, FLASH_ALPHA_NORMAL)
                    except Exception:
                        pass
                last_enabled = False

            time.sleep(0.005)

        except Exception as exc:
            logutil.debug(f"[antiflash] loop exception: {exc}")
            connector.invalidate()
            time.sleep(0.01)
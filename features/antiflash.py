from functions import memfuncs
from functions import logutil
from functions.process_watcher import ProcessConnector
import time

# Максимальная яркость вспышки: 255 = как обычно, 0 = вспышка не видна.
# Игровые константы, не оффсеты.
FLASH_ALPHA_NORMAL = 255.0
FLASH_ALPHA_BLOCKED = 0.0

# Период основного цикла: 5 мс = 200 Гц. Игра каждый тик (64 Гц) пытается
# вернуть 255, поэтому держать 0 нужно чаще тика.
LOOP_SLEEP = 0.005
# Пауза, когда антифлеш выключен и яркость уже нормализована: нет смысла
# 200 раз в секунду читать павн ради "ничего не делать"
IDLE_SLEEP = 0.05


def AntiFlashThreadFunction(Options, Offsets):
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    # Помним предыдущее состояние, чтобы один раз вернуть яркость при выключении
    last_enabled = None

    while True:
        try:
            process = connector.ensure_process()
            client = connector.ensure_module("client.dll")

            enabled = bool(Options.get("EnableAntiFlashbang", False))

            # Быстрый путь: выключено и нормализовано - спим дольше без чтений памяти
            if not enabled and last_enabled is False:
                time.sleep(IDLE_SLEEP)
                continue

            local_pawn = memfuncs.ProcMemHandler.ReadPointer(
                process, client + Offsets.offset.dwLocalPlayerPawn
            )
            if not local_pawn:
                last_enabled = None
                time.sleep(0.01)
                continue

            addr = local_pawn + Offsets.offset.m_flFlashMaxAlpha

            # Перепроверка павна ПЕРЕД записью: между чтением и записью павн
            # может освободиться (смерть/загрузка карты/конец матча), запись
            # тогда попадает в переиспользованную память. Та же страховка,
            # что в fovchanger/bhop.
            def _pawn_alive():
                try:
                    return memfuncs.ProcMemHandler.ReadPointer(
                        process, client + Offsets.offset.dwLocalPlayerPawn
                    ) == local_pawn
                except Exception:
                    return False

            if enabled:
                # Постоянно держим 0: игра каждый тик пытается вернуть 255,
                # поэтому разовая запись не работает.
                if _pawn_alive():
                    try:
                        memfuncs.ProcMemHandler.WriteFloat(process, addr, FLASH_ALPHA_BLOCKED)
                    except Exception:
                        pass
                last_enabled = True
            else:
                # После выключения один раз возвращаем нормальную яркость
                if last_enabled is not False:
                    if _pawn_alive():
                        try:
                            memfuncs.ProcMemHandler.WriteFloat(process, addr, FLASH_ALPHA_NORMAL)
                        except Exception:
                            pass
                    last_enabled = False

            time.sleep(LOOP_SLEEP)

        except Exception as exc:
            logutil.debug(f"[antiflash] loop exception: {exc}")
            connector.invalidate()
            time.sleep(0.01)
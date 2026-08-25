from pypresence import Presence
import time

def DiscordRpcThread(Options):
    presence = None
    connected = False
    last_update_time = 0.0
    
    while True:
        try:
            # Проверяем, включён ли RPC
            if not Options.get("EnableDiscordRPC", True):
                if connected and presence is not None:
                    try:
                        presence.close()
                    except Exception:
                        pass
                    presence = None
                    connected = False
                time.sleep(5)
                continue
            
            # Подключаемся, если ещё не подключены
            if not connected:
                if presence is None:
                    presence = Presence(1431365962321629185)
                try:
                    presence.connect()
                    connected = True
                except Exception:
                    presence = None
                    time.sleep(10)
                    continue
            
            # Обновляем статус раз в 15 секунд (не каждую секунду)
            now = time.time()
            if now - last_update_time >= 15.0:
                try:
                    presence.update(
                        state="cs2_neron_external",
                        details="External CS2 Cheat — ESP · Aimbot · Triggerbot",
                        start=int(time.time()),
                        large_image="cs2_neron",
                        large_text="cs2_neron_external",
                        small_image="khorami",
                        small_text="khorami.dev",
                        buttons=[{'label': 'Project page', 'url': 'https://github.com/SadraKhorami/cs2_neron_external'}]
                    )
                    last_update_time = now
                except Exception:
                    # Если обновление упало - переподключаемся
                    try:
                        presence.close()
                    except Exception:
                        pass
                    presence = None
                    connected = False
            
            time.sleep(1)
            
        except Exception:
            # Закрываем старое соединение перед переподключением
            if presence is not None:
                try:
                    presence.close()
                except Exception:
                    pass
                presence = None
                connected = False
            time.sleep(15)
from dataclasses import dataclass
import os
import json


class OffsetError(RuntimeError):
    """Отсутствует оффсет в дампе. Раньше здесь был print + exit(),
    молча убивавший процесс; теперь исключение с внятной причиной."""


@dataclass
class Offset:
    dwViewMatrix: int
    dwLocalPlayerPawn: int
    dwEntityList: int
    dwLocalPlayerController: int
    dwViewAngles: int
    dwGameRules: int
    dwSensitivity_sensitivity: int
    dwSensitivity: int
    ButtonJump: int
    ButtonLeft: int
    ButtonRight: int
    m_pMovementServices: int
    m_flLeftMove: int
    m_hViewEntity: int
    m_hObserverPawn: int
    m_hPlayerPawn: int
    m_iHealth: int
    m_lifeState: int
    m_iTeamNum: int
    m_vOldOrigin: int
    m_vecAbsOrigin: int
    m_pGameSceneNode: int
    m_modelState: int
    m_nodeToWorld: int
    m_sSanitizedPlayerName: int
    m_iIDEntIndex: int
    m_flFlashMaxAlpha: int
    m_fFlags: int
    m_iFOV: int
    m_pCameraServices: int
    m_bIsScoped: int
    m_vecViewOffset: int
    m_entitySpottedState: int
    m_bSpotted: int
    m_bBombPlanted: int
    m_iShotsFired: int
    m_pAimPunchServices: int
    m_predictableBaseAngle: int
    m_bSpottedByMask: int
    m_vecVelocity: int
    m_pObserverServices: int
    m_iObserverMode: int
    m_hObserverTarget: int
    m_bMatchWaitingForResume: int
    m_bGameRestart: int
    m_iDesiredFOV: int

    # ВАЖНО: m_boneArray удалён - был единственным хардкодом (128) и никем
    # не читался. Костный массив во всей кодовой базе вычисляется как
    # m_modelState + 0x80 (см. BONE_ARRAY_OFF в features/esp/core.py):
    # это структурная константа layout движка, в дампах её нет.


class Client:
    def __init__(self, prefer_local=True):
        # 1. Локальный дамп output/ (батник регенерит его при каждом запуске)
        if prefer_local and self._try_load_from_file():
            return

        # 2. Фоллбек: свежий дамп с a2x/cs2-dumper (например, если дамп
        #    не снялся, потому что игра была закрыта)
        if self._try_load_from_url():
            return

        raise OffsetError(
            "Не удалось загрузить оффсеты ни локально (output/), ни с сервера. "
            "Запусти CS2 и прогони cs2-dumper -f json в папке чита."
        )

    def _try_load_from_url(self):
        # Ленивый импорт: requests нужен только при реальном фоллбеке
        import requests
        try:
            self.offsets = self._get_json_from_url(
                'https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json',
                requests)
            self.clientdll = self._get_json_from_url(
                'https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json',
                requests)
            self.buttons = self._get_json_from_url(
                'https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/buttons.json',
                requests)
            return True
        except Exception as e:
            print(f'[-] Ошибка при получении оффсетов по URL: {e}', flush=True)
            return False

    def _get_json_from_url(self, url, requests):
        # Таймаут обязателен: без него сетевой подвис вешал старт навсегда
        return requests.get(url, timeout=10).json()

    def _try_load_from_file(self):
        try:
            # Путь от файла модуля, не от cwd: запуск из другой директории
            # ("python C:\neron_cat\main.py") больше не ломает поиск output/
            base_path = os.path.abspath(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'output'))
            self.offsets = self._load_json_from_file(base_path, 'offsets.json')
            self.clientdll = self._load_json_from_file(base_path, 'client_dll.json')
            self.buttons = self._load_json_from_file(base_path, 'buttons.json')
            return True
        except Exception:
            # Фоллбек на URL молча: это штатная ситуация, когда дамп не снялся
            return False

    def _load_json_from_file(self, base_path, filename):
        with open(os.path.join(base_path, filename), 'r', encoding='utf-8') as f:
            return json.load(f)

    def offset(self, a):
        return self._get_value_from_dict(self.offsets, ['client.dll', a])

    def get(self, a, b):
        try:
            return self.clientdll["client.dll"]['classes'][a]['fields'][b]
        except KeyError:
            raise OffsetError(
                f"Поле {a}.{b} не найдено в client_dll.json - обнови output/ "
                f"(запусти CS2, потом cs2-dumper -f json в папке чита)"
            )

    def button(self, a):
        return self._get_value_from_dict(self.buttons, ['client.dll', a])

    def _get_value_from_dict(self, data, keys):
        try:
            for key in keys:
                data = data[key]
            return data
        except KeyError:
            raise OffsetError(
                f"Ключ {' -> '.join(keys)} не найден в offsets.json/buttons.json - "
                f"обнови output/"
            )


def _safe_offset(oc: Client, key: str) -> int:
    """Возвращает оффсет или 0, если ключа нет в дампе.
    Нужно для полей, которые могут отсутствовать в актуальных оффсетах,
    но код их ожидает (например, dwSensitivity)."""
    try:
        return oc.offset(key)
    except OffsetError:
        return 0


def _safe_schema(oc: Client, class_name: str, field: str) -> int:
    """Оффсет поля схемы или 0, если класса/поля нет в дампе."""
    try:
        return oc.get(class_name, field)
    except OffsetError:
        return 0


def get_offsets() -> Offset:
    oc = Client(prefer_local=True)
    return Offset(
        dwViewMatrix=oc.offset("dwViewMatrix"),
        dwLocalPlayerPawn=oc.offset("dwLocalPlayerPawn"),
        dwEntityList=oc.offset("dwEntityList"),
        dwLocalPlayerController=oc.offset("dwLocalPlayerController"),
        dwViewAngles=oc.offset("dwViewAngles"),
        dwGameRules=oc.offset("dwGameRules"),
        dwSensitivity_sensitivity=_safe_offset(oc, "dwSensitivity_sensitivity"),
        dwSensitivity=_safe_offset(oc, "dwSensitivity"),
        ButtonJump=oc.button("jump"),
        ButtonLeft=oc.button("left"),
        ButtonRight=oc.button("right"),
        m_hObserverPawn=oc.get("CCSPlayerController", "m_hObserverPawn"),
        m_hViewEntity=oc.get("CPlayer_CameraServices", "m_hViewEntity"),
        m_hPlayerPawn=oc.get("CCSPlayerController", "m_hPlayerPawn"),
        m_iHealth=oc.get("C_BaseEntity", "m_iHealth"),
        m_lifeState=oc.get("C_BaseEntity", "m_lifeState"),
        m_iTeamNum=oc.get("C_BaseEntity", "m_iTeamNum"),
        m_vOldOrigin=oc.get("C_BasePlayerPawn", "m_vOldOrigin"),
        m_vecAbsOrigin=_safe_schema(oc, "CGameSceneNode", "m_vecAbsOrigin"),
        m_pGameSceneNode=oc.get("C_BaseEntity", "m_pGameSceneNode"),
        m_modelState=oc.get("CSkeletonInstance", "m_modelState"),
        m_nodeToWorld=oc.get("CGameSceneNode", "m_nodeToWorld"),
        m_sSanitizedPlayerName=oc.get("CCSPlayerController", "m_sSanitizedPlayerName"),
        m_iIDEntIndex=oc.get("C_CSPlayerPawn", "m_iIDEntIndex"),
        m_flFlashMaxAlpha=oc.get("C_CSPlayerPawnBase", "m_flFlashMaxAlpha"),
        m_fFlags=oc.get("C_BaseEntity", "m_fFlags"),
        m_iFOV=oc.get("CCSPlayerBase_CameraServices", "m_iFOV"),
        m_pCameraServices=oc.get("C_BasePlayerPawn", "m_pCameraServices"),
        m_bIsScoped=oc.get("C_CSPlayerPawn", "m_bIsScoped"),
        m_vecViewOffset=oc.get("C_BaseModelEntity", "m_vecViewOffset"),
        m_entitySpottedState=oc.get("C_CSPlayerPawn", "m_entitySpottedState"),
        m_bSpotted=oc.get("EntitySpottedState_t", "m_bSpotted"),
        m_bBombPlanted=oc.get("C_CSGameRules", "m_bBombPlanted"),
        m_iShotsFired=oc.get("C_CSPlayerPawn", "m_iShotsFired"),
        m_pAimPunchServices=oc.get("C_CSPlayerPawn", "m_pAimPunchServices"),
        m_predictableBaseAngle=oc.get("CCSPlayer_AimPunchServices", "m_predictableBaseAngle"),
        m_bSpottedByMask=oc.get("EntitySpottedState_t", "m_bSpottedByMask"),
        m_vecVelocity=oc.get("C_BaseEntity", "m_vecVelocity"),
        m_pMovementServices=oc.get("C_BasePlayerPawn", "m_pMovementServices"),
        m_flLeftMove=oc.get("CPlayer_MovementServices", "m_flLeftMove"),
        m_pObserverServices=oc.get("C_BasePlayerPawn", "m_pObserverServices"),
        m_iObserverMode=oc.get("CPlayer_ObserverServices", "m_iObserverMode"),
        m_hObserverTarget=oc.get("CPlayer_ObserverServices", "m_hObserverTarget"),
        m_bMatchWaitingForResume=oc.get("C_CSGameRules", "m_bMatchWaitingForResume"),
        m_bGameRestart=oc.get("C_CSGameRules", "m_bGameRestart"),
        m_iDesiredFOV=oc.get("CBasePlayerController", "m_iDesiredFOV"),
    )
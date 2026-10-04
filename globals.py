import os

import win32api

from ext import offsets

# Разрешение экрана для world_to_screen и оверлея
SCREEN_WIDTH = win32api.GetSystemMetrics(0)
SCREEN_HEIGHT = win32api.GetSystemMetrics(1)

# Оффсеты грузятся ОДИН раз при импорте: local output/ -> URL-фоллбек.
GAME_OFFSETS = offsets.get_offsets()

# Путь от файла модуля, не от cwd: запуск "python C:\neron_cat\main.py"
# из другой директории больше не уводит settings.json в сторону
SAVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

# ==================== Дефолтные настройки ====================
# Иерархия цветов рендера (features/esp/core.py):
#   Box:     EnableBoxCustomColor -> Box_color; иначе team (visible-white);
#   Tracer:  EnableTracerCustomColor -> Tracer_color; иначе team;
#   HP Bar:  ESP_HealthSyncBar -> по HP; иначе EnableHPBarCustomColor ->
#            HPBar_color; иначе team;
#   Skeleton: ESP_HealthSyncSkeleton -> по HP; иначе team.
CHEAT_SETTINGS = {
    "EnableAntiFlashbang": False,
    "EnableAutoAccept": False,
    "EnableFovChanger": False,
    "FovChangeSize": 90,

    "EnableAimbot": True,
    "EnableAimbotPrediction": True,
    "EnableAimbotTeamCheck": False,
    "EnableAimbotVisibilityCheck": False,
    "AimbotFOV": 75,
    "AimbotSmoothing": 1,
    "AimPosition": "Head",
    "AimbotKey": 6,

    "EnableRecoilControl": False,
    "RecoilControlSmoothing": 1.0,

    "EnableTriggerbot": True,
    "TriggerbotSpeedThreshold": 5.0,
    "TriggerbotRequireGround": True,
    "TriggerbotWallbang": False,
    "EnableTriggerbotTeamCheck": False,

    "EnableESP": True,
    "EnableESPTeamCheck": False,
    "EnableESPSkeletonRendering": True,
    "EnableESPBoxRendering": False,
    "EnableESPTracerRendering": False,
    "EnableESPNameText": False,
    "EnableESPWeaponText": False,
    "EnableESPHealthBarRendering": True,
    "EnableESPHealthText": False,
    "EnableESPDistanceText": False,

    "EnableESPBombTimer": False,

    # Цвета: базовая окраска по отношению к локальному игроку
    "Enemy_color": "#FF6A5A",
    "Teammate_color": "#4DA2FF",
    # Per-element кастом (галочка "Свой цвет" + пикер во вкладке "Цвета")
    "EnableBoxCustomColor": False,
    "Box_color": "#FF6A5A",
    "EnableTracerCustomColor": False,
    "Tracer_color": "#FFD24D",
    "EnableHPBarCustomColor": False,
    "HPBar_color": "#FF6A5A",
    # Толщина трейсеров (слайдер в "Визуал и толщина")
    "ESP_TracerThickness": 1.5,
    # Компенсация отставания ESP вперёд по скорости (мс; слайдер там же).
    # Аимка (пинг ~0): ~50 достаточно. Отстаёт бокс в матче - поднять до
    # 100-150; "перелетает" впереди модели - снизить до 0-30.
    "ESP_ExtrapolateMs": 0,

    "FOV_color": "#FFFFFF",            # GUI-ONLY: пикер в "Цветах", рендерер не читает

    # Точка-прицел при ноускопе (weapons, скрывающие встроенный прицел):
    # читает features/noscopedot.py.
    "EnableNoScopeDot": False,
    "NoScopeDot_color": "#FFFFFF",
    "NoScopeDot_radius": 5.0,          # радиус в px (1-12), слайдер во вкладке "Прицел"
    "NoScopeDot_opacity": 80,          # непрозрачность в % (10-100), слайдер во вкладке "Прицел"

    # Кастомный прицел (features/customcrosshair.py, вкладка "Прицел")
    "EnableCustomCrosshair": False,
    "EnableNoScopeDotSeparate": False,  # точка для снайперок, кастомный - для остального
    "Crosshair_Style": "Обычный",       # "Обычный" | "T-образный"
    "Crosshair_color": "#00FF00",
    "Crosshair_Opacity": 100,           # % (10-100)
    "Crosshair_Thickness": 2.0,         # px (1-10)
    "Crosshair_Length": 8.0,            # px (1-30)
    "Crosshair_Gap": 4.0,               # px (0-20)
    "Crosshair_Outline": True,

    "EnableBhop": False,
    "EnableBhopAutoStrafe": False,
    "BhopStrafeMaxAngle": 4.0,
    "BhopStrafeMinAngle": 1.0,         # GUI-ONLY: StrafeEngine не читает
    "BhopBezierIntensity": 0.5,
    "BhopStrafeSpeed": 1.0,
    "BhopMinAngleThreshold": 1.5,      # GUI-ONLY: StrafeEngine не читает
    "BhopMinAngleCorrection": 3.0,     # GUI-ONLY: StrafeEngine не читает
    "BhopRandomDelayMin": 2,           # GUI-ONLY: рандомизация живёт в gameinput
    "BhopRandomDelayMax": 8,           # GUI-ONLY: рандомизация живёт в gameinput

    "EnableShowSpectators": True,
    "EnableNoSmoke": False,

    "EnableNoScopeOverlay": False,
    "NoScopeActive": False,            # служебный флаг fovchanger, не настройка

    "ESP_HealthSyncSkeleton": True,
    "ESP_HealthSyncBar": True,
    "ESP_SkeletonThicknessScale": 1.0,
    "ESP_BoxThicknessScale": 1.0,
    "ESP_HealthBarThicknessScale": 1.0,

    "ESP_VisibleCheckBox": False,
}

# Мост "аимбот контролирует отдачу" - читается rcs.py на каждом такте.
# НЕ УДАЛЯТЬ, пока живёт текущий aimbot.py (он этот глобал ставит).
# Уйдёт вместе с перезаписью аимбота.
RCS_CTRL_BY_AIMBOT = False

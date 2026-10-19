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

    # Triggerbot: мультипозиционный режим (features/triggerbot.py читает
    # TriggerbotMode). EnableTriggerbot/TriggerbotWallbang - производные,
    # синхронизируются GUI ради старых конфигов и legacy-кода.
    "TriggerbotMode": "SadraKhorami",   # "Выкл" | "SadraKhorami" | "Releotkamaza"
    "EnableTriggerbot": True,
    "TriggerbotSpeedThreshold": 5.0,
    "TriggerbotRequireGround": True,
    "TriggerbotWallbang": False,
    "EnableTriggerbotTeamCheck": True,
    # Проверка видимости для триггербота (учитывает дым).
    # По умолчанию выкл — чтобы не ломать стрельбу до первой настройки.
    "EnableTriggerbotVisibilityCheck": False,

    # Triggerbot: задержка (реакция) перед выстрелом. Читает
    # features/triggerbot.py -> resolve_trigger_delay() (в том же файле).
    # TriggerbotDelayMode:
    #   "static"   - фиксированная TriggerbotDelayStatic, мс (ползунок 0..500);
    #   "range"    - случайная в [TriggerbotDelayMin, TriggerbotDelayMax], мс;
    #   "distance" - по таблице TriggerbotDelayTable: строка
    #                [дист_от, дист_до, задержка_от_мс, задержка_до_мс];
    #                задержка выбирается случайно внутри строки. Дефолт
    #                повторяет прежнюю жёсткую кривую gameinput
    #                (TRIGGER_DELAY_STEPS), поведение триггера не меняется.
    "TriggerbotDelayMode": "distance",   # "static" | "range" | "distance"
    "TriggerbotDelayStatic": 50.0,       # мс, 0..500
    "TriggerbotDelayMin": 10.0,          # мс, 0..500
    "TriggerbotDelayMax": 30.0,          # мс, 0..500
    "TriggerbotDelayTable": [
        [0.0, 250.0, 20.0, 30.0],
        [250.0, 500.0, 15.0, 25.0],
        [500.0, 800.0, 10.0, 20.0],
        [800.0, 1200.0, 6.0, 10.0],
        [1200.0, 2000.0, 4.0, 8.0],
        [2000.0, 100000.0, 2.0, 6.0],
    ],
    # Минимальный интервал между выстрелами (мс), ползунок 0..5000.
    "TriggerbotShotDelayMs": 400.0,

    # Glow (обводка персонажей, так называемый glow)
    "EnableGlow": False,
    "ToggleKey_EnableGlow": 0,
    "GlowMode": "Team",  # "Team" | "Health" | "Custom"
    "GlowShowEnemies": True,
    "GlowShowAllies": True,
    "GlowEnemyColor": "#FF5555",
    "GlowAllyColor": "#55AAFF",

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
    # Мультипозиционный ноускоп-прицел: "Выкл" | "Кастомный" | "Точка".
    # Заменяет пару bool-галочек. EnableNoScopeDot/EnableNoScopeDotSeparate
    # остаются производными (синхронизирует GUI) ради старых конфигов.
    "NoScopeCrosshairMode": "Выкл",
    "EnableNoScopeDotSeparate": False,  # производный: mode in ("Кастомный", "Точка")
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
    "EnableNoScopeCustomColor": False, # свой цвет креста+круга скопа (вкл -> чёрный)
    "NoScope_color": "#000000",        # общий цвет креста и круга-границы скопа
    "NoScopeThickness": 1.0,           # общая толщина линий креста и круга (1.0-5.0)

    "ESP_HealthSyncSkeleton": True,
    "ESP_HealthSyncBar": True,
    "ESP_SkeletonThicknessScale": 1.0,
    "ESP_BoxThicknessScale": 1.0,
    "ESP_HealthBarThicknessScale": 1.0,

    "ESP_VisibleCheckBox": False,

    # Панель "Активные функции" (вкладка GUI, оверлей features/active_list.py)
    "EnableActiveList": True,         # мастер-галочка: панель работает/выключена
    "ToggleKey_EnableActiveList": 0,  # мастер-ключ показа/скрытия (0 = выкл)
    "ActiveListPosX": 70,         # позиция окна X, % ширины экрана
    "ActiveListPosY": 4,          # позиция окна Y, % высоты экрана
    "ActiveListVisible": False,   # видимость окна (переключает мастер-ключ)
    "ListShow_EnableESP": True,
    "ListShow_TriggerbotMode": True,
    "ListShow_EnableAimbot": True,
    "ListShow_EnableRecoilControl": True,
    "ListShow_EnableBhop": True,
    "ListShow_EnableAntiFlashbang": True,
    "ListShow_EnableAutoAccept": True,
    "ListShow_EnableFovChanger": True,
    "ListShow_EnableNoSmoke": True,
    "ListShow_EnableNoScopeOverlay": True,
    "ListShow_NoScopeCrosshairMode": True,
    "ListShow_EnableESPBombTimer": True,
    "ListShow_EnableShowSpectators": True,

    # Позиции панелей оверлея (вкладка GUI «Прочее»), та же семантика, что у
    # ActiveListPosX/Y: X/Y в % — окно ЦЕЛИКОМ (0 = левый/верхний край,
    # 100 = правый/нижний). Дефолты повторяют прежние жёсткие позиции.
    "BombTimerPosX": 2,           # было x=28 при 1920 (карточка 236)
    "BombTimerPosY": 33,          # было y=(H-card_h)/3
    "SpectatorPosX": 98,          # было x=W-block_w-24 (правый край)
    "SpectatorPosY": 50,          # было по центру по вертикали
}

# Мост "аимбот контролирует отдачу" - читается rcs.py на каждом такте.
# НЕ УДАЛЯТЬ, пока живёт текущий aimbot.py (он этот глобал ставит).
# Уйдёт вместе с перезаписью аимбота.
RCS_CTRL_BY_AIMBOT = False

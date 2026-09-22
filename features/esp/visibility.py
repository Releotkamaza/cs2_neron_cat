from functions import memfuncs

# ==================== Структурные константы ====================
# В дампах cs2-dumper их нет по определению. Те же значения использует
# вся кодовая база (esp/core, aimbot, triggerbot, nosmoke, bhop).
ENT_BUCKET_STEP = 0x8      # шаг бакетов entity list
ENT_IDENTITY = 0x10        # смещение CEntityIdentity в слоте
ENT_STRIDE = 112           # stride слота (контроллеры и павны)
HANDLE_SER_MASK = 0x7FFF   # серийно-индексные биты handle
HANDLE_IDX_MASK = 0x1FF    # индекс внутри бакета
SPOTTED_BIT_OFFSET = 1     # бит локального игрока в маске = local_index - 1

# Слот локального контроллера константен всю карту, меняется только сам
# контроллер (смена карты/реконнект). Кэш по адресу контроллера: 2 RPM на
# промахе (раз за карту), 0 RPM на хите. Раньше - до 128 RPM на КАЖДЫЙ
# проход сканера (list_entry перечитывался на каждой итерации цикла).
_local_index_cache = {"ctrl": 0, "idx": 0}


def resolve_local_index(processHandle, EntityList, local_controller_addr) -> int:
    """Индекс слота локального контроллера в entity list (для бита в маске)."""
    if _local_index_cache["ctrl"] == local_controller_addr and _local_index_cache["idx"]:
        return _local_index_cache["idx"]
    try:
        # Слоты 1..64 живут в бакете 0 (i >> 9 == 0): list_entry - одно чтение
        list_entry = memfuncs.ProcMemHandler.ReadPointer(
            processHandle, EntityList + ENT_IDENTITY)
        if not list_entry:
            return 0
        for i in range(1, 65):
            controller = memfuncs.ProcMemHandler.ReadPointer(
                processHandle, list_entry + ENT_STRIDE * i)
            if controller == local_controller_addr:
                _local_index_cache["ctrl"] = local_controller_addr
                _local_index_cache["idx"] = i
                return i
    except Exception:
        return 0
    return 0


def is_visible_to_local(processHandle, pawn, Offsets, local_index: int) -> bool:
    """'Видим ли этот враг' по серверной маске засвета (m_bSpottedByMask).

    ВАЖНО: это НЕ трассировка лучей. m_bSpottedByMask - серверный флаг
    'игрока с индексом X засекли': лагает относительно реальной видимости
    и ретроактивен. Используется для окраски бокса (ESP_VisibleCheckBox),
    семантика сохранена как в оригинале."""
    try:
        if local_index <= 0:
            return False

        o = Offsets.offset
        base = pawn + o.m_entitySpottedState
        mask = memfuncs.ProcMemHandler.ReadInt(processHandle, base + o.m_bSpottedByMask)

        return bool(mask & (1 << (local_index - SPOTTED_BIT_OFFSET)))
    except Exception:
        return False
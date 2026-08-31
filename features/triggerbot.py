from functions import memfuncs
from functions import gameinput
from functions import logutil
from functions.process_watcher import ProcessConnector
import win32api, win32gui
import time
import math
import gc

prev_key_state = False


class Vector3:
    __slots__ = ("x", "y", "z")

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)


MIN_VALID_PTR = 0x1000
MAX_VALID_PTR = 0x7FFFFFFFFFFF


def valid_ptr(ptr):
    try:
        ptr = int(ptr)
    except:
        return False
    return MIN_VALID_PTR <= ptr <= MAX_VALID_PTR


def safe_read_ptr(process, address):
    if not valid_ptr(address):
        return 0
    try:
        ptr = memfuncs.ProcMemHandler.ReadPointer(process, address)
        return ptr if valid_ptr(ptr) else 0
    except:
        return 0


def safe_read_int(process, address, default=0):
    if not valid_ptr(address):
        return default
    try:
        return memfuncs.ProcMemHandler.ReadInt(process, address)
    except:
        return default


def safe_read_vec(process, address):
    if not valid_ptr(address):
        return None
    try:
        vec = memfuncs.ProcMemHandler.ReadVec(process, address)
        if vec is None:
            return None
        if not (math.isfinite(vec.x) and math.isfinite(vec.y) and math.isfinite(vec.z)):
            return None
        return Vector3(vec.x, vec.y, vec.z)
    except:
        return None


def read_head_center(process, boneMatrix):
    left_eye = safe_read_vec(process, boneMatrix + 25 * 32)
    right_eye = safe_read_vec(process, boneMatrix + 26 * 32)
    if left_eye is not None and right_eye is not None:
        return Vector3(
            (left_eye.x + right_eye.x) / 2.0,
            (left_eye.y + right_eye.y) / 2.0,
            (left_eye.z + right_eye.z) / 2.0
        )
    head = safe_read_vec(process, boneMatrix + 7 * 32)
    if head is not None:
        return head
    return safe_read_vec(process, boneMatrix + 6 * 32)


def to_float(value, default=0.0):
    try:
        return float(value)
    except:
        return default


def to_bool(value, default=False):
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "enabled")
        return bool(value)
    except:
        return default


def lerp_by_distance(d, points):
    if not points:
        return 0.1
    if d <= points[0][0]:
        return points[0][1]
    for i in range(len(points) - 1):
        d0, v0 = points[i]
        d1, v1 = points[i + 1]
        if d <= d1:
            if d1 == d0:
                return v1
            return v0 + (d - d0) * (v1 - v0) / (d1 - d0)
    return points[-1][1]


def calculate_angle(from_pos, to_pos):
    dx = to_pos.x - from_pos.x
    dy = to_pos.y - from_pos.y
    dz = to_pos.z - from_pos.z
    yaw = math.atan2(dy, dx) * 180.0 / math.pi
    dist = math.sqrt(dx * dx + dy * dy)
    pitch = -math.atan2(dz, dist) * 180.0 / math.pi
    return (yaw, pitch)


def angle_difference(angle1, angle2):
    yaw1, pitch1 = angle1
    yaw2, pitch2 = angle2
    diff_yaw = (yaw2 - yaw1 + 180) % 360 - 180
    diff_pitch = (pitch2 - pitch1 + 180) % 360 - 180
    return math.sqrt(diff_yaw * diff_yaw + diff_pitch * diff_pitch)


def TriggerbotThreadFunction(Options, Offsets):
    connector = ProcessConnector("cs2.exe", modules=["client.dll"])
    global prev_key_state

    # При включённом Key Check стартуем "разоружёнными": состояние теперь
    # живёт в общем конфиге (EnableTriggerbot), а не во внутренней переменной.
    try:
        if to_bool(Options.get("EnableTriggerbotKeyCheck", True), True):
            Options["EnableTriggerbot"] = False
    except Exception:
        pass

    # FOV автоволла - всегда адаптивный
    wallbang_fov_points = [
        (0.0, 2.1),
        (120.0, 1.5),
        (250.0, 1.2),
        (450.0, 0.7),
        (700.0, 0.45),
        (1000.0, 0.3),
        (1500.0, 0.18),
    ]

    LOOP_SLEEP = 0.015
    WALLBANG_EXTRA_SLEEP = 0.004

    dwLocalPlayerPawn_off = getattr(Offsets.offset, "dwLocalPlayerPawn", 37392664)
    dwEntityList_off = getattr(Offsets.offset, "dwEntityList", 39141456)
    dwViewAngles_off = getattr(Offsets.offset, "dwViewAngles", 0)
    m_iHealth_off = getattr(Offsets.offset, "m_iHealth", 844)
    m_iTeamNum_off = getattr(Offsets.offset, "m_iTeamNum", 999)
    m_iIDEntIndex_off = getattr(Offsets.offset, "m_iIDEntIndex", 13356)
    m_fFlags_off = getattr(Offsets.offset, "m_fFlags", 1012)
    m_vecVelocity_off = getattr(Offsets.offset, "m_vecVelocity", 1072)
    m_vOldOrigin_off = getattr(Offsets.offset, "m_vOldOrigin", 5048)
    m_vecViewOffset_off = getattr(Offsets.offset, "m_vecViewOffset", 3704)
    m_hPlayerPawn_off = getattr(Offsets.offset, "m_hPlayerPawn", 2324)
    m_pGameSceneNode_off = getattr(Offsets.offset, "m_pGameSceneNode", 816)
    m_modelState_off = getattr(Offsets.offset, "m_modelState", 320)
    m_angEyeAngles_off = getattr(Offsets.offset, "m_angEyeAngles", 13136)

    last_exception_time = 0.0
    last_gc_time = 0.0
    last_shot_time = 0.0

    while True:
        try:
            now = time.time()
            if now - last_gc_time >= 5.0:
                gc.collect()
                last_gc_time = now

            # Хоткей читается ДО проверки общего включения - иначе он не смог бы
            # включить триггер обратно. Нажатие переключает общий EnableTriggerbot
            # (галочка в GUI синхронизируется через _sync_external).
            if to_bool(Options.get("EnableTriggerbotKeyCheck", True), True):
                key_code = Options.get("TriggerbotKey", 17)
                current_state = bool(win32api.GetAsyncKeyState(key_code) & 0x8000)
                if current_state and not prev_key_state:
                    Options["EnableTriggerbot"] = not to_bool(Options.get("EnableTriggerbot", False), False)
                prev_key_state = current_state

            if not to_bool(Options.get("EnableTriggerbot", False), False):
                time.sleep(0.05)
                continue

            process = connector.ensure_process()
            client = connector.ensure_module("client.dll")
            if not process or not client:
                time.sleep(0.05)
                continue

            if win32gui.GetWindowText(win32gui.GetForegroundWindow()) != "Counter-Strike 2":
                time.sleep(0.02)
                continue

            local_pawn = safe_read_ptr(process, client + dwLocalPlayerPawn_off)
            if not valid_ptr(local_pawn):
                time.sleep(0.02)
                continue

            local_hp = safe_read_int(process, local_pawn + m_iHealth_off, 0)
            if local_hp <= 0:
                time.sleep(0.01)
                continue

            local_origin = safe_read_vec(process, local_pawn + m_vOldOrigin_off)
            view_offset = safe_read_vec(process, local_pawn + m_vecViewOffset_off)
            if local_origin is None or view_offset is None:
                time.sleep(LOOP_SLEEP)
                continue

            eye_pos = Vector3(
                local_origin.x + view_offset.x,
                local_origin.y + view_offset.y,
                local_origin.z + view_offset.z
            )

            wallbang_mode = to_bool(Options.get("TriggerbotWallbang", False), False)
            team_check = to_bool(Options.get("EnableTriggerbotTeamCheck", False), False)
            require_ground = to_bool(Options.get("TriggerbotRequireGround", True), True)
            speed_threshold = to_float(Options.get("TriggerbotSpeedThreshold", 5.0), 5.0)
            shot_delay = to_float(Options.get("TriggerbotShotDelay", 0.4), 0.4)

            target = None
            target_hp = 0
            target_dist = 0.0

            if not wallbang_mode:
                # ОБЫЧНЫЙ режим: исходная логика через m_iIDEntIndex
                local_id = safe_read_int(process, local_pawn + m_iIDEntIndex_off, 0)
                if local_id > 0:
                    entlist = safe_read_ptr(process, client + dwEntityList_off)
                    if valid_ptr(entlist):
                        entry = safe_read_ptr(process, entlist + 0x8 * (local_id >> 9) + 0x10)
                        if valid_ptr(entry):
                            maybe_target = safe_read_ptr(process, entry + 112 * (local_id & 0x1FF))
                            if valid_ptr(maybe_target) and maybe_target != local_pawn:
                                hp = safe_read_int(process, maybe_target + m_iHealth_off, 0)
                                if 0 < hp <= 100:
                                    target = maybe_target
                                    target_hp = hp
                                    t_origin = safe_read_vec(process, maybe_target + m_vOldOrigin_off)
                                    if t_origin is not None:
                                        target_dist = math.sqrt(
                                            (t_origin.x - local_origin.x) ** 2 +
                                            (t_origin.y - local_origin.y) ** 2 +
                                            (t_origin.z - local_origin.z) ** 2
                                        )
            else:
                # АВТОВОЛЛ: скан по углам, адаптивный FOV
                view_angles_vec = None
                if dwViewAngles_off:
                    view_angles_vec = safe_read_vec(process, client + dwViewAngles_off)
                if view_angles_vec is None:
                    view_angles_vec = safe_read_vec(process, local_pawn + m_angEyeAngles_off)
                if view_angles_vec is None:
                    time.sleep(LOOP_SLEEP)
                    continue
                view_angles = (view_angles_vec.y, view_angles_vec.x)

                entity_list = safe_read_ptr(process, client + dwEntityList_off)
                if not valid_ptr(entity_list):
                    time.sleep(LOOP_SLEEP)
                    continue

                best_angle = 360.0
                best_target = 0
                best_hp = 0
                best_dist = 0.0

                for i in range(1, 64):
                    list_entry = safe_read_ptr(process, entity_list + 0x8 * (i >> 9) + 0x10)
                    if not valid_ptr(list_entry):
                        continue

                    controller = safe_read_ptr(process, list_entry + 112 * (i & 0x1FF))
                    if not valid_ptr(controller):
                        continue

                    pawn_handle = safe_read_int(process, controller + m_hPlayerPawn_off, 0)
                    if pawn_handle <= 0 or pawn_handle == 0xFFFFFFFF or pawn_handle == -1:
                        continue

                    pawn_index = pawn_handle & 0x3FFF
                    if pawn_index <= 0:
                        continue

                    list_entry2 = safe_read_ptr(process, entity_list + 0x8 * (pawn_index >> 9) + 0x10)
                    if not valid_ptr(list_entry2):
                        continue

                    pawn = safe_read_ptr(process, list_entry2 + 112 * (pawn_index & 0x1FF))
                    if not valid_ptr(pawn) or pawn == local_pawn:
                        continue

                    hp = safe_read_int(process, pawn + m_iHealth_off, 0)
                    if hp <= 0 or hp > 100:
                        continue

                    if team_check:
                        tgt_team = safe_read_int(process, pawn + m_iTeamNum_off, 0)
                        me_team = safe_read_int(process, local_pawn + m_iTeamNum_off, 0)
                        if tgt_team not in (2, 3) or tgt_team == me_team:
                            continue

                    sceneNode = safe_read_ptr(process, pawn + m_pGameSceneNode_off)
                    if not valid_ptr(sceneNode):
                        continue

                    boneMatrix = safe_read_ptr(process, sceneNode + m_modelState_off + 0x80)
                    if not valid_ptr(boneMatrix):
                        continue

                    head_pos = read_head_center(process, boneMatrix)
                    if head_pos is None:
                        continue

                    angle_to_target = calculate_angle(eye_pos, head_pos)
                    diff = angle_difference(view_angles, angle_to_target)

                    dist = math.sqrt(
                        (head_pos.x - eye_pos.x) ** 2 +
                        (head_pos.y - eye_pos.y) ** 2 +
                        (head_pos.z - eye_pos.z) ** 2
                    )

                    if not math.isfinite(dist) or not math.isfinite(diff):
                        continue

                    if diff < best_angle:
                        best_angle = diff
                        best_target = pawn
                        best_hp = hp
                        best_dist = dist

                if valid_ptr(best_target) and best_hp > 0:
                    threshold = max(0.05, lerp_by_distance(best_dist, wallbang_fov_points))
                    if best_angle < threshold:
                        target = best_target
                        target_hp = best_hp
                        target_dist = best_dist

                time.sleep(WALLBANG_EXTRA_SLEEP)

            if target and team_check:
                tgt_team = safe_read_int(process, target + m_iTeamNum_off, 0)
                me_team = safe_read_int(process, local_pawn + m_iTeamNum_off, 0)
                if tgt_team not in (2, 3) or tgt_team == me_team:
                    target = None
                    target_hp = 0

            if not valid_ptr(target) or target_hp <= 0:
                time.sleep(LOOP_SLEEP)
                continue

            if require_ground:
                flags = safe_read_int(process, local_pawn + m_fFlags_off, 1)
                if not (flags & 1):
                    time.sleep(LOOP_SLEEP)
                    continue

            if speed_threshold > 0.0:
                velocity = safe_read_vec(process, local_pawn + m_vecVelocity_off)
                if velocity is None:
                    velocity = Vector3(0.0, 0.0, 0.0)
                speed = math.sqrt(
                    velocity.x * velocity.x +
                    velocity.y * velocity.y +
                    velocity.z * velocity.z
                )
                if math.isfinite(speed) and speed > speed_threshold:
                    time.sleep(LOOP_SLEEP)
                    continue

            if shot_delay > 0.0 and (now - last_shot_time) < shot_delay:
                time.sleep(0.01)
                continue

            if not win32api.GetAsyncKeyState(0x01):
                # Реакция (адаптивная по дистанции + рандом) живёт в gameinput
                gameinput.LeftClick(target_dist)
                last_shot_time = time.time()

            time.sleep(LOOP_SLEEP)

        except Exception as exc:
            now = time.time()
            if now - last_exception_time >= 1.0:
                logutil.debug(f"[triggerbot] loop exception: {exc}")
                last_exception_time = now
                connector.invalidate()
            time.sleep(0.05)
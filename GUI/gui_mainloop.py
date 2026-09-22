import dearpygui.dearpygui as dpg
from functions import logutil
from functions import toggle_registry
from functions.config_manager import ConfigManager, apply_profile, sanitize_name
import threading
import time
import win32api
import os
from functions import fontpaths

ROOT_TAG = "neron_root_window"

KeyNames = [
    "OFF  ",  "VK_LBUTTON  ",  "VK_RBUTTON  ",  "VK_CANCEL  ",  "VK_MBUTTON  ",  "VK_XBUTTON1  ",  "VK_XBUTTON2  ",  "Unknown  ",
    "VK_BACK  ",  "VK_TAB  ",  "Unknown  ",  "Unknown  ",  "VK_CLEAR  ",  "VK_RETURN  ",  "Unknown  ",  "Unknown  ",  "VK_SHIFT  ",  "VK_CONTROL  ",  "VK_MENU  ",
    "VK_PAUSE  ",  "VK_CAPITAL  ",  "VK_KANA  ",  "Unknown  ",  "VK_JUNJA  ",  "VK_FINAL  ",  "VK_KANJI  ",  "Unknown  ",  "VK_ESCAPE  ",  "VK_CONVERT  ",
    "VK_NONCONVERT  ",  "VK_ACCEPT  ",  "VK_MODECHANGE  ",  "VK_SPACE  ",  "VK_PRIOR  ",  "VK_NEXT  ",  "VK_END  ",  "VK_HOME  ",  "VK_LEFT  ",  "VK_UP  ",
    "VK_RIGHT  ",  "VK_DOWN  ",  "VK_SELECT  ",  "VK_PRINT  ",  "VK_EXECUTE  ",  "VK_SNAPSHOT  ",  "VK_INSERT  ",  "VK_DELETE  ",  "VK_HELP  ",
    "0  ",  "1  ",  "2  ",  "3  ",  "4  ",  "5  ",  "6  ",  "7  ",  "8  ",  "9  ",
    "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",
    "A  ",  "B  ",  "C  ",  "D  ",  "E  ",  "F  ",  "G  ",  "H  ",  "I  ",  "J  ",  "K  ",  "L  ",  "M  ",  "N  ",  "O  ",  "P  ",  "Q  ",  "R  ",  "S  ",  "T  ",  "U  ",  "V  ",  "W  ",  "X  ",  "Y  ",  "Z  ",
    "VK_LWIN  ",  "VK_RWIN  ",  "VK_APPS  ",  "Unknown  ",  "VK_SLEEP  ",
    "VK_NUMPAD0  ",  "VK_NUMPAD1  ",  "VK_NUMPAD2  ",  "VK_NUMPAD3  ",  "VK_NUMPAD4  ",  "VK_NUMPAD5  ",  "VK_NUMPAD6  ",  "VK_NUMPAD7  ",  "VK_NUMPAD8  ",  "VK_NUMPAD9  ",
    "VK_MULTIPLY  ",  "VK_ADD  ",  "VK_SEPARATOR  ",  "VK_SUBTRACT  ",  "VK_DECIMAL  ",  "VK_DIVIDE  ",
    "VK_F1  ",  "VK_F2  ",  "VK_F3  ",  "VK_F4  ",  "VK_F5  ",  "VK_F6  ",  "VK_F7  ",  "VK_F8  ",  "VK_F9  ",  "VK_F10  ",  "VK_F11  ",  "VK_F12  ",
    "VK_F13  ",  "VK_F14  ",  "VK_F15  ",  "VK_F16  ",  "VK_F17  ",  "VK_F18  ",  "VK_F19  ",  "VK_F20  ",  "VK_F21  ",  "VK_F22  ",  "VK_F23  ",  "VK_F24  ",
    "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",
    "VK_NUMLOCK  ",  "VK_SCROLL  ",
    "VK_OEM_NEC_EQUAL  ",  "VK_OEM_FJ_MASSHOU  ",  "VK_OEM_FJ_TOUROKU  ",  "VK_OEM_FJ_LOYA  ",  "VK_OEM_FJ_ROYA  ",
    "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",  "Unknown  ",
    "VK_LSHIFT  ",  "VK_RSHIFT  ",  "VK_LCONTROL  ",  "VK_RCONTROL  ",  "VK_LMENU  ",  "VK_RMENU  "
]


class NERON_GUI:
    def __init__(self, config, runtime, flags=None):
        self.runtime = runtime
        self.flags = flags
        self.n = 0
        self.ui_dragging = False
        self.viewport_width = 900
        self.viewport_height = 780
        self.root_window = None
        self._esp_master_cb = None
        self._trigger_enable_cb = None
        self.sep_theme = None
        self.bg_dl = None
        self.frames_dl = None
        self._frame_items = []      # (item, tab) - рамка принадлежит вкладке
        self._frame_sig = None
        self._tab_bar_id = None
        self._tab_tags = set()
        self._tab_by_label = {}
        self._active_tab = None
        self._cur_tab = None
        # Тогглы: реестр -> hover-попапы и sync галочек с хоткеями движка
        self._toggle_labels = dict(toggle_registry.TOGGLE_FEATURES)
        self._hover_rows = []       # (item_id, config_key, label)
        self._sync_tags = {}        # config_key -> checkbox item_id
        self._hover_popup = None
        self._hover_open_key = None
        self._hover_current_key = None
        self._hover_linger = 0.0
        # Захват клавиши бинда: поток только фиксирует код, DPG трогает
        # только GUI-цикл (_process_capture). Вызовы DPG из потока в ручном
        # цикле рендера не применялись - бинд терялся.
        self._capture_sender = None
        self._capture_key_id = None
        self._capture_done = None
        self._capture_busy = False
        # Троттлинг _sync_external: IPC-чтения из Manager не чаще 10 раз/сек,
        # а не на каждый кадр (тот же урок, что с Manager.Namespace в воркерах)
        self._sync_interval = 0.1
        self._sync_last_ts = 0.0
        # Профили конфигов: менеджер файлов cfg/ внутри GUI-процесса
        self.cfgmgr = ConfigManager()
        self._cfg_tab = None
        self._cfg_name_input = None
        self._cfg_status = None
        self._cfg_list_group = None
        self._cfg_list_sig = None
        self._cfg_list_ts = 0.0
        self._force_cfg_refresh = False
        # Реестр config-виджетов: item -> (key, type, default, extra).
        # Полная перерисовка (_sync_all_widgets) при смене config_ts -
        # загрузка профиля должна обновлять слайдеры/пикеры/комбо, а не
        # только галочки тогглов.
        self._widget_reg = {}
        self._hotkey_btns = {}          # button item -> config key
        self._color_element_pickers = {}  # picker item -> (cb_key, color_key, default_hex)
        self._last_config_ts = 0.0
        self.config = config
        self.control_width = 250
        self.card_padding = 3
        self.palette = {
            "bg_top": (44, 26, 84),
            "bg_bottom": (0, 0, 0),
            "panel": (21, 15, 37, 255),
            "frame": (32, 24, 54, 255),
            "frame_hover": (76, 48, 132, 170),
            "frame_active": (150, 40, 62, 255),
            "accent": (150, 92, 255, 255),
            "accent_hover": (176, 126, 255, 255),
            "accent_soft": (88, 56, 150, 210),
            "accent_red": (210, 52, 74, 255),
            "card_title": (236, 64, 88, 255),
            "red_border": (236, 64, 88, 255),
            "red_sep": (150, 44, 64, 150),
            "separator": (52, 40, 88, 200),
            "text_muted": (176, 164, 208, 255),
            "text_subtle": (128, 118, 158, 255),
        }
        self.init_context()
        self.create_theme()
        self.load_ui_font()
        self.build_ui()
        self.add_event_handlers()

    def hex_to_rgb(self, hex_code):
        hex_code = hex_code.lstrip('#')
        return tuple(int(hex_code[i:i+2], 16) for i in (0, 2, 4))

    def rgb_to_hex(self, rgb):
        r, g, b = [int(round(x)) for x in rgb[:3]]
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        return '#{:02X}{:02X}{:02X}'.format(r, g, b)

    def _color_value_to_hex(self, value):
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return None
        try:
            rgb = [float(v) for v in value[:3]]
        except (TypeError, ValueError):
            return None
        if max(rgb, default=0.0) <= 1.0:
            rgb = [v * 255.0 for v in rgb]
        return self.rgb_to_hex(rgb)

    def init_context(self):
        dpg.create_context()
        self.viewport = dpg.create_viewport(
            title="NERON",
            width=self.viewport_width,
            height=self.viewport_height,
            vsync=True,
            decorated=False,
            resizable=False,
            max_width=self.viewport_width,
            max_height=self.viewport_height
        )
        dpg.setup_dearpygui()

    def load_ui_font(self, path=None, size=16):
        """Load and bind the custom UI font. Tries multiple fallback paths."""
        self.ui_font = None
        candidates = []
        if path:
            candidates.append(path)
        base_dir = os.path.dirname(__file__)
        repo_dir = os.path.abspath(os.path.join(base_dir, ".."))
        font_name = "inter-semibold.ttf"
        candidates.extend(
            fontpaths.font_candidates(
                font_filename=font_name,
                anchors=[base_dir, repo_dir],
            )
        )
        seen = set()
        candidates = [c for c in candidates if not (c in seen or seen.add(c))]
        try:
            with dpg.font_registry():
                for cand in candidates:
                    try:
                        if os.path.exists(cand):
                            self.ui_font = dpg.add_font(cand, size)
                            logutil.debug(f"[gui] UI font loaded: {cand} (size={size})")
                            break
                    except Exception as e:
                        logutil.debug(f"[gui] font load failed for {cand}: {e}")
                        continue
        except Exception as e:
            logutil.debug(f"[gui] font registry error: {e}")
            self.ui_font = None

        if self.ui_font:
            try:
                dpg.bind_font(self.ui_font)
            except Exception as e:
                logutil.debug(f"[gui] bind_font failed: {e}")
        else:
            logutil.debug("[gui] No custom font found; using DearPyGui default font.")

    def keybind_use(self, sender, app_data, user_data):
        # Один захват за раз; повторный клик по любой кнопке-бинду игнор.
        # user_data: строка-ключ (в настройки) или ("cfgbind", имя) (в _binds.json).
        if self._capture_busy:
            return
        key_id = user_data
        if not key_id:
            return
        self._capture_busy = True
        self._capture_sender = sender
        self._capture_key_id = key_id
        try:
            dpg.set_item_label(sender, "...")
        except Exception:
            pass
        # Флаг для движков: биндимая клавиша не дёргает фичу/профиль.
        try:
            self.flags["capture"] = True
        except Exception:
            pass

        def capture_key():
            code = 0
            try:
                time.sleep(0.2)  # ждём отпускания ЛКМ от клика по кнопке
                while True:
                    for i in range(1, 256):
                        if win32api.GetAsyncKeyState(i) & 0x8000:
                            code = i
                            break
                    if code:
                        break
                    time.sleep(0.01)
            finally:
                self._capture_done = (key_id, code)

        threading.Thread(target=capture_key, daemon=True).start()

    def _process_capture(self):
        """Завершение захвата клавиши - ТОЛЬКО в GUI-потоке: лейбл и запись
        в конфиг/_binds.json. Поток захвата результат только фиксирует,
        DPG не трогает."""
        if self._capture_done is None:
            return
        key_id, code = self._capture_done
        self._capture_done = None
        try:
            self.flags["capture"] = False
        except Exception:
            pass
        if isinstance(key_id, tuple) and len(key_id) == 2 and key_id[0] == "cfgbind":
            cfg_name = key_id[1]
            vk = code if code > 0 else 0
            try:
                self.cfgmgr.set_bind(cfg_name, vk)
                # Дубликаты: одна клавиша - один профиль.
                if vk > 0:
                    for other, ovk in self.cfgmgr.all_binds().items():
                        if other != cfg_name and ovk == vk:
                            self.cfgmgr.set_bind(other, 0)
            except Exception as e:
                logutil.debug(f"[gui] cfg bind '{cfg_name}' failed: {e}")
            label = self._key_label(vk) if vk > 0 else self._key_label(0)
            self._cfg_set_status(f"Бинд: {cfg_name} -> {label.strip() if vk > 0 else 'OFF'}")
            self._force_cfg_refresh = True
        else:
            if code > 0:
                self._config_set(key_id, code)
                label = self._key_label(code)
            else:
                label = self._key_label(self._config_get(key_id, 0))
        try:
            dpg.set_item_label(self._capture_sender, label)
        except Exception:
            pass
        self._capture_sender = None
        self._capture_key_id = None
        self._capture_busy = False

    def _key_label(self, key_code):
        if 0 <= key_code < len(KeyNames):
            return KeyNames[key_code]
        return f"Unknown({key_code})"

    def _config_get(self, key, default=None):
        try:
            return self.config[key]
        except KeyError:
            pass
        except Exception:
            pass
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    def _config_set(self, key, value):
        try:
            self.config.update({key: value})
        except Exception:
            try:
                self.config[key] = value
            except Exception as e:
                logutil.debug(f"[gui] config set failed for {key}: {e}")

    def create_theme(self):
        with dpg.theme() as theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Text, (245, 242, 252, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, self.palette["text_subtle"])
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_PopupBg, self.palette["panel"])
                dpg.add_theme_color(dpg.mvThemeCol_Border, self.palette["separator"])
                dpg.add_theme_color(dpg.mvThemeCol_BorderShadow, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, self.palette["frame"])
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, self.palette["frame_hover"])
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, self.palette["frame_active"])
                dpg.add_theme_color(dpg.mvThemeCol_TitleBg, (18, 12, 32, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (26, 17, 46, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgCollapsed, (18, 12, 32, 255))
                dpg.add_theme_color(dpg.mvThemeCol_CheckMark, self.palette["accent"])
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, self.palette["accent"])
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, self.palette["accent_red"])
                dpg.add_theme_color(dpg.mvThemeCol_Button, self.palette["frame"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, self.palette["accent_soft"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, self.palette["accent"])
                dpg.add_theme_color(dpg.mvThemeCol_Header, (21, 15, 37, 200))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, self.palette["accent_soft"])
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, self.palette["accent"])
                dpg.add_theme_color(dpg.mvThemeCol_Separator, self.palette["separator"])
                dpg.add_theme_color(dpg.mvThemeCol_Tab, (21, 15, 37, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TabHovered, self.palette["accent_soft"])
                dpg.add_theme_color(dpg.mvThemeCol_TabActive, self.palette["accent"])
                dpg.add_theme_color(dpg.mvThemeCol_TabUnfocused, (21, 15, 37, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TabUnfocusedActive, (32, 24, 54, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg, (10, 7, 18, 220))
                dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, self.palette["frame"])
                dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabHovered, self.palette["accent_soft"])
                dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabActive, self.palette["accent_red"])

                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 16, 16)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 12, 6)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 10, 8)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 8)
                dpg.add_theme_style(dpg.mvStyleVar_GrabMinSize, 12)
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_TabRounding, 6)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1)
        dpg.bind_theme(theme)

        with dpg.theme() as stheme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Separator, self.palette["red_sep"])
        self.sep_theme = stheme

        # Тема hover-попапа: глобальная тема делает WindowBg прозрачным
        # (под ним градиент) - попапу нужен собственный непрозрачный фон.
        with dpg.theme() as ptheme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, self.palette["panel"])
                dpg.add_theme_color(dpg.mvThemeCol_Border, self.palette["separator"])
                dpg.add_theme_color(dpg.mvThemeCol_TitleBg, self.palette["panel"])
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, self.palette["panel"])
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 10, 10)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 6, 6)
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 6)
        self.popup_theme = ptheme

    def lerp(self, a, b, t): return a + (b - a) * t

    def is_dragging(self, _, data):
        if dpg.is_mouse_button_down(0):
            y = data[1]
            if -2 <= y <= 19:
                self.ui_dragging = True
                if dpg.is_viewport_vsync_on(): dpg.set_viewport_vsync(False)
        else:
            self.ui_dragging = False
            if not dpg.is_viewport_vsync_on(): dpg.set_viewport_vsync(True)

    def drag_logic(self, _, data):
        self.n += 1
        if self.n % 30 != 0: return
        self.n = 0
        if self.ui_dragging:
            pos = dpg.get_viewport_pos()
            x = data[1]; y = data[2]
            dpg.configure_viewport(self.viewport, x_pos=pos[0] + x, y_pos=pos[1] + y)

    def add_event_handlers(self):
        with dpg.handler_registry():
            dpg.add_mouse_drag_handler(0, callback=self.drag_logic)
            dpg.add_mouse_move_handler(callback=self.is_dragging)
        dpg.set_viewport_always_top(True)

    def run(self):
        # Ручной цикл рендера: sync галочек, захват бинда, hover-попапы,
        # рамки, список конфигов - каждый кадр в GUI-потоке.
        dpg.show_viewport()
        while dpg.is_dearpygui_running():
            now = time.time()
            if now - self._sync_last_ts >= self._sync_interval:
                self._sync_last_ts = now
                self._check_config_ts()
                self._sync_external()
            self._process_capture()
            try:
                self._update_hover_popup()
            except Exception as e:
                logutil.debug(f"[gui] hover popup error: {e}")
            try:
                self._update_frames()
            except Exception as e:
                logutil.debug(f"[gui] frames update error: {e}")
            try:
                active = self._active_tab_resolved()
            except Exception:
                active = None
            if active == self._cfg_tab and self._cfg_tab is not None:
                if self._force_cfg_refresh or (now - self._cfg_list_ts) >= 1.0:
                    self._cfg_list_ts = now
                    self._force_cfg_refresh = False
                    try:
                        self._refresh_cfg_list()
                    except Exception as e:
                        logutil.debug(f"[gui] cfg list refresh failed: {e}")
            dpg.render_dearpygui_frame()
        dpg.destroy_context()

    def _sync_external(self):
        """Подтягивает в галочки значения, изменённые вне GUI (общий движок
        тогглов). Один снапшот .items() на тик вместо RPC на каждый тоггл."""
        try:
            snap = dict(self.config.items())
        except Exception:
            return
        for key, _label in toggle_registry.TOGGLE_FEATURES:
            tag = self._sync_tags.get(key)
            if not tag:
                continue
            try:
                want = bool(snap.get(key, False))
                if bool(dpg.get_value(tag)) != want:
                    dpg.set_value(tag, want)
            except Exception:
                pass

    def _check_config_ts(self):
        """Смена config_ts (профиль применён кнопкой или хоткеем) ->
        полная перерисовка config-виджетов. Чтение flags - раз в
        _sync_interval, не каждый кадр (Manager.dict = IPC)."""
        if self.flags is None:
            return
        try:
            ts = float(self.flags.get("config_ts", 0.0) or 0.0)
        except Exception:
            return
        if ts != self._last_config_ts:
            self._last_config_ts = ts
            self._sync_all_widgets()
            self._force_cfg_refresh = True

    def _sync_all_widgets(self):
        """Полная перезаливка значений из конфига во ВСЕ зарегистрированные
        виджеты: галочки, слайдеры, комбо, пикеры цвета, лейблы хоткей-
        кнопок. Вызывается при применении профиля (config_ts)."""
        for item, reg in list(self._widget_reg.items()):
            key, vtype, default, extra = reg
            try:
                val = self._config_get(key, default)
                if vtype is bool:
                    dpg.set_value(item, bool(val))
                elif vtype is int:
                    v = int(val)
                    if extra:
                        v = max(extra[0], min(extra[1], v))
                    dpg.set_value(item, v)
                elif vtype is float:
                    v = float(val)
                    if extra:
                        v = max(extra[0], min(extra[1], v))
                    dpg.set_value(item, v)
                elif vtype == "combo":
                    items = extra or []
                    if val not in items:
                        val = default
                    dpg.set_value(item, val)
                elif vtype == "color":
                    hexv = val or default or "#FFFFFF"
                    dpg.set_value(item, self.hex_to_rgb(hexv))
            except Exception:
                continue
        # Пикеры элементов: значение + enabled по галочке "Свой цвет"
        for pk, (cb_key, color_key, def_hex) in list(self._color_element_pickers.items()):
            try:
                hexv = self._config_get(color_key, def_hex) or def_hex
                dpg.set_value(pk, self.hex_to_rgb(hexv))
                dpg.configure_item(pk, enabled=bool(self._config_get(cb_key, False)))
            except Exception:
                continue
        # Лейблы хоткей-кнопок (AimbotKey и т.п.)
        for btn, key in list(self._hotkey_btns.items()):
            try:
                dpg.configure_item(btn, label=self._key_label(self._config_get(key, 0)))
            except Exception:
                continue

    def _on_toggle_spectators(self, sender, value):
        self._config_set("EnableShowSpectators", bool(value))

    def _build_background(self):
        """Градиент вьюпорта (фиолетовый верх -> чёрный низ) позади окна +
        акцентная линия под титлбаром. viewport_drawlist(front=False):
        без клиппинга, в layout окна не участвует."""
        with dpg.viewport_drawlist(front=False) as dl:
            self.bg_dl = dl
            W, H = self.viewport_width, self.viewport_height
            bands = 48
            top = self.palette["bg_top"]
            bot = self.palette["bg_bottom"]
            band_h = H / float(bands)
            for i in range(bands):
                t = i / max(1, bands - 1)
                r = int(round(self.lerp(top[0], bot[0], t)))
                g = int(round(self.lerp(top[1], bot[1], t)))
                b = int(round(self.lerp(top[2], bot[2], t)))
                dpg.draw_rectangle(
                    (0, i * band_h),
                    (W, (i + 1) * band_h + 1),
                    color=(0, 0, 0, 0),
                    fill=(r, g, b, 255),
                    thickness=0.0,
                )
            x0, x1, y = 16, W - 16, 27
            lbands = 24
            lc = self.palette["accent"][:3]
            rc = self.palette["accent_red"][:3]
            bw = (x1 - x0) / float(lbands)
            for i in range(lbands):
                t = i / max(1, lbands - 1)
                r = int(round(self.lerp(lc[0], rc[0], t)))
                g = int(round(self.lerp(lc[1], rc[1], t)))
                b = int(round(self.lerp(lc[2], rc[2], t)))
                dpg.draw_rectangle(
                    (x0 + i * bw, y),
                    (x0 + (i + 1) * bw + 1, y + 2),
                    color=(0, 0, 0, 0),
                    fill=(r, g, b, 255),
                    thickness=0.0,
                )

    def _bind_tab(self, tab, label):
        """Регистрирует вкладку: привязка рамок + карта для колбэка."""
        self._cur_tab = tab
        self._tab_tags.add(tab)
        self._tab_by_label[label] = tab
        if self._active_tab is None:
            self._active_tab = tab

    def _on_tab_change(self, sender, app_data, user_data):
        # app_data в разных сборках DPG: тег вкладки или её label. Валидируем оба.
        tab = app_data
        if tab not in self._tab_tags:
            tab = self._tab_by_label.get(str(tab), self._active_tab)
        if tab != self._active_tab:
            self._active_tab = tab
            self._frame_sig = None  # принудительная перерисовка рамок

    def _active_tab_resolved(self):
        """Активная вкладка. Приоритет: прямой опрос значения таб-бара
        (если сборка его отдаёт), затем колбэк. Оба валидируются по тегам."""
        try:
            v = dpg.get_value(self._tab_bar_id)
            if v in self._tab_tags:
                return v
        except Exception:
            pass
        return self._active_tab

    def _register_frame(self, item):
        self._frame_items.append((item, self._cur_tab))

    def _rect_sane(self, rect):
        """Отсекает мусорную геометрию: вырожденную и за пределами вьюпорта."""
        (x0, y0), (x1, y1) = rect
        if (x1 - x0) < 4 or (y1 - y0) < 4:
            return False
        W, H = self.viewport_width, self.viewport_height
        if x1 < -20 or y1 < -20 or x0 > W + 20 or y0 > H + 20:
            return False
        return True

    def _item_rect(self, item):
        """rect карточки (min, max). Два способа: item_state и pos+size."""
        try:
            st = dpg.get_item_state(item)
            mn = st.get("rect_min")
            mx = st.get("rect_max")
            if mn and mx:
                w = mx[0] - mn[0]
                h = mx[1] - mn[1]
                if w > 4 and h > 4:
                    rect = (tuple(mn), tuple(mx))
                    if self._rect_sane(rect):
                        return rect
        except Exception:
            pass
        try:
            pos = dpg.get_item_pos(item)
            size = dpg.get_item_rect_size(item)
            if pos and size and size[0] > 4 and size[1] > 4:
                rect = ((pos[0], pos[1]), (pos[0] + size[0], pos[1] + size[1]))
                if self._rect_sane(rect):
                    return rect
        except Exception:
            pass
        return None

    def _update_frames(self):
        """Красные рамки карточек АКТИВНОЙ вкладки. frames_dl - фронт-слой.
        Только активная вкладка, дедуп совпадающих rect, принудительная
        перерисовка при смене вкладки."""
        if self.frames_dl is None:
            return
        active = self._active_tab_resolved()
        if active != self._active_tab:
            self._active_tab = active
            self._frame_sig = None
        items = [it for (it, tab) in self._frame_items if tab == active]
        sig = []
        for it in items:
            r = self._item_rect(it)
            if r is not None and r not in sig:
                sig.append(r)
        if sig == self._frame_sig:
            return
        self._frame_sig = sig
        try:
            dpg.delete_item(self.frames_dl, children_only=True)
        except Exception as e:
            # Неудаённое удаление = накопление прямоугольников: пропуск цикла
            logutil.debug(f"[gui] frames clear failed: {e}")
            return
        for (x0, y0), (x1, y1) in sig:
            dpg.draw_rectangle(
                (x0, y0), (x1, y1),
                color=self.palette["red_border"],
                thickness=1.0,
                parent=self.frames_dl,
            )

    # ==================== Hover-попап тоггл-хоткеев ====================
    # Наведение на галочку зарегистрированной функции -> маленькое окно
    # справа от курсора: подпись функции, кнопка-бинд (пишет
    # ToggleKey_<фича>), сброс. Позиция от координат мыши. Пока попап
    # показан, focus_item держит его НАД root: клик по чекбоксу поднимает
    # root в z-order, без фокуса попап уходил за текст.

    def _build_hover_popup(self):
        with dpg.window(
            autosize=True,
            no_move=True,
            no_resize=True,
            no_title_bar=True,
            no_close=True,
            no_collapse=True,
            no_saved_settings=True,
            show=False,
        ) as popup:
            self._hover_title = dpg.add_text("", color=self.palette["text_muted"])
            dpg.add_spacer(height=2)
            self._hover_bind_btn = dpg.add_button(
                label=self._key_label(0),
                width=190,
                callback=self.keybind_use,
            )
            self._hover_reset_btn = dpg.add_button(
                label="Сброс",
                width=190,
                callback=self._hover_reset,
            )
        try:
            dpg.bind_item_theme(popup, self.popup_theme)
        except Exception:
            pass
        self._hover_popup = popup

    def _hover_reset(self, sender=None, app_data=None, user_data=None):
        key = self._hover_current_key
        if not key:
            return
        kname = toggle_registry.toggle_key_name(key)
        self._config_set(kname, 0)
        try:
            dpg.configure_item(self._hover_bind_btn, label=self._key_label(0))
        except Exception:
            pass

    def _update_hover_popup(self):
        if self._hover_popup is None or not self._hover_rows:
            return
        now = time.time()
        try:
            mx, my = dpg.get_mouse_pos(local=False)
        except Exception:
            return

        # Зажатая кнопка мыши: попап полностью замирает. Раньше фокус и
        # позиция дёргались каждый кадр ПОСРЕДИ клика - DPG сбрасывал
        # active-id чекбокса, и клик отменялся до отпускания кнопки.
        try:
            if dpg.is_mouse_button_down(0):
                if self._hover_open_key is not None:
                    self._hover_linger = now + 0.35
                return
        except Exception:
            pass

        hovered = None
        for item, key, label in self._hover_rows:
            try:
                if dpg.get_item_state(item).get("hovered"):
                    hovered = (item, key, label)
                    break
            except Exception:
                continue

        inside_popup = False
        if self._hover_open_key is not None:
            try:
                if dpg.is_item_shown(self._hover_popup):
                    w, h = dpg.get_item_rect_size(self._hover_popup)
                    px, py = dpg.get_item_pos(self._hover_popup)
                    inside_popup = (px <= mx < px + max(w, 10)) and (py <= my < py + max(h, 10))
            except Exception:
                pass

        if hovered is not None:
            _item, key, label = hovered
            if key != self._hover_open_key:
                self._hover_open_key = key
                self._hover_current_key = key
                kname = toggle_registry.toggle_key_name(key)
                try:
                    dpg.set_value(self._hover_title, label)
                    dpg.configure_item(
                        self._hover_bind_btn,
                        user_data=kname,
                        label=self._key_label(self._config_get(kname, 0)),
                    )
                except Exception:
                    pass
                # Открытие: позиция/показ/фокус - ОДИН раз на переходе,
                # не каждый кадр. Каждый-кадровый focus_item убивал клики.
                try:
                    px = min(mx + 14, self.viewport_width - 226)
                    py = max(4, min(my - 10, self.viewport_height - 132))
                    dpg.set_item_pos(self._hover_popup, (px, py))
                    dpg.configure_item(self._hover_popup, show=True)
                    dpg.focus_item(self._hover_popup)
                except Exception:
                    pass
            self._hover_linger = now + 0.35
        elif inside_popup:
            self._hover_linger = now + 0.35
            # Если клик по галочке поднял root и попап ушёл под окно -
            # возвращаем фокус, но только пока попап реально НЕ наведён.
            # Когда курсор на нём и он сверху - фокус не трогаем, чтобы
            # не убить клик по кнопке бинда.
            try:
                if not dpg.is_item_hovered(self._hover_popup):
                    dpg.focus_item(self._hover_popup)
            except Exception:
                pass
        elif now > self._hover_linger and self._hover_open_key is not None:
            self._hover_open_key = None
            self._hover_current_key = None
            try:
                dpg.configure_item(self._hover_popup, show=False)
            except Exception:
                pass

    def build_ui(self):
        self._build_background()
        with dpg.viewport_drawlist(front=True) as fdl:
            self.frames_dl = fdl

        with dpg.window(
            label="NERON_CAT - developed by Releotkamaza",
            width=self.viewport_width,
            height=self.viewport_height,
            no_move=True,
            no_resize=True,
            no_close=True,
            no_collapse=True,
            tag=ROOT_TAG,
        ) as root:
            self.root_window = root

            with dpg.tab_bar(callback=self._on_tab_change) as tbar:
                self._tab_bar_id = tbar
                self._build_tab_aimbot()
                self._build_tab_visuals()
                self._build_tab_triggerbot()
                self._build_tab_recoil()
                self._build_tab_colors()
                self._build_tab_bhop()
                self._build_tab_misc()
                self._build_tab_configs()

        self._build_hover_popup()

    def _tab_card(self, title, subtitle=None):
        with dpg.child_window(
            width=-1,
            autosize_y=True,
            no_scrollbar=True,
            border=True
        ) as container:
            try:
                dpg.bind_item_theme(container, self.sep_theme)
            except Exception:
                pass
            self._register_frame(container)
            header = dpg.add_group(parent=container)
            dpg.add_text(title, color=self.palette["card_title"], parent=header)
            if subtitle:
                dpg.add_text(
                    subtitle,
                    color=self.palette["text_subtle"],
                    parent=header
                )
            dpg.add_separator(parent=container)
            dpg.add_spacer(height=10, parent=container)
            content = dpg.add_group(parent=container)
        return content

    def _build_tab_aimbot(self):
        with dpg.tab(label="Aimbot") as tab:
            self._bind_tab(tab, "Aimbot")
            card = self._tab_card("Настройки Aimbot'а", "Облегчение наведения на противников.")
            self._config_checkbox("Включение Aimbot'а", "EnableAimbot", parent=card)
            self._config_hotkey("Aimbot Hotkey", "AimbotKey", parent=card)
            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)
            self._config_checkbox("Проверка на тиммейта##Aimbot", "EnableAimbotTeamCheck", parent=card)
            self._config_checkbox("Проверка на видимость", "EnableAimbotVisibilityCheck", parent=card)
            self._config_slider_int("Aimbot FOV", "AimbotFOV", 90, 50, 200, parent=card)
            self._config_slider_int("Сглаживание Aimbot'а", "AimbotSmoothing", 5, 1, 10, parent=card)
            self._config_checkbox("Предсказание (на основе скорости)", "EnableAimbotPrediction", parent=card)
            self._config_combo("Позиция Aim'а", "AimPosition", ["Head", "Neck", "Torso", "Leg"], "Head", parent=card)

    def _build_tab_visuals(self):
        with dpg.tab(label="ESP & Visuals") as tab:
            self._bind_tab(tab, "ESP & Visuals")
            card = self._tab_card("ESP & Visuals", "Настройки ESP и вывода информации.")
            self._esp_master_cb = self._config_checkbox("Включение ESP", "EnableESP", default=True, parent=card)
            dpg.add_spacer(height=6, parent=card)

            with dpg.group(horizontal=True, horizontal_spacing=18, parent=card):
                # 0.34/0.54: левой колонке нужен запас под длинные лейблы,
                # правой 0.54 хватает: слайдеры 350px помещаются с запасом.
                left_col = dpg.add_child_window(width=int(self.viewport_width*0.34), autosize_y=True, no_scrollbar=True, border=True)
                right_col = dpg.add_child_window(width=int(self.viewport_width*0.54), autosize_y=True, no_scrollbar=True, border=True)
                # Колонки НЕ регистрируются в рамках _update_frames: вложенные
                # child_window отдают rect в координатах родительской карточки,
                # на фронт-слое рамки рисовались смещёнными левее/выше.
                for col in (left_col, right_col):
                    try:
                        dpg.bind_item_theme(col, self.sep_theme)
                    except Exception:
                        pass

                dpg.add_text("Renderers", color=self.palette["text_muted"], parent=left_col)
                # Один вертикальный столбец: child_window клипает лейблы по
                # правой кромке, горизонтальный сплит внутри колонки оставлял
                # правому подстолбцу ~160px - длинные лейблы обрезались.
                self._config_checkbox("Skeleton", "EnableESPSkeletonRendering", parent=left_col)
                self._config_checkbox("Box", "EnableESPBoxRendering", parent=left_col)
                self._config_checkbox("Проверка на видимость", "ESP_VisibleCheckBox", parent=left_col)
                self._config_checkbox("Трейсеры", "EnableESPTracerRendering", parent=left_col)
                self._config_checkbox("Проверка на тиммейта", "EnableESPTeamCheck", parent=left_col)

                dpg.add_spacer(height=6, parent=left_col)
                dpg.add_text("Labels", color=self.palette["text_muted"], parent=left_col)
                self._config_checkbox("Имя", "EnableESPNameText", parent=left_col)
                self._config_checkbox("Оружие", "EnableESPWeaponText", parent=left_col)
                self._config_checkbox("Дистанция", "EnableESPDistanceText", parent=left_col)
                self._config_checkbox("Вывод HP", "EnableESPHealthText", parent=left_col)
                self._config_checkbox("HP Bar", "EnableESPHealthBarRendering", parent=left_col)

                dpg.add_text("Визуал и толщина", color=self.palette["text_muted"], parent=right_col)
                dpg.add_spacer(height=2, parent=right_col)
                dpg.add_text("Синхронизация с HP", color=self.palette["text_subtle"], parent=right_col)
                self._config_checkbox("Skeleton базируется на HP", "ESP_HealthSyncSkeleton", default=True, parent=right_col)
                self._config_checkbox("HP Bar базируется на HP", "ESP_HealthSyncBar", default=True, parent=right_col)

                dpg.add_spacer(height=6, parent=right_col)
                dpg.add_separator(parent=right_col)
                dpg.add_spacer(height=6, parent=right_col)
                dpg.add_text("Толщина", color=self.palette["text_subtle"], parent=right_col)

                s1 = self._config_slider_float("Размер Skeleton", "ESP_SkeletonThicknessScale", 1.0, 0.6, 2.0, parent=right_col)
                s2 = self._config_slider_float("Размер Box", "ESP_BoxThicknessScale", 1.0, 0.6, 2.0, parent=right_col)
                s3 = self._config_slider_float("Толщина HP Bar", "ESP_HealthBarThicknessScale", 1.0, 0.6, 1.6, parent=right_col)
                s4 = self._config_slider_float("Толщина трейсеров", "ESP_TracerThickness", 1.5, 0.5, 4.0, parent=right_col, format="%.1f")

                try:
                    dpg.configure_item(s1, width=int(self.control_width*1.4))
                    dpg.configure_item(s2, width=int(self.control_width*1.4))
                    dpg.configure_item(s3, width=int(self.control_width*1.4))
                    dpg.configure_item(s4, width=int(self.control_width*1.4))
                except Exception:
                    pass

    def _build_tab_triggerbot(self):
        with dpg.tab(label="Triggerbot") as tab:
            self._bind_tab(tab, "Triggerbot")
            card = self._tab_card("Triggerbot", "Автоматический выстрел при наведении на врага.")
            self._trigger_enable_cb = self._config_checkbox("Включение triggerbot", "EnableTriggerbot", parent=card)
            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)
            self._config_checkbox("Проверка на тиммейта##Triggerbot", "EnableTriggerbotTeamCheck", parent=card)
            self._config_checkbox("Проверка на землю (стрельба только на земле)", "TriggerbotRequireGround", default=True, parent=card)
            self._config_slider_float("Проверка скорости (стрельба при скорости ниже)", "TriggerbotSpeedThreshold", 5.0, 0.0, 200.0, parent=card, format="%.1f")
            self._config_checkbox("Wallbang (аволл) режим", "TriggerbotWallbang", default=False, parent=card)

    def _build_tab_recoil(self):
        with dpg.tab(label="Контроль отдачи") as tab:
            self._bind_tab(tab, "Контроль отдачи")
            card = self._tab_card("Контроль отдачи", "Контроль отдачи оружия.")
            self._config_checkbox("Включение контроля отдачи", "EnableRecoilControl", parent=card)
            self._config_slider_float("Плавность контроля отдачи", "RecoilControlSmoothing", 1.5, 1.0, 3.0, parent=card, format="%.2f")

    def _build_tab_colors(self):
        with dpg.tab(label="Цвета") as tab:
            self._bind_tab(tab, "Цвета")
            card = self._tab_card("Настройки цвета", "Цвета функций и окраска по командам.")
            enemy_color = self._config_get("Enemy_color", "#FF6A5A") or "#FF6A5A"
            teammate_color = self._config_get("Teammate_color", "#4DA2FF") or "#4DA2FF"
            fov_color = self._config_get("FOV_color", "#FF3F88") or "#FF3F88"
            noscopedot_color = self._config_get("NoScopeDot_color", "#FFFFFF") or "#FFFFFF"

            dpg.add_text("Команды", color=self.palette["text_muted"], parent=card)
            dpg.add_spacer(height=4, parent=card)

            with dpg.group(horizontal=True, horizontal_spacing=18, parent=card):
                enemy_pk = dpg.add_color_picker(
                    label="Противники",
                    default_value=self.hex_to_rgb(enemy_color),
                    no_alpha=True,
                    no_inputs=True,
                    no_side_preview=True,
                    no_small_preview=True,
                    width=110,
                    height=110,
                    user_data=("Enemy_color", "color"),
                    callback=self._on_widget_change,
                )
                teammate_pk = dpg.add_color_picker(
                    label="Тиммейты",
                    default_value=self.hex_to_rgb(teammate_color),
                    no_alpha=True,
                    no_inputs=True,
                    no_side_preview=True,
                    no_small_preview=True,
                    width=110,
                    height=110,
                    user_data=("Teammate_color", "color"),
                    callback=self._on_widget_change,
                )
                self._widget_reg[enemy_pk] = ("Enemy_color", "color", "#FF6A5A", None)
                self._widget_reg[teammate_pk] = ("Teammate_color", "color", "#4DA2FF", None)

            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)

            dpg.add_text("Элементы", color=self.palette["text_muted"], parent=card)
            dpg.add_spacer(height=4, parent=card)

            # Горизонтальный ряд: элемент = вертикальная колонка (пикер
            # сверху, галочка снизу). Явный id группы как parent исправлял
            # v5.9: без него ряд пустовал, элементы складывались вертикально.
            with dpg.group(horizontal=True, horizontal_spacing=18, parent=card) as elem_row:
                self._config_color_element("Box", "EnableBoxCustomColor", "Box_color", elem_row)
                self._config_color_element("Трейсеры", "EnableTracerCustomColor", "Tracer_color", elem_row)
                self._config_color_element("HP Bar", "EnableHPBarCustomColor", "HPBar_color", elem_row)

            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)

            dpg.add_text("Misc Colors", color=self.palette["text_muted"], parent=card)
            with dpg.group(horizontal=True, horizontal_spacing=18, parent=card):
                fov_pk = dpg.add_color_picker(
                    label="FOV Color",
                    default_value=self.hex_to_rgb(fov_color),
                    no_alpha=True,
                    no_inputs=True,
                    no_side_preview=True,
                    no_small_preview=True,
                    width=100,
                    height=100,
                    user_data=("FOV_color", "color"),
                    callback=self._on_widget_change,
                )
                noscopedot_pk = dpg.add_color_picker(
                    label="Точка (ноускоп)",
                    default_value=self.hex_to_rgb(noscopedot_color),
                    no_alpha=True,
                    no_inputs=True,
                    no_side_preview=True,
                    no_small_preview=True,
                    width=100,
                    height=100,
                    user_data=("NoScopeDot_color", "color"),
                    callback=self._on_widget_change,
                )
            self._widget_reg[fov_pk] = ("FOV_color", "color", "#FF3F88", None)
            self._widget_reg[noscopedot_pk] = ("NoScopeDot_color", "color", "#FFFFFF", None)

    def _config_color_element(self, label, cb_key, color_key, parent, size=100):
        """Элемент с кастомным цветом: колонка (пикер + галочка "Свой цвет").
        Галочка выключена -> элемент красится командной окраской, пикер
        задизейблен для наглядности. Включена -> пикер перекрывает.
        Вертикальная группа-обёртка даёт колонку в горизонтальном ряду."""
        default_hex = self._config_get(color_key, "#FF6A5A") or "#FF6A5A"
        with dpg.group(parent=parent):
            pk = dpg.add_color_picker(
                label=label,
                default_value=self.hex_to_rgb(default_hex),
                no_alpha=True,
                no_inputs=True,
                no_side_preview=True,
                no_small_preview=True,
                width=size,
                height=size,
            )
            cb = dpg.add_checkbox(
                label="Свой цвет",
                default_value=bool(self._config_get(cb_key, False)),
                callback=self._on_custom_color_toggle,
            )
        try:
            dpg.configure_item(cb, user_data=(cb_key, pk))
            dpg.configure_item(pk, enabled=bool(self._config_get(cb_key, False)))
        except Exception as e:
            logutil.debug(f"[gui] color element bind failed for {cb_key}: {e}")
        self._widget_reg[cb] = (cb_key, bool, False, None)
        self._color_element_pickers[pk] = (cb_key, color_key, default_hex)
        return pk

    def _on_custom_color_toggle(self, sender, app_data, user_data):
        cb_key, picker_id = user_data
        self._config_set(cb_key, bool(app_data))
        try:
            dpg.configure_item(picker_id, enabled=bool(app_data))
        except Exception as e:
            logutil.debug(f"[gui] color picker toggle failed for {cb_key}: {e}")

    def _config_checkbox(self, label, key, default=False, parent=None):
        kwargs = {
            "label": label,
            "default_value": bool(self._config_get(key, default)),
            "user_data": (key, bool),
            "callback": self._on_widget_change,
        }
        if parent is not None:
            kwargs["parent"] = parent
        cb = dpg.add_checkbox(**kwargs)
        self._widget_reg[cb] = (key, bool, default, None)
        # Тоггл-фича из реестра: hover-попап бинда + sync галочки с движком
        if key in self._toggle_labels:
            self._hover_rows.append((cb, key, self._toggle_labels[key]))
            self._sync_tags[key] = cb
        return cb

    def _config_slider_int(self, label, key, default, min_value, max_value, parent=None, format=None):
        current = self._config_get(key, default)
        if current is None:
            current = default
        kwargs = {
            "label": label,
            "default_value": int(current),
            "min_value": min_value,
            "max_value": max_value,
            "user_data": (key, int),
            "callback": self._on_widget_change,
            "width": self.control_width,
        }
        if format:
            kwargs["format"] = format
        if parent is not None:
            kwargs["parent"] = parent
        sl = dpg.add_slider_int(**kwargs)
        self._widget_reg[sl] = (key, int, default, (min_value, max_value))
        return sl

    def _config_slider_float(self, label, key, default, min_value, max_value, parent=None, format="%.2f"):
        current = self._config_get(key, default)
        if current is None:
            current = default
        kwargs = {
            "label": label,
            "default_value": float(current),
            "min_value": min_value,
            "max_value": max_value,
            "format": format,
            "user_data": (key, float),
            "callback": self._on_widget_change,
            "width": self.control_width,
        }
        if parent is not None:
            kwargs["parent"] = parent
        sl = dpg.add_slider_float(**kwargs)
        self._widget_reg[sl] = (key, float, default, (min_value, max_value))
        return sl

    def _config_combo(self, label, key, items, default, parent=None):
        current = self._config_get(key, default)
        if current not in items:
            current = default
        kwargs = {
            "label": label,
            "items": items,
            "default_value": current,
            "user_data": (key, "combo"),
            "callback": self._on_widget_change,
            "width": self.control_width,
        }
        if parent is not None:
            kwargs["parent"] = parent
        cmb = dpg.add_combo(**kwargs)
        self._widget_reg[cmb] = (key, "combo", default, list(items))
        return cmb

    def _config_hotkey(self, heading, key, parent=None):
        group_kwargs = {}
        if parent is not None:
            group_kwargs["parent"] = parent
        group_id = dpg.add_group(**group_kwargs)
        dpg.add_text(heading, color=self.palette["text_muted"], parent=group_id)
        btn = dpg.add_button(
            label=self._key_label(self._config_get(key, 0)),
            user_data=key,
            callback=self.keybind_use,
            width=int(self.control_width * 0.66),
            parent=group_id,
        )
        self._hotkey_btns[btn] = key
        return btn

    def _on_widget_change(self, sender, app_data, user_data):
        key, value_type = user_data
        if value_type is bool:
            value = bool(app_data)
        elif value_type is int:
            value = int(app_data)
        elif value_type is float:
            value = float(app_data)
        elif value_type == "color":
            hex_value = self._color_value_to_hex(app_data)
            if hex_value is None:
                return
            value = hex_value
        else:
            value = app_data
        self._config_set(key, value)

    def _build_tab_misc(self):
        with dpg.tab(label="Прочее") as tab:
            self._bind_tab(tab, "Прочее")
            card = self._tab_card("Прочее", "Прочие различные настройки.")
            self._config_checkbox("Убрать чёрный скоуп (AWP/SSG/SCAR-20/G3SG1)", "EnableNoScopeOverlay", parent=card)
            self._config_checkbox("Точка при ноускопе (AWP/SSG/SCAR-20/G3SG1)", "EnableNoScopeDot", parent=card)
            self._config_slider_float("Радиус точки (px)", "NoScopeDot_radius", 5.0, 1.0, 12.0, parent=card, format="%.1f")
            self._config_slider_int("Непрозрачность точки (%)", "NoScopeDot_opacity", 80, 10, 100, parent=card)
            self._config_checkbox("Включение таймера бомбы", "EnableESPBombTimer", parent=card)
            self._config_checkbox("Включение Антифлеша", "EnableAntiFlashbang", parent=card)
            self._config_checkbox("Удаление смоков", "EnableNoSmoke", parent=card)
            self._config_checkbox("Включение автопринятия матча", "EnableAutoAccept", parent=card)
            spec_cb = dpg.add_checkbox(
                label="Список наблюдателей (в матче)",
                default_value=self.config.get("EnableShowSpectators", False),
                callback=self._on_toggle_spectators,
                parent=card,
            )
            if "EnableShowSpectators" in self._toggle_labels:
                self._hover_rows.append((spec_cb, "EnableShowSpectators", self._toggle_labels["EnableShowSpectators"]))
                self._sync_tags["EnableShowSpectators"] = spec_cb
            self._config_checkbox("Включить изменение угла обзора", "EnableFovChanger", parent=card)
            self._config_slider_int("Угол обзора (90-170)", "FovChangeSize", 90, 90, 170, parent=card)

    def _build_tab_bhop(self):
        with dpg.tab(label="Бхоп") as tab:
            self._bind_tab(tab, "Бхоп")
            card = self._tab_card("Баннихоп и автострейф", "Настройка бхопа и автострейфа.")

            self._config_checkbox("Включить бхоп", "EnableBhop", parent=card)
            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)

            dpg.add_text("Автострейф", color=self.palette["text_muted"], parent=card)
            dpg.add_spacer(height=4, parent=card)

            self._config_checkbox("Включить автострейф", "EnableBhopAutoStrafe", parent=card)
            dpg.add_spacer(height=8, parent=card)

            self._config_slider_float(
                "Макс. угол стрейфа (°)", "BhopStrafeMaxAngle",
                4.0, 1.0, 12.0, parent=card, format="%.1f"
            )
            self._config_slider_float(
                "Мин. угол стрейфа (°)", "BhopStrafeMinAngle",
                1.0, 0.5, 5.0, parent=card, format="%.1f"
            )
            self._config_slider_float(
                "Интенсивность кривой Безье", "BhopBezierIntensity",
                0.5, 0.0, 1.0, parent=card, format="%.2f"
            )
            self._config_slider_float(
                "Скорость автострейфа", "BhopStrafeSpeed",
                1.0, 0.3, 3.0, parent=card, format="%.2f"
            )

            dpg.add_spacer(height=8, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)

            dpg.add_text("Анти-детект", color=self.palette["text_muted"], parent=card)
            dpg.add_spacer(height=4, parent=card)

            self._config_slider_float(
                "Порог мин. угла (°)", "BhopMinAngleThreshold",
                1.5, 0.5, 4.0, parent=card, format="%.1f"
            )
            self._config_slider_float(
                "Коррекция след. угла (°)", "BhopMinAngleCorrection",
                3.0, 1.0, 8.0, parent=card, format="%.1f"
            )
            self._config_slider_int(
                "Мин. задержка (мс)", "BhopRandomDelayMin",
                2, 1, 20, parent=card
            )
            self._config_slider_int(
                "Макс. задержка (мс)", "BhopRandomDelayMax",
                8, 2, 30, parent=card
            )

    # ==================== Вкладка "Конфигурации" ====================
    # Профили настроек: cfg/<имя>.json + бинды в cfg/_binds.json.
    # Создание - снапшот текущих настроек. Загрузка - apply_profile
    # (единый путь с хоткеем: update в ManagedConfig -> автосейв
    # settings.json + config_ts в SharedFlags -> _sync_all_widgets).
    # Список перестраивается при смене сигнатуры (имена+бинды),
    # опрос раз в 1 с и только на активной вкладке.

    def _build_tab_configs(self):
        with dpg.tab(label="Конфигурации") as tab:
            self._bind_tab(tab, "Конфигурации")
            self._cfg_tab = tab
            card = self._tab_card("Конфигурации", "Созданные вами конфигурации настроек.")
            with dpg.group(horizontal=True, horizontal_spacing=8, parent=card):
                self._cfg_name_input = dpg.add_input_text(
                    hint="Имя конфигурации",
                    width=260,
                )
                dpg.add_button(label="Создать", width=110, callback=self._on_cfg_create)
            dpg.add_text(
                "Профиль сохраняет все текущие настройки. Загрузка применяет их мгновенно.",
                color=self.palette["text_subtle"],
                parent=card,
            )
            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)
            self._cfg_status = dpg.add_text("", color=self.palette["text_muted"], parent=card)
            dpg.add_spacer(height=4, parent=card)
            self._cfg_list_group = dpg.add_group(parent=card)

    def _cfg_set_status(self, text, ok=True):
        try:
            dpg.configure_item(
                self._cfg_status,
                default_value=text,
                color=self.palette["text_muted"] if ok else self.palette["accent_red"],
            )
        except Exception:
            pass

    def _refresh_cfg_list(self):
        """Перестройка списка профилей при изменении сигнатуры (имена+бинды).
        Удаление детей группы и пересоздание - только в GUI-потоке."""
        if self._cfg_list_group is None:
            return
        names = self.cfgmgr.list()
        try:
            binds = self.cfgmgr.all_binds()
        except Exception:
            binds = {}
        sig = tuple((n, binds.get(n, 0)) for n in names)
        if sig == self._cfg_list_sig:
            return
        self._cfg_list_sig = sig
        try:
            dpg.delete_item(self._cfg_list_group, children_only=True)
        except Exception as e:
            logutil.debug(f"[gui] cfg list clear failed: {e}")
            return
        if not names:
            dpg.add_text(
                "Конфигураций пока нет. Введите имя и нажмите «Создать».",
                color=self.palette["text_subtle"],
                parent=self._cfg_list_group,
            )
            return
        for name in names:
            vk = binds.get(name, 0)
            with dpg.group(horizontal=True, horizontal_spacing=8, parent=self._cfg_list_group):
                dpg.add_text(name, color=self.palette["text_muted"])
                dpg.add_button(label="Загрузить", width=100, user_data=name, callback=self._on_cfg_load)
                dpg.add_button(label="Перезаписать", width=120, user_data=name, callback=self._on_cfg_overwrite)
                dpg.add_button(
                    label=f"Бинд: {self._key_label(vk).strip() if vk > 0 else 'OFF'}",
                    width=110,
                    user_data=("cfgbind", name),
                    callback=self.keybind_use,
                )
                dpg.add_button(label="Удалить", width=85, user_data=name, callback=self._on_cfg_delete)

    def _on_cfg_create(self, sender=None, app_data=None, user_data=None):
        raw = ""
        try:
            raw = dpg.get_value(self._cfg_name_input)
        except Exception:
            pass
        name = sanitize_name(raw)
        if not name:
            self._cfg_set_status("Некорректное имя: буквы/цифры/_/пробел/дефис, до 32 символов, не с '_'", ok=False)
            return
        try:
            snapshot = dict(self.config.items())
        except Exception as e:
            logutil.debug(f"[gui] cfg snapshot failed: {e}")
            snapshot = dict(self._config_get("__all__", {}) or {})
        if self.cfgmgr.save(name, snapshot):
            try:
                dpg.set_value(self._cfg_name_input, "")
            except Exception:
                pass
            self._cfg_set_status(f"Создан: {name}")
            self._force_cfg_refresh = True
        else:
            self._cfg_set_status(f"Не удалось сохранить профиль '{name}'", ok=False)

    def _on_cfg_load(self, sender=None, app_data=None, user_data=None):
        name = user_data
        if not name:
            return
        if apply_profile(name, self.cfgmgr, self.config, self.flags):
            self._cfg_set_status(f"Загружен: {name}")
        else:
            self._cfg_set_status(f"Профиль '{name}' не найден или битый", ok=False)

    def _on_cfg_overwrite(self, sender=None, app_data=None, user_data=None):
        name = user_data
        if not name:
            return
        try:
            snapshot = dict(self.config.items())
        except Exception as e:
            logutil.debug(f"[gui] cfg snapshot failed: {e}")
            return
        if self.cfgmgr.save(name, snapshot):
            self._cfg_set_status(f"Перезаписан: {name}")
        else:
            self._cfg_set_status(f"Не удалось перезаписать '{name}'", ok=False)

    def _on_cfg_delete(self, sender=None, app_data=None, user_data=None):
        name = user_data
        if not name:
            return
        if self.cfgmgr.delete(name):
            self._cfg_set_status(f"Удалён: {name}")
            self._force_cfg_refresh = True
        else:
            self._cfg_set_status(f"Не удалось удалить '{name}'", ok=False)


def run_gui(Options, Runtime, Flags=None):
    gui = NERON_GUI(Options, Runtime, Flags)
    gui.run()
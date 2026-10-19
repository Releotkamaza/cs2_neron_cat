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

# Triggerbot: внутренние id режима задержки срабатывания (в конфиг пишет
# выпадающий список через _config_combo_map, в списке - русские подписи).
# Строки ДОЛЖНЫ совпадать с functions/gameinput.DELAY_MODE_*.
DELAY_MODE_STATIC = "static"
DELAY_MODE_RANGE = "range"
DELAY_MODE_DISTANCE = "distance"
DELAY_MODE_ITEMS = [
    ("Статическая", DELAY_MODE_STATIC),
    ("Рандомная из промежутка", DELAY_MODE_RANGE),
    ("Рандомная от расстояния", DELAY_MODE_DISTANCE),
]
# Пределы полей задержки (мс) и дистанции (юниты) в таблице задержек.
DELAY_MS_MIN = 0.0
DELAY_MS_MAX = 500.0
DELAY_DIST_MAX = 100000.0
# Дефолт таблицы задержек - копия globals.CHEAT_SETTINGS["TriggerbotDelayTable"]
# (GUI не импортирует globals: его импорт тянет ext/offsets с сетью).
DELAY_TABLE_DEFAULT = [
    [0.0, 250.0, 20.0, 30.0],
    [250.0, 500.0, 15.0, 25.0],
    [500.0, 800.0, 10.0, 20.0],
    [800.0, 1200.0, 6.0, 10.0],
    [1200.0, 2000.0, 4.0, 8.0],
    [2000.0, 100000.0, 2.0, 6.0],
]

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


CAT_MATRIX = (
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    ".......#..........#.............",
    ".......##........##.............",
    ".......###......###.............",
    ".......############.............",
    ".......############.............",
    ".......############.............",
    "......####.####.####............",
    "......####.####.####............",
    "......#############.............",
    ".......############.............",
    ".......###########..............",
    "........#########......##.......",
    "........#########.....###.......",
    "........##########....###.......",
    "........##########....###.......",
    ".......###########....##........",
    ".......############..###........",
    ".......############..##.........",
    ".......############.###.........",
    ".......###############..........",
    ".......##############...........",
    ".......#############............",
    "........###########.............",
    "........##########..............",
)
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
        self._hover_rows = []       # (item_id, config_key, label, bindable)
        self._sync_tags = {}        # config_key -> checkbox item_id (bool-тоггл)
        self._sync_mode_tags = {}   # config_key -> combo item_id (мультипозиционный)
        self._hover_popup = None
        self._hover_open_key = None
        self._hover_current_key = None
        self._hover_linger = 0.0
        self._hover_show_at = 0.0
        self._hover_target_rect = None
        self._hover_clicked_close = False
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
        # Вкладка "Прицел": drawlist'ы превью (создаются в _build_tab_crosshair)
        self._xc_preview_dl = None
        self._dot_preview_dl = None
        self._xc_noscope_panel = None   # группа "Точка ноускопа" (видимость по режиму)
        self._glow_custom_panel = None  # группа цветов обводки (видимость по режиму)
        # Triggerbot, задержка: три группы-панели (видимость по режиму) и
        # динамическая таблица "дистанция -> задержка". _delay_rows - список
        # записей {row, cells, btn} в том же порядке, что и строки таблицы.
        self._delay_panel_static = None
        self._delay_panel_range = None
        self._delay_panel_table = None
        self._delay_table_id = None
        self._delay_table_theme = None
        self._delay_rows = []
        # Чёрная панель категорий слева (дизайн v8.1): sidebar_w - ширина
        # панели, content_w - ширина контента вкладок правее неё.
        self.sidebar_w = 160
        self.content_w = self.viewport_width - self.sidebar_w
        # Категории -> субвкладки таб-бара.
        self._sidebar = None
        self._cat_buttons = {}
        self._cat_tabs = {}
        self._cat_last = {}
        self._active_cat = "Стрельба"
        self.sidebar_theme = None
        self.cat_on_theme = None
        self.cat_off_theme = None
        self._cat_tex_tag = None
        self._cat_tex_data = None
        self._cat_w = 144
        self._cat_h = 144
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
        # Чёрная панель категорий (дизайн v8.1): непрозрачный чёрный фон,
        # без бордера, без скругления.
        with dpg.theme() as sbtheme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 12, 14)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 8)
        self.sidebar_theme = sbtheme

        # Тема root-окна: паддинг по X = 0 - чёрная панель категорий
        # упирается в левый край окна (раньше WindowPadding 16 оставлял
        # чёрную полосу между панелью и краем, потом под артом вылезал
        # градиент). Паддинг по Y = 16 - зазор под титлбаром (28px), в
        # котором видна акцентная линия градиента (v8.3): при паддинге 0
        # линия наезжала на таб-хедеры (контент окна начинался сразу под
        # титлбаром). Вертикаль панели доходит до низа окна (height=-1).
        with dpg.theme() as rtheme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 16)
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
        self.root_theme = rtheme

        # Кнопки категорий: активная (accent-заливка) и неактивная (прозрачная)
        with dpg.theme() as caton:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Button, self.palette["accent"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, self.palette["accent_hover"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, self.palette["accent"])
                dpg.add_theme_color(dpg.mvThemeCol_Text, (16, 10, 36, 255))
        self.cat_on_theme = caton

        with dpg.theme() as catoff:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, self.palette["frame_hover"])
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, self.palette["frame_active"])
                dpg.add_theme_color(dpg.mvThemeCol_Text, self.palette["text_muted"])
        self.cat_off_theme = catoff

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
        # Мультипозиционные тогглы (хоткей перебирает строковое значение)
        for key, tag in list(self._sync_mode_tags.items()):
            try:
                cycle = toggle_registry.TOGGLE_CYCLE.get(key) or []
                want = str(snap.get(key, cycle[0] if cycle else "") or "")
                if str(dpg.get_value(tag)) != want:
                    dpg.set_value(tag, want)
            except Exception:
                pass
        if self._sync_mode_tags:
            self._update_noscope_panel()

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
                elif vtype == "combo_map":
                    # В списке - подпись, в конфиге - внутренний id
                    # (см. _config_combo_map): показываем подпись по id.
                    labels, values = extra
                    if val not in values:
                        val = default
                    dpg.set_value(item, labels[values.index(val)])
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
        # Превью вкладки "Прицел" (если вкладка уже собрана)
        self._redraw_crosshair_preview()
        # Видимость подвкладки "Точка ноускопа" по режиму
        self._update_noscope_panel()
        # ...и блока пользовательских цветов обводки (режим "Пользовательские")
        self._update_glow_panel()
        # Задержка триггера: блоки по режиму + перестройка таблицы
        # "дистанция -> задержка" из профиля (строки таблицы - динамические,
        # в _widget_reg их нет).
        self._update_trigger_delay_panels()
        self._rebuild_delay_rows(self._delay_rows_from_config())

    def _on_toggle_spectators(self, sender, value):
        self._config_set("EnableShowSpectators", bool(value))

    def _on_toggle_active_list(self, sender, value):
        """Мастер-галочка панели "Активные функции". Включение галочкой
        СРАЗУ показывает панель (не ждём мастер-хоткей), выключение прячет.
        Доступ (EnableActiveList) и видимость (ActiveListVisible) - два
        отдельных ключа: хоткей ToggleKey_EnableActiveList (биндится во
        всплывающем попапе галочки, как у остальных функций) переключает
        только видимость.
        """
        on = bool(value)
        self._config_set("EnableActiveList", on)
        self._config_set("ActiveListVisible", on)

    def _build_background(self):
        """Градиент вьюпорта (фиолетовый верх -> чёрный низ) позади окна +
        акцентная линия под титлбаром. viewport_drawlist(front=False):
        без клиппинга, в layout окна не участвует."""
        with dpg.viewport_drawlist(front=False) as dl:
            self.bg_dl = dl
            W, H = self.viewport_width, self.viewport_height
            # Плавный градиент: одна полоса на пиксель (H полос по 1px). 8-битный
            # цвет всё равно даёт видимые ступени (бандинг): шаг ~0.3/255 на
            # полосу - соседние полосы совпадают, скачок на 1/255 каждые
            # несколько пикселей образует полосы на больших участках фона.
            # Дизеринг (v8.4.2 ±2, v8.4.3 ±1) убран: зерно видно даже ±1 на
            # тёмном фоне. 8 бит на канал физически дают ступени (бандинг),
            # полосы 1px - самые мягкие из возможных; дизеринг заменяется
            # лёгкими переходами 1/255 каждые ~3px.
            bands = H
            top = self.palette["bg_top"]
            bot = self.palette["bg_bottom"]
            for i in range(bands):
                t = i / max(1, bands - 1)
                r = max(0, min(255, round(self.lerp(top[0], bot[0], t))))
                g = max(0, min(255, round(self.lerp(top[1], bot[1], t))))
                b = max(0, min(255, round(self.lerp(top[2], bot[2], t))))
                dpg.draw_rectangle(
                    (0, i),
                    (W, i + 1),
                    color=(0, 0, 0, 0),
                    fill=(r, g, b, 255),
                    thickness=0.0,
                )
            # Акцентная линия под титлбаром: титлбар ~28px + зазор
            # WindowPadding(0,16) = 44; линия на 36 видна в зазоре и
            # находится ВЫШЕ контента окна (панель/таб-хедеры 44+).
            x0, x1, y = 16, W - 16, 36
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
        if self._active_tab is None:
            self._active_tab = tab

    def _setup_categories(self):
        """Группировка вкладок по категориям левой панели. Порядок списка
        должен совпадать с порядком построения в build_ui (порядок табов в
        таб-баре определяется порядком создания)."""
        L = self._tab_by_label.get
        self._cat_tabs = {
            "Стрельба":     [L("Aimbot"), L("Контроль отдачи"), L("Triggerbot")],
            "Визуал":       [L("ESP & Visuals"), L("Цвета"), L("Обводка"), L("Кастомный прицел")],
            "Прочее":       [L("Бхоп"), L("Прочее"), L("Активные функции")],
            "Конфигурации": [L("Конфигурации")],
        }
        self._cat_tabs = {c: [t for t in ts if t is not None]
                          for c, ts in self._cat_tabs.items()}
        for cat, tabs in self._cat_tabs.items():
            if tabs and cat not in self._cat_last:
                self._cat_last[cat] = tabs[0]

    def _on_category(self, sender, app_data, user_data):
        self._apply_category(user_data)

    def _apply_category(self, cat):
        """Показывает субвкладки категории, скрывает остальные, активирует
        последнюю выбранную в этой категории (при старте - первую)."""
        if cat not in self._cat_tabs:
            return
        self._active_cat = cat
        for c, tabs in self._cat_tabs.items():
            on = (c == cat)
            for t in tabs:
                try:
                    dpg.configure_item(t, show=on)
                except Exception:
                    pass
            btn = self._cat_buttons.get(c)
            if btn is not None:
                try:
                    dpg.bind_item_theme(
                        btn, self.cat_on_theme if on else self.cat_off_theme)
                except Exception:
                    pass
        want = self._cat_last.get(cat) or self._cat_tabs[cat][0]
        try:
            dpg.set_value(self._tab_bar_id, want)
        except Exception:
            pass
        if want != self._active_tab:
            self._active_tab = want
            self._frame_sig = None

    def _on_tab_change(self, sender, app_data, user_data):
        # app_data в разных сборках DPG: тег вкладки или её label. Валидируем оба.
        tab = app_data
        if tab not in self._tab_tags:
            tab = self._tab_by_label.get(str(tab), self._active_tab)
        if tab != self._active_tab:
            self._active_tab = tab
            self._frame_sig = None  # принудительная перерисовка рамок
        # Запомнить выбор субвкладки в текущей категории (дизайн v8.1)
        if tab in self._tab_tags and self._cat_tabs:
            for cat, tabs in self._cat_tabs.items():
                if tab in tabs:
                    self._cat_last[cat] = tab
                    break

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
        # Смещение рамок на позицию правой области (таб-бар): локальные
        # rect карточек считаются от неё, на фронт-слое вьюпорта без
        # поправки рамки рисовались прижатыми к левому краю окна (v8.3).
        try:
            ra_pos = dpg.get_item_pos(getattr(self, "_right_area", None))
        except Exception:
            ra_pos = (0, 0)
        for (x0, y0), (x1, y1) in sig:
            dpg.draw_rectangle(
                (x0 + ra_pos[0], y0 + ra_pos[1]), (x1 + ra_pos[0], y1 + ra_pos[1]),
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
            self._hover_desc = dpg.add_text(
                "", color=self.palette["text_subtle"], wrap=210, show=False)
            self._hover_spacer = dpg.add_spacer(height=2)
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
        for row in self._hover_rows:
            try:
                st = dpg.get_item_state(row[0])
                if st and st.get("hovered"):
                    hovered = row
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

        if now > self._hover_linger:
            self._hover_clicked_close = False

        if hovered is not None:
            _item, key, label, bindable = hovered
            self._hover_target_rect = self._item_rect(_item)
            if self._hover_open_key != key:
                self._hover_open_key = key
                self._hover_current_key = key if bindable else None
                self._hover_show_at = now + 1.0
                desc = toggle_registry.DESCRIPTIONS.get(key, "")
                try:
                    dpg.set_value(self._hover_title, label)
                    dpg.set_value(self._hover_desc, desc)
                    dpg.configure_item(self._hover_desc, show=bool(desc))
                    dpg.configure_item(self._hover_spacer, show=bindable)
                    dpg.configure_item(self._hover_bind_btn, show=bindable)
                    dpg.configure_item(self._hover_reset_btn, show=bindable)
                    if bindable:
                        kname = toggle_registry.toggle_key_name(key)
                        dpg.configure_item(
                            self._hover_bind_btn,
                            user_data=kname,
                            label=self._key_label(self._config_get(kname, 0)),
                        )
                except Exception:
                    pass
            self._hover_linger = now + 0.35
        elif inside_popup:
            self._hover_linger = now + 0.35
        elif now > self._hover_linger and self._hover_open_key is not None:
            self._hover_open_key = None
            self._hover_current_key = None
            self._hover_show_at = 0.0
            self._hover_target_rect = None
            self._hover_clicked_close = False
            try:
                dpg.configure_item(self._hover_popup, show=False)
            except Exception:
                pass

        if self._hover_open_key is not None and not inside_popup:
            if self._hover_show_at > 0.0 and now >= self._hover_show_at:
                if not dpg.is_item_shown(self._hover_popup):
                    try:
                        r = self._hover_target_rect
                        if r is not None:
                            (x0, y0), (x1, y1) = r
                            px = min(x1 + 8, self.viewport_width - 226)
                            py = max(4, min(y0, self.viewport_height - 132))
                            dpg.set_item_pos(self._hover_popup, (px, py))
                        else:
                            px = min(mx + 14, self.viewport_width - 226)
                            py = max(4, min(my - 10, self.viewport_height - 132))
                            dpg.set_item_pos(self._hover_popup, (px, py))
                        dpg.configure_item(self._hover_popup, show=True)
                        # Не фокусим попап, чтобы текст функций не оказывался сверху при клике по чекбоксу
                    except Exception:
                        pass

    def _cat_texture_build(self):
        """Белый пиксельный кот: CAT_MATRIX (W x H символов) -> RGBA-текстура
        W*scale x H*scale в ближайшем соседе (без сглаживания пикселей).
        scale подбирается так, чтобы ширина не вылезала за контент панели.
        Возвращает (data, tag, w_px, h_px)."""
        try:
            n = len(CAT_MATRIX)                       # высота в "пикселях"
            w = max(len(r) for r in CAT_MATRIX)       # ширина в "пикселях"
            rows = [r.ljust(w, ".")[:w] for r in CAT_MATRIX]
            scale = max(3, min(9, (self.sidebar_w - 24) // w))
            data = []
            for y in range(n * scale):
                ry = y // scale
                row = rows[ry]
                for x in range(w * scale):
                    rx = x // scale
                    on = rx < len(row) and row[rx] == "#"
                    # Важно: плоский список чисел, а НЕ список кортежей:
                    # список кортежей в этой сборке DPG роняет рендер на
                    # уровне C (ACCESS_VIOLATION). int 0..255 - работает.
                    data.extend((255, 255, 255, 255) if on else (0, 0, 0, 0))
            tag = dpg.generate_uuid()
            with dpg.texture_registry(show=False):
                dpg.add_static_texture(
                    width=w * scale, height=n * scale,
                    default_value=data, tag=tag)
            return data, tag, w * scale, n * scale
        except Exception:
            return None, None, 0, 0

    def build_ui(self):
        self._build_background()
        with dpg.viewport_drawlist(front=True) as fdl:
            self.frames_dl = fdl

        # Текстура пиксельного кота (белый, без сглаживания - ближайший
        # сосед: масштаб подбирается в _cat_texture_build)
        self._cat_tex_data, self._cat_tex_tag, self._cat_w, self._cat_h = \
            self._cat_texture_build()

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
            try:
                dpg.bind_item_theme(root, self.root_theme)
            except Exception:
                pass

            with dpg.group(horizontal=True, horizontal_spacing=0):
                # --- Чёрная панель категорий слева ---
                with dpg.child_window(
                    width=self.sidebar_w,
                    height=-1,
                    border=False,
                    no_scrollbar=True,
                ) as sb:
                    self._sidebar = sb
                    dpg.bind_item_theme(sb, self.sidebar_theme)
                    with dpg.group():
                        for cat in ("Стрельба", "Визуал", "Прочее", "Конфигурации"):
                            b = dpg.add_button(
                                label=cat, width=-1,
                                callback=self._on_category, user_data=cat)
                            self._cat_buttons[cat] = b
                            if self.cat_off_theme is not None:
                                dpg.bind_item_theme(b, self.cat_off_theme)
                    # Кот прижат к низу панели: панель фиксированной высоты,
                    # категории - сверху, между ними spacer. Вправо на 16px:
                    # (ширина панели 160 - кот 128) / 2 - кот по центру.
                    # PANEL_TOP_OFFSET=61: 28 титлбар + 16 WindowPadding(root)
                    # + 17 эмпирическая дельта высоты контента child (замер
                    # v8.3: панель 719px при вьюпорте 780). Без поправки кот
                    # обрезался снизу (проверено: низ кота 786 > низ панели
                    # 763, scroll_max панели 23px).
                    pad = 14
                    cat_h = self._cat_h or 144
                    head = 4 * 34 + 3 * 8 + pad          # 4 кнопки + спейсинги
                    area_h = self.viewport_height - 61
                    spacer = area_h - head - cat_h - 24
                    dpg.add_spacer(height=max(12, int(spacer)))
                    if self._cat_tex_tag is not None:
                        with dpg.group(horizontal=True):
                            dpg.add_spacer(width=16)
                            dpg.add_image(self._cat_tex_tag,
                                          width=self._cat_w, height=self._cat_h)

                # --- Правая область: таб-бар с субвкладками категории ---
                with dpg.child_window(
                    width=-1,
                    height=-1,
                    border=False,
                ) as right_area:
                    self._right_area = right_area
                    with dpg.tab_bar(callback=self._on_tab_change) as tbar:
                        self._tab_bar_id = tbar
                        # Порядок построения = порядок субвкладок внутри
                        # категорий (см. _setup_categories).
                        self._build_tab_aimbot()
                        self._build_tab_recoil()
                        self._build_tab_triggerbot()
                        self._build_tab_visuals()
                        self._build_tab_colors()
                        self._build_tab_glow()
                        self._build_tab_crosshair()
                        self._build_tab_bhop()
                        self._build_tab_misc()
                        self._build_tab_active_list()
                        self._build_tab_configs()

        self._setup_categories()
        self._apply_category(self._active_cat)
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
            with dpg.group(horizontal=True, parent=container) as _rowhdr:
                dpg.add_spacer(width=12)
                header = dpg.add_group()
                dpg.add_text(title, color=self.palette["card_title"], parent=header)
                if subtitle:
                    dpg.add_text(
                        subtitle,
                        color=self.palette["text_subtle"],
                        parent=header
                    )
            dpg.add_separator(parent=container)
            dpg.add_spacer(height=10, parent=container)
            with dpg.group(horizontal=True, parent=container) as _rowbody:
                dpg.add_spacer(width=12)
                content = dpg.add_group()
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
                # 0.28/0.60 (было 0.34/0.54): child_window с no_scrollbar
                # КЛИПАЕТ контент по правой кромке, а лейбл слайдера рисуется
                # СПРАВА от бара и в ширину width не входит. При 0.54 контент
                # правой колонки = 0.54*900 - 2*WindowPadding(16) - 2*border(1)
                # = 452px, а слайдер «Экстраполяция ESP (мс)» с лейблом занимал
                # 512px -> лейблы обрезались (замер по item rect живого GUI).
                # Левой колонке 0.28 хватает с запасом: самый широкий её
                # элемент 189px при контенте 218px.
                # Колонки от content_w (ширина окна минус панель категорий):
                # левая чуть шире самого широкого элемента (189px), правая
                # растягивается на остаток (width=-1).
                # Колонки - обычные группы (не child_window): child_window в
                # горизонтальной группе растягивается на ВСЮ доступную
                # высоту ряда (замер: 623px вместо ~170 контента), из-за
                # этого слайдеры «Толщина линий» выталкивались за нижнюю
                # кромку карточки и пропадали (фикс v8.3). Группа растёт
                # по контенту и не клипает лейблы (нет собственных границ).
                left_col = dpg.add_group()
                right_col = dpg.add_group()

                dpg.add_text("Renderers", color=self.palette["text_muted"], parent=left_col)
                # Один вертикальный столбец: child_window клипает лейблы по
                # правой кромке, горизонтальный сплит внутри колонки оставлял
                # правому подстолбцу ~160px - длинные лейблы обрезались.
                self._config_checkbox("Skeleton", "EnableESPSkeletonRendering", parent=left_col)
                self._config_checkbox("Box", "EnableESPBoxRendering", parent=left_col)
                self._config_checkbox("Проверка на видимость", "ESP_VisibleCheckBox", parent=left_col)
                self._config_checkbox("Трейсеры", "EnableESPTracerRendering", parent=left_col)
                self._config_checkbox("Проверка на тиммейта", "EnableESPTeamCheck", parent=left_col)

                dpg.add_text("Визуал и толщина", color=self.palette["text_muted"], parent=right_col)
                dpg.add_spacer(height=2, parent=right_col)
                dpg.add_text("Синхронизация с HP", color=self.palette["text_subtle"], parent=right_col)
                self._config_checkbox("Skeleton базируется на HP", "ESP_HealthSyncSkeleton", default=True, parent=right_col)
                self._config_checkbox("HP Bar базируется на HP", "ESP_HealthSyncBar", default=True, parent=right_col)

                # Labels переехал в правую колонку (фикс v8.3): в левой
                # колонке блок из 10 галочек делал группу 531px, слайдеры
                # «Толщина линий» выталкивались за видимую область (747px)
                # карточки и пропадали из виду. Раскладка 5/7: левая ~200px,
                # правая ~318px - слайдеры остаются видимыми.
                dpg.add_spacer(height=10, parent=right_col)
                dpg.add_text("Labels", color=self.palette["text_muted"], parent=right_col)
                self._config_checkbox("Имя", "EnableESPNameText", parent=right_col)
                self._config_checkbox("Оружие", "EnableESPWeaponText", parent=right_col)
                self._config_checkbox("Дистанция", "EnableESPDistanceText", parent=right_col)
                self._config_checkbox("Вывод HP", "EnableESPHealthText", parent=right_col)
                self._config_checkbox("HP Bar", "EnableESPHealthBarRendering", parent=right_col)

                # Слайдеры толщины вынесены из правой колонки в отдельный блок
                # на всю ширину карточки (дизайн v8.1): в правой колонке им
                # не хватало ширины - слайдер «Экстраполяция ESP (мс)» с
                # лейблом занимает 300+162px, а контент колонки стал уже
                # из-за панели категорий слева.

            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)
            dpg.add_text("Толщина линий", color=self.palette["text_muted"], parent=card)

            s1 = self._config_slider_float("Размер Skeleton", "ESP_SkeletonThicknessScale", 1.0, 0.6, 2.0, parent=card)
            s2 = self._config_slider_float("Размер Box", "ESP_BoxThicknessScale", 1.0, 0.6, 2.0, parent=card)
            s3 = self._config_slider_float("Толщина HP Bar", "ESP_HealthBarThicknessScale", 1.0, 0.6, 1.6, parent=card)
            s4 = self._config_slider_float("Толщина трейсеров", "ESP_TracerThickness", 1.5, 0.5, 4.0, parent=card, format="%.1f")
            s5 = self._config_slider_int("Экстраполяция ESP (мс)", "ESP_ExtrapolateMs", 0, 0, 200, parent=card)
            # Бары слайдеров фиксированной ширины: лейбл справа не входит в
            # ширину бара (item rect = width + ~162px для самой широкой).
            for s in (s1, s2, s3, s4, s5):
                try:
                    dpg.configure_item(s, width=250)
                except Exception:
                    pass
            dpg.add_spacer(height=8, parent=card)

    def _build_tab_triggerbot(self):
        with dpg.tab(label="Triggerbot") as tab:
            self._bind_tab(tab, "Triggerbot")
            card = self._tab_card("Triggerbot", "Автоматический выстрел при наведении на врага.")
            self._trigger_enable_cb = self._config_combo(
                "Triggerbot", "TriggerbotMode",
                ["Выкл", "SadraKhorami", "Releotkamaza"], "SadraKhorami",
                parent=card)
            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)
            # «Проверка на тиммейта» (EnableTriggerbotTeamCheck) убрана
            # 2026-10-07: team check в triggerbot.py теперь безусловный
            # (требование «в прицеле тиммейт -> не стрелять»), галочка
            # врала бы возможностью отключения несуществующей опции.
            cb_ground = self._config_checkbox("Проверка на полёт", "TriggerbotRequireGround", default=True, parent=card)
            self._register_hover(cb_ground, "TriggerbotRequireGround",
                                 "Проверка на полёт", bindable=False)
            # Проверка на видимость (учитывает дым) — включена по умолчанию.
            # Аналогична ESP_VisibleCheckBox / EnableAimbotVisibilityCheck.
            cb_vis = self._config_checkbox("Проверка на видимость", "EnableTriggerbotVisibilityCheck", default=True, parent=card)
            self._register_hover(cb_vis, "EnableTriggerbotVisibilityCheck",
                                 "Не стрелять в врагов за дымом (серверная маска + локальный расчёт купола)", bindable=False)
            self._config_slider_float("Проверка скорости (стрельба при скорости ниже)", "TriggerbotSpeedThreshold", 5.0, 0.0, 200.0, parent=card, format="%.1f")
            # Задержка между выстрелами (мин. интервал), мс. 2026-10-19:
            # числовое поле ввода вместо ползунка (юзер: «ползунком неудобно,
            # вводом проще»); ключ и диапазон 0..5000 те же.
            self._config_input_float("Задержка между выстрелами, мс", "TriggerbotShotDelayMs",
                                     400.0, 0.0, 5000.0, parent=card, format="%.0f")

            # ---- Задержка срабатывания ----
            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)
            dpg.add_text("Задержка срабатывания", color=self.palette["text_muted"], parent=card)
            self._trigger_delay_mode_cb = self._config_combo_map(
                "Режим задержки", "TriggerbotDelayMode", DELAY_MODE_ITEMS,
                DELAY_MODE_DISTANCE, parent=card)

            # Панель "Статическая": один ползунок 0..500 мс.
            with dpg.group(parent=card) as panel_static:
                self._delay_panel_static = panel_static
                self._config_slider_float("Задержка, мс", "TriggerbotDelayStatic",
                                          50.0, DELAY_MS_MIN, DELAY_MS_MAX,
                                          parent=panel_static, format="%.0f")

            # Панель "Рандомная из промежутка": два поля (мин/макс), мс.
            with dpg.group(parent=card) as panel_range:
                self._delay_panel_range = panel_range
                self._config_input_float("Минимальная задержка, мс", "TriggerbotDelayMin",
                                         10.0, DELAY_MS_MIN, DELAY_MS_MAX,
                                         parent=panel_range, format="%.0f")
                self._config_input_float("Максимальная задержка, мс", "TriggerbotDelayMax",
                                         30.0, DELAY_MS_MIN, DELAY_MS_MAX,
                                         parent=panel_range, format="%.0f")

            # Панель "Рандомная от расстояния": таблица диапазонов
            # (дистанция -> задержка) + динамические строки (+/-).
            with dpg.group(parent=card) as panel_table:
                self._delay_panel_table = panel_table
                dpg.add_text("Диапазоны: расстояние (юниты) -> задержка (мс)",
                             color=self.palette["text_subtle"], parent=panel_table)
                self._delay_table_id = dpg.add_table(
                    header_row=True,
                    borders_innerH=True,
                    borders_outerH=True,
                    borders_innerV=True,
                    borders_outerV=True,
                    no_saved_settings=True,
                    parent=panel_table,
                )
                # Колонки: 4 поля + кнопка "-". Ширины подобраны так, чтобы
                # заголовки и значения НЕ обрезались (значения вводятся в
                # поля без кнопок шага, см. _add_delay_row: step=0).
                dpg.add_table_column(label="Расст. от", init_width_or_weight=100,
                                     width_fixed=True, parent=self._delay_table_id)
                dpg.add_table_column(label="Расст. до", init_width_or_weight=100,
                                     width_fixed=True, parent=self._delay_table_id)
                dpg.add_table_column(label="Задержка от, мс", init_width_or_weight=128,
                                     width_fixed=True, parent=self._delay_table_id)
                dpg.add_table_column(label="Задержка до, мс", init_width_or_weight=128,
                                     width_fixed=True, parent=self._delay_table_id)
                dpg.add_table_column(label="", init_width_or_weight=36,
                                     width_fixed=True, parent=self._delay_table_id)
                # Тема таблицы: шапка и сетка в цветах окна (иначе DPG рисует
                # дефолтную серую плашку, чуждую стилю). Дальше по коду - строки.
                with dpg.theme() as self._delay_table_theme:
                    with dpg.theme_component(dpg.mvAll):
                        dpg.add_theme_color(dpg.mvThemeCol_TableHeaderBg,
                                            self.palette["frame"])
                        dpg.add_theme_color(dpg.mvThemeCol_TableBorderStrong,
                                            self.palette["separator"])
                        dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight,
                                            (52, 40, 88, 110))
                        dpg.add_theme_color(dpg.mvThemeCol_TableRowBg, (0, 0, 0, 0))
                        dpg.add_theme_color(dpg.mvThemeCol_TableRowBgAlt, (0, 0, 0, 0))
                        dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 6, 4)
                dpg.bind_item_theme(self._delay_table_id, self._delay_table_theme)
                # Строки таблицы строятся из конфига (ниже), затем кнопка "+"
                # сразу после последнего ряда.
                self._rebuild_delay_rows(self._delay_rows_from_config())
                dpg.add_spacer(height=4, parent=panel_table)
                dpg.add_button(label="+##trigger_delay_row_add",
                               width=140, parent=panel_table,
                               callback=self._on_delay_row_add)
            self._update_trigger_delay_panels()

    # ---------- Triggerbot: таблица задержек по расстоянию ----------

    @staticmethod
    def _delay_rows_from_config_values(raw):
        """Нормализует TriggerbotDelayTable в список [d0, d1, ms0, ms1].
        Строки битые/неполные отбрасываются; границы упорядочиваются."""
        rows = []
        if not isinstance(raw, (list, tuple)):
            return rows
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) < 4:
                continue
            try:
                d0 = max(0.0, float(item[0]))
                d1 = max(0.0, float(item[1]))
                ms0 = max(DELAY_MS_MIN, min(DELAY_MS_MAX, float(item[2])))
                ms1 = max(DELAY_MS_MIN, min(DELAY_MS_MAX, float(item[3])))
            except (TypeError, ValueError):
                continue
            if d0 > d1:
                d0, d1 = d1, d0
            if ms0 > ms1:
                ms0, ms1 = ms1, ms0
            rows.append([d0, d1, ms0, ms1])
        return rows

    def _delay_rows_from_config(self):
        raw = self._config_get("TriggerbotDelayTable", None)
        if raw is None:
            # Первый запуск без ключа в конфиге: дефолт таблицы.
            raw = DELAY_TABLE_DEFAULT
        return self._delay_rows_from_config_values(raw)

    def _add_delay_row(self, values, record_to=None):
        """Создаёт строку таблицы задержек. values = [d0, d1, ms0, ms1].
        record_to - если задан, запись строки пишется в этот список (при
        перестройке из конфига); иначе - в self._delay_rows."""
        if self._delay_table_id is None:
            return None
        rec = {"row": None, "cells": []}
        # step=0.0 -> DPG НЕ рисует кнопки "-"/"+" внутри поля (при шаге != 0
        # они съедали ширину и обрезали число, путая с кнопкой удаления строки).
        # Ширина поля = колонка минус отступы ячейки (CellPadding 6x2), см.
        # блок колонок в _build_tab_triggerbot.
        cells_spec = (
            (0, DELAY_DIST_MAX, 88.0),   # дистанция от
            (0, DELAY_DIST_MAX, 88.0),   # дистанция до
            (DELAY_MS_MIN, DELAY_MS_MAX, 112.0),  # задержка от
            (DELAY_MS_MIN, DELAY_MS_MAX, 112.0),  # задержка до
        )
        with dpg.table_row(parent=self._delay_table_id) as row_id:
            rec["row"] = row_id
            for i, (lo, hi, col_w) in enumerate(cells_spec):
                cell = dpg.add_input_float(
                    default_value=float(values[i]),
                    min_value=lo, max_value=hi,
                    min_clamped=True, max_clamped=True,
                    step=0.0, format="%.0f", width=col_w,
                    callback=self._on_delay_row_change,
                    user_data=rec,
                )
                rec["cells"].append(cell)
            dpg.add_button(label="-", width=26,
                           callback=self._on_delay_row_delete, user_data=rec)
            rec["btn"] = dpg.get_item_children(row_id, 1)[-1]
        (self._delay_rows if record_to is None else record_to).append(rec)
        return rec

    def _rebuild_delay_rows(self, values):
        """Полная перестройка строк таблицы задержек по значениям из конфига
        (применение профиля). Пользовательские виджеты пересоздаются."""
        if self._delay_table_id is None:
            return
        for rec in list(self._delay_rows):
            try:
                dpg.delete_item(rec["row"])
            except Exception:
                pass
        self._delay_rows = []
        for row in values:
            self._add_delay_row(row)

    def _delay_table_values(self):
        """Текущее содержимое таблицы (порядок строк = визуальный) как
        список [d0, d1, ms0, ms1]."""
        values = []
        for rec in self._delay_rows:
            try:
                vals = [float(dpg.get_value(c)) for c in rec["cells"]]
            except Exception:
                continue
            vals[0] = max(0.0, vals[0])
            vals[1] = max(0.0, vals[1])
            vals[2] = max(DELAY_MS_MIN, min(DELAY_MS_MAX, vals[2]))
            vals[3] = max(DELAY_MS_MIN, min(DELAY_MS_MAX, vals[3]))
            values.append(vals)
        return values

    def _save_delay_table(self):
        self._config_set("TriggerbotDelayTable", self._delay_table_values())

    def _on_delay_row_change(self, sender, app_data, user_data):
        self._save_delay_table()

    def _on_delay_row_delete(self, sender, app_data, user_data):
        rec = user_data
        try:
            self._delay_rows.remove(rec)
        except ValueError:
            pass
        try:
            dpg.delete_item(rec["row"])
        except Exception:
            pass
        self._save_delay_table()

    def _on_delay_row_add(self, sender, app_data, user_data):
        # Новая строка продолжает таблицу: её начало = конец последней.
        if self._delay_rows:
            try:
                last = [float(dpg.get_value(c)) for c in self._delay_rows[-1]["cells"]]
                d0 = max(0.0, last[1])
            except Exception:
                d0 = 0.0
        else:
            d0 = 0.0
        d1 = min(DELAY_DIST_MAX, d0 + 250.0) if d0 < DELAY_DIST_MAX else DELAY_DIST_MAX
        self._add_delay_row([d0, d1, 10.0, 20.0])
        self._save_delay_table()

    def _update_trigger_delay_panels(self):
        """Видимость блоков задержки: ползунок / поля мин-макс / таблица
        по расстоянию. Как _update_noscope_panel/_update_glow_panel."""
        try:
            mode = str(self._config_get("TriggerbotDelayMode", DELAY_MODE_DISTANCE)
                       or DELAY_MODE_DISTANCE)
        except Exception:
            mode = DELAY_MODE_DISTANCE
        panels = (
            (self._delay_panel_static, mode == DELAY_MODE_STATIC),
            (self._delay_panel_range, mode == DELAY_MODE_RANGE),
            (self._delay_panel_table, mode == DELAY_MODE_DISTANCE),
        )
        for panel, on in panels:
            if panel is None:
                continue
            try:
                dpg.configure_item(panel, show=on)
            except Exception:
                pass

    def _build_tab_recoil(self):
        with dpg.tab(label="Контроль отдачи") as tab:
            self._bind_tab(tab, "Контроль отдачи")
            card = self._tab_card("Контроль отдачи", "Контроль отдачи оружия.")
            self._config_checkbox("Включение контроля отдачи", "EnableRecoilControl", parent=card)
            self._config_slider_float("Плавность контроля отдачи", "RecoilControlSmoothing", 1.5, 1.0, 3.0, parent=card, format="%.2f")

    # ==================== Вкладка "Прицел" ====================
    # Кастомный прицел (features/customcrosshair.py) + перенос точки
    # ноускопа из "Прочее". Колбек _xc_change: запись конфига + живое
    # превью. Регистрации в _widget_reg совместимы с _sync_all_widgets
    # (bool/int/float/"color"/"combo"), профили подхватывают значения.

    def _xc_change(self, sender, app_data, user_data):
        key, vtype = user_data
        value = app_data
        try:
            if vtype is bool:
                value = bool(app_data)
            elif vtype is int:
                value = int(app_data)
            elif vtype is float:
                value = float(app_data)
            elif vtype == "color":
                hexv = self._color_value_to_hex(app_data)
                if hexv is None:
                    self._redraw_crosshair_preview()
                    return
                value = hexv
            self._config_set(key, value)
            self._apply_derived_modes(key, value)
        except Exception as e:
            logutil.debug(f"[gui] xc change failed for {key}: {e}")
        self._redraw_crosshair_preview()

    def _preview_blend(self, hexstr, op01):
        """Альфа-имитация на белой подложке превью: c*op + 255*(1-op)."""
        r, g, b = self.hex_to_rgb(hexstr)
        return (int(round(r * op01 + 255 * (1.0 - op01))),
                int(round(g * op01 + 255 * (1.0 - op01))),
                int(round(b * op01 + 255 * (1.0 - op01))),
                255)

    def _redraw_crosshair_preview(self):
        """Перерисовка превью прицела и точки. Один bulk-снапшот конфига
        на вызов (IPC-канон). Нет drawlist'ов (вкладка не собрана) - выход."""
        if self._xc_preview_dl is None or self._dot_preview_dl is None:
            return
        try:
            snap = dict(self.config.items())
        except Exception:
            snap = {}
        # --- прицел ---
        try:
            W, H = self._xc_preview_size
            cx, cy = W // 2, H // 2
            dpg.delete_item(self._xc_preview_dl, children_only=True)
            dpg.draw_rectangle((0, 0), (W, H), color=(190, 190, 190, 255),
                               fill=(255, 255, 255, 255), parent=self._xc_preview_dl)
            th = max(1.0, min(10.0, float(snap.get("Crosshair_Thickness", 2.0) or 2.0)))
            ln = max(1.0, min(30.0, float(snap.get("Crosshair_Length", 8.0) or 8.0)))
            gap = max(0.0, min(20.0, float(snap.get("Crosshair_Gap", 4.0) or 4.0)))
            op = max(10, min(100, int(snap.get("Crosshair_Opacity", 100) or 100))) / 100.0
            hexc = snap.get("Crosshair_color", "#00FF00") or "#00FF00"
            outline = bool(snap.get("Crosshair_Outline", True))
            tshape = str(snap.get("Crosshair_Style", "Обычный") or "Обычный") == "T-образный"
            col = self._preview_blend(hexc, op)
            out_col = self._preview_blend("#000000", min(1.0, op + 0.25))
            half = th / 2.0
            segs = [
                (cx - gap - ln, cy - half, ln, th),
                (cx + gap,      cy - half, ln, th),
                (cx - half,     cy + gap,  th, ln),
            ]
            if not tshape:
                segs.append((cx - half, cy - gap - ln, th, ln))
            if outline:
                for (x, y, w, h) in segs:
                    dpg.draw_rectangle((x - 1, y - 1), (x + w + 1, y + h + 1),
                                       color=out_col, fill=out_col, parent=self._xc_preview_dl)
            for (x, y, w, h) in segs:
                dpg.draw_rectangle((x, y), (x + w, y + h),
                                   color=col, fill=col, parent=self._xc_preview_dl)
        except Exception as e:
            logutil.debug(f"[gui] xc preview: {e}")
        # --- точка ноускопа ---
        try:
            W, H = self._dot_preview_size
            cx, cy = W // 2, H // 2
            dpg.delete_item(self._dot_preview_dl, children_only=True)
            dpg.draw_rectangle((0, 0), (W, H), color=(190, 190, 190, 255),
                               fill=(255, 255, 255, 255), parent=self._dot_preview_dl)
            radius = max(1.0, min(12.0, float(snap.get("NoScopeDot_radius", 5.0) or 5.0)))
            op = max(10, min(100, int(snap.get("NoScopeDot_opacity", 80) or 80))) / 100.0
            hexc = snap.get("NoScopeDot_color", "#FFFFFF") or "#FFFFFF"
            col = self._preview_blend(hexc, op)
            dpg.draw_circle((cx, cy), max(1, int(round(radius))),
                            color=col, fill=col, parent=self._dot_preview_dl)
        except Exception as e:
            logutil.debug(f"[gui] dot preview: {e}")

    def _build_tab_crosshair(self):
        with dpg.tab(label="Кастомный прицел") as tab:
            self._bind_tab(tab, "Кастомный прицел")
            card = self._tab_card("Кастомный прицел", "Свой прицел поверх стандартного.")
            sw = int(self.content_w * 0.74)   # слайдеры почти во всю ширину контента

            # --- Кастомный прицел (мастер) ---
            cb = dpg.add_checkbox(
                label="Кастомный прицел",
                default_value=bool(self._config_get("EnableCustomCrosshair", False)),
                callback=self._xc_change,
                user_data=("EnableCustomCrosshair", bool),
                parent=card)
            self._widget_reg[cb] = ("EnableCustomCrosshair", bool, False, None)
            self._register_hover(cb, "EnableCustomCrosshair",
                                 "Кастомный прицел", bindable=False)

            # --- Noscope прицел (мультипозиционный тумблер) ---
            # "Выкл" | "Кастомный" | "Точка". Подвкладка "Точка ноускопа"
            # показывается только в положении "Точка".
            self._config_combo(
                "Noscope прицел", "NoScopeCrosshairMode",
                ["Выкл", "Кастомный", "Точка"], "Выкл",
                parent=card)

            with dpg.group(parent=card) as ns_panel:
                dpg.add_spacer(height=6)
                dpg.add_separator()
                dpg.add_spacer(height=6)
                dpg.add_text("Точка ноускопа", color=self.palette["text_muted"])
                s_dr = dpg.add_slider_float(
                    label="Радиус точки (px)",
                    default_value=float(self._config_get("NoScopeDot_radius", 5.0)),
                    min_value=1.0, max_value=12.0, format="%.1f",
                    callback=self._xc_change,
                    user_data=("NoScopeDot_radius", float))
                s_do = dpg.add_slider_int(
                    label="Непрозрачность точки (%)",
                    default_value=int(self._config_get("NoScopeDot_opacity", 80)),
                    min_value=10, max_value=100, format="%d%%",
                    callback=self._xc_change,
                    user_data=("NoScopeDot_opacity", int))
            self._xc_noscope_panel = ns_panel
            self._widget_reg[s_dr] = ("NoScopeDot_radius", float, 5.0, (1.0, 12.0))
            self._widget_reg[s_do] = ("NoScopeDot_opacity", int, 80, (10, 100))
            self._update_noscope_panel()

            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)

            # --- Форма и цвет ---
            dpg.add_text("Форма и цвет", color=self.palette["text_muted"], parent=card)
            cur_style = self._config_get("Crosshair_Style", "Обычный")
            if cur_style not in ("Обычный", "T-образный"):
                cur_style = "Обычный"
            cmb = dpg.add_combo(
                label="Тип прицела",
                items=["Обычный", "T-образный"],
                default_value=cur_style,
                callback=self._xc_change,
                user_data=("Crosshair_Style", "combo"),
                parent=card)
            self._widget_reg[cmb] = ("Crosshair_Style", "combo", "Обычный", ["Обычный", "T-образный"])

            hexc = self._config_get("Crosshair_color", "#00FF00") or "#00FF00"
            pk = dpg.add_color_picker(
                label="Цвет прицела",
                default_value=self.hex_to_rgb(hexc),
                no_alpha=True, no_inputs=True, no_side_preview=True, no_small_preview=True,
                width=90, height=90,
                callback=self._xc_change,
                user_data=("Crosshair_color", "color"),
                parent=card)
            self._widget_reg[pk] = ("Crosshair_color", "color", "#00FF00", None)

            s_op = dpg.add_slider_int(
                label="Непрозрачность (%)",
                default_value=int(self._config_get("Crosshair_Opacity", 100)),
                min_value=10, max_value=100, format="%d%%",
                callback=self._xc_change,
                user_data=("Crosshair_Opacity", int),
                parent=card)
            s_th = dpg.add_slider_float(
                label="Толщина (px)",
                default_value=float(self._config_get("Crosshair_Thickness", 2.0)),
                min_value=1.0, max_value=10.0, format="%.1f",
                callback=self._xc_change,
                user_data=("Crosshair_Thickness", float),
                parent=card)
            s_ln = dpg.add_slider_float(
                label="Длина (px)",
                default_value=float(self._config_get("Crosshair_Length", 8.0)),
                min_value=1.0, max_value=30.0, format="%.1f",
                callback=self._xc_change,
                user_data=("Crosshair_Length", float),
                parent=card)
            s_gp = dpg.add_slider_float(
                label="Зазор (px)",
                default_value=float(self._config_get("Crosshair_Gap", 4.0)),
                min_value=0.0, max_value=20.0, format="%.1f",
                callback=self._xc_change,
                user_data=("Crosshair_Gap", float),
                parent=card)
            cb_out = dpg.add_checkbox(
                label="Обводка",
                default_value=bool(self._config_get("Crosshair_Outline", True)),
                callback=self._xc_change,
                user_data=("Crosshair_Outline", bool),
                parent=card)
            self._widget_reg[cb_out] = ("Crosshair_Outline", bool, True, None)
            self._register_hover(cb_out, "Crosshair_Outline", "Обводка", bindable=False)
            for s in (s_op, s_th, s_ln, s_gp, s_dr, s_do):
                try:
                    dpg.configure_item(s, width=sw)
                except Exception:
                    pass

            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)

            # --- Предпросмотр: прицел + точка, белая подложка ---
            dpg.add_text("Предпросмотр", color=self.palette["text_muted"], parent=card)
            with dpg.group(horizontal=True, horizontal_spacing=14, parent=card):
                self._xc_preview_size = (300, 130)
                self._dot_preview_size = (150, 130)
                self._xc_preview_dl = dpg.add_drawlist(width=300, height=130)
                self._dot_preview_dl = dpg.add_drawlist(width=150, height=130)
            self._redraw_crosshair_preview()

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

            # Два ряда по 2 пикера (фикс v8.3): 4 колонки в один ряд на
            # 706px не влезали - лейбл «Скоп (крест+круг)» уезжал за правую
            # кромку окна. HP Bar и Скоп перенесены во второй ряд.
            with dpg.group(horizontal=True, horizontal_spacing=18, parent=card) as elem_row:
                self._config_color_element("Box", "EnableBoxCustomColor", "Box_color", elem_row)
                self._config_color_element("Трейсеры", "EnableTracerCustomColor", "Tracer_color", elem_row)
            with dpg.group(horizontal=True, horizontal_spacing=18, parent=card) as elem_row2:
                # Общий цвет креста и круга-границы скопа (ТЗ 2026-10-08);
                # галочка выкл -> чёрный, как раньше хардкод.
                self._config_color_element("HP Bar", "EnableHPBarCustomColor", "HPBar_color", elem_row2)
                self._config_color_element("Скоп (крест+круг)", "EnableNoScopeCustomColor", "NoScope_color", elem_row2)

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
                # Фикс 2026-10-08: у пикера не было callback -> цвет элемента
                # (Box/Tracer/HPBar/Скоп) никогда не сохранялся, в конфиг
                # шёл только дефолт. Как у FOV/Точка: пишем через
                # _on_widget_change -> _config_set(color_key, hex).
                user_data=(color_key, "color"),
                callback=self._on_widget_change,
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
        # Регистрация пикера: _sync_all_widgets подхватывает цвет из профиля
        # (config -> widget), как у остальных color-виджетов.
        self._widget_reg[pk] = (color_key, "color", default_hex, None)
        self._color_element_pickers[pk] = (cb_key, color_key, default_hex)
        return pk

    def _on_custom_color_toggle(self, sender, app_data, user_data):
        cb_key, picker_id = user_data
        self._config_set(cb_key, bool(app_data))
        try:
            dpg.configure_item(picker_id, enabled=bool(app_data))
        except Exception as e:
            logutil.debug(f"[gui] color picker toggle failed for {cb_key}: {e}")
        # Закрываем попап бинда при клике по чекбоксу
        if self._hover_open_key is not None:
            self._hover_clicked_close = True
            try:
                dpg.configure_item(self._hover_popup, show=False)
            except Exception:
                pass
            self._hover_open_key = None
            self._hover_current_key = None
            self._hover_show_at = 0.0
            self._hover_target_rect = None

    def _register_hover(self, item, key, label=None, bindable=None):
        """Регистрирует элемент в hover-попапе. bindable=True - фича с
        хоткеем (кнопка бинда + сброс), False - только заголовок/описание.
        Мультипозиционные тумблеры (TOGGLE_CYCLE) синкаются отдельно."""
        if label is None:
            label = self._toggle_labels.get(key, key)
        if bindable is None:
            bindable = key in self._toggle_labels
        self._hover_rows.append((item, key, label, bool(bindable)))
        if bindable:
            if key in toggle_registry.TOGGLE_CYCLE:
                self._sync_mode_tags[key] = item
            else:
                self._sync_tags[key] = item

    def _apply_derived_modes(self, key, value):
        """Производные ключи мультипозиционных тумблеров + видимость
        подвкладки точки ноускопа. Пишутся в конфиг, чтобы старые bool-
        ключи и профили оставались согласованными с режимом."""
        try:
            if key == "TriggerbotMode":
                mode = str(value or "Выкл")
                self._config_set("EnableTriggerbot", mode != "Выкл")
                self._config_set("TriggerbotWallbang", mode == "Releotkamaza")
            elif key == "TriggerbotDelayMode":
                # Видимость блоков задержки (ползунок / мин-макс / таблица)
                self._update_trigger_delay_panels()
            elif key == "NoScopeCrosshairMode":
                mode = str(value or "Выкл")
                self._config_set("EnableNoScopeDot", mode == "Точка")
                self._config_set("EnableNoScopeDotSeparate", mode in ("Кастомный", "Точка"))
                self._update_noscope_panel()
            elif key == "GlowMode":
                # Видимость блока своих цветов обводки (как у точки ноускопа)
                self._update_glow_panel()
        except Exception:
            pass

    def _update_noscope_panel(self):
        """Видимость группы «Точка ноускопа»: только в режиме "Точка"."""
        grp = self._xc_noscope_panel
        if grp is None:
            return
        try:
            mode = str(self._config_get("NoScopeCrosshairMode", "Выкл") or "Выкл")
            dpg.configure_item(grp, show=(mode == "Точка"))
        except Exception:
            pass

    def _update_glow_panel(self):
        """Видимость блока пользовательских цветов обводки: только в режиме
        "Custom" (в остальных режимах цвет задаёт игра) - та же логика, что у
        "Точки ноускопа" выше."""
        grp = getattr(self, "_glow_custom_panel", None)
        if grp is None:
            return
        try:
            mode = str(self._config_get("GlowMode", "Team") or "Team")
            dpg.configure_item(grp, show=(mode == "Custom"))
        except Exception:
            pass

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
            self._register_hover(cb, key)
        # При клике по чекбоксу закрываем попап бинда
        try:
            orig_cb = dpg.get_item_callback(cb)
            def wrapped(sender=cb, app_data=None, user_data=None):
                if self._hover_open_key is not None:
                    self._hover_clicked_close = True
                    try:
                        if self._hover_popup is not None:
                            dpg.configure_item(self._hover_popup, show=False)
                    except Exception:
                        pass
                    self._hover_open_key = None
                    self._hover_current_key = None
                    self._hover_show_at = 0.0
                    self._hover_target_rect = None
                if orig_cb is not None:
                    orig_cb(sender, app_data, user_data)
            dpg.set_item_callback(cb, wrapped)
        except Exception:
            pass
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

    def _config_input_float(self, label, key, default, min_value, max_value, parent=None,
                            format="%.1f", step=0.0, width=None):
        """Числовое поле (add_input_float) для конфига: точный ввод числа,
        в отличие от слайдера. Значение клампится в [min_value, max_value]
        (min_clamped/max_clamped), в _widget_reg пишется как float - значит
        синхронизируется с профилем (config -> widget) как слайдеры.
        step=0.0 по умолчанию: DPG при ненулевом шаге рисует ВНУТРИ поля
        кнопки "-"/"+" (съедают ширину, число обрезается) - нам нужен
        обычный ввод без них."""
        current = self._config_get(key, default)
        try:
            current = float(current)
        except (TypeError, ValueError):
            current = float(default)
        current = max(min_value, min(max_value, current))
        kwargs = {
            "default_value": current,
            "min_value": min_value,
            "max_value": max_value,
            "min_clamped": True,
            "max_clamped": True,
            "step": step,
            "format": format,
            "user_data": (key, float),
            "callback": self._on_widget_change,
            "width": self.control_width if width is None else width,
        }
        if label:
            kwargs["label"] = label
        if parent is not None:
            kwargs["parent"] = parent
        inp = dpg.add_input_float(**kwargs)
        self._widget_reg[inp] = (key, float, default, (min_value, max_value))
        return inp

    def _config_combo(self, label, key, items, default, parent=None, callback=None):
        current = self._config_get(key, default)
        if current not in items:
            current = default
        kwargs = {
            "label": label,
            "items": items,
            "default_value": current,
            "user_data": (key, "combo"),
            "callback": callback if callback is not None else self._on_widget_change,
            "width": self.control_width,
        }
        if parent is not None:
            kwargs["parent"] = parent
        cmb = dpg.add_combo(**kwargs)
        self._widget_reg[cmb] = (key, "combo", default, list(items))
        # Тоггл-фича из реестра: hover-попап бинда (мультипозиционные
        # тумблеры хоткей перебирает по кругу)
        if key in self._toggle_labels:
            self._register_hover(cmb, key)
        return cmb

    def _config_combo_map(self, label, key, pairs, default, parent=None):
        """Комбо с раздельными подписью и значением: в списке юзер видит
        pairs[i][0], в конфиг уходит pairs[i][1] (режимы хранятся внутренними
        id: "Team"/"Health"/"Custom"). Виджет, стиль и регистрация - как у
        _config_combo (type "combo_map" в _widget_reg), поэтому профили и
        синхронизация значений идут тем же путём."""
        labels = [p[0] for p in pairs]
        values = [p[1] for p in pairs]
        cur = self._config_get(key, default)
        if cur not in values:
            cur = default
        kwargs = {
            "label": label,
            "items": labels,
            "default_value": labels[values.index(cur)],
            "user_data": (key, "combo_map", (labels, values)),
            "callback": self._on_widget_change,
            "width": self.control_width,
        }
        if parent is not None:
            kwargs["parent"] = parent
        cmb = dpg.add_combo(**kwargs)
        self._widget_reg[cmb] = (key, "combo_map", default, (labels, values))
        if key in self._toggle_labels:
            self._register_hover(cmb, key)
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
        key = user_data[0]
        value_type = user_data[1]
        extra = user_data[2] if len(user_data) > 2 else None
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
        elif value_type == "combo_map":
            # В списке - подпись, в конфиг уходит внутренний id
            # (см. _config_combo_map).
            labels, values = extra
            if app_data not in labels:
                return
            value = values[labels.index(app_data)]
        else:
            value = app_data
        # При изменении из чекбокса (value_type bool) закрываем попап бинда
        if value_type is bool and self._hover_open_key is not None:
            try:
                if self._hover_popup is not None:
                    dpg.configure_item(self._hover_popup, show=False)
            except Exception:
                pass
            self._hover_open_key = None
            self._hover_current_key = None
            self._hover_show_at = 0.0
            self._hover_target_rect = None
            self._hover_clicked_close = True
        # Страховка диапазона: слайдер физически не выпускает значение за
        # min/max, а числовое поле (add_input_float) клампит только при вводе
        # с клавиатуры — программный set_value кламп не применяет (проверено
        # пробой 2026-10-19). Поэтому клампим по диапазону из _widget_reg и
        # возвращаем клампнутое значение в сам виджет, чтобы UI не врал.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            reg = self._widget_reg.get(sender)
            if (reg is not None and reg[1] in (int, float)
                    and isinstance(reg[3], (tuple, list)) and len(reg[3]) == 2):
                try:
                    lo, hi = float(reg[3][0]), float(reg[3][1])
                except (TypeError, ValueError):
                    lo = hi = None
                if lo is not None:
                    clamped = max(lo, min(hi, float(value)))
                    if value_type is int:
                        clamped = int(round(clamped))
                    if clamped != value:
                        value = clamped
                        try:
                            dpg.set_value(sender, value)
                        except Exception:
                            pass
        self._config_set(key, value)
        # Производные ключи мультипозиционных тумблеров
        self._apply_derived_modes(key, value)

    def _build_tab_misc(self):
        with dpg.tab(label="Прочее") as tab:
            self._bind_tab(tab, "Прочее")
            card = self._tab_card("Прочее", "Прочие различные настройки.")
            self._config_checkbox("Удаление чёрноты скопа", "EnableNoScopeOverlay", parent=card)
            # Общая толщина линий креста и круга-границы скопа (ТЗ 2026-10-08):
            # ползунок стоит прямо под галочкой снятия скопа.
            self._config_slider_float("Толщина линий скопа (крест и круг)", "NoScopeThickness",
                                      1.0, 1.0, 5.0, parent=card, format="%.1f")
            # Точка ноускопа (галочка + радиус + непрозрачность) переехала
            # во вкладку "Прицел" (v6.3), ключи прежние.
            self._config_checkbox("Включение таймера бомбы", "EnableESPBombTimer", parent=card)
            # Позиция карточки бомбы в оверлее: X/Y в % (0 = левый/верхний
            # край, 100 = правый/нижний), как у панели активных функций.
            self._config_slider_int("Позиция таймера X, %", "BombTimerPosX", 2, 0, 100, parent=card)
            self._config_slider_int("Позиция таймера Y, %", "BombTimerPosY", 33, 0, 100, parent=card)
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
                self._register_hover(spec_cb, "EnableShowSpectators")
            try:
                orig_cb = dpg.get_item_callback(spec_cb)
                def wrapped(sender=spec_cb, app_data=None, user_data=None):
                    if self._hover_open_key is not None:
                        self._hover_clicked_close = True
                        try:
                            if self._hover_popup is not None:
                                dpg.configure_item(self._hover_popup, show=False)
                        except Exception:
                            pass
                        self._hover_open_key = None
                        self._hover_current_key = None
                        self._hover_show_at = 0.0
                        self._hover_target_rect = None
                    if orig_cb is not None:
                        orig_cb(sender, app_data, user_data)
                dpg.set_item_callback(spec_cb, wrapped)
            except Exception:
                pass
            # Позиция панели зрителей в оверлее: X/Y в % (0 = левый/верхний
            # край, 100 = правый/нижний). Дефолт повторяет прежний вид
            # (правый край, по центру по вертикали).
            self._config_slider_int("Позиция списка X, %", "SpectatorPosX", 98, 0, 100, parent=card)
            self._config_slider_int("Позиция списка Y, %", "SpectatorPosY", 50, 0, 100, parent=card)
            dpg.add_text("Позиции в % от краёв монитора: 0 = левый верх, 100 = правый низ.",
                         color=self.palette["text_subtle"], parent=card)
            self._config_checkbox("FOV Changer", "EnableFovChanger", parent=card)
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

    def _build_tab_active_list(self):
        """Вкладка "Активные функции" (категория "Прочее"). Список активных
        функций рисуется ТОЛЬКО в оверлее игры (features/active_list.py,
        паттерн панели зрителей), поверх CS2. В окне настроек панели нет
        (v8.5: превью-окно убрано - мешало и висело на всех вкладках).
        Мастер-хоткей показа/скрытия ставится во всплывающем попапе галочки,
        как у остальных функций: он переключает ActiveListVisible. Позиция
        окна в игре - ползунки X/Y (% от монитора), чекбоксы "показывать ли
        функцию в списке". Колонки - обычные группы (не child_window): child
        в горизонтальной группе растягивается на всю высоту ряда (баг v8.3)."""
        with dpg.tab(label="Активные функции") as tab:
            self._bind_tab(tab, "Активные функции")
            card = self._tab_card("Активные функции", "Вывод активных функций")
            al_cb = dpg.add_checkbox(
                label="Включение активных функций",
                default_value=bool(self._config_get("EnableActiveList", True)),
                callback=self._on_toggle_active_list,
                parent=card,
            )
            dpg.add_spacer(height=8, parent=card)
            # Хоткей - как у остальных функций: всплывающий попап на галочке
            # (кнопка бинда пишет ToggleKey_EnableActiveList, сброс обнуляет).
            self._register_hover(al_cb, "EnableActiveList",
                                 label="Включение активных функций", bindable=True)
            try:
                orig_cb = dpg.get_item_callback(al_cb)

                def _al_wrapped(sender=al_cb, app_data=None, user_data=None):
                    if self._hover_open_key is not None:
                        self._hover_clicked_close = True
                        try:
                            if self._hover_popup is not None:
                                dpg.configure_item(self._hover_popup, show=False)
                        except Exception:
                            pass
                        self._hover_open_key = None
                        self._hover_current_key = None
                        self._hover_show_at = 0.0
                        self._hover_target_rect = None
                    if orig_cb is not None:
                        orig_cb(sender, app_data)

                dpg.set_item_callback(al_cb, _al_wrapped)
            except Exception:
                pass
            dpg.add_spacer(height=8, parent=card)
            dpg.add_text("Окно со списком показывается в игре (поверх CS2).",
                         color=self.palette["text_subtle"], parent=card)
            dpg.add_text("Позиция ниже - в % от краёв монитора: 0 = левый верх, 100 = правый низ.",
                         color=self.palette["text_subtle"], parent=card)
            # Ползунки позиции окна в игре (% от монитора). Пишут штатно:
            # _on_widget_change -> SharedOptions, оверлей берёт позицию из
            # local_opts (обновляется раз в 100 мс в главном цикле main.py).
            self._config_slider_int("Позиция окна X, %", "ActiveListPosX", 70, 0, 100, parent=card)
            self._config_slider_int("Позиция окна Y, %", "ActiveListPosY", 4, 0, 100, parent=card)
            dpg.add_spacer(height=6, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=6, parent=card)
            dpg.add_text("Отображать в списке:", color=self.palette["text_muted"], parent=card)
            feats = list(toggle_registry.TOGGLE_FEATURES)
            half = (len(feats) + 1) // 2
            with dpg.group(horizontal=True, horizontal_spacing=18, parent=card) as _cols:
                left_col = dpg.add_group()
                right_col = dpg.add_group()
                for key, label in feats[:half]:
                    self._config_checkbox(label, "ListShow_" + key, default=True, parent=left_col)
                for key, label in feats[half:]:
                    self._config_checkbox(label, "ListShow_" + key, default=True, parent=right_col)

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

    # ==================== Вкладка «Обводка» (glow) ====================
    def _build_tab_glow(self):
        """Обводка персонажей (glow). Настройки пишутся в общий конфиг
        (self._config_set -> SharedOptions); воркер features/glow.py читает
        их раз в кадр и патчит блок glow у сущности."""
        with dpg.tab(label="Обводка") as tab:
            self._bind_tab(tab, "Обводка")
            card = self._tab_card("Обводка", "Обводка персонажей, так называемый glow.")

            self._config_checkbox("Включить обводку", "EnableGlow", parent=card)

            dpg.add_spacer(height=8, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=8, parent=card)

            # Селектор режима - тот же виджет, что у тригера и точки ноускопа
            # (выплывающий список _config_combo_map: подпись в списке, "Team"/
            # "Health"/"Custom" в конфиге), а не радиокнопки с заголовком.
            self._config_combo_map(
                "Режим цвета", "GlowMode",
                [("По командам (КТ/Т)", "Team"),
                 ("По здоровью (HP)", "Health"),
                 ("Пользовательские", "Custom")],
                "Team", parent=card)
            dpg.add_spacer(height=4, parent=card)
            dpg.add_text(
                "«По командам» и «По здоровью» берут цвета из игры (КТ - синий, "
                "Т - оранжевый / по остатку HP), свои цвета там не используются.",
                color=self.palette["text_subtle"], parent=card, wrap=520,
            )

            dpg.add_spacer(height=8, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=8, parent=card)

            self._config_checkbox("Показывать врагов", "GlowShowEnemies", parent=card)
            self._config_checkbox("Показывать союзников", "GlowShowAllies", parent=card)

            dpg.add_spacer(height=8, parent=card)
            dpg.add_separator(parent=card)
            dpg.add_spacer(height=8, parent=card)

            # Блок своих цветов живёт только в режиме "Пользовательские" -
            # как подвкладка "Точка ноускопа" у прицела (та же логика показа).
            with dpg.group(parent=card) as glow_cols:
                dpg.add_text("Пользовательские цвета (режим «Пользовательские»)",
                             color=self.palette["text_muted"])
                dpg.add_spacer(height=4)
                with dpg.group(horizontal=True, horizontal_spacing=18):
                    self._glow_color_picker("Противники", "GlowEnemyColor", "#FF5555")
                    self._glow_color_picker("Союзники", "GlowAllyColor", "#55AAFF")
            self._glow_custom_panel = glow_cols
            self._update_glow_panel()

    def _glow_color_picker(self, label, color_key, default_hex):
        """Пикер цвета glow. Пишет hex в конфиг через _on_widget_change
        (тот же путь, что у остальных цветов вкладки «Цвета»)."""
        default_hex = self._config_get(color_key, default_hex) or default_hex
        pk = dpg.add_color_picker(
            label=label,
            default_value=self.hex_to_rgb(default_hex),
            no_alpha=True,
            no_inputs=True,
            no_side_preview=True,
            no_small_preview=True,
            width=100,
            height=100,
            user_data=(color_key, "color"),
            callback=self._on_widget_change,
        )
        self._widget_reg[pk] = (color_key, "color", default_hex, None)
        return pk


def run_gui(Options, Runtime, Flags=None):
    gui = NERON_GUI(Options, Runtime, Flags)
    gui.run()

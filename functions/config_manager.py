import json
import os
import re
import time

import win32api

from functions import logutil

# Папка профилей: корень репо (functions/..), рядом со settings.json
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_DIR = os.path.join(_REPO_DIR, "cfg")
_BINDS_FILE = os.path.join(CFG_DIR, "_binds.json")

BINDS_POLL_INTERVAL = 1.0     # перечитывание файла биндов движком
KEY_DEBOUNCE = 0.2            # пауза перед опросом клавиш (отпускание ЛКМ)

# Служебные ключи, не попадающие в снапшот профиля
NO_SNAPSHOT_EXCLUDE = {"NoScopeActive"}

_NAME_RE = re.compile(r"[^\w\-\ ]", re.UNICODE)
_NAME_MAX = 32


def sanitize_name(raw):
    """Имя профиля: только буквы/цифры/_/пробел/дефис, без ведущего '_'.
    None - если имя невалидно."""
    if not isinstance(raw, str):
        return None
    name = _NAME_RE.sub("_", raw.strip())
    if not name or name.startswith("_") or len(name) > _NAME_MAX:
        return None
    return name


class ConfigManager:
    """Файловые операции с профилями cfg/*.json и биндами cfg/_binds.json."""

    def __init__(self, cfg_dir=CFG_DIR):
        self.cfg_dir = cfg_dir
        self._binds_path = os.path.join(cfg_dir, "_binds.json")

    def list(self):
        """Имена профилей (отсортированные), служебные файлы исключены."""
        try:
            names = []
            for fn in os.listdir(self.cfg_dir):
                if fn.endswith(".json") and not fn.startswith("_"):
                    names.append(fn[:-5])
            return sorted(names)
        except Exception:
            return []

    def _path(self, name):
        return os.path.join(self.cfg_dir, name + ".json")

    def save(self, name, settings):
        """Сохранить снапшот настроек как профиль. False - имя невалидно."""
        name = sanitize_name(name)
        if not name or not isinstance(settings, dict):
            return False
        try:
            os.makedirs(self.cfg_dir, exist_ok=True)
            data = {k: v for k, v in settings.items()
                    if k not in NO_SNAPSHOT_EXCLUDE and not k.startswith("__")}
            with open(self._path(name), "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logutil.debug(f"[config] save '{name}' failed: {e}")
            return False

    def load(self, name):
        """Профиль как dict, None при отсутствии/битом файле."""
        if not name:
            return None
        try:
            with open(self._path(name), "r", encoding="utf-8") as fp:
                data = json.load(fp)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def delete(self, name):
        """Удалить профиль и его бинд. False - имя невалидно."""
        name = sanitize_name(name)
        if not name:
            return False
        try:
            os.remove(self._path(name))
        except Exception:
            pass
        self.set_bind(name, 0)
        return True

    # ---------- Бинды переключения ----------

    def _read_binds(self):
        try:
            with open(self._binds_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            binds = data.get("binds")
            return binds if isinstance(binds, dict) else {}
        except Exception:
            return {}

    def get_bind(self, name):
        return int(self._read_binds().get(name, 0) or 0)

    def set_bind(self, name, vk):
        """vk=0 снимает бинд. False - имя невалидно."""
        name = sanitize_name(name)
        if not name:
            return False
        try:
            os.makedirs(self.cfg_dir, exist_ok=True)
            binds = self._read_binds()
            try:
                vk = int(vk or 0)
            except Exception:
                vk = 0
            if vk > 0:
                binds[name] = vk
            else:
                binds.pop(name, None)
            with open(self._binds_path, "w", encoding="utf-8") as fp:
                json.dump({"binds": binds}, fp, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logutil.debug(f"[config] set_bind '{name}' failed: {e}")
            return False

    def all_binds(self):
        return {str(k): int(v or 0) for k, v in self._read_binds().items()}


def apply_profile(name, cfgmgr, Options, SharedFlags=None, local_opts=None):
    """Загрузка профиля в Options (ManagedConfig -> автосейв settings.json).
    Единый путь для кнопки GUI и хоткея движка. Возвращает True при успехе."""
    data = cfgmgr.load(name)
    if data is None:
        print(f"[config] профиль '{name}' не найден или битый - загрузка пропущена")
        logutil.debug(f"[config] apply '{name}': missing/corrupt")
        return False
    data = {k: v for k, v in data.items()
            if k not in NO_SNAPSHOT_EXCLUDE and not k.startswith("__")}
    try:
        Options.update(data)
    except Exception as e:
        logutil.debug(f"[config] apply '{name}' options update failed: {e}")
        return False
    if local_opts is not None:
        try:
            local_opts.update(data)
        except Exception:
            pass
    if SharedFlags is not None:
        try:
            SharedFlags["config_ts"] = time.time()
        except Exception:
            pass
    return True


class ConfigHotkeyEngine:
    """Хоткеи переключения профилей. Бинды - в cfg/_binds.json (вне настроек:
    загрузка профиля не стирала бинды). Файл перечитывается раз в
    BINDS_POLL_INTERVAL. Во время захвата клавиши GUI (флаг capture) молчит,
    prev-состояния сбрасываются - отпускание биндимой клавиши не даёт фронт."""

    def __init__(self, cfgmgr, SharedFlags=None):
        self.cfgmgr = cfgmgr
        self.flags = SharedFlags
        self._binds = {}
        self._binds_ts = 0.0
        self._prev = {}

    def _refresh_binds(self, now):
        if now - self._binds_ts >= BINDS_POLL_INTERVAL:
            self._binds_ts = now
            self._binds = self.cfgmgr.all_binds()

    def _capture_active(self):
        if self.flags is None:
            return False
        try:
            return bool(self.flags.get("capture", False))
        except Exception:
            return False

    def poll(self, local_opts, Options):
        now = time.time()
        self._refresh_binds(now)
        if self._capture_active():
            self._prev.clear()
            return
        for name, code in self._binds.items():
            if code <= 0:
                self._prev[name] = False
                continue
            try:
                pressed = bool(win32api.GetAsyncKeyState(code) & 0x8000)
            except Exception:
                pressed = False
            was = self._prev.get(name, False)
            self._prev[name] = pressed
            if pressed and not was:
                apply_profile(name, self.cfgmgr, Options, self.flags, local_opts)
# markers: END functions/config_manager.py v1
import ctypes
import threading
import time
from typing import Dict, Iterable, Optional
import pymem
from pymem.process import module_from_name
from functions import logutil

# GetExitCodeProcess: код STILL_ACTIVE у живого процесса, иначе он завершился.
_STILL_ACTIVE = 259
_k32 = ctypes.windll.kernel32
_k32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
_k32.GetExitCodeProcess.restype = ctypes.c_int

# Как часто проверять живость процесса (в секундах). Проверка - один сисколл,
# но в циклах на 1000 Гц её нельзя делать каждую итерацию.
_ALIVE_CHECK_INTERVAL = 0.5


class ProcessConnector:
    def __init__(
        self,
        process_name: str,
        modules: Optional[Iterable[str]] = None,
        poll_interval: float = 1.0,
    ) -> None:
        self.process_name = process_name
        self.poll_interval = max(0.1, float(poll_interval))
        self._lock = threading.Lock()
        self._proc: Optional[pymem.Pymem] = None
        self._module_cache: Dict[str, int] = {}
        self._module_whitelist = {m.lower() for m in modules} if modules else set()
        self._alive_ts = 0.0

    @staticmethod
    def _proc_alive(proc: pymem.Pymem) -> bool:
        """Живой ли ещё процесс у этого хэндла.

        pymem держит хэндл до close() и НЕ проверяет смерть процесса: чтение
        атрибута process_handle никогда не падает. Без этой проверки после
        закрытия/перезапуска CS2 чит остаётся со СТАРЫМ хэндлом и СТАРЫМ
        кэшем баз модуля - фичи молча перестают работать (ESP/glow/nosmoke/
        fovchanger), а записи уходят в мёртвый хэндл. Fail-open: если саму
        проверку сделать не удалось, считаем процесс живым (поведение не хуже
        прежнего и никаких ложных переподключений)."""
        try:
            handle = proc.process_handle
            if not handle:
                return False
            code = ctypes.c_ulong(0)
            if not _k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                return True
            return int(code.value) == _STILL_ACTIVE
        except Exception:
            return True

    def _wait_for_process(self) -> pymem.Pymem:
        while True:
            try:
                proc = pymem.Pymem(self.process_name)
                return proc
            except Exception:
                logutil.debug(f"[proc] waiting for process {self.process_name} ...")
                time.sleep(self.poll_interval)

    def _wait_for_module(self, module_name: str) -> int:
        module_key = module_name.lower()
        while True:
            proc = self.ensure_process()
            try:
                module = module_from_name(proc.process_handle, module_name)
                if module:
                    return module.lpBaseOfDll
            except Exception:
                self.invalidate()
                continue
            logutil.debug(f"[proc] waiting for module {module_name} ...")
            time.sleep(self.poll_interval)

    def ensure_process(self) -> pymem.Pymem:
        now = time.time()
        with self._lock:
            proc = self._proc
        if proc is not None:
            # Живость проверяем не чаще _ALIVE_CHECK_INTERVAL (сисколл).
            if now - self._alive_ts < _ALIVE_CHECK_INTERVAL:
                return proc
            if self._proc_alive(proc):
                self._alive_ts = now
                return proc
            logutil.debug("[proc] процесс завершился - переподключаемся")
            self.invalidate()
        new_proc = self._wait_for_process()
        with self._lock:
            self._module_cache.clear()
            self._proc = new_proc
        self._alive_ts = time.time()
        return new_proc

    def ensure_module(self, module_name: str) -> int:
        key = module_name.lower()
        with self._lock:
            cached = self._module_cache.get(key)
            if cached:
                return cached
        base = self._wait_for_module(module_name)
        with self._lock:
            self._module_cache[key] = base
        return base

    def invalidate(self) -> None:
        with self._lock:
            # КРИТИЧНО: закрываем хэндл перед обнулением
            if self._proc is not None:
                try:
                    self._proc.close()
                except Exception:
                    pass
            self._proc = None
            self._module_cache.clear()

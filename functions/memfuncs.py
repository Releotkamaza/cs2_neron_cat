import struct
import ctypes
import threading

from ext.datatypes import *

# ==================== Быстрый слой чтения ====================
# Прямой ReadProcessMemory вместо pymem-обвязки: чтение - самое горячее
# место (ESP-сканер, триггер, аим). Семантика: при СБОЕ RPM буфер
# ОБНУЛЯЕТСЯ (ноль вместо ошибки, исключения нет) - верхние уровни
# валидируют значения valid_ptr/falsy-чеками. Буферы переиспользуются
# (thread-local, рендер и ридер ESP живут в одном процессе и не дерутся
# за буфер), lookup kernel32 и argtypes настраиваются один раз.
# Обнуление только в ветке сбоя: быстрый путь не платит memset.
_k32 = ctypes.windll.kernel32
_RPM = _k32.ReadProcessMemory
_RPM.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                 ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
_RPM.restype = ctypes.c_int

_tls = threading.local()


def _tbuf(size):
    """Переиспользуемый буфер на поток. ВАЖНО: валиден только до следующего
    _tbuf того же размера в этом потоке - наружу не возвращать (ReadBytes
    отдаёт копию .raw)."""
    bufs = getattr(_tls, "bufs", None)
    if bufs is None:
        bufs = _tls.bufs = {}
    buf = bufs.get(size)
    if buf is None:
        buf = ctypes.create_string_buffer(size)
        bufs[size] = buf
    return buf


def _rpm_buf(handle, address, size):
    buf = _tbuf(size)
    # 0 = полный сбой чтения (частичное чтение через границу недоступной
    # страницы по MSDN тоже фейл). Без проверки буфер держал бы СТАРЫЕ
    # данные прошлого чтения - "призраки" вместо нулей.
    if not _RPM(handle, address, buf, size, None):
        ctypes.memset(buf, 0, size)
    return buf


class ProcMemHandler:
    @staticmethod
    def ReadPointer(proc, address):
        return struct.unpack_from('<q', _rpm_buf(proc.process_handle, address, 8), 0)[0]

    @staticmethod
    def ReadBytes(proc, address, bytes_count):
        return _rpm_buf(proc.process_handle, address, bytes_count).raw

    @staticmethod
    def WriteBytes(proc, address, newbytes):
        return proc.write_bytes(address, newbytes, len(newbytes))

    @staticmethod
    def ReadInt(proc, address):
        return struct.unpack_from('<i', _rpm_buf(proc.process_handle, address, 4), 0)[0]

    @staticmethod
    def ReadFloat(proc, address):
        return struct.unpack_from('<f', _rpm_buf(proc.process_handle, address, 4), 0)[0]

    @staticmethod
    def ReadVec(proc, address):
        buf = _rpm_buf(proc.process_handle, address, 12)
        x, y, z = struct.unpack_from('fff', buf, 0)
        return Vector3(x, y, z)

    @staticmethod
    def ReadUShort(proc, address):
        return struct.unpack_from('H', _rpm_buf(proc.process_handle, address, 2), 0)[0]

    @staticmethod
    def ReadUInt(proc, address):
        return struct.unpack_from('<I', _rpm_buf(proc.process_handle, address, 4), 0)[0]

    @staticmethod
    def ReadBool(proc, address):
        return struct.unpack_from('?', _rpm_buf(proc.process_handle, address, 1), 0)[0]

    @staticmethod
    def ReadString(proc, address, length):
        try:
            raw = ProcMemHandler.ReadBytes(proc, address, length)
            # Ищем конец строки (нулевой байт)
            null_idx = raw.find(b'\x00')
            if null_idx != -1:
                raw = raw[:null_idx]
            # Декодируем с игнорированием ошибок, чтобы кракозябры не крашили софт
            return raw.decode('utf-8', errors='ignore')
        except Exception:
            return "?"

    @staticmethod
    def ReadMatrix(proc, address):
        bytes_ = ProcMemHandler.ReadBytes(proc, address, 4 * 16)
        matrix = struct.unpack('16f', bytes_)
        matrix = Matrix([
            [matrix[0], matrix[1], matrix[2], matrix[3]],
            [matrix[4], matrix[5], matrix[6], matrix[7]],
            [matrix[8], matrix[9], matrix[10], matrix[11]],
            [matrix[12], matrix[13], matrix[14], matrix[15]]])
        return matrix

    @staticmethod
    def WriteInt(proc, address, value):
        return proc.write_int(address, value)

    @staticmethod
    def WriteFloat(proc, address, value):
        return proc.write_float(address, value)

    @staticmethod
    def WriteBool(proc, address, value):
        return proc.write_bool(address, value)

import os
import hashlib
import tempfile
from functions import fontpaths
from functions import logutil

_CACHE = {}
_TMPDIR = os.path.join(tempfile.gettempdir(), "neron_unicode_text")
_CAPABLE = None
_PRINTED = set()   # чтобы не спамить одинаковыми ошибками

# ===========================================================================
# Посимвольный подбор шрифта (font fallback).
# Основной шрифт рисует что может; недостающие глифы добираются из
# системных шрифтов Windows (они уже лицензированы пользователю его ОС,
# мы ничего не бандлим) и из .ttf/.otf/.ttc, которые пользователь
# сам положил в папку fonts/ (drag&drop-расширяемость).
# ===========================================================================

_WIN_FONTS_DIR = None

def _win_fonts_dir():
    global _WIN_FONTS_DIR
    if _WIN_FONTS_DIR is None:
        windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
        _WIN_FONTS_DIR = os.path.join(windir, "Fonts") if windir else ""
    return _WIN_FONTS_DIR

# Системные кандидаты по приоритету (специализированные раньше).
_SYSTEM_CANDIDATES = (
    "seguisym.ttf",  # Segoe UI Symbol: ♡ ❄  ⌈ ⌋ и тысячи символов
    "seguiemj.ttf",  # Segoe UI Emoji: эмодзи-наборы
    "seguihis.ttf",  # Segoe UI Historic: 𓆩 𓆪 египетские иероглифы, древние письмена
    "msyh.ttc",      # Microsoft YaHei: CJK (仁 廾 ...)
    "simsun.ttc",    # SimSun: CJK запасной
    "leelawui.ttf",  # Leelawadee UI: тайский (ภ ...)
    "tahoma.ttf",    # Tahoma: широкая_coverage старых Windows
    "segoeui.ttf",   # Segoe UI: расширенная латиница, диакритика
    "arial.ttf",     # последний системный фолбэк
)

_CHAIN = None
_FONT_OBJ_CACHE = {}
_HAS_GLYPH_CACHE = {}
_PROBE_CH = "\uFFFE"  # гарантированный non-character: всегда .notdef

def _err(tag, e):
    key = (tag, str(e))
    if key not in _PRINTED:
        _PRINTED.add(key)
        print(f"[textrender] {tag}: {type(e).__name__}: {e}", flush=True)
        logutil.debug(f"[textrender] {tag}: {type(e).__name__}: {e}")

def _probe(pme):
    global _CAPABLE
    if _CAPABLE is not None:
        return _CAPABLE
    ok = False
    try:
        import PIL  # noqa
        ok = hasattr(pme, "load_texture") and hasattr(pme, "draw_texture")
        if not ok:
            _err("probe", Exception("no load_texture/draw_texture in pyMeow"))
    except Exception as e:
        _err("probe", e)
        ok = False
    _CAPABLE = ok
    return ok

def _font_path():
    base = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(base, ".."))
    p = fontpaths.locate_font(anchors=[base, repo])
    if p:
        return p
    wd = _win_fonts_dir()
    if wd:
        for fname in ("segoeui.ttf", "arial.ttf", "verdana.ttf"):
            cand = os.path.join(wd, fname)
            if os.path.exists(cand):
                return cand
    return None

def _user_fonts():
    """Все ttf/otf/ttc из папки fonts/ проекта (drag&drop-расширяемость)."""
    out = []
    base = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(base, ".."))
    for anchor in (base, repo):
        d = os.path.join(anchor, "fonts")
        if not os.path.isdir(d):
            continue
        try:
            for fn in sorted(os.listdir(d)):
                if fn.lower().endswith((".ttf", ".otf", ".ttc")):
                    p = os.path.join(d, fn)
                    if p not in out:
                        out.append(p)
        except Exception:
            pass
    return out

def _build_chain():
    chain = []
    primary = _font_path()
    if primary:
        chain.append(primary)
    for p in _user_fonts():
        if p not in chain:
            chain.append(p)
    wd = _win_fonts_dir()
    if wd:
        for fn in _SYSTEM_CANDIDATES:
            p = os.path.join(wd, fn)
            if os.path.exists(p) and p not in chain:
                chain.append(p)
    return chain

def _chain():
    global _CHAIN
    if _CHAIN is None:
        _CHAIN = _build_chain()
    return _CHAIN

def _get_font(path, size):
    key = (path, int(size))
    f = _FONT_OBJ_CACHE.get(key)
    if f is None:
        from PIL import ImageFont
        f = ImageFont.truetype(path, int(size))
        _FONT_OBJ_CACHE[key] = f
    return f

_SIG_CACHE = {}

def _glyph_sig(f, ch):
    """Сигнатура битмапа глифа: (w, h, md5). Рендерим через ImageDraw —
    это работает на любой версии Pillow, в отличие от getmask().tobytes()."""
    key = (id(f), ch)
    sig = _SIG_CACHE.get(key)
    if sig is None:
        try:
            from PIL import Image, ImageDraw
            asc, desc = f.getmetrics()
            w = max(8, int(f.getlength(ch)) + 4)
            h = max(8, asc + desc + 4)
            img = Image.new("L", (w, h), 0)
            d = ImageDraw.Draw(img)
            d.text((2, asc + 2), ch, font=f, anchor="ls", fill=255)
            sig = (w, h, hashlib.md5(img.tobytes()).digest())
        except Exception:
            sig = (0, 0, None)
        _SIG_CACHE[key] = sig
    return sig

def _font_has_glyph(f, ch):
    """Есть ли в шрифте реальный глиф: битмап отличается от .notdef."""
    try:
        a = _glyph_sig(f, ch)
        if a[2] is None:
            return False
        b = _glyph_sig(f, _PROBE_CH)
        if b[2] is None:
            return True
        if a == b:
            # Совпало с .notdef — глифа нет
            return False
        return True
    except Exception:
        return False

def _pick_font(ch, size):
    for p in _chain():
        try:
            f = _get_font(p, size)
        except Exception:
            continue
        if _font_has_glyph(f, ch):
            return f
    try:
        return _get_font(_chain()[0], size)
    except Exception:
        return None

def _layout(text, size):
    """Посимвольная раскладка: [(ch, font, advance)] + метрики и ширина."""
    items = []
    asc = desc = 0
    width = 0.0
    for ch in text:
        f = _pick_font(ch, size)
        if f is None:
            return None, 0, 0, 0.0
        a, d = f.getmetrics()
        asc = max(asc, a)
        desc = max(desc, d)
        adv = f.getlength(ch)
        items.append((ch, f, adv))
        width += adv
    return items, asc, desc, width

def _make_texture(pme, text, size):
    try:
        from PIL import Image, ImageDraw
        items, asc, desc, width = _layout(text, size)
        if not items:
            _err("make_texture", Exception("no fonts available at all"))
            return None
        pad = 2
        w = int(width) + pad * 2 + 2
        h = asc + desc + pad * 2
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        x = float(pad)
        baseline = pad + asc
        try:
            for ch, f, adv in items:
                d.text((x, baseline), ch, font=f, anchor="ls", fill=(255, 255, 255, 255))
                x += adv
        except Exception:
            # Старый Pillow без anchor: рисуем через bbox каждого глифа
            x = float(pad)
            for ch, f, adv in items:
                l, t, r, b = f.getbbox(ch)
                d.text((x - l, baseline - t), ch, font=f, fill=(255, 255, 255, 255))
                x += adv
        os.makedirs(_TMPDIR, exist_ok=True)
        fname = os.path.join(_TMPDIR, hashlib.md5(f"{text}|{size}".encode("utf-8")).hexdigest() + ".png")
        img.save(fname, "PNG")
        tex = pme.load_texture(fname)
        return (tex, -pad, -pad)
    except Exception as e:
        _err("make_texture", e)
        return None

_DRAW_VARIANT = None

def _draw(pme, tex, x, y, color):
    global _DRAW_VARIANT
    x = float(x); y = float(y)
    variants = (
        (tex, x, y, 0.0, 1.0, color),           # (tex, x, y, rotation, scale, tint)
        (tex, int(x), int(y), 0.0, 1.0, color), # (tex, x:int, y:int, rotation, scale, tint)
        (tex, x, y, color, 0.0, 1.0),           # (tex, x, y, tint, rotation, scale)
        (tex, x, y, 0.0, color, 1.0),           # (tex, x, y, rotation, tint, scale)
        (tex, x, y, color),                     # (tex, x, y, tint)
    )
    if _DRAW_VARIANT is not None:
        try:
            pme.draw_texture(*variants[_DRAW_VARIANT])
            return True
        except Exception:
            _DRAW_VARIANT = None
    for i, args in enumerate(variants):
        try:
            pme.draw_texture(*args)
            _DRAW_VARIANT = i
            return True
        except TypeError:
            continue
        except Exception as e:
            _err("draw_texture", e)
            return False
    # Ни один вариант не подошёл - печатаем реальную сигнатуру для диагностики
    try:
        _err("draw_texture_sig", Exception(str(getattr(pme.draw_texture, "__doc__", "no doc"))))
    except Exception:
        pass
    return False

def draw_unicode(pme, text, x, y, size, color):
    """Рисует текст с любыми символами текстурой. True = успели, False = фолбэк."""
    if not _probe(pme):
        return False
    key = (text, int(size))
    entry = _CACHE.get(key)
    if entry is None:
        entry = _make_texture(pme, text, size)
        if entry is None:
            return False
        if len(_CACHE) > 200:
            for old_key, old_entry in list(_CACHE.items())[:64]:
                try:
                    pme.unload_texture(old_entry[0])
                except Exception:
                    pass
                _CACHE.pop(old_key, None)
        _CACHE[key] = entry
    tex, ox, oy = entry
    return _draw(pme, tex, int(x) + ox, int(y) + oy, color)
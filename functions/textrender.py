import os
import hashlib
import tempfile
from functions import fontpaths
from functions import logutil

_CACHE = {}
_TMPDIR = os.path.join(tempfile.gettempdir(), "neron_unicode_text")
_CAPABLE = None
_PRINTED = set()   # чтобы не спамить одинаковыми ошибками


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
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windir:
        for fname in ("segoeui.ttf", "arial.ttf", "verdana.ttf"):
            cand = os.path.join(windir, "Fonts", fname)
            if os.path.exists(cand):
                return cand
    return None


def _make_texture(pme, text, size):
    try:
        from PIL import Image, ImageDraw, ImageFont
        fp = _font_path()
        if not fp:
            _err("font", Exception("font not found"))
            return None
        font = ImageFont.truetype(fp, int(size))
        tmp = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(tmp)
        l, t, r, b = d.textbbox((0, 0), text, font=font)
        w = max(1, r - l)
        h = max(1, b - t)
        pad = 2
        img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((pad - l, pad - t), text, font=font, fill=(255, 255, 255, 255))
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
        (tex, x, y, 0.0, 1.0, color),        # (tex, x, y, rotation, scale, tint)
        (tex, int(x), int(y), 0.0, 1.0, color),  # (tex, x:int, y:int, rotation, scale, tint)
        (tex, x, y, color, 0.0, 1.0),        # (tex, x, y, tint, rotation, scale)
        (tex, x, y, 0.0, color, 1.0),        # (tex, x, y, rotation, tint, scale)
        (tex, x, y, color),                  # (tex, x, y, tint)
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
    """Рисует текст с кириллицей текстурой. True = успели, False = фолбэк."""
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
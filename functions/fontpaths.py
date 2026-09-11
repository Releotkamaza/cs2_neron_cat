import os
from typing import Iterable, List, Optional

DEFAULT_FONT_FILENAME = "inter-semibold.ttf"
_FALLBACK_EXTS = (".ttf", ".otf", ".ttc")

def _unique_paths(paths: Iterable[str]) -> List[str]:
    seen = set()
    unique = []
    for path in paths:
        if not path:
            continue
        norm = os.path.normpath(path)
        if norm not in seen:
            seen.add(norm)
            unique.append(norm)
    return unique

def _fonts_dirs(anchors: Optional[Iterable[str]]) -> List[str]:
    dirs = []
    for anchor in (anchors or []):
        if not anchor:
            continue
        anchor = os.path.abspath(anchor)
        dirs.append(anchor)
        dirs.append(os.path.join(anchor, "fonts"))
    cwd = os.getcwd()
    dirs.append(os.path.join(cwd, "fonts"))
    dirs.append(cwd)
    return _unique_paths(dirs)

def font_candidates(
    font_filename: str = DEFAULT_FONT_FILENAME,
    anchors: Optional[Iterable[str]] = None,
) -> List[str]:
    candidates = [os.path.join(d, font_filename) for d in _fonts_dirs(anchors)]
    return _unique_paths(candidates)

def _any_font_in(dirs: List[str]) -> Optional[str]:
    """Drag&drop-фолбэк: любой шрифт из папки fonts/, первый по алфавиту."""
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            names = sorted(fn for fn in os.listdir(d) if fn.lower().endswith(_FALLBACK_EXTS))
        except Exception:
            continue
        if names:
            return os.path.join(d, names[0])
    return None

def locate_font(
    font_filename: str = DEFAULT_FONT_FILENAME,
    anchors: Optional[Iterable[str]] = None,
) -> Optional[str]:
    for cand in font_candidates(font_filename, anchors):
        if os.path.exists(cand):
            return cand
    return _any_font_in(_fonts_dirs(anchors))
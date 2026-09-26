from __future__ import annotations
import sys
from PySide6.QtCore import QRect, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from .geometry import clamp_window_rect

BURGUNDY = "#7b1020"
BURGUNDY_DARK = "#5f0c19"
BURGUNDY_PALE = "#fcf7f7"
BURGUNDY_PALE_2 = "#fcf7f7"
AMBER = "#d98919"
TEXT = "#2b2b2b"
BORDER = "#d8c4c9"


def app_icon_path(base_dir):
    return base_dir / "resources" / "pstbskx.png"


def apply_windows_caption_color(window, color: str = BURGUNDY):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(window.winId())
        DWMWA_CAPTION_COLOR = 35
        DWMWA_TEXT_COLOR = 36
        def colorref(hexcolor):
            c = QColor(hexcolor)
            return c.red() | (c.green() << 8) | (c.blue() << 16)
        cap = ctypes.c_int(colorref(color))
        txt = ctypes.c_int(colorref("#ffffff"))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(cap), ctypes.sizeof(cap))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR, ctypes.byref(txt), ctypes.sizeof(txt))
    except Exception:
        pass


def restore_window_geometry(window, config: dict, key: str, default_size=(1280, 800), minimum_size=(320, 240)):
    screens = []
    primary = QGuiApplication.primaryScreen()
    ordered = []
    if primary is not None:
        ordered.append(primary)
    for s in QGuiApplication.screens():
        if s not in ordered:
            ordered.append(s)
    for s in ordered:
        r = s.availableGeometry()
        screens.append((r.x(), r.y(), r.width(), r.height()))

    saved = None
    raw = config.get("windows", {}).get(key)
    if isinstance(raw, dict):
        try:
            saved = (int(raw["x"]), int(raw["y"]), int(raw["w"]), int(raw["h"]))
        except Exception:
            saved = None
    x, y, w, h = clamp_window_rect(saved, screens, default_size, minimum_size)
    # The outer scroll area owns overflow; never force a window larger than the
    # current monitor's available area.
    if screens:
        window.setMinimumSize(min(minimum_size[0], screens[0][2]), min(minimum_size[1], screens[0][3]))
    window.setGeometry(QRect(x, y, w, h))
    if isinstance(raw, dict) and raw.get("maximized") is True:
        QTimer.singleShot(0, window.showMaximized)


def save_window_geometry(window, config: dict, key: str):
    g = window.normalGeometry() if window.isMaximized() or window.isMinimized() else window.geometry()
    config.setdefault("windows", {})[key] = {
        "x": int(g.x()), "y": int(g.y()), "w": int(g.width()), "h": int(g.height()),
        "maximized": window.isMaximized(),
    }


def common_stylesheet():
    return f"""
        QMainWindow {{ background:{BURGUNDY_PALE}; }}
        QWidget#pageRoot {{ background:{BURGUNDY_PALE}; color:{TEXT}; }}
        QFrame#card {{ background:#fffafa; border:1px solid {BORDER}; border-radius:9px; }}
        QGroupBox {{
            background:#fffafa; border:1px solid {BORDER}; border-radius:8px;
            margin-top:12px; padding-top:8px; font-weight:700;
        }}
        QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 5px; color:{BURGUNDY}; }}
        QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget {{
            background:white; color:{TEXT}; border:1px solid #cdbcc0; border-radius:5px; padding:4px;
        }}
        QComboBox QAbstractItemView {{ background:white; color:{TEXT}; selection-background-color:{BURGUNDY}; selection-color:white; }}
        QComboBox:on {{ background:#fff8f9; color:{TEXT}; }}
        QLineEdit::selection, QPlainTextEdit::selection {{ background:{BURGUNDY}; color:white; }}
        QListWidget::item:selected {{ background:{BURGUNDY}; color:white; }}
        QPushButton {{
            background:#f1e5e8; border:1px solid #bc9fa6; border-radius:6px; padding:7px 10px;
        }}
        QPushButton:hover {{ background:#e7cbd2; border-color:#a15869; }}
        QPushButton:disabled {{ background:#f7f4f4; color:#777; border-color:#d7d0d0; }}
        QPushButton:checked {{ background:{BURGUNDY}; color:white; border-color:{BURGUNDY}; }}
        QPushButton#autoCQ:checked, QPushButton#autoCQ:checked:hover {{ background:#c52234; color:#ffffff; border:2px solid #9b1424; font-weight:800; }}
        QRadioButton {{ background:transparent; color:{BURGUNDY}; font-weight:700; }}
        QRadioButton::indicator:checked {{ background:{BURGUNDY}; border:2px solid white; border-radius:7px; }}
        QPushButton#primary {{ background:{BURGUNDY}; color:white; border-color:{BURGUNDY}; font-weight:700; }}
        QPushButton#primary:hover {{ background:#bf3650; border-color:#9a1c31; }}
        QPushButton#primary:disabled {{ background:#e3d9dc; color:#625b5d; border-color:#cfc5c8; }}
        QMenuBar {{ background:#f8f0f1; color:{TEXT}; }}
        QMenuBar::item:selected {{ background:#e4c7ce; }}
        QMenu {{ background:white; color:{TEXT}; }}
        QMenu::item:selected {{ background:{BURGUNDY}; color:white; }}
        QStatusBar {{ background:#f8f0f1; }}
        QProgressBar {{ background:white; border:1px solid #cdbcc0; border-radius:4px; max-height:15px; }}
        QProgressBar::chunk {{ background:#398b67; border-radius:3px; }}
    """

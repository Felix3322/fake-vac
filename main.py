#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import ctypes
import ctypes.wintypes as wt
from PySide6.QtCore import Qt, QTimer, QPoint, QEvent, QEasingCurve, Property, QUrl
from PySide6.QtGui import QPixmap, QMouseEvent, QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QFrame, QVBoxLayout
from PySide6.QtWebEngineWidgets import QWebEngineView

# ==== Win32 API ====
user32 = ctypes.WinDLL("user32", use_last_error=True)

EnumWindows = user32.EnumWindows
EnumWindows.restype = wt.BOOL
EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]

IsWindowVisible = user32.IsWindowVisible
IsWindowVisible.argtypes = [wt.HWND]
IsWindowVisible.restype = wt.BOOL

GetWindowTextW = user32.GetWindowTextW
GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, wt.INT]
GetWindowTextW.restype = wt.INT

GetWindowRect = user32.GetWindowRect
GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
GetWindowRect.restype = wt.BOOL

GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.restype = wt.HWND

IsIconic = user32.IsIconic
IsIconic.argtypes = [wt.HWND]
IsIconic.restype = wt.BOOL


def find_window_by_title_exact(title: str):
    """找到标题完全匹配的可见窗口"""
    result = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def enum_proc(hwnd, lParam):
        if not IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        GetWindowTextW(hwnd, buf, 512)
        if buf.value.strip() == title:
            result.append(hwnd)
            return False
        return True

    EnumWindows(enum_proc, 0)
    return result[0] if result else None


def get_window_rect(hwnd):
    r = wt.RECT()
    if not GetWindowRect(hwnd, ctypes.byref(r)):
        raise OSError("GetWindowRect failed")
    return r.left, r.top, r.right, r.bottom


def is_window_covered_or_not_foreground(hwnd_steam, hwnd_overlay) -> bool:
    """
    “被覆盖/不前台”的判据：
      - Steam 窗口被最小化 -> True
      - 前台窗口既不是 Steam，也不是 Overlay -> True
      - 其余情况（前台是 Steam 或 Overlay） -> False
    """
    try:
        if not hwnd_steam:
            return True
        if IsIconic(hwnd_steam):
            return True
        fg = GetForegroundWindow()
        if fg == hwnd_steam:
            return False
        if hwnd_overlay and fg == hwnd_overlay:
            return False
        return True
    except Exception:
        # 保守策略：异常时认为被覆盖（隐藏）
        return True


# ================== SteamShell 部分 ==================
class Theme:
    SHELL = "#32373f"
    PANEL_BG = "#32373f"

    TOP_FROM = "#02bded"
    TOP_TO = "#2d4dab"
    TOP_H = 2

    BORDER_TOP = 36
    BORDER_BOTTOM = 36
    BORDER_LEFT = 28
    BORDER_RIGHT = 28

    CLOSE_W = 46
    CLOSE_H = 36
    CLOSE_FONT_PT = 14

    CLOSE_IDLE_BG = QColor(0, 0, 0, 0)
    CLOSE_HOVER_BG = QColor(0xD3, 0x2F, 0x2F)
    CLOSE_PRESS_BG = QColor(0xB7, 0x1C, 0x1C)
    CLOSE_TEXT_IDLE = QColor(0xE6, 0xE6, 0xE6)
    CLOSE_TEXT_ON = QColor(0xFF, 0xFF, 0xFF)

    ANIM_MS = 120


class CloseButton(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg = Theme.CLOSE_IDLE_BG
        self._pressed = False
        self.setFixedSize(Theme.CLOSE_W, Theme.CLOSE_H)
        self.setCursor(Qt.ArrowCursor)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        from PySide6.QtCore import QPropertyAnimation
        self._anim = QPropertyAnimation(self, b"backgroundColor", self)
        self._anim.setDuration(Theme.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)

        self._font = QFont()
        self._font.setPointSize(Theme.CLOSE_FONT_PT)

    def getBackgroundColor(self): return self._bg
    def setBackgroundColor(self, c: QColor):
        if self._bg != c:
            self._bg = c
            self.update()
    backgroundColor = Property(QColor, getBackgroundColor, setBackgroundColor)

    def _animate_to(self, color: QColor):
        self._anim.stop()
        self._anim.setStartValue(self._bg)
        self._anim.setEndValue(color)
        self._anim.start()

    def enterEvent(self, e): self._animate_to(Theme.CLOSE_HOVER_BG)
    def leaveEvent(self, e): self._animate_to(Theme.CLOSE_IDLE_BG)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._pressed = True
            self._animate_to(Theme.CLOSE_PRESS_BG)
    def mouseReleaseEvent(self, e):
        if self._pressed and e.button() == Qt.LeftButton:
            self._pressed = False
            inside = self.rect().contains(e.position().toPoint())
            if inside:
                self._animate_to(Theme.CLOSE_HOVER_BG)
                w = self.window()
                if isinstance(w, QWidget):
                    w.close()
            else:
                self._animate_to(Theme.CLOSE_IDLE_BG)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), self._bg)
        text_color = Theme.CLOSE_TEXT_ON if self._bg.alpha() > 0 else Theme.CLOSE_TEXT_IDLE
        p.setPen(QPen(text_color))
        p.setFont(self._font)
        p.drawText(self.rect(), Qt.AlignCenter, "✕")


class SteamShell(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Steam VAC Shell")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.resize(862, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top_line = QFrame()
        top_line.setFixedHeight(Theme.TOP_H)
        top_line.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {Theme.TOP_FROM}, stop:1 {Theme.TOP_TO}); border:none;"
        )
        root.addWidget(top_line)

        self.chrome = QFrame()
        self.chrome.setStyleSheet(f"background:{Theme.SHELL}; border:none;")
        root.addWidget(self.chrome, 1)

        chrome_v = QVBoxLayout(self.chrome)
        chrome_v.setContentsMargins(
            Theme.BORDER_LEFT, Theme.BORDER_TOP,
            Theme.BORDER_RIGHT, Theme.BORDER_BOTTOM
        )
        chrome_v.setSpacing(0)

        panel = QFrame()
        panel.setStyleSheet(f"background:{Theme.PANEL_BG}; border:none;")
        panel_v = QVBoxLayout(panel)
        panel_v.setContentsMargins(0, 0, 0, 0)
        panel_v.setSpacing(0)

        self.web = QWebEngineView()
        self.web.setContextMenuPolicy(Qt.NoContextMenu)
        self.web.setStyleSheet("QWebEngineView{border:none; background:transparent;}")
        panel_v.addWidget(self.web)
        chrome_v.addWidget(panel, 1)

        self.btn_close = CloseButton(self.chrome)
        self.btn_close.raise_()

        self._drag_pt: QPoint | None = None
        self.chrome.installEventFilter(self)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        x = int(self.chrome.width() - Theme.CLOSE_W)
        y = 0
        self.btn_close.move(max(0, x), max(0, y))

    def eventFilter(self, obj, ev):
        if obj is self.chrome:
            et = ev.type()
            if self.btn_close.underMouse():
                return False
            if et == QEvent.MouseButtonPress:
                me: QMouseEvent = ev
                if me.button() == Qt.LeftButton and self._in_border(me.position().toPoint()):
                    self._drag_pt = me.globalPosition().toPoint()
                    return True
            if et == QEvent.MouseMove:
                me: QMouseEvent = ev
                if self._drag_pt and (me.buttons() & Qt.LeftButton):
                    delta = me.globalPosition().toPoint() - self._drag_pt
                    self.move(self.pos() + delta)
                    self._drag_pt = me.globalPosition().toPoint()
                    return True
            if et == QEvent.MouseButtonRelease:
                self._drag_pt = None
                return True
        return super().eventFilter(obj, ev)

    def _in_border(self, pt):
        x, y = pt.x(), pt.y()
        w, h = self.chrome.width(), self.chrome.height()
        if x < Theme.BORDER_LEFT: return True
        if y < Theme.BORDER_TOP: return True
        if x >= w - Theme.BORDER_RIGHT: return True
        if y >= h - Theme.BORDER_BOTTOM: return True
        return False

    def set_html(self, html: str):
        self.web.setHtml(html)

    def set_url(self, url: str | QUrl):
        self.web.setUrl(url if isinstance(url, QUrl) else QUrl(url))


# ================== Overlay 部分 ==================
class OverlayWindow(QWidget):
    def __init__(self, image_path, hwnd_parent, rel_offset):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)

        self.pixmap = QPixmap(image_path)
        self.hwnd_parent = hwnd_parent
        self.rel_offset = rel_offset

        self.resize(170, 25)
        self.label.setPixmap(
            self.pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

        # 定时器：跟随 + 可见性检查
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1)

        # 保存已开的 shell
        self.shells: list[SteamShell] = []

    def _tick(self):
        """跟随 + 显隐控制（忽略自己）"""
        try:
            # 取自己的 HWND（winId 在首次调用时会创建句柄）
            hwnd_overlay = int(self.winId())
        except Exception:
            hwnd_overlay = 0

        # 1) 显隐控制：Steam 最小化或前台既不是 Steam 也不是 Overlay -> 隐藏
        covered = is_window_covered_or_not_foreground(self.hwnd_parent, hwnd_overlay)
        if covered and self.isVisible():
            self.hide()
        elif not covered and not self.isVisible():
            self.show()

        # 2) 位置跟随
        try:
            if self.hwnd_parent:
                l, t, r, b = get_window_rect(self.hwnd_parent)
                dx, dy = self.rel_offset
                self.move(r + dx, t + dy)
        except Exception:
            pass

        # 3) 清理已关闭的 shell
        if self.shells:
            self.shells = [w for w in self.shells if w is not None and w.isVisible()]

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            # 每次点击都新建一个窗口
            shell = SteamShell()
            shell.show()
            shell.set_html("""<!DOCTYPE html>

<html class="responsive touch" lang="zh-cn">
<head>
<meta charset="utf-8"/>
<meta content="width=device-width,initial-scale=1" name="viewport"/>
<meta content="#171a21" name="theme-color"/>
<title>VAC 游戏封禁警示</title>
<link href="/favicon.ico" rel="shortcut icon" type="image/x-icon"/>



<style>
        .accountname[contenteditable]:focus, .gamename[contenteditable]:focus {
            outline: none;
        }
    </style>
<script>
        function getTime() {
            var dateObj = new Date();
            var year = dateObj.getFullYear();
            var month = (dateObj.getMonth() + 1).toString().padStart(2, '0');
            var date = dateObj.getDate().toString().padStart(2, '0');
            document.getElementById("date1").innerHTML = year + "年" + month + "月" + date + "日";
        }

        function OnSupportMessageAcked(checkboxId) {
            var checkbox = document.getElementById('checkbox_' + checkboxId);
            var closeButton = document.getElementById('supportmessages_closebtn');
            
            if (checkbox.checked) {
                closeButton.classList.remove('btn_disabled');
                closeButton.onclick = CloseSupportMessageWindow;
            } else {
                closeButton.classList.add('btn_disabled');
                closeButton.onclick = null;
            }
        }

        function CloseSupportMessageWindow() {
            window.close();
        }

        function makeEditable(element) {
            element.contentEditable = true;
            element.focus();
        }

        function handleEdit(element) {
            element.addEventListener('blur', function() {
                element.contentEditable = false;
            });
            element.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    element.contentEditable = false;
                }
            });
        }

        function makeAllEditable() {
            var editableElements = document.querySelectorAll('.accountname, .gamename');
            editableElements.forEach(function(element) {
                element.addEventListener('click', function() {
                    makeEditable(this);
                    handleEdit(this);
                });
            });
        }

        window.onload = function() {
            getTime();
            makeAllEditable();
        }
    </script>
<style>
/* ---- buttons.css ---- */
.btn_green_white_innerfade {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #D2E885 !important;

				background: #a4d007;
			background: -webkit-linear-gradient( top, #a4d007 5%, #536904 95%);
	background: linear-gradient( to bottom, #a4d007 5%, #536904 95%);
	}

	.btn_green_white_innerfade > span {
		border-radius: 2px;
		display: block;


					background: #799905;
			background: -webkit-linear-gradient( top, #799905 5%, #536904 95%);
	background: linear-gradient( to bottom, #799905 5%, #536904 95%);
			}

.btn_green_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #fff !important;

				background: #b6d908;
			background: -webkit-linear-gradient( top, #b6d908 5%, #80a006 95%);
	background: linear-gradient( to bottom, #b6d908 5%, #80a006 95%);
	}

	.btn_green_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
					background: #a1bf07;
			background: -webkit-linear-gradient( top, #a1bf07 5%, #80a006 95%);
	background: linear-gradient( to bottom, #a1bf07 5%, #80a006 95%);
			}

.btn_blue_white_innerfade {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #fff !important;

				background: #aaceff;
			background: -webkit-linear-gradient( top, #aaceff 5%, #3c6091 95%);
	background: linear-gradient( to bottom, #aaceff 5%, #3c6091 95%);
	}

	.btn_blue_white_innerfade > span {
		border-radius: 2px;
		display: block;


					background: #82a6d7;
			background: -webkit-linear-gradient( top, #82a6d7 5%, #3c6091 95%);
	background: linear-gradient( to bottom, #82a6d7 5%, #3c6091 95%);
			}

.btn_blue_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #fff !important;

				background: #bbd8ff;
			background: -webkit-linear-gradient( top, #bbd8ff 5%, #4873a7 95%);
	background: linear-gradient( to bottom, #bbd8ff 5%, #4873a7 95%);
	}

	.btn_blue_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
					background: #9ab7de;
			background: -webkit-linear-gradient( top, #9ab7de 5%, #4873a7 95%);
	background: linear-gradient( to bottom, #9ab7de 5%, #4873a7 95%);
			}

.btn_darkblue_white_innerfade {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #A4D7F5 !important;

				background: rgba(47,137,188,1);
			background: -webkit-linear-gradient( top, rgba(47,137,188,1) 5%, rgba(23,67,92,1) 95%);
	background: linear-gradient( to bottom, rgba(47,137,188,1) 5%, rgba(23,67,92,1) 95%);
	}

	.btn_darkblue_white_innerfade > span {
		border-radius: 2px;
		display: block;


					background: rgba(33,101,138,1);
			background: -webkit-linear-gradient( top, rgba(33,101,138,1) 5%, rgba(23,67,92,1) 95%);
	background: linear-gradient( to bottom, rgba(33,101,138,1) 5%, rgba(23,67,92,1) 95%);
			}

.btn_darkblue_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #ffffff !important;

				background: rgba(102,192,244,1);
			background: -webkit-linear-gradient( top, rgba(102,192,244,1) 5%, rgba(47,137,188,1) 95%);
	background: linear-gradient( to bottom, rgba(102,192,244,1) 5%, rgba(47,137,188,1) 95%);
	}

	.btn_darkblue_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

	.btn_darkblue_white_innerfade.btn_active, btn_darkblue_white_innerfade.active {
	text-decoration: none !important;
	color: #323b49 !important;

		background: #fff !important;			}

	.btn_darkblue_white_innerfade.btn_active > span, btn_darkblue_white_innerfade.active > span {
					background: #989b9e;
			background: -webkit-linear-gradient( top, #989b9e 5%, #aeb1b5 95%);
	background: linear-gradient( to bottom, #989b9e 5%, #aeb1b5 95%);
			}

	.btn_darkred_white_innerfade {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #F5D7A4 !important;

				background: rgba(188,47,47,1);
			background: -webkit-linear-gradient( top, rgba(188,47,47,1) 5%, rgba(92,37,23,1) 95%);
	background: linear-gradient( to bottom, rgba(188,47,47,1) 5%, rgba(92,37,23,1) 95%);
	}

	.btn_darkred_white_innerfade > span {
		border-radius: 2px;
		display: block;


					background: rgba(138,51,33,1);
			background: -webkit-linear-gradient( top, rgba(138,51,33,1) 5%, rgba(92,37,23,1) 95%);
	background: linear-gradient( to bottom, rgba(138,51,33,1) 5%, rgba(92,37,23,1) 95%);
			}

.btn_darkred_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #ffffff !important;

				background: rgba(244,92,102,1);
			background: -webkit-linear-gradient( top, rgba(244,92,102,1) 5%, rgba(188,67,47,1) 95%);
	background: linear-gradient( to bottom, rgba(244,92,102,1) 5%, rgba(188,67,47,1) 95%);
	}

	.btn_darkred_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

	.btn_darkred_white_innerfade.btn_active, btn_darkred_white_innerfade.active {
	text-decoration: none !important;
	color: #493b32 !important;

		background: #fff !important;			}

	.btn_darkred_white_innerfade.btn_active > span, btn_darkred_white_innerfade.active > span {
					background: #9e9b98;
			background: -webkit-linear-gradient( top, #9e9b98 5%, #b5b1ae 95%);
	background: linear-gradient( to bottom, #9e9b98 5%, #b5b1ae 95%);
			}

	.btn_grey_white_innerfade {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #fff !important;

				background: #acb5bd;
			background: -webkit-linear-gradient( top, #acb5bd 5%, #414a52 95%);
	background: linear-gradient( to bottom, #acb5bd 5%, #414a52 95%);
	}

	.btn_grey_white_innerfade > span {
		border-radius: 2px;
		display: block;


					background: #778088;
			background: -webkit-linear-gradient( top, #778088 5%, #414a52 95%);
	background: linear-gradient( to bottom, #778088 5%, #414a52 95%);
			}

.btn_grey_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #fff !important;

				background: #cfd8e0;
			background: -webkit-linear-gradient( top, #cfd8e0 5%, #565f67 95%);
	background: linear-gradient( to bottom, #cfd8e0 5%, #565f67 95%);
	}

	.btn_grey_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
					background: #99a2aa;
			background: -webkit-linear-gradient( top, #99a2aa 5%, #565f67 95%);
	background: linear-gradient( to bottom, #99a2aa 5%, #565f67 95%);
			}

.btn_grey_grey {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #ebebeb !important;

	background: rgba( 0, 0, 0, 0.4);	}

	.btn_grey_grey > span {
		border-radius: 2px;
		display: block;


		background: transparent;			}

.btn_grey_grey:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #000 !important;

	background: #7bb7e3;	}

	.btn_grey_grey:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

.btn_grey_grey_outer_bevel {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #ebebeb !important;

	background: #000;	}

	.btn_grey_grey_outer_bevel > span {
		border-radius: 2px;
		display: block;


					background: #2B2B2B;
			background: -webkit-linear-gradient( top, #2B2B2B 5%, #202020 95%);
	background: linear-gradient( to bottom, #2B2B2B 5%, #202020 95%);
			}

.btn_grey_grey_outer_bevel:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #ebebeb !important;

				background: #57749e;
			background: -webkit-linear-gradient( top, #57749e 5%, #364963 95%);
	background: linear-gradient( to bottom, #57749e 5%, #364963 95%);
	}

	.btn_grey_grey_outer_bevel:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
					background: #445b7c;
			background: -webkit-linear-gradient( top, #445b7c 5%, #364963 95%);
	background: linear-gradient( to bottom, #445b7c 5%, #364963 95%);
			}


.btn_grey_grey_outer_bevel:not(:hover) > span {
	box-shadow: inset 0 1px 1px #434343;
}
.btn_grey_black {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #67c1f5 !important;

	background: rgba(0, 0, 0, 0.5 );	}

	.btn_grey_black > span {
		border-radius: 2px;
		display: block;


		background: transparent;			}

.btn_grey_black:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #fff !important;

	background: rgba( 102, 192, 244, 0.4 );	}

	.btn_grey_black:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

	.btn_grey_black.btn_active, btn_grey_black.active {
	text-decoration: none !important;
	color: #fff !important;

		background: rgba( 102, 192, 244, 0.2 );;			}

	.btn_grey_black.btn_active > span, btn_grey_black.active > span {
		background: transparent;			}

	.btn_black {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #ebebeb !important;

	background: #000;	}

	.btn_black > span {
		border-radius: 2px;
		display: block;


		background: transparent;			}

.btn_black:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #000 !important;

	background: #97C0E3;	}

	.btn_black:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

.btnv6_blue_hoverfade {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #67c1f5 !important;

	background: rgba( 103, 193, 245, 0.2 );	}

	.btnv6_blue_hoverfade > span {
		border-radius: 2px;
		display: block;


		background: transparent;			}

.btnv6_blue_hoverfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #fff !important;

				background: #417a9b;
			background: -webkit-linear-gradient( 150deg, #417a9b 5%,#67c1f5 95%);
	background: linear-gradient( -60deg, #417a9b 5%,#67c1f5 95%);
	}

	.btnv6_blue_hoverfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

	.btnv6_blue_hoverfade.btn_active, btnv6_blue_hoverfade.active {
	text-decoration: none !important;
	color: #fff !important;

		background: rgba( 103, 193, 245, 0.6 );;			}

	.btnv6_blue_hoverfade.btn_active > span, btnv6_blue_hoverfade.active > span {
		background: transparent;			}

	.btnv6_lightblue_blue {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #2B5066 !important;

				background: rgba(193,228,249,1);
			background: -webkit-linear-gradient( top, rgba(193,228,249,1) 5%, rgba(148,183,202,1) 95%);
	background: linear-gradient( to bottom, rgba(193,228,249,1) 5%, rgba(148,183,202,1) 95%);
	}

	.btnv6_lightblue_blue > span {
		border-radius: 2px;
		display: block;


		background: transparent;		text-shadow: 1px 1px 0px rgba( 255, 255, 255, 0.1 );	}

.btnv6_lightblue_blue:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #ffffff !important;

				background: rgba(102,192,244,1);
			background: -webkit-linear-gradient( top, rgba(102,192,244,1) 5%, rgba(47,137,188,1) 95%);
	background: linear-gradient( to bottom, rgba(102,192,244,1) 5%, rgba(47,137,188,1) 95%);
	}

	.btnv6_lightblue_blue:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

.btnv6_blue_blue_innerfade {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #A4D7F5 !important;

				background: rgba(47,137,188,1);
			background: -webkit-linear-gradient( top, rgba(47,137,188,1) 5%, rgba(23,67,92,1) 95%);
	background: linear-gradient( to bottom, rgba(47,137,188,1) 5%, rgba(23,67,92,1) 95%);
	}

	.btnv6_blue_blue_innerfade > span {
		border-radius: 2px;
		display: block;


		background: transparent;		text-shadow: -1px -1px 0px rgba( 0, 0, 0, 0.1 );	}

.btnv6_blue_blue_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #ffffff !important;

				background: rgba(102,192,244,1);
			background: -webkit-linear-gradient( top, rgba(102,192,244,1) 5%, rgba(47,137,188,1) 95%);
	background: linear-gradient( to bottom, rgba(102,192,244,1) 5%, rgba(47,137,188,1) 95%);
	}

	.btnv6_blue_blue_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

.btnv6_green_white_innerfade {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #D2E885 !important;

				background: rgba(121,153,5,1);
			background: -webkit-linear-gradient( top, rgba(121,153,5,1) 5%, rgba(83,105,4,1) 95%);
	background: linear-gradient( to bottom, rgba(121,153,5,1) 5%, rgba(83,105,4,1) 95%);
	}

	.btnv6_green_white_innerfade > span {
		border-radius: 2px;
		display: block;


		background: transparent;		text-shadow: -1px -1px 0px rgba( 0, 0, 0, 0.1 );	}

.btnv6_green_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #ffffff !important;

				background: rgba(164,208,7,1);
			background: -webkit-linear-gradient( top, rgba(164,208,7,1) 5%, rgba(107,135,5,1) 95%);
	background: linear-gradient( to bottom, rgba(164,208,7,1) 5%, rgba(107,135,5,1) 95%);
	}

	.btnv6_green_white_innerfade:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

.btnv6_grey_black {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #66c0f4 !important;

	background: #212c3d;	}

	.btnv6_grey_black > span {
		border-radius: 2px;
		display: block;


		background: transparent;			}

.btnv6_grey_black:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #fff !important;

	background: #66c0f4;	}

	.btnv6_grey_black:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

	.btnv6_grey_black.btn_active, btnv6_grey_black.active {
	text-decoration: none !important;
	color: #fff !important;

		background: rgba( 103, 193, 245, 0.4 );;			}

	.btnv6_grey_black.btn_active > span, btnv6_grey_black.active > span {
		background: transparent;			}

	.btnv6_white_transparent {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #fff !important;

	background: transparent;	}

	.btnv6_white_transparent > span {
		border-radius: 2px;
		display: block;


		background: transparent;		border: 1px solid rgba(255,255,255,0.4);
border-radius: 2px;	}

.btnv6_white_transparent:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #fff !important;

	background: transparent;	}

	.btnv6_white_transparent:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;		border: 1px solid rgba(255,255,255,1);
border-radius: 2px;	}

.btn_teal {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #A4D7F5 !important;

				background: rgba(62,133,154,1);
			background: -webkit-linear-gradient( top, rgba(62,133,154,1) 5%, rgba(30,73,85,1) 95%);
	background: linear-gradient( to bottom, rgba(62,133,154,1) 5%, rgba(30,73,85,1) 95%);
	}

	.btn_teal > span {
		border-radius: 2px;
		display: block;


					background: rgba(33,101,138,1);
			background: -webkit-linear-gradient( top, rgba(33,101,138,1) 5%, rgba(23,67,92,1) 95%);
	background: linear-gradient( to bottom, rgba(33,101,138,1) 5%, rgba(23,67,92,1) 95%);
			}

.btn_teal:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #ffffff !important;

				background: rgba(92,163,184,1);
			background: -webkit-linear-gradient( top, rgba(92,163,184,1) 5%, rgba(60,103,115,1) 95%);
	background: linear-gradient( to bottom, rgba(92,163,184,1) 5%, rgba(60,103,115,1) 95%);
	}

	.btn_teal:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

	.btn_teal.btn_active, btn_teal.active {
	text-decoration: none !important;
	color: #323b49 !important;

		background: #fff !important;			}

	.btn_teal.btn_active > span, btn_teal.active > span {
					background: rgba(72,143,164,1);
			background: -webkit-linear-gradient( top, rgba(72,143,164,1) 5%, rgba(40,83,95,1) 95%);
	background: linear-gradient( to bottom, rgba(72,143,164,1) 5%, rgba(40,83,95,1) 95%);
			}

	.btn_royal_blue {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #A4D7F5 !important;

				background: rgba(79,78,181,1);
			background: -webkit-linear-gradient( top, rgba(79,78,181,1) 5%, rgba(49,48,151,1) 95%);
	background: linear-gradient( to bottom, rgba(79,78,181,1) 5%, rgba(49,48,151,1) 95%);
	}

	.btn_royal_blue > span {
		border-radius: 2px;
		display: block;


					background: rgba(33,101,138,1);
			background: -webkit-linear-gradient( top, rgba(33,101,138,1) 5%, rgba(23,67,92,1) 95%);
	background: linear-gradient( to bottom, rgba(33,101,138,1) 5%, rgba(23,67,92,1) 95%);
			}

.btn_royal_blue:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #ffffff !important;

				background: rgba(109,108,211,1);
			background: -webkit-linear-gradient( top, rgba(109,108,211,1) 5%, rgba(79,78,181,1) 95%);
	background: linear-gradient( to bottom, rgba(109,108,211,1) 5%, rgba(79,78,181,1) 95%);
	}

	.btn_royal_blue:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

	.btn_royal_blue.btn_active, btn_royal_blue.active {
	text-decoration: none !important;
	color: #323b49 !important;

		background: #fff !important;			}

	.btn_royal_blue.btn_active > span, btn_royal_blue.active > span {
					background: rgba(72,143,164,1);
			background: -webkit-linear-gradient( top, rgba(72,143,164,1) 5%, rgba(40,83,95,1) 95%);
	background: linear-gradient( to bottom, rgba(72,143,164,1) 5%, rgba(40,83,95,1) 95%);
			}

	.btn_plum {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #A4D7F5 !important;

				background: rgba(111,35,74,1);
			background: -webkit-linear-gradient( top, rgba(111,35,74,1) 5%, rgba(81,5,44,1) 95%);
	background: linear-gradient( to bottom, rgba(111,35,74,1) 5%, rgba(81,5,44,1) 95%);
	}

	.btn_plum > span {
		border-radius: 2px;
		display: block;


					background: rgba(33,101,138,1);
			background: -webkit-linear-gradient( top, rgba(33,101,138,1) 5%, rgba(23,67,92,1) 95%);
	background: linear-gradient( to bottom, rgba(33,101,138,1) 5%, rgba(23,67,92,1) 95%);
			}

.btn_plum:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #ffffff !important;

				background: rgba(151,75,114,1);
			background: -webkit-linear-gradient( top, rgba(151,75,114,1) 5%, rgba(121,45,84,1) 95%);
	background: linear-gradient( to bottom, rgba(151,75,114,1) 5%, rgba(121,45,84,1) 95%);
	}

	.btn_plum:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
		background: transparent;			}

	.btn_plum.btn_active, btn_plum.active {
	text-decoration: none !important;
	color: #323b49 !important;

		background: #fff !important;			}

	.btn_plum.btn_active > span, btn_plum.active > span {
					background: rgba(72,143,164,1);
			background: -webkit-linear-gradient( top, rgba(72,143,164,1) 5%, rgba(40,83,95,1) 95%);
	background: linear-gradient( to bottom, rgba(72,143,164,1) 5%, rgba(40,83,95,1) 95%);
			}

	.btn_green_steamui {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #dfe3e6; !important;

	background: transparent;	}

	.btn_green_steamui > span {
		border-radius: 2px;
		display: block;


					background: #75b022;
			background: -webkit-linear-gradient( top, #75b022 5%, #588a1b 95%);
	background: linear-gradient( to bottom, #75b022 5%, #588a1b 95%);
		background: linear-gradient( to right, #75b022 5%, #588a1b 95%);	}

.btn_green_steamui:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #fff; !important;

	background: transparent;	}

	.btn_green_steamui:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
					background: #8ed629;
			background: -webkit-linear-gradient( top, #8ed629 5%, #6aa621 95%);
	background: linear-gradient( to bottom, #8ed629 5%, #6aa621 95%);
		background: linear-gradient( to right, #8ed629 5%, #6aa621 95%);	}

	.btn_green_steamui.btn_active, btn_green_steamui.active {
	text-decoration: none !important;
	color: #fff; !important;

		background: transparent;			}

	.btn_green_steamui.btn_active > span, btn_green_steamui.active > span {
					background: #8ed629;
			background: -webkit-linear-gradient( top, #8ed629 5%, #6aa621 95%);
	background: linear-gradient( to bottom, #8ed629 5%, #6aa621 95%);
		background: linear-gradient( to right, #8ed629 5%, #6aa621 95%);	}

	.btn_grey_steamui {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #dfe3e6; !important;

	background: transparent;	}

	.btn_grey_steamui > span {
		border-radius: 2px;
		display: block;


					background: #75b022;
			background: -webkit-linear-gradient( top, #75b022 5%, #588a1b 95%);
	background: linear-gradient( to bottom, #75b022 5%, #588a1b 95%);
		background: linear-gradient( to right, #32363f 5%, #32363f 95%); box-shadow: 2px 2px 5px rgba(0, 0, 0, 0.2); transition: all 0.2s ease-out;	}

.btn_grey_steamui:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #fff; !important;

	background: transparent;	}

	.btn_grey_steamui:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
					background: #8ed629;
			background: -webkit-linear-gradient( top, #8ed629 5%, #6aa621 95%);
	background: linear-gradient( to bottom, #8ed629 5%, #6aa621 95%);
		background: linear-gradient( to right, #464d58 5%, #464d58 95%); box-shadow: 2px 2px 15px rgba(0, 0, 0, 0.5);	}

.btn_blue_steamui {
	border-radius: 2px;
	border: none;
	padding: 1px;
	display: inline-block;
	cursor: pointer;
	text-decoration: none !important;
	color: #dfe3e6; !important;

	background: transparent;	}

	.btn_blue_steamui > span {
		border-radius: 2px;
		display: block;


					background: #75b022;
			background: -webkit-linear-gradient( top, #75b022 5%, #588a1b 95%);
	background: linear-gradient( to bottom, #75b022 5%, #588a1b 95%);
		background: linear-gradient( to right, #47bfff 5%, #1a44c2 60%); box-shadow: 2px 2px 5px rgba(0, 0, 0, 0.2); background-position: 25%; background-size: 330% 100%;	}

.btn_blue_steamui:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover {
	text-decoration: none !important;
	color: #fff; !important;

	background: transparent;	}

	.btn_blue_steamui:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover > span {
					background: #8ed629;
			background: -webkit-linear-gradient( top, #8ed629 5%, #6aa621 95%);
	background: linear-gradient( to bottom, #8ed629 5%, #6aa621 95%);
		background: linear-gradient( to right, #47bfff 5%, #1a44c2 60%); box-shadow: 2px 2px 15px rgba(0, 0, 0, 0.5); background-position: 0%; background-size: 330% 100%;	}


/* This class must be applied to anything you want to use buttons in to enable hover states. */
.btn_hover {}

.inner_bevel {
	-moz-box-shadow:	2px 2px 5px rgba(0,0,0,0.75) inset, -2px -2px 5px rgba(150,150,150,1) inset;
	-webkit-box-shadow:	2px 2px 5px rgba(0,0,0,0.75) inset, -2px -2px 5px rgba(150,150,150,1) inset;
	box-shadow: 		2px 2px 5px rgba(0,0,0,0.75) inset, -2px -2px 5px rgba(150,150,150,1) inset;
}

/* fix for mozilla <button> elements */
button::-moz-focus-inner
{
	padding: 0;
	border: none;
}

/* Borders */
.btn_border_2px {
	border-radius: 4px;
	border: 2px solid #172030;
}

.btn_border_2px > span {
	border-radius: 3px;
}

.btnv6_border_2px {
	border-radius: 4px;
	border: 2px solid #17202f;
}

.btnv6_border_2px > span {
	border-radius: 3px;
}

/* Sizing */
.btn_large > span, input.btn_large {
	padding: 0 15px;
	font-size: 16px;
	line-height: 40px;
}

.btn_medium_tall > span, input.btn_medium_tall {
	padding: 0 15px;
	font-size: 15px;
	line-height: 36px;
}

.btn_medium > span, input.btn_medium {
	padding: 0 15px;
	font-size: 15px;
	line-height: 30px;
}

.btn_medium .ico16 {
	margin: 7px 0;
	vertical-align: top;
}

.btn_medium_thin > span, input.btn_medium_thin {
	padding: 0 5px;
	font-size: 15px;
	line-height: 30px;
}

.btn_medium_wide > span, input.btn_medium_wide {
	padding: 0 24px;
	font-size: 15px;
	line-height: 30px;
}

.btn_small > span, input.btn_small {
	padding: 0 15px;
	font-size: 12px;
	line-height: 20px;
}

.btn_small_thin > span, input.btn_small_thin {
	padding: 0 5px;
	font-size: 12px;
	line-height: 20px;
}

.btn_small_tall > span, input.btn_small_tall {
    padding: 0 15px;
    font-size: 12px;
    line-height: 24px;
}

.btn_small_wide > span, input.btn_small_wide {
	padding: 0 24px;
	font-size: 12px;
	line-height: 20px;
}
.btn_tiny > span, input.btn_tiny {
	padding: 0 7px;
	font-size: 11px;
	line-height: 17px;
}

/* Misc effects */
.btn_uppercase > span {
	text-transform: uppercase;
}

/* Icons */

/* 18x18 */
.ico18{
	display: inline-block;
	width: 18px;
	height: 18px;
	margin: 0 0px;
	background: url(https://store.st.dl.bscstorage.net/public/shared/images/buttons/icons_18.png?v=3);
	vertical-align: text-top;
}


	.ico18.thumb_down {
		background-position: -18px 0px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico18.thumb_down {
			background-position: -90px 0px;		}
	
			.btn_active .ico18.thumb_down, .active .ico18.thumb_down {
			background-position: -54px 0px;		}
		
	.ico18.thumb_up {
		background-position: 0px 0px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico18.thumb_up {
			background-position: -72px 0px;		}
	
			.btn_active .ico18.thumb_up, .active .ico18.thumb_up {
			background-position: -36px 0px;		}
		
	.ico18.accepted_and_voted {
		background-position: 0px -18px;	}

	
		
/* 16x16 */
.ico16{
	display: inline-block;
	width: 16px;
	height: 16px;
	background: url(https://store.st.dl.bscstorage.net/public/shared/images/buttons/icons_16.png?v=5);
	vertical-align: text-top;
}


	.ico16.comment {
		background-position: 0px 0px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico16.comment {
			background-position: -16px 0px;		}
	
		
	.ico16.thumb_down {
		background-position: -32px 0px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico16.thumb_down {
			background-position: -48px 0px;		}
	
			.btn_active .ico16.thumb_down, .active .ico16.thumb_down {
			background-position: -64px 0px;		}
		
	.ico16.thumb_up {
		background-position: -80px 0px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico16.thumb_up {
			background-position: -112px 0px;		}
	
			.btn_active .ico16.thumb_up, .active .ico16.thumb_up {
			background-position: -96px 0px;		}
		
	.ico16.thumb_downv6 {
		background-position: -64px -16px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico16.thumb_downv6 {
			background-position: -80px -16px;		}
	
			.btn_active .ico16.thumb_downv6, .active .ico16.thumb_downv6 {
			background-position: -96px -16px;		}
		
	.ico16.thumb_upv6 {
		background-position: -112px -16px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico16.thumb_upv6 {
			background-position: -144px -16px;		}
	
			.btn_active .ico16.thumb_upv6, .active .ico16.thumb_upv6 {
			background-position: -128px -16px;		}
		
	.ico16.arrow_down {
		background-position: -48px -16px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico16.arrow_down {
			background-position: -32px -16px;		}
	
		
	.ico16.report {
		background-position: -128px 0px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico16.report {
			background-position: -144px 0px;		}
	
			.btn_active .ico16.report, .active .ico16.report {
			background-position: -160px 0px;		}
		
	.ico16.reportv6 {
		background-position: -256px 0px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico16.reportv6 {
			background-position: -272px 0px;		}
	
			.btn_active .ico16.reportv6, .active .ico16.reportv6 {
			background-position: -288px 0px;		}
		
	.ico16.arrow_next {
		background-position: -176px 0px;	}

	
		
	.ico16.checkbox {
		background-position: -192px 0px;	}

	
		
	.ico16.bucketnew {
		background-position: -208px 0px;	}

	
		
	.ico16.bucketqueue {
		background-position: -224px 0px;	}

	
		
	.ico16.bucketrefresh {
		background-position: -240px 0px;	}

	
		
	.ico16.bucketfollow {
		background-position: -176px -16px;	}

	
		
	.ico16.bucketfavorite {
		background-position: -192px -16px;	}

	
		
	.ico16.funny {
		background-position: -208px -16px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico16.funny {
			background-position: -224px -16px;		}
	
			.btn_active .ico16.funny, .active .ico16.funny {
			background-position: -224px -16px;		}
		
	.ico16.bluearrow_down {
		background-position: -304px 0px;	}

			.ico_hover:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .ico16.bluearrow_down {
			background-position: -304px -16px;		}
	
			.btn_active .ico16.bluearrow_down, .active .ico16.bluearrow_down {
			background-position: -304px -16px;		}
		
/* Arrows are the only icons I've not fully replaced yet. If you need to use them, please convert to the new icon code */

.btn_details_arrow
{
	display: inline-block;
	width: 15px;
	height: 16px;
	background-image:url('https://store.st.dl.bscstorage.net/public/shared/images/buttons/icon_double_arrows.png');
	vertical-align: middle;
}

.btn_details_arrow.up
{
	background-position: 0px 0px;
}

.btn_details:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .btn_details_arrow.up
{
	background-position: -15px 0px;
}

.btn_details_arrow.down
{
	background-position: 15px 0px;
}

.btn_details:not(.btn_disabled):not(:disabled):not(.btn_active):not(.active):hover .btn_details_arrow.down
{
	background-position: 30px 0px;
}

.btn_disabled, button:disabled {
	opacity: 0.45;
	cursor: default;
}

.btn_disabled:hover, button:disabled:hover {
	text-decoration: none;
}

.packageTagsArrow
{
     display: inline-block;
     width: 15px;
     height: 16px;
     background-image:url('https://store.st.dl.bscstorage.net/public/shared/images/buttons/icon_double_arrows.png');
}

.packageTagsArrow.Expand
{
     background-position: 18px 1px;
}

.packageTagsArrow.Collapse
{
     background-position: 3px 1px;
}


/* ---- store.css ---- */

* {
	padding: 0;
	margin: 0;
}

img {
	border: none;
}


a {
	text-decoration: none;
	color: #ffffff;
}


.a:focus {
	outline: 0px none;
}

a:hover {
	text-decoration: none;
    color: #66c0f4;
}

a.nohover:hover {
	text-decoration: none;
}


html {
	height: 100%;
}

body.v6 {
	position: relative;
	min-height: 100%;
	font-family: Arial, Helvetica, sans-serif;
	color: #c6d4df;
	font-size: 12px;
}

body.v6.in_client {
	background-position: center top;
}

body.v6.game_bg {
    background: #1b2838;
}

body.v6 > div#global_header {
	border-bottom-color: #171a21;
}

.v6_bg {
	/* background: url( '/public/images/v6/tag_browse_header_bg.png' ) no-repeat center top; */
}

body.blue .v6_bg {
	background:
		url( '/public/images/v6/blue_top_center.png' ) center top no-repeat,
		url( '/public/images/v6/blue_top_repeat.png' ) center top repeat-x
;

	min-height: 370px;
}

body.v6 div#store_header {
	background-color: transparent;
}

.page_background {
	background-position: center top;
	background-repeat: no-repeat;
}

body.v6 #footer {
	font-family: Arial, Helvetica, sans-serif;
	position: absolute;
	left: 0;
	right: 0;
	bottom: 0;
	padding: 16px 0 60px 0;
	margin: 0;

	text-size-adjust: none;
	-webkit-text-size-adjust: none;

    background: -moz-linear-gradient(top,  rgba(0,0,0,0.3) 0%, rgba(0,0,0,0.5) 100%); /* FF3.6+ */
    background: -webkit-gradient(linear, left top, left bottom, color-stop(0%,rgba(0,0,0,0.3)), color-stop(100%,rgba(0,0,0,0.5))); /* Chrome,Safari4+ */
    background: -webkit-linear-gradient(top,  rgba(0,0,0,0.3) 0%,rgba(0,0,0,0.5) 100%); /* Chrome10+,Safari5.1+ */
    background: -o-linear-gradient(top,  rgba(0,0,0,0.3) 0%,rgba(0,0,0,0.5) 100%); /* Opera 11.10+ */
    background: -ms-linear-gradient(top,  rgba(0,0,0,0.3) 0%,rgba(0,0,0,0.5) 100%); /* IE10+ */
    background: linear-gradient(to bottom,  rgba(0,0,0,0.3) 0%,rgba(0,0,0,0.5) 100%); /* W3C */
    filter: progid:DXImageTransform.Microsoft.gradient( startColorstr='#4d000000', endColorstr='#80000000',GradientType=0 ); /* IE6-9 */

}

	body.v6.infinite_scrolling #footer.small_footer {
		position: relative;
		top: auto;
		bottom: auto;
	}

	body.v6.infinite_scrolling #footer_spacer.small_footer {
		height: 50px;
	}

    body.v6 #footer .footer_content {
        width: 940px;
        margin: 0px auto;
        padding-top: 16px;
    }
    body.v6 #footer #footer_logo {
        float: left;
        padding-top: 2px;
    }
	body.v6 #footer #footer_logo_steam {
		float: right;
		padding-top: 2px;
	}
    body.v6 #footer #footer_text {
        float: left;
        margin-left: 12px;
        color: #8F98A0;
		font-size: 12px;
		line-height: 16px;
    }
    body.v6 #footer #footer_text a {
        color: #C6D4DF;
    }
    body.v6 #footer #footer_text a:hover {
        color: #ffffff;
    }
    body.v6 #footer .rule{
        height: 8px;
		border-top: 1px solid #29363d;
    }
    body.v6 #footer .valve_links {
        margin-top: 8px;
        float: left;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: normal; /* normal */

		        font-size: 13px;
        color: #61686D;
    }
    body.v6 #footer .valve_links a {
       color: #C6D4DF;
    }
    body.v6 #footer .valve_links a:hover {
        color: #ffffff;
    }
	body.v6 #footer .valve_links img {
		vertical-align: bottom;
	}



body #footer .responsive_optin_link {
	display: none;
}

body.v6.blue #footer {
	background: #000000;
}

body.v6 #footer_spacer {
	height: 290px;
}

html.force_desktop body.v6 #footer_spacer {
	height: 345px;
}



body.v6 > .perf_timing_area .perf_timing_link {
	position: absolute;
	left: 15px;
	bottom: 15px;
}

.perf_timing_data {
	position: relative;
	background-color: #000000;
	margin: 0px auto 48px auto;
	padding: 8px;
	text-align: left;
	width: 936px;
	font-size: 14px;
	z-index: 5;
}

body.v6 h2 {
			font-family: "Motiva Sans", Sans-serif;
		font-weight: 300; /* light */

			font-size: 14px;
	text-transform: uppercase;
	color: #fff;
	margin: 0 0 10px;
	letter-spacing: 2px;
	font-weight: normal;
	padding-top: 2px;
}
body.v6 h2 a {
    color: #67c1f5;
    text-decoration: none;
}
body.v6 h2 a:hover {
    color: #ffffff;
    text-decoration: none;
}

body.v6 .home_rightcol h2 {
    margin-bottom: 7px;
    margin-top: 0px;
}
body.v6 .home_rightcol.recommended h2, body.v6 .home_leftcol h2 {
    margin-top: 30px;
    margin-bottom: 7px;
}

body.v6 .responsive_home_spotlight_recommended .home_leftcol .spotlight_content h2 {
	margin-bottom: 2px;
	margin-top: 1px;
}

body.v6 .discovery_queue_ctn h2, body.v6 .steam_curators_ctn h2, body.v6  .apps_recommended_by_curators_ctn h2 {
    margin-top: 40px;
    margin-bottom: 7px;
}

body.v6 .upcoming_queue_ctn h2, body.v6 .steam_curators_ctn h2 {
    margin-top: 40px;
    margin-bottom: 7px;
}

body.v6 h2 .header_inline {
	color: #9099a1;
	font-size: 17px;
}

body.v6 h2 .header_inline a {
	color: #c6d4df;
	cursor: pointer;
}
body.v6 h2 .header_inline a:hover {
	color: #67c1f5;
}

body.v6 h2.pageheader {
	color: #ffffff;
	font-size: 34px;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: 300; /* light */

			text-shadow: 1px 1px 0 rgba( 0, 0, 0, 0.4 );
	margin-top: -4px;
}

body.v6 h3 {
	color: #ffffff;
	font-size: 22px;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: normal; /* normal */

			font-weight: normal;
}

body.v6 .page_content {
	width: 940px;
	margin: 0 auto;
}

.ellipsis {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.page_header_ctn {
    background: url('/public/images//v6/temp/cluster_bg.png' ) bottom center no-repeat;
    padding-bottom: 64px;
    margin-bottom: -30px;
}

.page_header_ctn.tabs {
    padding-bottom: 100px;
    margin-bottom: -78px;
}

.page_header_ctn.tabs.capsules {
    padding-bottom: 100px;
    margin-bottom: -78px;
	overflow: hidden;
}

.discovery_queue_content_ctn {
	overflow: hidden;
	margin-top: 26px;
}
body.v6.explore .page_header_ctn {
	padding-bottom: 30px;
	margin-bottom: -20px;
}

.breadcrumbs {
    color: #56707f;
    font-size: 12px;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: normal; /* normal */

			padding-top: 10px;
}
.breadcrumbs a {
    color: #8f98a0;
}
.breadcrumbs a:hover {
    color: #ffffff;
    text-decoration: none;
}

div.leftcol {
	width: 616px;
	float: left;
}
div.leftcol.large {
    width: 686px;
}
div.leftcol.small {
	width: 458px;
}

div.rightcol {
	width: 308px;
	margin-left: 14px;
	float: right;
}
div.rightcol.small {
	width: 238px;
}
div.rightcol.large {
	width: 466px;
}



.store_tooltip {
	background: #c2c2c2;
	color: #3d3d3f;
	font-size: 11px;
	border-radius: 3px;
	padding: 5px;
	max-width: 275px;
	white-space: normal;
	box-shadow: 0 0 3px #000000;
	word-wrap: break-word;
}

.store_tooltip ul {
	padding-left: 15px;
}


body.v6 .supernav_content, body.v6 #global_header, body.v6 #global_header .content
{
	background: #171a21;
}

body.v6 #store_header {
	padding-left: 0;
	padding-right: 0;
}


/*
 * STORE-SPECIFIC HEADER
 */



div#store_header {
	background-color: #3b3938;
	min-width: 940px;
	margin-bottom: 16px;
}

div#store_header .content {
	position: relative;
	width: 940px;
	margin: 0 auto;
	z-index: 300;
}

div#store_header, div#store_header .content {
	height: 66px;
}

div#store_header.dlc, div#store_header.dlc .content {
	height: 29px;
}

div#store_controls {
	position: absolute;
	right: 0;
	top: 10px;
	text-align: right;
	z-index: 300;
	font-size: 11px;
}

div.store_header_btn {
	height: 20px;
	position: relative;
	margin-left: 1px;
    border-radius: 1px;
	float: left;
}

a.store_header_btn_content {
	display: inline-block;

	padding: 0 25px;
	margin: 0 1px;

	line-height: 20px;
	text-align: center;
	text-transform: uppercase;
	font-size: 11px;
}

a.store_header_btn_content:hover {
	text-decoration: none;
}

.store_header_btn_gray {
	background-color: rgba( 255, 255, 255, 0.4 );
    border-radius: 1px;
}

.store_header_btn_gray a {
	color: #ffffff;
}

.store_header_btn_gray a:hover {
    color: #111111;
    border-radius: 1px;
    background: #ffffff; /* Old browsers */
    background: -moz-linear-gradient(-60deg,  #ffffff 0%, #919aa3 100%); /* FF3.6+ */
    background: -webkit-gradient(linear, left top, right bottom, color-stop(0%,#ffffff), color-stop(100%,#919aa3)); /* Chrome,Safari4+ */
    background: -webkit-linear-gradient(-60deg,  #ffffff 0%,#919aa3 100%); /* Chrome10+,Safari5.1+ */
    background: -o-linear-gradient(-60deg,  #ffffff 0%,#919aa3 100%); /* Opera 11.10+ */
    background: -ms-linear-gradient(-60deg,  #ffffff 0%,#919aa3 100%); /* IE10+ */
    background: linear-gradient(135deg,  #ffffff 0%,#919aa3 100%); /* W3C */
    filter: progid:DXImageTransform.Microsoft.gradient( startColorstr='#ffffff', endColorstr='#919aa3',GradientType=1 ); /* IE6-9 fallback on horizontal gradient */

}

.store_header_btn_green {
	background-color: rgba( 164, 208, 7, 0.4 );
}

.store_header_btn_green a {
	color: #a4d007;
}

.store_header_btn_green a:hover {
	color: #111111;
	background-color: rgba( 164, 208, 7, 0.50 );
}

div#store_search {
	float: right;
	padding: 3px 4px 2px;
	height: 30px;
}

a#store_search_link {
	position: absolute;
	right: 2px;
	top: 0;
}

a#store_search_link img {
	width: 24px;
	height: 27px;
}

.searchbox {

	background-image: url( '/public/images/v6/store_header_search.png?v=1' );

	color: #a6a5a2;
	width: 216px;
	height: 30px;

	position: relative;
	z-index: 150;
	cursor: text;
}
.searchbox:hover {
    background-image: url( '/public/images/v6/store_header_search_hover.png' );
}


.searchbox input {
	border: none;
	background-color: transparent;
	color: #000000;
	margin-top: 2px;
	margin-left: 8px;
	width: 180px;
	outline: none;
	line-height: 26px;
}

.searchbox input.default {
	font-style: italic;
    color: #305d8a;
}

.searchbox input:focus::placeholder {
	color: transparent;
}

#store_nav_area {
	position: absolute;
	left: 0;
	right: 0;
	top: 24px;
	height: 49px;
}

#store_nav_area .store_nav_bg {
	height: 35px;
	margin: 7px 0;
	background: rgba( 103, 193, 245, 0.4 );

}

.store_nav {
	height: 35px;
}

.store_nav .tab {
	float: left;


	border-right: 1px solid #000000;

	cursor: pointer;
}


.tab.active.tab_filler {
	height: 26px;
	margin-bottom: -1px;
}

.tab_page_link_holder {
    position: relative;
    text-align: center;
    height: 24px;
    line-height: 24px;
    margin-top: 1px;
    background-color: #262626;
    color: #626366;
    font-size: 10px;
}
.tab_page_link_prev a, .tab_page_link_next a {
    position: absolute;
    height: 24px;
    padding: 0px 16px;
    color: #67c1f5;
}
.tab_page_link_prev a img, .tab_page_link_next a img {
    top: 2px;
}
.tab_page_link_prev a:hover, .tab_page_link_next a:hover {
    position: absolute;
    height: 24px;
    padding: 0px 16px;
    text-decoration: none;
    color: #ffffff;
    background: #67c1f5; /* Old browsers */
    background: -moz-linear-gradient(-60deg,  #67c1f5 0%, #417a9b 100%); /* FF3.6+ */
    background: -webkit-gradient(linear, left top, right bottom, color-stop(0%,#67c1f5), color-stop(100%,#417a9b)); /* Chrome,Safari4+ */
    background: -webkit-linear-gradient(-60deg,  #67c1f5 0%,#417a9b 100%); /* Chrome10+,Safari5.1+ */
    background: -o-linear-gradient(-60deg,  #67c1f5 0%,#417a9b 100%); /* Opera 11.10+ */
    background: -ms-linear-gradient(-60deg,  #67c1f5 0%,#417a9b 100%); /* IE10+ */
    background: linear-gradient(135deg,  #67c1f5 0%,#417a9b 100%); /* W3C */
    filter: progid:DXImageTransform.Microsoft.gradient( startColorstr='#67c1f5', endColorstr='#417a9b',GradientType=1 ); /* IE6-9 fallback on horizontal gradient */
}
.tab_page_link_next a {
    right: 0px;
}
.tab_page_link_prev a {
    left: 0px;
}

.store_nav .tab.focus {
	background-color: #67c1f5;
}

#genre_flyout {
	top: 55px;
}


.store_nav .tab {
	padding: 1px;
	display: inline-block;
	text-decoration: none;
	cursor: pointer;

}
.store_nav .tab > span {

	font-size: 12px;
	color: #67c1f5;
	line-height: 33px;
	padding: 0 15px;

	display: block;
}

.store_nav .tab.lesspadding > span {
	padding: 0 12px;
}


.store_nav .tab:hover > span, .store_nav .tab:hover, .store_nav .tab.focus > span, .store_nav .tab.focus {
	filter: none;
    color: #ffffff;
    background: #67c1f5; /* Old browsers */
    background: -moz-linear-gradient(-60deg,  #67c1f5 0%, #417a9b 100%); /* FF3.6+ */
    background: -webkit-gradient(linear, left top, right bottom, color-stop(0%,#67c1f5), color-stop(100%,#417a9b)); /* Chrome,Safari4+ */
    background: -webkit-linear-gradient(-60deg,  #67c1f5 0%,#417a9b 100%); /* Chrome10+,Safari5.1+ */
    background: -o-linear-gradient(-60deg,  #67c1f5 0%,#417a9b 100%); /* Opera 11.10+ */
    background: -ms-linear-gradient(-60deg,  #67c1f5 0%,#417a9b 100%); /* IE10+ */
    background: linear-gradient(135deg,  #67c1f5 0%,#417a9b 100%); /* W3C */
    filter: progid:DXImageTransform.Microsoft.gradient( startColorstr='#67c1f5', endColorstr='#417a9b',GradientType=1 ); /* IE6-9 fallback on horizontal gradient */

}

.store_nav .tab.active, .store_nav .tab.active:hover {
}

.store_nav .tab.active > span, 	.store_nav .tab.active:hover > span {
}

.store_nav .tab > span.pulldown {
	padding-right: 7px;
	background: none;
}

.store_nav .tab > span.pulldown > span {
	width: 19px;
	height: 12px;
	padding: 0;
	display: inline-block;
	background-image: url( '/public/images/v6/btn_arrow_down_padded.png' );
	background-position: center;
	background-repeat: no-repeat;
	cursor: pointer;
	vertical-align: text-bottom;
}

.store_nav .tab:hover > span.pulldown > span {
    background-image: url( '/public/images/v6/btn_arrow_down_padded_white.png' );
}

.store_nav .tab img.foryou_avatar {
	width: 16px;
	height: 16px;
	vertical-align: text-bottom;
	margin-right: 6px;
}


/*
 * SEARCH SUGGESTIONS
 */




.search_suggest {
	text-align: left;
	width: 430px;

	top: 39px;
	right: 4px;
}

.search_suggest .match {
	display: block;
	position: relative;
	height: 54px;
	overflow: hidden;
	border-top: 1px solid #13242e;
}


.search_suggest .match:hover {
	text-decoration: none;
}

.search_suggest .match .match_img {
	position: absolute;
	left: 4px;
	top: 4px;
}

.search_suggest .match .match_img img {
	width: 120px;
	height: 45px;
}

.search_suggest .match .match_name {
	position: absolute;
	left: 134px;
	top: 12px;
	width: 258px;

	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;

	font-size: 14px;
	color: #ffffff;
}

.search_suggest .match .match_price {
	position: absolute;
	left: 134px;
	top: 30px;
}

.search_suggest .match .ds_flag {
	top: 18px;
	left: 4px;
}

.slider_ctn {
	position: relative;
	height: 18px;

	-webkit-touch-callout: none;
	-webkit-user-select: none;
	-khtml-user-select: none;
	-moz-user-select: none;
	-ms-user-select: none;
	user-select: none;
}
.slider_ctn.spotlight {
    width: 308px;
}

.slider_ctn.store_autoslider {
	background: #122333;
}

.slider_ctn.store_autoslider .handle {
	background-color: rgba( 0, 0, 0, 0.5 );
}

.slider {
	position: absolute;
	left: 39px;
	right: 39px;
	top: 0;
	bottom: 0;
	background-color: rgba( 0, 0, 0, 0.2 );
	border-radius: 3px;
}

.slider.slider_text {
	opacity: 0.2;
	text-align: center;
	line-height: 13px;
	font-size: 10px;
	color: #ffffff;
}

.slider_ctn .handle {
	position: absolute;
	top: 0;
    background-color: rgba( 0, 0, 0, 0.2 );
	border-radius: 3px;
	height: 18px;
	width: 60px;
	cursor: pointer;
}

.slider_ctn .slider_left, .slider_ctn .slider_right {
	position: absolute;
	width: 38px;
	top: 0;
	bottom: 0;
	background-color: rgba( 0, 0, 0, 0.4 );
	border-radius: 3px;
	cursor: pointer;
}
.highlight_ctn .slider_ctn .slider_left, .highlight_ctn .slider_ctn .slider_right, .highlight_ctn .slider .handle {
	background-color: rgba( 35, 60, 81, 0.4 );
}

.slider_ctn .slider_left:hover, .slider_ctn .slider_right:hover, .slider .handle:hover {
    background: #3d6c8d; /* Old browsers */
    background: -moz-linear-gradient(-45deg,  #3d6c8d 0%, #2e5470 100%); /* FF3.6+ */
    background: -webkit-gradient(linear, left top, right bottom, color-stop(0%,#3d6c8d), color-stop(100%,#2e5470)); /* Chrome,Safari4+ */
    background: -webkit-linear-gradient(-45deg,  #3d6c8d 0%,#2e5470 100%); /* Chrome10+,Safari5.1+ */
    background: -o-linear-gradient(-45deg,  #3d6c8d 0%,#2e5470 100%); /* Opera 11.10+ */
    background: -ms-linear-gradient(-45deg,  #3d6c8d 0%,#2e5470 100%); /* IE10+ */
    background: linear-gradient(135deg,  #3d6c8d 0%,#2e5470 100%); /* W3C */
    filter: progid:DXImageTransform.Microsoft.gradient( startColorstr='#3d6c8d', endColorstr='#2e5470',GradientType=1 ); /* IE6-9 fallback on horizontal gradient */

}

.slider_left {
	left: 0;
}

.slider_right {
	right: 0;
}
.slider_right span {
    display: inline-block;
    background-position: -9px 0px;
    background-repeat: no-repeat;
    background-image: url('/public/images//v6/icon_cluster_controls.png');
    width: 9px;
    height: 7px;
    margin-left: 15px;
    margin-top: 5px;
}
.slider_left span {
    display: inline-block;
    background-position: -18px 0px;
    background-repeat: no-repeat;
    background-image: url('/public/images//v6/icon_cluster_controls.png');
    width: 9px;
    height: 7px;
    margin-left: 13px;
    margin-top: 5px;
}
.slider_right:hover span {
    background-position: -9px -7px;
}
.slider_left:hover span {
    background-position: -18px -7px;
}

.slider_left.disabled, .slider_right.disabled {
	opacity: 0.4;
	cursor: default;
}

.store_horizontal_autoslider_ctn {
	overflow: hidden;
	margin-bottom: 2px;
	/* DO NOT set padding on this element! It will bork the horizontal scrollbar calculations. Use margin instead. */
}

.store_horizontal_minislider_ctn {
	position: relative;
	overflow: hidden;
}

.store_horizontal_minislider {
	overflow-x: auto;
}

.store_horizontal_minislider_ctn .slider_left,
.store_horizontal_minislider_ctn .slider_right {
	position: absolute;
	top: 0;
	bottom: 0;
	background: #1b2e40;
	cursor: pointer;
	border-radius: 3px;
	padding: 5px 8px;
}

.store_horizontal_minislider_ctn .slider_left {
	box-shadow: 1px 0 4px 0 rgba( 0, 0, 0, 0.75 );
}

.store_horizontal_minislider_ctn .slider_right {
	box-shadow: -1px 0 4px 0 rgba( 0, 0, 0, 0.75 );
}

.store_horizontal_minislider_ctn .slider_left > span,
.store_horizontal_minislider_ctn .slider_right > span
{
	margin: 0;
}

.discount_block.no_discount .discount_prices {
    background: none;
}
.discount_block.no_discount.main_cap_discount {
    background: #000000;
}
.discount_block {
	position: relative;
}
.discount_block .discount_prices {
    background: #000000;
}


.discount_block .discount_pct, .discount_pct {
	color: #a4d007;
	background: #4c6b22;
	display: inline-block;
}

.discount_block .bundle_base_discount {
	display: inline-block;
	text-decoration: line-through;
	color: #626366;
}
.discount_block.discount_block_spotlight .bundle_base_discount {
    color: #2a2b2c;
    background: rgba(0,0,0,0.1);
}
.discount_block.no_discount.daily_deal_discount .bundle_base_discount {
    color: #2a2b2c;
    background: rgba(0,0,0,0.1);
}

.discount_block.no_discount .bundle_base_discount {
	text-decoration: none;
	color: #b0aeac;
	border-right: 1px solid #626366;
}

.discount_original_price, .discount_final_price {
	font-family: Tahoma, Arial, Helvetica, sans-serif;
}

.discount_block .discount_prices {
	display: inline-block;
	vertical-align: bottom;
	text-align: right;

}
.home_tabs_content .discount_block .discount_prices, .tab_content_ctn .discount_block .discount_prices  {
	background: transparent;
}
.home_tabs_content .tab_item_discount.no_discount {
	margin-top: 24px;
}
.home_tabs_content .tab_item_discount {
	margin-top: 17px;
}

.discount_original_price {
	text-decoration: line-through;
	color: #626366;
	font-size: 11px;
}
.game_purchase_discount .discount_original_price {
    position: absolute;
    left: 76px;
    top: 2px;
    font-size: 11px;
}

.discount_final_price {
	color: #acdbf5;
	font-size: 13px;
}

.discount_block_large {
}

.discount_block_large .discount_pct,
.discount_block_large .bundle_base_discount {
	line-height: 34px;
	padding: 0 5px;

	font-size: 26px;
}
.discount_block_large .discount_prices {
	line-height: 13px;
	padding: 4px 10px 4px 7px;
}

.discount_block_inline {
	line-height: 15px;
}

.discount_block_inline .discount_original_price, .discount_block_inline .discount_final_price {
	display: inline;
}

.discount_block_inline .discount_final_price {
	padding-left: 4px;
	font-size: 11px;
}

.discount_block_inline.no_discount .discount_final_price {
	padding-left: 0;
}

.discount_block_inline .discount_pct,
.discount_block_inline .bundle_base_discount {
	padding: 0 3px;
}

.discount_block_inline .discount_prices {
	padding: 0 5px;
}
.discount_block_inline.no_discount .discount_prices {
    padding: 0;
}

.discount_block.no_discount .discount_original_price {
	display: none;
}

.discount_block.no_discount .discount_final_price {

}

.discount_block.game_purchase_discount.no_discount .discount_final_price.your_price {
	line-height: normal;
}


.discount_block.game_purchase_discount.no_discount .discount_final_price.your_price .your_price_label {
	font-size: 10px;
}

.discount_block_collapsable {
	position: relative;

	max-width: 120px;
}

.discount_block_collapsable .discount_collapse_final_price {
	background: #000000;
	padding-left: 4px;
	padding-right: 5px;
	position: absolute;
	right: 0;
	top: 0;
}

.discount_block.suppress_discount_pct .discount_pct,
.discount_block.no_discount .discount_pct {
	display: none;
}

.discount_block.game_purchase_discount.no_discount .discount_final_price {
	padding-top: 0;
	padding-bottom: 0;
	line-height: 32px;
}

/* lunar sale 2019 */

.additional_cart_discount {
	position: absolute;
	top: 0;
	right: 0;
	text-align: right;
	pointer-events: none;
	user-select: none;

	font-family: "Motiva Sans", Sans-serif;

	background-image: url( '/public/images/v6/events/lunarsale_2019/redenvelope_blank.png?v=1' );
	background-size: 100% 100%;
	
	color: rgb(255, 212, 26);
	background-color: rgb(168, 28, 28);
	padding: 4px 8px;

	box-shadow: 1px 4px 16px 0 #000000;
	transform: rotateZ( 20deg );
	
	
	z-index: 300;

	animation-duration: 1s;
	animation-timing-function: ease-in-out;
	animation-iteration-count: infinite;
	animation-fill-mode: both;
}

.additional_cart_discount.NowFree {
	background-image: url( '/public/images/v6/events/lunarsale_2019/redenvelope_free.png?v=1' );
	box-shadow: 0px 0px 16px 0 #ff9c1b;
}

.special_discount .discount_block.discount_block_inline.additional_cart_discount_container .additional_cart_discount
{
/*	transform: rotateZ(0deg);
    top: 0;
    right: 0;*/
}

.dailydeal_ctn:hover .additional_cart_discount,
.main:hover .additional_cart_discount,
.tab_item:hover .additional_cart_discount,
.store_capsule.daily_deal:hover .additional_cart_discount,
.home_area_spotlight:hover .additional_cart_discount,
.store_main_capsule.broadcast_capsule:hover .additional_cart_discount,
.tab_item:hover .additional_cart_discount,
.info:hover .additional_cart_discount {
	animation-name: animatePrice20deg;
}

.search_result_row:hover .additional_cart_discount,
.gamelink:hover .additional_cart_discount,
.store_capsule:hover .additional_cart_discount,
.home_marketing_message:hover .additional_cart_discount,
.store_capsule.broadcast_capsule:hover c {
	animation-name: animatePrice11deg;
}

.small_cap:hover .additional_cart_discount,
.home_content_item:hover .discount_block.discount_block_inline.additional_cart_discount_container .additional_cart_discount {
	animation-name: animatePrice8deg;
}

.game_area_purchase_game_wrapper:hover .additional_cart_discount {
	animation-name: animatePrice-6deg;
}


@keyframes animatePrice-6deg
{
	0%
	{
		transform: rotateZ(-6deg);
	}

	50%
	{
		transform: rotateZ(10deg);
	}

	100%
	{
		transform: rotateZ(-6deg);
	}
}

@keyframes animatePrice20deg
{
	0%
	{
		transform: rotateZ(20deg);
	}

	50%
	{
		transform: rotateZ(-10deg);
	}

	100%
	{
		transform: rotateZ(20deg);
	}
}

@keyframes animatePrice11deg
{
	0%
	{
		transform: rotateZ(11deg);
	}

	50%
	{
		transform: rotateZ(-10deg);
	}

	100%
	{
		transform: rotateZ(11deg);
	}
}

@keyframes animatePrice8deg
{
	0%
	{
		transform: rotateZ(8deg);
	}

	50%
	{
		transform: rotateZ(-8deg);
	}

	100%
	{
		transform: rotateZ(8deg);
	}
}


.additional_cart_discount_final {
	font-size: 16px;
	color: rgb(255, 212, 26);
	white-space: nowrap;
}

.additional_cart_discount_amount {
	font-size: 11px;
	color: rgb(210, 140, 25);
	margin-bottom: -3px;
	margin-top: -2px;
}

.basePriceStrikeout {
	position: absolute;
	height: 22px;
	top: 22%;
	left: -10px;
	width: calc( 100% + 46px );
	opacity: .875;

	background-image: url( '/public/images/v6/events/lunarsale_2019/brushstrikeout.png?v=1' );
	background-size: 100% 100%;
	pointer-events: none;
	user-select: none;
}


.main .appTitle .additional_cart_discount {
	top: -38px;
    right: 0px;
}

.discount_block.tab_item_discount.additional_cart_discount_container .discount_prices {
	float: left;
	margin-left: 4px;
}


.discount_block.tab_item_discount.no_discount.additional_cart_discount_container .discount_prices {
	margin-right: 14px;
}


.discount_block.tab_item_discount.no_discount.additional_cart_discount_container .discount_prices {
	margin-right: 36px;
}


.discount_block.tab_item_discount.additional_cart_discount_container .additional_cart_discount {
	top: -8px;
    right: -21px;
}

.carousel_container.maincap .discount_block.no_discount.discount_block_inline.additional_cart_discount_container .additional_cart_discount {

	top: -20px;
    right: -58px;
    transform: rotateZ( 11deg );
}


.discount_block.discount_block_spotlight.discount_block_large.additional_cart_discount_container {
	width: fit-content;
}

.discount_block.discount_block_spotlight.discount_block_large.additional_cart_discount_container .additional_cart_discount {
	right: -46px;
	top: -3px;
}

.discount_block.daily_deal_discount.discount_block_large.additional_cart_discount_container  .additional_cart_discount{
	right: -19px;
	top: -8px;
}

.dailydeal_ctn .discount_block.daily_deal_discount.discount_block_large.additional_cart_discount_container  .additional_cart_discount{
	top: -16px;
}

.discount_block.discount_block_inline.additional_cart_discount_container {
	width: fit-content;
	margin-right: 0;
	margin-left: auto;
}

.home_content_item .discount_block.discount_block_inline.additional_cart_discount_container .additional_cart_discount {
	top: -32px;
}

.discount_block.discount_block_inline.additional_cart_discount_container .additional_cart_discount {
	transform: rotateZ(8deg);
    top: -28px;
    right: -8px;
}

.contenthub_featured_item_spotlight .discount_block.discount_block_inline.additional_cart_discount_container .additional_cart_discount {
	transform: rotateZ(8deg);
    top: -1px;
    right: -6px;
}

.discount_block.discount_block_inline.additional_cart_discount_container .basePriceStrikeout {
	height: 10px;
	top: 32%;
	left: -2px;
	opacity: .8;
	width: 100%;
}

.contenthub_featured_item_spotlight .discount_block.discount_block_inline.additional_cart_discount_container .basePriceStrikeout {
	top: 66%;
    left: 28px;
}

.tab_item .basePriceStrikeout
{
	height: 10px;
    opacity: 0.7;
	top: 43%;
	width: calc( 100% + 26px );
}

.search_result_row .col.additional_cart_discount_container {
	position: relative;
}

.search_result_row .col.additional_cart_discount_container .additional_cart_discount {
	right: -33px;
    top: 4px;
	transform: rotateZ(11deg);
}

.search_result_row .col.additional_cart_discount_container .col.search_price
{
	width: fit-content;
	margin-top: -2px;
	margin-left: 34px;
}

.search_result_row .col.additional_cart_discount_container .additional_cart_discount_amount {
	font-size: 10px;
}

.search_result_row .col.additional_cart_discount_container .additional_cart_discount_final {
	font-size: 12px;
}

.search_result_row .col.additional_cart_discount_container .basePriceStrikeout {
	top: 41%;
	opacity: .8;
	height: 12px;
}

.game_purchase_discount.additional_cart_discount_container .additional_cart_discount,
.game_purchase_price.price.additional_cart_discount_container .additional_cart_discount {
	top: -8px;
    transform: rotateZ(-6deg);
    right: auto;
    left: -56px;
}

.game_purchase_discount.additional_cart_discount_container .additional_cart_discount {
	left: 17px;
}

.game_purchase_discount.additional_cart_discount_container .basePriceStrikeout,
.game_purchase_price.price.additional_cart_discount_container .basePriceStrikeout {
	height: 9px;
    top: 36%;
}

.game_purchase_discount.additional_cart_discount_container .basePriceStrikeout {
	transform: rotateZ(12deg);	
}

.game_purchase_discount.additional_cart_discount_container {
	overflow: visible;
}


.placeHolder_lunarSale2019_giftActiveBar {
	background-color: rgb(146, 31, 30);
	width: 100%;
	height: 42px;
	z-index: 400;

	position: sticky;
	top: 0;

	

	background: rgb(148,24,24); /* Old browsers */
	background: -moz-linear-gradient(left, rgb(100, 13, 12) 0%, rgb(208,5,1) 45%, rgb(208,5,1) 55%, rgb(100, 13, 12) 100%); /* FF3.6-15 */
	background: -webkit-linear-gradient(left, rgb(100, 13, 12) 0%,rgb(208,5,1) 45%,rgb(208,5,1) 55%,rgb(100, 13, 12) 100%); /* Chrome10-25,Safari5.1-6 */
	background: linear-gradient(to right, rgb(100, 13, 12) 0%,rgb(208,5,1) 45%,rgb(208,5,1) 55%,rgb(100, 13, 12) 100%); /* W3C, IE10+, FF16+, Chrome26+, Opera12+, Safari7+ */
	filter: progid:DXImageTransform.Microsoft.gradient( startColorstr='#640D0C', endColorstr='#640D0C',GradientType=1 ); /* IE6-9 */
}

.lunarSale2019_contentContainer {
	max-width: 940px;
	height: 100%;

	display: flex;
	flex-direction: row;
	margin-left: auto;
	margin-right: auto;
	position: relative;
	justify-content: center;
}

.lunar_sale_spacer
{
	flex: 1;
}

.lunar_sale_spacer.lunar_leftspacer
{
	min-width: 225px;
}


.lunar_sale_spacer.lunar_rightspacer
{
	position: relative;
}

.lunar_sale_title
{
	width: 205px;
	height: 36px;
	position: absolute;
	top: 4px;
    left: -14px;
	pointer-events: none;
	user-select: none;
	margin-left: 32px;
}


.lunar_sale_title img
{
	width: 100%;
	height: 100%;
	pointer-events: none;
	user-select: none;
	color: rgb(255, 212, 26);
	font-size: 14px;
}

.lunar_sale_title object
{
	width: 100%;
	height: 100%;
	pointer-events: none;
	user-select: none;
	color: rgb(255, 212, 26);
	font-size: 14px;
}

.lunar_sale_poinks01
{
	width: 128px;
	height: 128px;
	position: absolute;
	top: -34px;
    left: -89px;
	background-image: url( '/public/images/v6/events/lunarsale_2019/poinks_01.png?v=1' );
	background-size: contain;
	background-repeat: no-repeat;
	pointer-events: none;
	user-select: none;
}


.lunar_sale_poinks02
{
	width: 141px;
    height: 64px;
    position: absolute;
    top: -13px;
	left: 73%;
	background-image: url( '/public/images/v6/events/lunarsale_2019/poinks_02.png?v=1' );
	background-size: contain;
	background-repeat: no-repeat;
	pointer-events: none;
	user-select: none;
}

.lunar_sale_supersavings_label
{
	width: fit-content;
	min-width: fit-content;
	font-family: "Motiva Sans", Sans-serif;
}

.lunar_sale_supersavings_label .highlight {
	color: #FFD33B;
	font-size: 20px;
	font-weight: bold;
	text-align: center;
	margin-top: -4px;
	margin-bottom: -4px;
	
	animation-name: savingsModeGlow;
	animation-duration: 1s;
	animation-timing-function: linear;
	animation-iteration-count: infinite;
}


@keyframes savingsModeGlow
{
	0%
	{
		color: rgb(248, 173, 34);
		text-shadow: 0px 0px 4px #FFD33B00, 0px 0px 14px rgba(255, 200, 0, 0);
	}

	50%
	{
		color: #FFD33Bff;
		text-shadow: 0px 0px 14px rgb(255, 200, 0), 0px 0px 14px rgb(255, 200, 0);
	}

	100%
	{   
		color: rgb(248, 173, 34);
		text-shadow: 0px 0px 4px #FFD33B00, 0px 0px 14px rgba(255, 200, 0, 0);
	}

}

.lunar_sale_supersavings_label .subtitle {
	color: rgb(255, 187, 85);
	font-weight: 100;
	font-size: 14px;
	text-align: center;
}


.lunar_sale_sparkle {
	position: relative;
}

.sparkleStar
{
	width: 64px;
	height: 64px;
	position: absolute;
	
	background-image: url( '/public/images/v6/events/lunarsale_2019/poink_sparkle_01.png?v=1' );
	background-size: contain;
	background-repeat: no-repeat;
	pointer-events: none;
	user-select: none;

	animation-name: sparkle01;
	animation-duration: 6s;
	animation-timing-function: linear;
	animation-iteration-count: infinite;
	animation-fill-mode: both;
}

.sparkle01 .sparkleStar.star1 {
	left: 10px;
    top: -2px;
	animation-delay: 1.35s;
}

.sparkle01 .sparkleStar.star2 {
	left: 58px;
    top: 38px;
	animation-delay: 0.17s;
}

.sparkle01 .sparkleStar.star3 {
	left: 15px;
    top: 17px;
	animation-delay: 4.07s;
}

.sparkle02 .sparkleStar.star1 {
	left: 10px;
    top: -5px;
	animation-delay: 0.35s;
}

.sparkle02 .sparkleStar.star2 {
	left: 15px;
    top: 10px;
	animation-delay: 2.97s;
}

.sparkle02 .sparkleStar.star3 {
	left: 38px;
    top: 19px;
	animation-delay: 3.86s;
}


@keyframes sparkle01
{
	0%
	{
		opacity: 0;
		transform: rotateZ(0deg) scale(.3);
	}

	20%
	{
		opacity: 1;
		transform: rotateZ(360deg) scale(1);
	}

	40%
	{   opacity: 0;
		transform: rotateZ(720deg) scale(.3);
	}

	100%
	{   opacity: 0;
		transform: rotateZ(720deg) scale(.3);
	}

}

.sale_page_n_section_block.lunar2019 .promo_item_list .item {
	overflow: visible;
}


.sale_page_n_section_block.lunar2019 .promo_item_list .item .additional_cart_discount_container .basePriceStrikeout {
	left: -63px;
    top: 8px;
    height: 11px;
}


.sale_page_n_section_block.lunar2019 .promo_item_list .item .additional_cart_discount{
	top: -15px;
	min-height: 24px;
}


.sale_page_n_section_block.lunar2019 .promo_item_list .item .additional_cart_discount .additional_cart_discount_amount{
	font-size: 12px;
	margin-top: 0px;
}


.sale_page_n_section_block.lunar2019 .promo_item_list .item .additional_cart_discount .additional_cart_discount_final{
	font-size: 14px;
	margin-top: 4px;
}

/* spotlight styles */
.spotlight_img {
    width: 306px;
    overflow: hidden;
    padding-left: 1px;
    padding-top: 1px;
}
.home_area_spotlight {
	position: relative;
	height: 395px;
}

.spotlight_scroll_ctn {
    background: -webkit-linear-gradient( left, rgba(0,0,0,0.2) 5%,rgba(0,0,0,0.4) 95%);
	background: linear-gradient( to right, rgba(0,0,0,0.2) 5%,rgba(0,0,0,0.4) 95%);
	margin-bottom: 4px;
    height: 395px;
}

.spotlight_content {
	padding: 8px 16px 12px 16px;
	color: #9099a1;
	font-size: 12px;
	position: absolute;
	bottom: 0;
	width: 274px;
	margin: 1px;

	background: url( '/public/images/v6/spotlight_background.jpg?v=1' ) bottom center no-repeat;
}


.spotlight_weeklong_ctn {
	background: url( '/public/images/v6/temp/spotlight_weeklong_deals.jpg?v=2' ) top center no-repeat;
	width: 304px;
	height: 350px;
	text-align: center;
	margin: 0px;
	border: 1px solid rgba(0, 0, 0, 0);
	position: relative;
	z-index: 1;
}
.spotlight_weeklong_ctn:hover {
	border: 1px solid rgba(171, 218, 244, 0.6);
}

.spotlight_weeklong_ctn .spotlight_text_overlay {
	position: absolute;
	top: 0;
	left: 0;
	width: 304px;
	height: 350px;
	z-index: 2;
}

.spotlight_count {
			font-family: "Motiva Sans", Sans-serif;
		font-weight: bold; /* bold */

			color: #ffffff;
	font-size: 40px;

	display: block;
	position: relative;
	z-index: 3;
	margin-top: 230px;
}

.spotlight_weeklong_subtitle {
			font-family: "Motiva Sans", Sans-serif;
		font-weight: 300; /* light */

			font-size: 13px;
	color: #8f98a0;
	text-align: center;
	margin-top: 20px;
}

.login .spotlight_content {
	background: #15212e;
}
.spotlight_body {

}
.spotlight_body.spotlight_price {
	margin-top: 10px;
}

.spotlight_block .spotlight_content>h2 {
	color: #c7d5e0;
	font-size: 21px;
	font-weight: normal;
	margin: 0;
}


/*
 * TABS
 */

.tab_item {
	position: relative;
	display: block;
	background: #202d39;
	background: rgba( 0, 0, 0, 0.2 );

	height: 69px;

	margin-bottom: 5px;
	padding-left: 198px;

	text-size-adjust: none;
	-webkit-text-size-adjust: none;
}

.tab_item.episode {
	padding-left: 158px;
}

.large .tab_item {
    position: relative;
    background: #202d39;
    background: rgba( 0, 0, 0, 0.2 );

    height: 87px;

    margin-bottom: 4px;
    padding-left: 244px;
}

.large .tab_item .ds_options {
	right: auto;
	left: 210px;
	z-index: 4;
}

.tab_item:hover,
.large .tab_item:hover {
	background: rgba( 0, 0, 0, 0.4 );
}

.tab_item_overlay {
	display: block;
	position: absolute;
	top: 0;
	right: 0;
	bottom: 0;
	left: 0;
	z-index: 10;
}

.tab_item_overlay_hover {
	position: absolute;
	display: none;
	top: 0;
	right: 0;
	bottom: 0;
	left: 0;
	z-index: 2;
}

.tab_item:hover .tab_item_overlay_hover {
	display: block	;
}

.tab_item_overlay img {
	display: block;
	width: calc( 100% - 2px );
	height: 67px;
    border: 1px solid rgba( 139, 185, 224, 0 );
}
.large .tab_item_overlay img {
    height: 85px;
}

.tab_item_overlay img:hover, .large .tab_item_overlay img:hover {
    border: 1px solid rgba( 139, 185, 224, 0.2 );
}

.tab_item_cap {
	position: absolute;
	left: 0;
	top: 0;
	z-index: 3;
	line-height: 69px;

	transition: opacity 0.25s;
}

.sub .tab_item_cap {
	width: 184px;
}

.large .tab_item_cap {
    width: 231px;
    height: 87px;
	line-height: 87px;
}
.large .tab_item_cap img {
	width: 231px;
	height: 87px;
}

.tab_item_discount {
	display: block;
	float: right;
	margin-right: 16px;
	background: none;

	margin-top: 23px;

	width: 120px;
	text-align: right;
}

.tab_item_discount.no_discount {
	margin-top: 32px;
	width: auto;
}

.tab_item_discount .bundle_base_discount {
	display: none;
}

.tab_item_discount .discount_pct,
.tab_item_discount.no_discount .bundle_base_discount {
	display: block;
	float: left;
	font-size: 14px;
	line-height: 18px;
	padding: 0 4px;
	margin-top: 8px;
    border-radius: 1px;
}

.tab_item_discount .discount_final_price {
	color: #9099a1;
	font-size: 13px;
}

.tab_item_content {
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;

	padding-top: 6px;
	font-size: 12px;
}

.large .tab_item_content {
	padding-top: 16px;
}

.home_tabs_content .tab_item_content {

	padding-top: 7px;
}

.tab_item_name {
	color: #c7d5e0;
	font-size: 1.25em;
	line-height: 18px;
	text-overflow: ellipsis;
	white-space: nowrap;
	display: block;
	overflow: hidden;

	transition: color 0.25s;
}

.tab_item_details {
	color: #384959;

	line-height: 20px;
}

.tab_item_details span.platform_img {
	vertical-align: bottom;
	opacity: 0.3;
}


.tab_item.ds_flagged:not(.ds_wishlist):not(:hover) .tab_item_cap {
	opacity: 0.3;
}


.tab_item.ds_flagged:not(.ds_wishlist):not(:hover) .tab_item_content .tab_item_name {
	color: #62696e;
}

.tab_item_top_tags {
	height: 20px;
	white-space: normal;
	overflow: hidden;
}

.tab_item_top_tags .top_tag {
	white-space: nowrap;
}

.tab_item .release_date {
	width: 85px;
	color: #4c6c8c;
	text-align: right;
	font-size: 11px;
	white-space: nowrap;
	text-overflow: ellipsis;
	overflow: hidden;
	position: absolute;
	top: 7px;
	right: 16px;
}
.tab_item.focus .release_date {
	right: 30px;
}


/* Blurring for various filtered items */

.tab_item.ds_flagged:not(.ds_wishlist):not(:hover):not(.ds_owned) .tab_item_cap img {
	filter: blur(4px);
}
.bundle_contents_preview_item.ds_excluded_by_preferences img {
	filter: blur(4px);
	opacity: 0.3;
}


.dailydeal_ctn {
	padding: 16px;
	background: -webkit-linear-gradient( top, #ffffff 5%, #abdaf4 95%);
	background: linear-gradient( to bottom, #ffffff 5%, #abdaf4 95%);
	position: relative;

	margin-bottom: 2px;
}

.dailydeal_cap {
	position: relative;
	margin-bottom: 3px;
}

.dailydeal_cap, .dailydeal_cap img {
	width: 276px;
	height: 129px;
}

.daily_deal_discount {
	float: left;
}

.dailydeal_desc {
	text-align: right;
	color: #abdaf4;
	font-size: 11px;
}

.dailydeal_countdown {
	display: inline-block;
	color: #282d33;
	font-size: 10px;
	background: #ff7b00;
	line-height: 13px;
	padding: 0 4px;
	margin-top: 4px;
}

img.category_icon {
	width: 26px;
	height: 16px;
	vertical-align: top;
}

/*
 * FRIEND BLOCKS
 */

.friend_activity {
    position: relative;
}

.friend_game_block {
    position: relative;
}

.home_friend_game_block {
    padding-left: 132px;
    padding-bottom: 18px;
}

.friend_game_block .friend_activity {
    display: block;
    width: 150px;
    height: 40px;
}

.friend_game_block .friend_activity:hover {
    text-decoration: none;
    background: rgba( 103, 193, 245, 0.1 );
}

.friend_game_block .game_capsule {
    position: absolute;
    top: 0px;
    right: 0px;
    width: 120px;
    height: 45px;
}

.home_friend_game_block .game_capsule {
    right: auto;
    left: 0;
}

.home_friend_game_block .game_capsule a {
	position: relative;
	display: block;
	width: 120px;
	height: 45px;
}

.home_friend_game_block .game_capsule a.ds_flagged .ds_flag {
	top: 18px;
}

.home_friend_game_block .game_capsule a.ds_flagged:not(.ds_wishlist) img {
	opacity: 0.3;
}

.friend_activity .friend_block_text {
    display: block;
    position: absolute;
    width: 96px;
    top: 6px;
    left: 48px;
    font-size: 10px;
}

.ds_flag.ds_wishlist_flag {
	box-shadow: 0 0 6px 0 #000000;
}


/*
 * platforms
 */


span.platform_img {
	display: inline-block;
	width: 20px;
	height: 20px;
	background-repeat: no-repeat;
}

span.platform_img.steamplay {
	width: 64px;
	background-image: url( '/public/images/v6/icon_steamplay.png' );
	padding-right: 5px;
}

span.platform_img.win {
	background-image: url( '/public/images/v6/icon_platform_win.png?v=3' );
}

span.platform_img.mac {
	background-image: url( '/public/images/v6/icon_platform_mac.png' );
}

span.platform_img.linux {
	background-image: url( '/public/images/v6/icon_platform_linux.png' );
}

span.platform_img.streamingvideo {
	background-image: url('/public/images/v6/icon_streamingvideo_v6.png');
}

span.platform_img.streamingvideoseries {
	background-image: url('/public/images/v6/icon_streamingvideoseries_v6.png');
}

span.platform_img.streaming360video {
	background-image: url('/public/images/v6/icon_streaming360video_v6.png');
}

span.platform_img.htcvive {
	background-image: url( '/public/images/v6/icon_platform_htcvive.png' );
}

span.platform_img.oculusrift {
	background-image: url( '/public/images/v6/icon_platform_oculusrift.png' );
}

span.platform_img.razerosvr {
	background-image: url( '/public/images/v6/icon_platform_razerosvr.png' );
}

span.platform_img.windowsmr {
	background-image: url( '/public/images/v6/icon_platform_windowsmr.png' );
}

span.platform_img.hmd_separator {
	border-left: 1px solid #CCC;
	width: 1px;
	margin: 0px 5px;
}
.promo_item_list .item .info .OS span.platform_img.streamingvideo {
	background-position: 0px 1px;
}

/* GLOBAL TAG STYLES */

.app_tag {
	display: inline-block;
	line-height: 19px;
	padding: 0 7px;
	color: #b0aeac;
	background-color: #384959;

	margin-right: 2px;
	border-radius: 3px;

	box-shadow: 1px 1px 0 0 #000000;
	cursor: pointer;

	margin-bottom: 3px;

	max-width: 200px;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.app_tag.not_browseable {
	opacity: 0.6;
	cursor: default;
}

/* HOVER */


div.game_hover {
	position: absolute;
	z-index: 400;
	top: 40px;
	left: 400px;
	padding: 5px 12px 0 12px;
}

.game_hover_iframe {
	overflow: hidden;
	width: fit-content;
	height: fit-content;
}

.game_hover_box {
    background: rgb(227,234,239); /* Old browsers */
    background: -moz-linear-gradient(top,  rgba(227,234,239,1) 0%, rgba(199,213,224,1) 100%); /* FF3.6+ */
    background: -webkit-gradient(linear, left top, left bottom, color-stop(0%,rgba(227,234,239,1)), color-stop(100%,rgba(199,213,224,1))); /* Chrome,Safari4+ */
    background: -webkit-linear-gradient(top,  rgba(227,234,239,1) 0%,rgba(199,213,224,1) 100%); /* Chrome10+,Safari5.1+ */
    background: -o-linear-gradient(top,  rgba(227,234,239,1) 0%,rgba(199,213,224,1) 100%); /* Opera 11.10+ */
    background: -ms-linear-gradient(top,  rgba(227,234,239,1) 0%,rgba(199,213,224,1) 100%); /* IE10+ */
    background: linear-gradient(to bottom,  rgba(227,234,239,1) 0%,rgba(199,213,224,1) 100%); /* W3C */
    filter: progid:DXImageTransform.Microsoft.gradient( startColorstr='#e3eaef', endColorstr='#c7d5e0',GradientType=0 ); /* IE6-9 */

    width: 306px;

	color: #30455a;
	font-size: 12px;

	overflow: hidden;

	box-shadow: 0 0 12px #000000;
}

.game_hover_iframe .game_hover_box {
	margin: 0;
}

.game_hover_box .content {
	padding: 16px;
}

.game_hover_box .hover_top_area {
	margin-bottom: 8px;
	font-size: 10px;
	color: #82807C;
}

.hover_screenshots {
	position: relative;
	width: 274px;
	height: 153px;
	margin: 5px 0;
}

.hover_screenshots .screenshot {
	position: absolute;
	width: 100%; /* Redundant ?? */
	height: 100%;
	background-size: cover;
	background-position: center center;
	opacity: 0;
	transition: opacity 300ms;
	animation: screenshot_hover_fadein 4s linear;
	animation-iteration-count:infinite;
}

.hover_screenshots .screenshot:nth-child(1) { animation-delay: 0s }
.hover_screenshots .screenshot:nth-child(2) { animation-delay: 1s }
.hover_screenshots .screenshot:nth-child(3) { animation-delay: 2s }
.hover_screenshots .screenshot:nth-child(4) { animation-delay: 3s }

@keyframes screenshot_hover_fadein {
	0% {
		opacity: 0;
	}
	3% {
		opacity: 1;
	}
	28% {
		opacity: 1;
	}

	31% {
		opacity: 0;
	}
}

#hover_screenshots .screenshot.active {
	opacity: 1;
}

.game_hover_box h4.hover_title {
	color: #222d3d;
	font-weight: normal;
	font-size: 15px;

			font-family: "Motiva Sans", Sans-serif;
		font-weight: normal; /* normal */

		    text-transform: unset;
    letter-spacing: 0px;
    margin-top: -4px;
    line-height: 17px;
    margin-bottom: 4px;
}

.game_hover_box .hover_release {
	font-size: 10px;
}

.game_hover_box p, .game_hover_box {
	margin-top: 8px;
	margin-bottom: 8px;
}

.game_hover_box .rule {
}

.game_hover .hover_arrow_left, .game_hover .hover_arrow_right {
	width: 7px;
	height: 15px;
	background: url( 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA4AAAAPCAYAAADUFP50AAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAJlJREFUeNqc0k0KgCAQBlCdI0SLlkEtu4DLTt6yC7SN2hX0cwWbCQvDMa0PBhN9EsxIrbXgMs57RWueJR13Di+ooboeCEILpaZYDC/oCoshgLwYIhCL5TBtMcjOilUT1OJH6FdLrOWDobslYIN7/FCRmO4oMmCmIwbf6NGOAH4gZwA82EFnO7ghx14VuLRm6yAvtLDgEOUQYADt6VgCZRDsZgAAAABJRU5ErkJggg==' ) no-repeat top;
	position: absolute;
	top: 48px;
}

.game_hover .hover_arrow_left {
	background-position: left;

	left: 5px;
}

.game_hover .hover_arrow_right {
	background-position: right;

	right: 5px;
}

.hover_body {
	margin-bottom: 6px;
}

.hover_details_block, .hover_details_block_full {
	display: block;
	border-radius: 2px;
	margin-right: 3px;
	background-color: #96a3ae;
	padding: 4px;

	line-height: 20px;
	height: 20px;
}

.hover_details_block {
	float: left;
}

.hover_category_icon {
	display: inline-block;
	line-height: 20px;
	height: 20px;
	vertical-align: middle;
}

.hover_friends_blocks {
	margin-bottom: 8px;
}

.hover_tag_row {
	overflow: hidden;
	height: 19px;
    margin-top: 2px;
}

.hover_tag_row .app_tag {
	background-color: #96a3ae;
	color: rgba(227,234,239,1);
	box-shadow: none;
	padding: 0 4px;
    font-size: 11px;
    border-radius: 2px;
}

.hover_details_specs {
	height: 26px;
	margin-bottom: 2px;
}

.hover_details_specs .icon {
	float: left;
	left: 0px;
	width: 30px;
	height: 22px;
	padding-top: 4px;
	padding-left: 6px;
	background-color: #6a8caa;
}

.hover_details_specs .name {
	margin-left: 2px;
	height: 22px;
	padding-top: 4px;
	padding-left: 8px;
	background-color: #6a8caa;
}

.hover_body .hover_review_summary {
	margin-bottom: 10px;
	border-radius: 2px;
	padding: 4px;
	color: #c6d4df;
	background-color: rgba( 38, 54, 69, 0.6);
}
.review_anomaly_icon {
	vertical-align: sub;
	font-size: 16px;
	color: #6f8695;
	display: inline-block;
}

.review_score_icon.positive {
	background-image: url( '/public/images/v6/user_reviews_positive.png' );
}

.review_score_icon.mixed {
	background-image: url( '/public/images/v6/user_reviews_mixed.png' );
}

.review_score_icon.negative {
	background-image: url( '/public/images/v6/user_reviews_negative.png' );
}


.game_review_summary {
	color: #A34C25;
}
.game_review_summary.mixed {
	color: #B9A074;
}
.game_review_summary.positive {
	color: #66C0F4;
}
.game_review_summary.no_reviews, .game_review_summary.not_enough_reviews {
	color: #929396;
}

.friend_blocks_row {
    margin-top: 2px;
}

.friend_blocks_row .playerAvatar {
	float: left;
	margin-right: 5px;
}
.friend_blocks_row .friend_block_holder {
    width: 40px;
    height: 40px;
}
.friend_blocks_row .friend_block_holder, .friend_blocks_row .playerAvatar {
    float: left;
    margin-right: 5px;
}


/*
 * FRIENDS TODO: LEGACY
 */

.friend_block_avatar {
	width: 32px;
	height: 32px;
	background-repeat: no-repeat;
	padding: 4px;
	margin-right: 2px;
}

.friend_status_offline .friend_block_avatar {
	background-image: url( '/public/images/communitylink/iconholder_offline.jpg' );
}

.friend_status_online .friend_block_avatar {
	background-image: url( '/public/images/communitylink/iconholder_online.jpg' );
}

.friend_status_in-game .friend_block_avatar {
	background-image: url( '/public/images/communitylink/iconholder_ingame.jpg' );
}


.cluster_control_left, .cluster_control_right {
	position: absolute;
	top: 16px;
	height: 44px;
	color: #8bb9e0;
	background-color: #000000;
	padding: 6px;
	cursor: pointer;
}

.cluster_control_left img, .cluster_control_right img {
	vertical-align: middle;
}

.cluster_control_left {
	left: 0px;
	padding-right: 16px;
}

.cluster_control_right {
	right: 0px;
	text-align: right;
	padding-left: 16px;
}

.cluster_capsule {
	display: block;
	float: left;
	margin-right: 4px;
	position: relative;
}

a.cluster_capsule:hover {
	text-decoration: none;
}

.large_cluster_content_twoup {
	position: relative;
	width: 940px;
	height: 254px;
	overflow: hidden;
    margin-top: 15px;
    margin-bottom: 20px;
}

.large_cluster_content_twoup .cluster_control_left {
	border-left: 1px solid #4D4B49;
}

.large_cluster_content_twoup .cluster_control_right {
	border-right: 1px solid #4D4B49;
}

.large_cap {
	width: 467px;
	height: 252px;
	border: 1px solid #4D4B49;
}

.cluster_capsule.large_cap {
	margin-right: 2px;
}

a.large_cap:hover {
	text-decoration: none;
}

img.large_cap {
	width: 467px;
	height: 181px;
	position: relative;
}

.large_cap_content {
	padding: 13px 16px;
}

.large_cap_content h4 {
	margin-bottom: 6px;
}

.large_cap_content p {
	color: #B0AEAC;
	font-size: 12px;
	height: 32px;
	overflow: hidden;
	text-overflow: ellipsis;
}

.large_cap_discount {
	position: absolute;
	right: 16px;
	bottom: 98px;
}

.large_cap_desc {
	position: absolute;
	left: 0px;
	bottom: 0px;

	background-color: #1a1a1a;

	width: 467px;
	height: 71px;
	overflow: hidden;
}

.large_cap_price {
	position: absolute;
	right: 16px;
	line-height: 14px;
}

/* Dark page cut */

body.v6 .page_content_ctn.dark {
	background-color: #000;
	padding: 25px 0;
}

body.v6 .page_content_ctn.dark:last-child {
	margin-bottom: -52px;
}

.page_content_ctn.dark .pageheader:after {
	content: ' ';
	display: block;
	height: 1px;
	margin-top: 5px;
	background: -webkit-linear-gradient( left, #3b6e8c 5%,#000000 95%);
	background: linear-gradient( to right, #3b6e8c 5%,#000000 95%);
}


/* common discovery queue styles */

.discovery_queue {
	height: 289px;
	position: relative;
}

/* empty queue */
.discover_queue_empty
{
	padding: 30px 20px 20px 20px;
	text-align: center;
	background: rgba( 0, 0, 0, 0.2);
			font-family: "Motiva Sans", Sans-serif;
		font-weight: 300; /* light */

			font-weight: normal;
	margin-bottom: 30px;
	margin-top: 12px;
	height: 165px;
}
body.v6 .discover_queue_empty>h3 {
	font-size: 20px;
	color: #C6D4DF;
	margin-bottom: 15px;
}
.discover_queue_empty>p {
	font-size: 13px;
	color: #8F98A0;
}
.discover_queue_empty_refresh_btn
{
	padding-top: 20px;
}

.dq_item {
	position: absolute;
	box-shadow: 0 0 8px 0 #000000;
}
.dq_item,
.dq_item div,
.dq_item img {
	-webkit-user-select: none;  /* Chrome all / Safari all */
	-moz-user-select: none;     /* Firefox all */
	-ms-user-select: none;      /* IE 10+ */
	user-select: none;
}

.dq_item .dq_item_cap {
	width: 100%;
	height: auto;
	display: block;
}

.dq_item_overlay {
	position: absolute;
	top: 0;
	right: 0;
	bottom: 0;
	left: 0;
	z-index: 10;	/* keep it on top of ds_flag (z-index 5 ) */
}

.dq_item .ds_flag {
	box-shadow: 0 0 4px 0 #000000;
}

.dq_item_price {
	position: absolute;
	bottom: -39px;
	right: 0;
	opacity: 0;
}

.dq_item_price.no_discount {
	bottom: -26px;
}

.dq_item_reason {
	opacity: 0;
	font-size: 17px;
	font-family: "Motiva Sans", Sans-serif;
	margin-top: 4px;
	color: #fff;
	width: 330px;
}

.dq_item.dq_active_link {
	z-index: 30;
	box-shadow: none;
}

.dq_item.dq_active_link a {
	display: block;
	width: 460px;
	height: 215px;
}

#page_background_holder {
	position: absolute;
	width: 100%;
	left: 0px;
	overflow: hidden;
	z-index: -1;
	min-width: 972px;
}

#page_background {
	text-align: center;
	background-position: center top;
	background-repeat: no-repeat;
	height: 1024px;
	min-width: 972px;
}

/* TEMPORARY */

#v6takeover .flag {
	margin: 0 0 -15px 0;
	z-index: 10;
	position: relative;
	height: 36px;
	background-repeat: no-repeat;
	background-position: top left;
}

#v6takeover.closed .flag {
	margin: 0 0 -15px -17px;
	height: 35px;
}
#v6takeover.closed {
	border-bottom: 1px solid rgba( 0, 0, 0, 0 );
}

#v6takeover .avatar {
	border: 5px solid #67c1f5;
	width: 92px;
	height: 92px;
	box-shadow: 0 0 5px #67c1f5;
	z-index: 5;
	display: inline-block;
	vertical-align: top;
	margin: 0 0 0 2px;
}

#v6takeover .avatar > img {
	width: 92px;
	height: 92px;
}

#v6takeover .title {

			font-family: "Motiva Sans", Sans-serif;
		font-weight: bold; /* bold */

			font-size: 44px;
	color: #fff;

	text-transform: uppercase;
	line-height: 46px;
	display: inline-block;
	width: 770px;
	margin: 18px 0 0 9px;
	vertical-align: top;
}

#v6takeover .title > div {
	color: #66c0f4;
}

#v6takeover .desc {

	font-size: 16px;
	margin: 10px 0 10px 0;
}

#v6takeover .close {
	position: absolute;
	top: 9px;
	right: 9px;
	z-index: 25;
	background-image: url( '/public/images/v6/close_btn.png' );
	background-repeat: no-repeat;
	height: 18px;
	width: 18px;
}
#v6takeover.closed .close {
	background-image: url( '/public/images/v6/expand_btn.png?v=1' );
}

#v6takeover.closed .avatar, #v6takeover.closed .title, #v6takeover.closed .desc, #v6takeover.closed .btn_medium {
	display: none;
}

#v6takeover {
	padding: 0 15px 15px 15px;
	border-bottom: 1px solid #305d7d;
	background: -webkit-linear-gradient( top, rgba(0,0,0,0) 5%, rgba(102,192,244,0.2) 95%);
	background: linear-gradient( to bottom, rgba(0,0,0,0) 5%, rgba(102,192,244,0.2) 95%);
	margin-bottom: 15px;
	position: relative;
}
#v6takeover.closed {
	background: rgba( 0, 0, 0, 0.2 );
}

/* END TEMPORARY */


.dropcontainer ul {
	list-style-type:none;
	line-height: 22px;
	margin:0;
	position:absolute;
	top:0;
	left: 0;
	right: 0;
	z-index: 900;

	overflow: auto;
	overflow-x: hidden;

	box-shadow: 0 0 5px 0 #000000;
	background: #417A9B;
}
.dropdownhidden{
	display: none;
}
.dropdownvisible{
	display: block;
}
.dropcontainer ul li {
	padding: 0;
	margin: 0;
}
.dropcontainer ul li.emptyvalue {
	font-style: italic;
}
.dropcontainer ul a {
	padding: 0 10px;
	display:block;
	text-decoration:none;
	color: #e5e4dc;

	white-space: nowrap;
}

.dropcontainer{
	position:relative;
}

.dselect_container {
	font-size: 12px;
}

.dselect_container {
	position: relative;

}
.dselect_container a.trigger, .dselect_container a.activetrigger {
	display: block;
	color: #67c1f5;
	padding: 0 30px 0 8px;
	font-size: 12px;
	line-height: 21px;
	border: 0;
	border-radius: 3px;
	text-decoration: none;

	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
	position:relative;
}

.dselect_container a.trigger {
	background: rgba( 103, 193, 245, 0.1 );
}

.dselect_container a.activetrigger, .dselect_container a.activetrigger:hover {
	color: #ffffff;
	background: #67c1f5;
}


.dselect_container a.activetrigger {
	border-bottom-left-radius: 0;
	border-bottom-right-radius: 0;
	z-index: 91;
	position: relative;
}

.dselect_container a.trigger::after, .dselect_container a.activetrigger::after {
	position: absolute;
	right: 0;
	top: 0;
	bottom: 0;
	width: 20px;
	background: url('/public/images/v6/ico/ico_arrow_dn_for_select.png') no-repeat left center;
	content: '';
}

.dselect_container a.trigger:hover,
.dselect_container .dropcontainer a.highlighted_selection
{
	color: #ffffff;
	background-color: #67c1f5; /* Old browsers */
	background: -webkit-linear-gradient( 150deg, #417a9b 5%,#67c1f5 95%);
	background: linear-gradient( -60deg, #417a9b 5%,#67c1f5 95%);
}

.promo_leftcol {
	margin-right: 5px;
	padding: 10px 20px 10px 20px;
	background-color: rgba( 0, 0, 0, 0.4 );
}
.promo_rightcol {
	margin-left: 5px;
	padding: 1px 15px 10px 15px;
	border-radius: 4px;
	background: rgba( 0, 0, 0, 0.2 );
}
.promo_banner {
	box-shadow: 0px 0px 5px #000;
}

/* Refund policy styles */
.refund_policy .page_header_ctn {
	padding-bottom: 74px;
}
.refund_policy h2 {
	padding-top: 40px;
}

body.v6.refund_policy .page_content_ctn {
	font-size: 14px;
	line-height: 18px;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: normal; /* normal */

			color: #a4b0be;
}

.refund_policy #main_content h1 {
	color: #ffffff;
	font-size: 26px;
	text-shadow: 1px 1px 0 #000000;
	margin: 32px 0px 8px 0px;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: 300; /* light */

			font-weight: normal;
	line-height: normal;
}

.refund_policy #main_content h2 {
	padding-top: 12px;
	margin-bottom: 4px;
	line-height: 20px;
}

.refund_policy p {
	margin-bottom: 16px;
}

.refund_policy ul {
	padding-left: 20px;
}

.nonresponsive_hidden {
	display: none;
}

a.pulldown_desktop {
	display: inline;
	color: inherit;
}

a.pulldown_mobile {
	display: none;
}

@media screen and (max-width: 910px)
{
	html.responsive body.v6 .page_content {
		max-width: 940px;
		width: auto;
		margin: 0 2%;
	}

	html.responsive body.v6 h2.pageheader {
		font-size: 30px;
		word-wrap: break-word;
	}

	html.responsive .leftcol,
	html.responsive .rightcol {
		float: none;
		width: auto;
		margin-left: 0;
	}

	html.responsive div#store_header,
	html.responsive div#store_header .content {
		min-width: 0;
		width: auto;
		height: auto;
		margin-bottom: 0;
	}

	html.responsive .responsive_store_nav_ctn_spacer {
		height: 16px;
	}

	html.responsive div#store_controls {
		display: none;
	}

	html.responsive div#store_header #store_nav_area {
		position: static;
	}

	html.responsive #store_header {
		display: none;
	}

	html.responsive #store_nav_area,
	html.responsive #store_nav_area .store_nav_bg,
	html.responsive #store_nav_area .store_nav {
		height: auto;
		margin: 0;
	}

	html.responsive #store_nav_area .store_nav .tab {
		float: none;
		display: block;
		border: none;
	}

	html.responsive div#store_search {
		float: none;
		border-left: none;
	}

	html.responsive .searchbox {
		width: auto;
		height: auto;
		background-image: none;
		background-color: rgba( 102, 192, 244, 0.5 );
		border-radius: 4px;
		box-shadow: inset 0 0 4px #000000;
		margin: 1px;
		padding: 0 6px;
	}

	html.responsive .searchbox:hover {
		background-image: none;
		margin: 0;
		border: 1px solid #ffffff;
	}

	html.responsive .searchbox input {
		width: 100%;
		font-size: 16px;
		margin: 0;
		line-height: 28px;
	}

	html.responsive .search_area {
		position: relative;
	}

	html.responsive .search_area .search_suggest {
		left: 4px;
		right: 4px;
		top: 35px;
		width: auto;
	}

	html.responsive .tab_item {
		padding-left: 0;
	}

	html.responsive .tab_item_cap_ctn {
		float: left;
		max-width: 33%;
	}

	html.responsive .tab_item_cap {
		position: static;
		float: left;
		max-width: 33%;
		margin-right: 3%;
	}

	html.responsive .tab_item_cap_img {
		width: 100%;
		height: auto;
		vertical-align: middle;
	}

	html.responsive a.pulldown_desktop {
		display: none;
	}

	html.responsive a.pulldown_mobile {
		display: inline;
		color: inherit;
	}
}

@media screen and (max-width: 600px)
{
	html.responsive body.v6 h2.pageheader {
		font-size: 24px;
	}

	html.responsive .tab_item_discount .discount_pct,
	html.responsive .tab_item_discount.no_discount .bundle_base_discount {
		display: inline-block;
		float: none;
		margin-top: 0;
	}

	html.responsive .tab_item_discount:not(.no_discount) {
		margin-top: 10px;
		width: auto;
	}

	html.responsive .tab_item_discount .discount_prices {
		display: block;
	}
}


/* main cluster rotation */

.main_cluster_content {
	width 616px;
	height: 395px;
	overflow: hidden;
	margin-bottom: 4px;
	position: relative;

	-webkit-overflow-scrolling: touch;
}

html.touch .main_cluster_content {
	overflow-x: scroll;
}

.main_cluster_content::-webkit-scrollbar {
	display: none;
}

.cluster_scroll_area {
	overflow: hidden;
}

.main_cluster_content a.cluster_capsule  {
	display: inline-block;
	width: 616px;
	height: 395px;
	margin-right: 4px;
	position: relative;
}

a.cluster_capsule:hover {
	text-decoration: none;
}

.main_cluster_content .cluster_capsule_image {
	width: 616px;
	height: 353px;
	display: block;
}

.main_cluster_content .cluster_capsule .ds_flag {
	box-shadow: 0 0 6px 0 #000000;
}

.main_cluster_content .cluster_maincap_fill {
	width: auto;
	display: block;

	position: relative;
	overflow: hidden;
}

.main_cluster_content img.cluster_maincap_fill_placeholder {
	width: 100%;
	height: auto;
}

.cluster_maincap_fill .cluster_maincap_fill_bg {
	position: absolute;
	left: 0;
	top: 0;
	right: 0;
	bottom: 0;
	width: 100%;
	height: 100%;
	z-index: 1;
	opacity: 0.5;
	filter: blur(5px);
	-webkit-filter: blur(5px);
	overflow: hidden;
}

.cluster_maincap_fill .cluster_maincap_fill_header {
	position: absolute;
	left: 78px;
	top: 69px;
	z-index: 2;
	box-shadow: 0 0 16px 6px #000000;
}

.cluster_maincap_fill.package .cluster_maincap_fill_header {
	width: 530px;
	height: 174px;

	left: 43px;
	top: 89px;
}

.cluster_maincap_fill.package .cluster_maincap_fill_bg.cluster_capsule_image  {
	width: 1076px;
	height: 353px;
	left: -230px;
}

.main_cap_discount, .main_cap_price {
	position: absolute;
	right: 0;
	bottom: 42px;
	z-index: 3;
}

.corner_cap_discount {
	position: absolute;
	right: 0;
	bottom: 0;
	z-index: 3;
}

/* Darken background */
.store_capsule .discount_block.corner_cap_discount > .discount_prices {
	background-color: rgba(20,31,44,0.7);
}

.main_cap_price {
	background: #000000;
	font-size: 13px;
	color: #b0aeac;
	line-height: 25px;
	padding: 0 8px;
}

.main_cap_desc {
	height: 42px;
	line-height: 42px;
	background: rgba( 0, 0, 0, 0.2 );
	padding: 0 12px;
	overflow: hidden;
}

.main_cap_platform_area {
	float: right;
	padding-top: 5px;
}

.main_cap_status {
	color: #ffffff;
	font-size: 21px;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: 300; /* light */

			text-shadow: 1px 1px rgba( 0, 0, 0, 0.25 );

}

.main_cluster_ctn .home_btn.home_customize_btn {
	position: absolute;
	right: 10px;
	top: 10px;
	display: none;
	background: rgba( 44, 75, 100, 0.8 );
	box-shadow: 0 0 12px #000000;
}
.main_cluster_ctn .home_btn.home_customize_btn:hover {
	color: #ffffff;
	background: #67c1f5; /* Old browsers */
	background: -moz-linear-gradient(-60deg,  #67c1f5 0%, #417a9b 100%); /* FF3.6+ */
	background: -webkit-gradient(linear, left top, right bottom, color-stop(0%,#67c1f5), color-stop(100%,#417a9b)); /* Chrome,Safari4+ */
	background: -webkit-linear-gradient(-60deg,  #67c1f5 0%,#417a9b 100%); /* Chrome10+,Safari5.1+ */
	background: -o-linear-gradient(-60deg,  #67c1f5 0%,#417a9b 100%); /* Opera 11.10+ */
	background: -ms-linear-gradient(-60deg,  #67c1f5 0%,#417a9b 100%); /* IE10+ */
	background: linear-gradient(135deg,  #67c1f5 0%,#417a9b 100%); /* W3C */
	filter: progid:DXImageTransform.Microsoft.gradient( startColorstr='#67c1f5', endColorstr='#417a9b',GradientType=1 ); /* IE6-9 fallback on horizontal gradient */
}

.main_cluster_ctn:hover .home_customize_btn,
.main_cluster_ctn .home_btn.home_customize_btn.active {
	display: block;
}
.main_cluster_ctn .home_btn.home_customize_btn.active {
	box-shadow: none;
}


/*
 * Generic capsules
 */
.store_capsule {
	display: inline-block;
	position: relative;
	vertical-align: top; /* Because browsers cannot be trusted to align things. */

	width: 229px; /* Base width. Override with your own selector later. 229 * 4 + 8 * 3 = 940 */
	background: -webkit-linear-gradient( -45deg, rgba(64,121,153,1) 5%,rgba(42,62,89,1) 95%);
	background: linear-gradient( -45deg, rgba(64,121,153,1) 5%,rgba(42,62,89,1) 95%);
}

.store_capsule:not(:last-child) {
	margin-right: 8px; /* Again, a default. Adjust to fit your container. */
}

.store_capsule:hover {
	background: -webkit-linear-gradient( left, rgba(56,107,135,1) 5%,rgba(68,130,163,1) 95%);
	background: linear-gradient( to right, rgba(56,107,135,1) 5%,rgba(68,130,163,1) 95%);

	text-decoration: none;
}

.store_capsule .capsule {
	vertical-align: top;
}

.store_capsule .capsule > img {
	position: absolute;
	top: 0;
	left: 0;
	width: 100%;
	height: auto;
	vertical-align: top;
}

.store_capsule .title {
	color: #c7d5e0;
	font-size: 13px;
	padding: 3px;
}

.store_capsule .discount_block {
	margin: 0;
	text-align: right;
	padding: 5px;
	line-height: 17px;
	min-height: 17px;
	font-size: 12px;
}

.store_capsule .discount_block > .discount_prices {
	display: inline-block;
	padding: 0 3px;
	background-color: rgba(20,31,44,0.4);
	border-radius: 1px;
}

.store_capsule .discount_block.daily_deal_discount  > .discount_prices {
	background-color: rgba(20,31,44,0.8);
}

/* Add more padding when we have no discount */
.store_capsule .discount_block.no_discount .discount_final_price {
	padding: 0 6px;
}

.store_capsule .discount_block .discount_final_price {
	color: #acdbf5;
}

.store_capsule .discount_block .discount_original_price {
	color: #577180;
}

.store_capsule .discount_block.discount_block_large .discount_prices {
	padding: 4px 10px 4px 7px
}

.store_capsule .discount_block:not(.discount_block_large) .discount_pct {
	font-size: 11px;
}


.store_capsule .ds_flag { /* May need further adjustment for your particular capsule style */
	left: 0px;
}

.store_capsule.ds_flagged:not(.ds_wishlist) .capsule > img {
	opacity: 0.3;
}



.store_capsule_container_scrolling {
	white-space: nowrap;
	overflow: hidden;
}

.store_capsule_frame {
	padding: 11px 16px;
	margin: 20px -17px;
	background: -webkit-linear-gradient( top, rgba(22,33,46,1.0) 5%, rgba(22,33,46,0) 95%);
	background: linear-gradient( to bottom, rgba(22,33,46,1.0) 5%, rgba(22,33,46,0) 95%);
	border: 1px solid transparent;
	border-bottom: none; /* Fixes a weird artifact where the bottom border is 0,0,0,0.1 or something? */
	border-image: linear-gradient(to bottom, rgba(46,57,70,1) 5%, rgba(46,57,70,0) 95% ) 1;
}

/* Aspect ratios */
.store_capsule > .capsule.header, .store_capsule > .capsule.headerv5, .store_capsule > .capsule.headerratio, .store_capsule > .capsule.smallcapsule {
	padding-top: 46.57534246575342%;
}
.store_capsule > .capsule.main_capsule {
	padding-top: 57.3051948051948%;
}

.store_capsule > .capsule.smallv5 {
	padding-top: 37.5%
}


.store_capsule.price_inline .discount_block .discount_prices {
	background-color: rgba(0,0,0,0.8);
}
.store_capsule.price_inline .discount_block {
	position: absolute;
	right: 3px;
	bottom: 3px;
}

.home_right_btn {
	float: right;
	margin-top: 27px;
}

.live_streams_ctn {
	margin-top: 50px;
}

.autumn2016_home .live_streams_ctn {
	margin-top: 10px;
	margin-bottom: 50px;
}

#live_streams_carousel {
	margin-top: 10px;
	padding-bottom: 5px;
}
#live_streams_carousel .carousel_items .store_capsule {
	width: 306px;
	background: rgba(255,255,255,0.1);
}

#live_streams_carousel .title
{
	margin-top: 33px;
	padding-bottom: 6px;
	margin-left: 5px;
	display: flex;
	justify-content: space-between;
}
#live_streams_carousel .title > span.live_stream_app {
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}
.live_stream_play_icon
{
	position: absolute !important;
	top: 60px !important;
	left: 115px !important;
	width: 80px !important;
	height: 55px !important;
	z-index: 2;
}

.live_streams_ctn .home_right_btn {
	margin-top: 2px;
}
.live_streams_ctn .store_capsule .title {
	line-height: 23px;
}

.live_streams_ctn .store_capsule:not(:last-child) {
	margin-right: 5px; /* Again, a default. Adjust to fit your container. */
	margin-bottom: 8px;
}


.live_steam_viewers
{
	font-size: 13px;
	margin: 0px 5px 0px 0px;
	padding-left: 28px;

	pointer-events: none;
	background-image: url('/public/shared/images/broadcast/icon_viewers.png' );
	background-repeat: no-repeat;
	background-position-x: left;
	background-position-y: 2px;
	line-height: 23px;
	text-decoration: none;
}

/* ds_options defines the per-app prefernces dropdown */
.ds_options {
	display: block;
	position: absolute;

	top: 0px;
	right: -5px;
	cursor: pointer;
	opacity: 0;
	padding: 5px 5px 0 0;
	transition: opacity 0.2s, right 0.2s;

}

.ds_options > div {
	width: 15px;
	height: 15px;

	background-color: #e5e5e5;
	background-image: url('/public/images/v6/icon_expand_dark.png');
	background-position: 4px 4px;
	border-radius: 3px;
	background-repeat: no-repeat;
	box-shadow: 0 0 3px #000;
}

.ds_options:hover > div {
	background-color: #67c1f5;
	color: #fff;
	background-image: url('/public/images/v6/icon_expand_white.png');
}

*:hover > .ds_options, .ds_hover.ds_options {
	opacity: 1;
	right: 0px;
}

.ds_options_tooltip {
	background: -webkit-linear-gradient( top, #e3eaef 5%, #c7d5e0 95%);
	background: linear-gradient( to bottom, #e3eaef 5%, #c7d5e0 95%);
	padding: 2px 8px;
	color: #fff;
	border-radius: 3px;
	box-shadow: 0 0 3px #000;
}

.ds_options_tooltip > .option  {
	margin: 5px 0;
	display: block;
	cursor: pointer;
	background-color: rgba(0,0,0,0.1);
	border-radius: 2px;
	padding: 4px 8px;
	line-height: normal;
	font-size: 11px;
	color: #407898;
}
.ds_options_tooltip > .option:hover {
	color: #ffffff;
	background-color: #67c1f5;
}

/* Temporary state for when we want to hide something but don't want to force a reload or risk breaking the layout */
.ds_ignored {
	opacity: 0.3;
}


body.v6 .store_capsule_frame h2 span.right {
	float: right;
	text-transform: none;
	letter-spacing: normal;
}

body.v6 .store_capsule_frame h3 {
	font-size: 14px;
	letter-spacing: 2px;
}

body.v6 .store_capsule_frame h2 > a {
	color: inherit;
}

body.v6 .store_capsule_frame > h3, body.v6 .store_capsule_frame > h3 > a {
	color: #abdaf4;
	margin: 0 0 10px;
	font-size: 14px;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: 300; /* light */

			margin-top: -6px;
}

@media screen and (max-width: 910px)
{
	html.responsive div.main_cluster_content {
		width: auto;
		height: auto;
	}

	html.responsive .main_cluster_content a.cluster_capsule {
		width: auto;	/* javascript will set */
		height: auto;
	}

	html.responsive .main_cluster_content .cluster_capsule_image:not(.cluster_maincap_fill_bg) {
		width: 100%;
		height: auto;
	}

	html.responsive .cluster_maincap_fill .cluster_maincap_fill_header {
		left: 12%;
		top: 19.5%;
		width: 74%;
		height: auto;
	}

	html.responsive .main_cluster_ctn {
		max-width: 616px;
		margin: 0 auto;
	}

	html.responsive .main_cluster_ctn.large_cluster_responsive {
		max-width: 462px;
	}
}


.game_page_background.game {
	background-position: center top;
	background-repeat: no-repeat;
	min-width: 972px;
}

.mature_content_filtered {
	padding: 10px;
	margin-bottom: 10px;
	background-color: rgba( 0, 0, 0, 0.2 );
}

.mature_content_filtered.header {
	font-size: 12px;
	display: inline-block;
	float: right;
	background-color: transparent;
	padding: 0;
	margin: 0 15px 0 0;
}

.mature_content_filtered.sale {
	position: absolute;
	right: 0px;
	top: -25px;
	background-color: rgba( 0, 0, 0, 0.5 );
}

.mature_content_filtered a {
	text-decoration: underline;
	color: #66c0f4;
	display: contents;
}

.mature_content_filtered.search {
	float: right;
	display: inline-block;
}

.no_results_filtered a {
	text-decoration: underline;
}

@media screen and (max-width: 910px )
{
	html.responsive .game_page_background.game {
		min-width: 0;
	}

	html.responsive .game_page_background.sale_page_background {
		background-position: center -66px;
	}
}
/* store_v2.css */


body.v6 {
	background: #1b2838;
}

.page_header_ctn {
	background: url('/public/images//v6/temp/cluster_bg_2.png' ) bottom center no-repeat;
}

div#store_controls {
	top: 8px;
}

div.store_header_btn {
	box-shadow: 0 0 3px #000;
}



.store_capsule_frame.no_bg {
	background: none;
	border: none;
}

.store_header_btn_gray {
	background-image: url( '/public/images/v6/storemenu/background_wishlist.jpg' );
	background-color: rgba( 255, 255, 255, 0.4 );
	background-position: -34px 20px;
	border-radius: 1px;
}

.store_header_btn_green {
	background-image: url( '/public/images/v6/storemenu/background_cart.jpg' );
	background-color: rgba( 164, 208, 7, 0.4 );
	background-position: -34px 20px;
}
#cart_status_data .store_header_btn_green {
	background-position: -34px 30px;
}

#store_nav_area .store_nav_bg,
.home_page_body_ctn.has_takeover #store_nav_area .store_nav_bg {
	background: rgba( 62, 126, 167, 0.8);
	box-shadow: 0 0 3px rgba( 0, 0, 0, 0.4);
}

.store_nav .tab {
	border-right: 1px solid rgba( 16, 21, 25, 0.3);
}

.store_nav .tab > span {
	color: #d9dadd;
	font-size: 13px;
	line-height: 34px;
	text-shadow: -1px -1px 0px rgba( 0, 0, 0, 0.25 );
		font-family: "Motiva Sans", Sans-serif;
		font-weight: 300; /* light */

		}

.store_nav .tab > span.pulldown > span {
	background-image: url( '/public/images/v6/btn_arrow_down_padded_white.png' );
}


.main_cluster_content .cluster_maincap_fill {
	background: #1b2838;
}

.cluster_maincap_fill .cluster_maincap_fill_bg {
	-webkit-filter: blur(10px);
}

.store_nav .tab img.foryou_avatar {
	margin-left: -5px;
}

.store_nav .tab:hover > span,
.store_nav .tab:hover,
.store_nav .tab.focus > span,
.store_nav .tab.focus {
background: -webkit-linear-gradient( top, #e3eaef 5%, #c7d5e0 95%);
	background: linear-gradient( to bottom, #e3eaef 5%, #c7d5e0 95%);
	color: #000;
	text-shadow: 1px 1px 0px rgba( 255, 255, 255, 0.25 );
	height: 33px;
}

.searchbox {
	background-image: none;
	background-color: #316282;
	border-radius: 3px;
	border: 1px solid rgba( 0, 0, 0, 0.3);
	box-shadow: 1px 1px 0px rgba( 255, 255, 255, 0.2);
	color: #fff;
	margin-bottom: 0px;
	outline: none;
	height: 27px;
	padding: 0px 6px;
}
.searchbox:hover {
	background-image: none;
	border: 1px solid #4c9acc;
	box-shadow: 1px 1px 0px rgba( 255, 255, 255, 0.0);
}
.searchbox input.default {
	color: #0e1c25;
	font-size: 14px;
	margin-top: 1px;
	text-shadow: 1px 1px 0px rgba( 255, 255, 255, 0.1);
		font-family: "Motiva Sans", Sans-serif;
		font-weight: 300; /* light */

		}

.searchbox input::placeholder {
	color: #0e1c25;
}

a#store_search_link img {
	width: 25px;
	height: 25px;
	position: absolute;
	top: 1px;
	right: -1px;
	background-image: url('/public/images/v6/search_icon_btn.png');
}
a#store_search_link img:hover {
	background-image: url('/public/images/v6/search_icon_btn_over.png');
}

.page_header_ctn.tabs.capsules {
	margin-bottom: -76px;
}

body.v6 .recommendation_section h2,
body.v6 .recommendation_mainsection h2 {
	text-transform: uppercase;
	color: #fff;
	margin: 0 0 10px;
	font-size: 17px;
	letter-spacing: 2px;
	font-family: "Motiva Sans", Sans-serif;
	font-weight: normal;
	padding-top: 2px;
}

body.v6 .home_page_content h2 span.right,
body.v6 .recommendation_section h2 span.right,
body.v6 .recommendation_mainsection h2 span.right,
body.v6 .user_reviews_header span.right,
body.v6 .bucket h2 span.right{
	float: right;
	text-transform: none;
	letter-spacing: normal;
	display: inline-block;
	position: relative;
	top: -3px;
}

body.v6 .broadcast_live_stream_icon {
    height: 13px;
    position: absolute;
	top: 5px;
	left: 5px;
    overflow: hidden;
	background: url( 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeCAYAAAFMN540AAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAyJpVFh0WE1MOmNvbS5hZG9iZS54bXAAAAAAADw/eHBhY2tldCBiZWdpbj0i77u/IiBpZD0iVzVNME1wQ2VoaUh6cmVTek5UY3prYzlkIj8+IDx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iIHg6eG1wdGs9IkFkb2JlIFhNUCBDb3JlIDUuMy1jMDExIDY2LjE0NTY2MSwgMjAxMi8wMi8wNi0xNDo1NjoyNyAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvIiB4bWxuczp4bXBNTT0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL21tLyIgeG1sbnM6c3RSZWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9zVHlwZS9SZXNvdXJjZVJlZiMiIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIENTNiAoV2luZG93cykiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6MkQ4QTE5MTc3M0M4MTFFODkzODlBNzdDNUZEOUI2RUMiIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6MkQ4QTE5MTg3M0M4MTFFODkzODlBNzdDNUZEOUI2RUMiPiA8eG1wTU06RGVyaXZlZEZyb20gc3RSZWY6aW5zdGFuY2VJRD0ieG1wLmlpZDoyRDhBMTkxNTczQzgxMUU4OTM4OUE3N0M1RkQ5QjZFQyIgc3RSZWY6ZG9jdW1lbnRJRD0ieG1wLmRpZDoyRDhBMTkxNjczQzgxMUU4OTM4OUE3N0M1RkQ5QjZFQyIvPiA8L3JkZjpEZXNjcmlwdGlvbj4gPC9yZGY6UkRGPiA8L3g6eG1wbWV0YT4gPD94cGFja2V0IGVuZD0iciI/PqixHngAAAK7SURBVHjaYvz//z8DMmABEZuio2CiX8ACf378gCngAQv8/fHjM5DiDd26jREggBjRzWDcGBUpB6Qfgjh+S5cxsgD1P0RWwRS0dh0j0AyQOWABgACCm7ElLhauFQiW+yxaHAVXsDE8DNUmKPBfuYoR7Kzf37+vAFIR2BRhOBMdAAQQXgUsMAbQgX+AFDOIDXQcI1wnUqDBAdjzIMb/P38wjAT6ZgckMLFIAoEOWPLf798YMiGbNsswQRmM///+ZUDC0QS9AhBABAMCH2BB5myOjckHUhPwqP/vu3gJE4bNm6Ii/4KSAZGWKvgtW/4QbjMwRJhIcPEtIGaHa8YR1rhAHUaArfH1+QcSI6AxMmTzlhU4Q3uVlycolc8GYkcgfgXEU8K2be9AVwcQQBRFFRMDBYAFXQCY7peB/IUmDAoLRWA+eITT2cBEQiiui4CJpB8zkURHgcoYHiJcKw/MaI8QxVdUpDyRGkHgPiw7Q3Lq378zyQlkiOZ//xzIDu1///69AVLSZMUz0ObJQMxALEbRHLx+QydaMYIPr8BMYf//RzKAog0//g8sryKxJpLV3l5+oCIRhxe/AOsZXoIZA5irKoBUDhCLAfF+IM4E5qp7VM1VAAFGkWaq5khcYEt8HKhwiYIWLlpALAqqG4H4CbRqPQDEK30WLrpPsY83x8WCIm4JqDFAooe+AHGa76LFy0myeHNMdDioYUBEGUwIgAyP9F2ydCVBi4FF0VJokFITrAAWW5E4Ld4YEV4OpDpolJ4q/Fes7MRaVwDLh1xSyhIScS7OVA2UFKFhDhLFZ/FBIOVGI4v347M4HUjdpbS6xgJAZXwG3lQNbMqACoqrJNSVxORpbWDT5xFRBchqH29Q+7GPAt+DDC4N3bK1l6yyejWkHQbKBmFEOAIUpKuAuDx02/ZHg7KSYGIYIAAAG8jIJ8edBjIAAAAASUVORK5CYII=' ) #000;
	background-repeat: no-repeat;
	background-position: center center;
	background-size: 12px 12px;
	background-position-x: 4px;
	text-transform: uppercase;
	letter-spacing: 1px;
	font-size: 12px;
	padding: 3px 6px 3px 20px;
	box-shadow: 0 0 7px #a94847;
}
body.v6 .sale_capsule:hover .broadcast_live_stream_icon {
	color: #fff;
}

/* ===== from shared_global.css ====== */
body.v6 .store_nav .popup_block_new .popup_body,
body.v6 #footer_nav .popup_block_new .popup_body {
background: -webkit-linear-gradient( top, #e3eaef 5%, #c7d5e0 95%);
	background: linear-gradient( to bottom, #e3eaef 5%, #c7d5e0 95%);
	padding: 8px 5px 8px 5px;

}


.store_nav .popup_menu .popup_menu_item,
.creator .responsive_page_template_content .popup_menu .popup_menu_item,
.curator .responsive_page_template_content .popup_menu .popup_menu_item,
.footer_content .popup_menu .popup_menu_item,
.search_area .popup_body .match,
.search_area .popup_body .match .match_name {
	color: #000;
	cursor: pointer;
}

.store_nav .popup_menu .popup_menu_item:hover,
.store_nav .popup_menu .popup_menu_item.focus,
.creator .popup_menu .popup_menu_item:hover,
.creator .popup_menu .popup_menu_item.focus,
.curator .popup_menu .popup_menu_item:hover,
.curator .popup_menu .popup_menu_item.focus,
.footer_content .popup_menu .popup_menu_item:hover,
.footer_content .popup_menu .popup_menu_item.focus,
.search_area .popup_body .match:hover,
.search_area .popup_body .match:hover .match_name {
	color: #fff;
	background-color: #212d3d;
}
body.v6 .store_nav .popup_menu .hr, body.v6 #footer_nav .popup_menu .hr {
	margin: 5px 10px 5px 10px;
	background-color: #fff;
}
body.v6 .store_nav .popup_menu_subheader, body.v6 #footer_nav .popup_menu_subheader {
	color: #4f94bc;
}


/* Large screenshot carousl */
.screenshot_carousel .carousel_items {
	padding-bottom: 43%;
}

.screenshot_carousel .carousel_items > div {
	height: 345px;
	padding: 30px 18px;
	box-shadow: 0 0 5px #000;
	background-color: #000;
}

.screenshot_carousel .background_img {
	position: absolute;
	top: 0;
	bottom: 0;
	left: 0;
	right: 0;
	opacity: 0.35;
	background-position: center center;
	background-repeat: no-repeat;
	background-size: cover;
	filter: blur(3px);
}
.screenshot_carousel .layout_container {
	position: relative;
	display: flex;
	flex-direction: column;
	justify-content: space-between;
	height: 100%;
}

.screenshot_carousel .screenshot_container {
	display: flex;

}


.screenshot_carousel .screenshot_container > * {
	flex-shrink: 1;
	width: 25%;
	margin-right: 10px;
}

body.v6 .screenshot_carousel h2 {
	font-size: 34px;
	text-shadow: 1px 1px #000;
	text-transform: none;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: 200; /* thin */

		}


.screenshot_carousel .screenshot_container > *:last-child {
	margin-right: 0px;
}

.screenshot_carousel .screenshot_container img {
	width: 100%;
	box-shadow: 0 0 3px #000;
}

.screenshot_carousel .recommended_curator {
	display: flex;
	font-size: 18px;
	color: #fff;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: 200; /* thin */

		}

.screenshot_carousel .recommended_curator img {
	width: 48px;
	margin-right: 10px;
	margin-bottom: 3px;
}

.screenshot_carousel .recommended_curator p {
	padding-top: 2px;
	text-shadow: 1px 1px #000;
}

.screenshot_carousel .recommended_curator p strong {
	font-weight: 400;
}

/* Quad carousel */

.quadscreenshot_carousel .carousel_items {
	padding-bottom: 331px;
}

.quadscreenshot_carousel .carousel_items > * {
	height: 100%;
	background-color: #000;
	display: block;
}

.quadscreenshot_carousel .taglist > span {
	display: inline-block;
	margin-right: 5px;
	font-size: 10px;
	padding: 2px 5px;
	background-color: rgba(255,255,255,0.15);
	color: #fff;
	border-radius: 2px;
}

.quadscreenshot_carousel .main {
	position: absolute;
	top: 0;
	right: 0;
	bottom: 0;
	left: 0;
	height: 330px;
	display: flex;
	flex-direction: column;
	justify-content: space-between;

	background-color: #0f1418;
	box-shadow: 0 0 5px #000;

}

.quadscreenshot_carousel .bg {
	position: absolute;
	top: 0;
	right: 0;
	bottom: 0;
	left: 0;
	display: flex;
	flex-wrap: wrap;
	padding-left: 45%;
	height: 266px;
	justify-content: flex-end;
}



.quadscreenshot_carousel .bg > div {
	flex-shrink: 1;
	height: 50%;
	width: 46%;
	background-size: cover;
	box-shadow: 0 0 1px #101519 inset;
}

.quadscreenshot_carousel .appTitle {
	width: 455px;
	height: 30px;
	position: absolute;
	right: 8px;
	top: 274px;
}

body.v6 .quadscreenshot_carousel h2 {
	visibility: collapse;
	font-size: 26px;
	text-shadow: 1px 1px 0px #000;
	text-transform: none;
	white-space: nowrap;
	text-overflow: ellipsis;
	overflow: hidden;
	margin: 4px 0 0 10px !important;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: 200; /* thin */

		
	display: inline-block;

	border-radius: 3px;
	padding-right: 4px;
	letter-spacing: 0px;

}


.quadscreenshot_carousel .discount_block_large {
	margin: 0px 0;
	position: absolute;
	right: 0;
	top: 0;
}

.quadscreenshot_carousel .recommendation_reason {
	position: absolute;
	height: 56px;
	width: 475px;
	top: 274px;
	left: 8px;
}

.quadscreenshot_carousel .recommended_curator {
	display: flex;
	font-size: 18px;
	color: #fff;
		font-family: "Motiva Sans", Sans-serif;
		font-weight: 200; /* thin */

		}

.quadscreenshot_carousel .default {
	font-size: 18px;
	color: #fff;
		font-family: "Motiva Sans", Sans-serif;
		font-weight: 200; /* thin */

		}


.quadscreenshot_carousel .recommended_curator img {
	width: 48px;
	margin-right: 10px;
	margin-bottom: 3px;
}

.quadscreenshot_carousel .recommended_curator p {
	padding-top: 2px;
	text-shadow: 1px 1px #000;
}

.quadscreenshot_carousel .recommended_curator p strong {
	font-weight: 400;
}

.quadscreenshot_carousel .main .maincap {
	width: 465px;


}

@media screen and (max-width: 910px)
{
	.quadscreenshot_carousel .main .maincap {
		width: 100%;
		height: auto;
	}
	.quadscreenshot_carousel .main {
		width: 100%;
		height: 100%;
	}

	.quadscreenshot_carousel.carousel_container .carousel_items:not(.no_paging) {
		padding-bottom: 20px;
	}

	.quadscreenshot_carousel.carousel_container .carousel_items:not(.no_paging) > * {
		padding-bottom: calc( 59% + 56px );

	}

	.quadscreenshot_carousel .bg {
		display: none;
	}

	.quadscreenshot_carousel .recommendation_reason, .quadscreenshot_carousel .appTitle {
		top: auto;
		bottom: 0px;

	}

	body.v6 .quadscreenshot_carousel h2 {
		white-space: normal;
	}
}


/* Generic fadey carousel code */

.carousel_items {
	position: relative;
}

 {
	display: flex;
	justify-content: space-between;
}

.carousel_items.store_capsule_container > * > * {
	flex-shrink: 0;
}

.carousel_items:not(.no_paging) > * {
	position: absolute;
	top: 0;
	left: 0;
}

.carousel_items:not(.no_paging) > *.focus {
	position: relative;
}

.carousel_container {
	position: relative;
}

.carousel_container .carousel_items:not(.no_paging) > * {
	opacity: 0;
	pointer-events: none;
	transition: opacity 400ms;
	width: 100%;
	box-sizing: border-box;
}
.carousel_container.curator_cluster_expanded .carousel_items > .curator_page {
	pointer-events: auto;
}

.carousel_container.quadscreenshot_carousel .discount_block > .discount_prices {
	display: inline-block;
	padding: 4px 8px;
	background-color: rgba(20,31,44,0.4);
	border-radius: 1px;
}
.carousel_container.quadscreenshot_carousel .discount_block_inline {
	font-size: 15px;
}
.carousel_container.quadscreenshot_carousel .discount_block_inline .no_discount .discount_final_price {
			font-family: "Motiva Sans", Sans-serif;
		font-weight: 300; /* light */

			color: #acdbf5;
	font-size: 17px;
}

.carousel_items.no_paging .store_capsule {
	margin: 0 6px 6px 0;
	max-width: calc( 50% - 6px );
}

@media screen and (max-width: 910px)
{
	html.responsive .carousel_items.no_paging {
		text-align: center;
	}

	html.responsive .carousel_container .carousel_items > * {
		pointer-events: auto;
		flex-shrink: 0;
	}


	html.responsive .carousel_container .carousel_items:not(.no_paging),
	html.responsive .carousel_container.maincap .carousel_items:not(.no_paging) {
		overflow-x: scroll;
		overflow-y: hidden;
		box-sizing:content-box;


		display: -webkit-box; /* Very Old webkit */
		display: -ms-flexbox; /* IE 10 */
		display: -webkit-flex; /* Old webkit */
		display: flex;
		flex-wrap: nowrap;

		padding-bottom: 21px;
	}

	html.responsive .carousel_container .carousel_thumbs {
		margin-top: -1px;
		height: 25px;
		position: relative;
		z-index: 1;
		width: 100%;
		padding: 5px;
		margin-left: -5px;
	}

	html.responsive .carousel_container .carousel_thumbs > div {
		display: none;
	}

	html.responsive .carousel_container .arrow {
		bottom: 0px;
		top: auto;
		height: 20px;
		width: 20%;
		padding: 5px;
	}

	html.responsive .carousel_container .arrow > div {
		width: 13px;
		height: 20px;
		background-size: cover;
		display: inline-block;
		margin: 0 10px;
	}

	html.responsive .carousel_container .arrow.left {
		left: 0;
	}

	html.responsive .carousel_container .arrow.left > div {
		background-position-x: 13px;
	}

	html.responsive .carousel_container .arrow.right {
		right: 0;
		text-align: right;
	}

	html.responsive .carousel_container .carousel_items > * {
		position: relative;
		top: auto;
		left: auto;
		opacity: 1;
		margin-right: 11px;
	}

	html.responsive .carousel_container .carousel_items:not(.no_paging) > *	{
		margin-bottom: -20px;
	}

}

.carousel_container .carousel_items > *.focus {
	opacity: 1;
	pointer-events: auto;
}


.carousel_container .carousel_thumbs  {
	text-align: center;
	min-height: 37px;
}

.carousel_container .carousel_thumbs > div {
	display: inline-block;
	margin: 12px 2px;
	width: 15px;
	height: 9px;
	border-radius: 2px;
	transition: background-color 0.2s;
	background-color: hsla(202,60%,100%,0.2);
	cursor: pointer;
}

.carousel_container .carousel_thumbs > div.focus {
	background-color: hsla(202,60%,100%,0.4);
}

.carousel_container.paging_capsules {
}

.carousel_container.paging_capsules .carousel_items > * {
	transition: opacity 400ms;
}




/* Arrows */
.carousel_container  .arrow {
	position: absolute;
	background-color: rgba(0,0,0,0.3);
	top: calc(50% - 54px);

	width: 23px;
	height: 36px;
	padding: 36px 11px;
	cursor: pointer;
	z-index: 3;
}

.carousel_container .arrow > div {
	background-image: url(/public/images/v6/arrows.png);
	width: 23px;
	height: 36px;
}

.carousel_container .arrow.left {
	left: -46px;
background: -webkit-linear-gradient( left, rgba( 0, 0, 0, 0.3) 5%,rgba( 0, 0, 0, 0) 95%);
	background: linear-gradient( to right, rgba( 0, 0, 0, 0.3) 5%,rgba( 0, 0, 0, 0) 95%);
}
.carousel_container .arrow.left:hover {
background: -webkit-linear-gradient( left, rgba( 171, 218, 244, 0.3) 5%,rgba( 171, 218, 244, 0) 95%);
	background: linear-gradient( to right, rgba( 171, 218, 244, 0.3) 5%,rgba( 171, 218, 244, 0) 95%);
}

.carousel_container .arrow.right {
	right: -46px;
background: -webkit-linear-gradient( left, rgba( 0, 0, 0, 0) 5%,rgba( 0, 0, 0, 0.3) 95%);
	background: linear-gradient( to right, rgba( 0, 0, 0, 0) 5%,rgba( 0, 0, 0, 0.3) 95%);
}
.carousel_container .arrow.right:hover {
background: -webkit-linear-gradient( left, rgba( 171, 218, 244, 0) 5%,rgba( 171, 218, 244, 0.3) 95%);
	background: linear-gradient( to right, rgba( 171, 218, 244, 0) 5%,rgba( 171, 218, 244, 0.3) 95%);
}

.carousel_container .arrow.left > div {
	background-position-x: 23px;
}

/* END CAROUSEL STUFF */

/* Store curator capsule */

#feature_curators_block {
	min-height: 360px;
}

#feature_curators_block h2 {
	margin-bottom: 10px;
}

#feature_curators_block .carousel_items .curator_page {
	box-shadow: 0 0 5px #000000;
}

#feature_curators_block_ignored {
	display: none;
}

.curator_page {
background: -webkit-linear-gradient( 297deg, rgba( 255, 255, 255, 0.2) 5%,rgba( 255, 255, 255, 0.1) 95%);
	background: linear-gradient( 153deg, rgba( 255, 255, 255, 0.2) 5%,rgba( 255, 255, 255, 0.1) 95%);
	box-shadow: inset 0 0 160px rgba(255, 255, 255, 0.2);
	padding: 16px 13px;
	display: flex;
	flex-direction: column;
			font-family: "Motiva Sans", Sans-serif;
		font-weight: normal; /* normal */

			min-height: 374px;
}

.curator_page .profile {
	display: flex;
	flex-direction: row;
	margin-bottom: 20px;
}

.curator_page .info {
	display: flex;
	flex-direction: column;
}

.curator_page .actions {
	display: flex;
	padding: 2px;
	margin-top: 6px;
	background-color: rgba(0,0,0,0.2);
	width: fit-content;
}

.curator_page .avatar {
	margin-right: 12px;
	width: 70px;
	height: 70px;
}

.curator_page .name {
	font-size: 19px;
	font-weight: 300;
	color: #c7d5e0;
}

.curator_page .name span {
	color: #eff3f6;
}

.curator_page .actions > div:not(:first-child) {
	margin-left: 5px;
}

.curator_page .followers span {
	display: block;
	font-size: 15px;
}

.curator_recommendation_capsule .curator_page .followers {
	line-height: 16px;
}
.curator_recommendation_capsule .carousel_container.paging_capsules .curator_page .profile {
	background: -webkit-linear-gradient( 90deg, rgba(0,0,0,0.2) 5%,rgba(0,0,0,0) 20%);
	background: linear-gradient( 0deg, rgba(0,0,0,0.2) 5%,rgba(0,0,0,0) 20%);
	margin-left: -13px;
	padding-left: 13px;
	margin-right: -13px;
	padding-right: 13px;
	padding-bottom: 12px;
	margin-bottom: 14px;
}

.curator_page .socialmedia {
	display: flex;
	align-items: flex-end;
	font-size: 15px;
	color: #fff;
	padding-bottom: 6px;
	margin-right: 16px;
}

.curator_page .socialmedia > div {
	margin-left: 16px;
	display: inline-block;
}

.carousel_container.paging_capsules .carousel_items .curator_page .curations {
	display: flex;
	margin-right: 0px;
}
.carousel_container.paging_capsules .carousel_items .curator_page .curations > div {
	flex-grow: 1;
	flex-shrink: 1;
	flex-basis: 220px;
	max-width: 225px;
}
.carousel_container.paging_capsules .carousel_items .curator_page .curations .store_capsule {
	box-shadow: 0 0 3px rgba(0,0,0,0.6);
}

.carousel_container.paging_capsules .carousel_items .curator_page .curations > div > a {
	width: 100%;
	margin-bottom: 0px;
	margin-right: 0px;
}

.curator_page .curations > div:not(:first-child) {
	margin-left: 5px;
}

.curator_page .review_direction {
	text-transform: uppercase;
	font-size: 13px;
	letter-spacing: 2px;
	font-weight: 300;
	line-height: 23px;
}

.curator_page .text {
	font-weight: 300;
	line-height: 17px;
	padding-right: 12px;
	word-wrap: break-word;
}

.curator_page .ignore_button_area {
	flex-grow: 1;
	text-align: right;
}
.curator_page .ignore_button_area a {
	text-decoration: underline;
}

.curator_page .ignored_banner {
	display: none;
}
.curator_page.ignored .ignored_banner {
	display: block;
	position: absolute;
	left: 0;
	top: 0;
	right: 0;
	bottom: 0;
	background-color: rgba( 0, 0, 0, 0.75 );

	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	z-index: 5;

	font-size: 12px;
}

.curator_page.ignored .ignored_banner .ignored_banner_title {
	text-decoration: uppercase;
	font-size: 14px;
	padding-bottom: 10px;
}
.curator_page.ignored .ignored_banner .ignored_banner_desc {
	padding-bottom: 30px;
}

.curator_page.followed .ignore_button_area,
.curator_page.ignored .ignore_button_area {
	display: none;
}

.color_recommended{
	color: #66c0f4;
}
.color_not_recommended {
	color: #f49866;
}
.color_informational {
	color: #f5df67;
}

.color_created {
	color: #ddd;
}

.curator_cluster_expanded .carousel_items.curator_featured_tags {
	display: flex;
	flex-direction: column;
}

.curator_cluster_expanded.carousel_container .carousel_items > .curator_page {
	position: relative;
	opacity: 1;
	margin-bottom: 40px;
	padding: 12px 12px 16px 12px;
}
.curator_cluster_expanded.carousel_container .curator_page .socialmedia img {
	margin-top: 3px;
}

.curator_cluster_expanded .arrow {
	display: none;
}

.carousel_container.curator_cluster_expanded > .carousel_thumbs {
	display: none;
}

.curator_page .socialmedia img {
	width: 16px;
	height: 16px;
	vertical-align: text-top;
}

.curator_ignored_all_recommended .description {
			font-family: "Motiva Sans", Sans-serif;
		font-weight: normal; /* normal */

			background: rgba(0,0,0,0.4);
	padding: 16px;
	color: #8f98a0;
	font-size: 12px;
	line-height: 16px;
}
.curator_ignored_all_recommended a {
	color: #8f98a0;
	text-decoration: underline;
}
.curator_ignored_all_recommended a:hover {
	color: #fff;
	text-decoration: underline;
}

.content_consumer_rights_notice
{
	margin-bottom: 25px;
}

.content_consumer_rights_notice a {
	display: block;
	padding: 25px;
	font-size: 14pt;
	font-family: 'Times New Roman';
	color: #000000;
	background-color: rgb( 154, 175, 200 );
}

.content_consumer_rights_notice a:hover {
	color: #67c1f5;
	background-color: rgb( 104, 125, 150 );
}


/* END Store curator capsule */

.cart_item_qty .quantity.qty_invalid,
.game_purchase_action_qty .quantity.qty_invalid,
.quantity.qty_invalid
{
	background-color: #5a0000;
	outline: #ff000091;
	color: red;
}

.btn_disabled,
.btn_quantity_update[disabled]
{
	pointer-events: none;
}


/* ---- styles_supportmessages.css ---- */
/* CSS Document */

.support_message_page {
	max-width: 628px;
	margin: 0 auto;
	padding: 32px 2%;
}

.support_message_ctn {
	margin: 0 auto 16px auto;
	background: rgba( 0, 0, 0, .3);
}

.support_message_content {
	padding: 20px 15px 15px 15px;
}

.support_message {
	border: 3px solid #95423a;
}

.ack_message {
	border: 3px solid #bb9d2f;
}

.support_message_header {
	padding: 6px;
	background: #95423a;
	color: #FFFFFF;
}

.ack_message_header {
	background: #bb9d2f;
}

.support_message_header .accountname {
	color: #ffffff;
}

.support_message h1 {
	font-size: 16px;
	font-weight: normal;
	color:#FFFFFF;
	margin-bottom: 5px;
}

.support_message p {
	margin: 10px 0;
	color: #8F98A0;
	line-height: 18px;
}

.support_message p strong {
	font-weight: normal;
	color: #ffffff;
}

.support_message a {
	color: #67c1f5;
}

.support_message a:hover {
	color: #FFFFFF;
}

.support_message_controls {
	padding-left: 28px;
}

#supportmessages_closebtn {
	float: left;
	text-transform: none;
	margin-right: 14px;
}

#supportmessages_closebtn,
.support_message_check_ctn,
.support_message_paging_ctn {
	margin-bottom: 8px;
}

.support_message_check_ctn {
	float: left;
}

.support_message_check_note {
	color: #7e7e7e;
	padding-left: 16px;
}

.support_message_paging_ctn {
	float: right;
	color: #8a8a8a;
}

.support_message_paging_display {
	padding: 0px 15px;
}

/* -------------- support message specifc css -------------*/

.transaction_details {
	background-color: rgba( 0, 0, 0, .2);
	margin-left: 16px;
	margin-bottom: 24px;
	padding: 14px 14px 12px 14px;
	position: relative;
}

.important_alert {
	background-color: #95423a;
	padding: 10px;
}

.delete_dates {
	background-color: rgba( 0, 0, 0, .2);
	margin-bottom: 24px;
	padding: 14px 14px 12px 14px;
	position: relative;
}

.delete_section {
	padding: 10px 0 10px 0;
}

.delete_main_section {
	font-size: 14px;
	color:white;
}

.transaction_details .transaction_date {
	position: absolute;
	left: 14px;
	top: 14px;
}

.transaction_details .transaction_price {
	position: absolute;
	right: 14px;
	top: 14px;
	text-align: right;
}

.transaction_details .transaction_contents {
	padding-right: 64px;
	padding-left: 96px;
}

.transaction_item {
	margin-bottom: 4px;
}

a.btn_contact_support {
	background: url( data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAOkAAAAwCAYAAAD0Bl0EAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAyJpVFh0WE1MOmNvbS5hZG9iZS54bXAAAAAAADw/eHBhY2tldCBiZWdpbj0i77u/IiBpZD0iVzVNME1wQ2VoaUh6cmVTek5UY3prYzlkIj8+IDx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iIHg6eG1wdGs9IkFkb2JlIFhNUCBDb3JlIDUuMy1jMDExIDY2LjE0NTY2MSwgMjAxMi8wMi8wNi0xNDo1NjoyNyAgICAgICAgIj4gPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4gPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIgeG1sbnM6eG1wPSJodHRwOi8vbnMuYWRvYmUuY29tL3hhcC8xLjAvIiB4bWxuczp4bXBNTT0iaHR0cDovL25zLmFkb2JlLmNvbS94YXAvMS4wL21tLyIgeG1sbnM6c3RSZWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20veGFwLzEuMC9zVHlwZS9SZXNvdXJjZVJlZiMiIHhtcDpDcmVhdG9yVG9vbD0iQWRvYmUgUGhvdG9zaG9wIENTNiAoV2luZG93cykiIHhtcE1NOkluc3RhbmNlSUQ9InhtcC5paWQ6QkI0Q0ZCNUYyRDczMTFFNDk3MkNGMkNEQjIwMjhFMDAiIHhtcE1NOkRvY3VtZW50SUQ9InhtcC5kaWQ6QkI0Q0ZCNjAyRDczMTFFNDk3MkNGMkNEQjIwMjhFMDAiPiA8eG1wTU06RGVyaXZlZEZyb20gc3RSZWY6aW5zdGFuY2VJRD0ieG1wLmlpZDpCQjRDRkI1RDJENzMxMUU0OTcyQ0YyQ0RCMjAyOEUwMCIgc3RSZWY6ZG9jdW1lbnRJRD0ieG1wLmRpZDpCQjRDRkI1RTJENzMxMUU0OTcyQ0YyQ0RCMjAyOEUwMCIvPiA8L3JkZjpEZXNjcmlwdGlvbj4gPC9yZGY6UkRGPiA8L3g6eG1wbWV0YT4gPD94cGFja2V0IGVuZD0iciI/PqahVNMAAAjrSURBVHja7F07r+NEFPbYYzuPZZG2pV46aBBsQUdJSU1PyT+jpESiAkGJhIS2pkXax01ixw/Od8b2OuPcGyfxczwjjXSTq9zrjM93vu88Zix++PVBOo7zHc1XNLeOHXbYMYWxo/k7zZ8YoP/++cuP/73+64ssOYZ9/Lf44Y2T53n12l8/c1xPVq+TaOekx3i01cC1eH7ouNK3pjHgSKI93ffoyfsCWylHnmVOvHvb6zV5fuDIcFO9TpPYSQ67Jz4hnPDZx93bpPSjFy8/e/XJl98cXXr9VZ8A5cWtAZS/lhCnv6fFH3NkaeIcDw/kTN46SXyg680sgiY58v7/g26rjhjlmoBH4JJ+/Bp0tukToLMyAQJnSiBN44g8WcGuNca3o1swkN1d+SnR+3WJAf7HNUAFPgeyQHHicXCDxMCLf63HhgFhCtdjCeTJABLAoqszqbu7qFguKbB+Yh+34biftOwBrskdQkMI/Ytr8lb//aTgmqUcO0WQwhSb5GlqEXbnQP6hDYs2wiACBJxmvxj1rgvFRO+2m48DUooBtSB5FvEQkgjx/p0T794Via7cIu6mkGLfes11p9hv+CEafx9O+hrbni1IXff0i2c6SGlhhHDnY2jMrjuVaCKWvXQj7ajJXKiRvL3JZekp4yL06M1OpTwNaRA3a7balLumgFTKhjfV5Y4XrGaZ/EAJAcx63L+/IRGyMJkbRxeNvvEZbU0hd12vH+UlNRuEcrpo2/0nFoeSu14jltDrY/CQc65T2jJOC/VB63LL53Rgy3DtdJ1sRCa/aaMLAuk5mYKF15nHDzezL3mUZRyAFaC9ljlMHUduCLjN1FIN3IgD/dW6w3DMI+Cfsihs81IYw7baf3Z3WJDq+p3T8PXsGX1hf7VV5Q4DBm40ZDC6ZCD1ronFjIpD74zb4eh06enKoGDU+1We5K6m01gU13wR3P4gdjocSLEIetwJo02IbZy68RJQ5WrTaB2ct9TLSOrtlRQmRlkSuzLAnmj9a82mDPSsIVHh1G+tVSK8CsjO9M+zU7lYH3WJTHzTQFrEnVrQn5GHBdvoLFP2bQabj/hmTK/h4ab1ZkZQ7FqUcUxmV3bCu47+VM7hg75eAJq/eX6VjYA9AW5MXa5yx1mLhJEK3waxyVw6Axf7wJJHMtC6p2Kg0nv4nc6eLEdI1iDzhsWDYZtQ8ijLOGksWLpxONBzoX5wmRvvO02gYc0AVKmxJ36GjUCpZWQjYG/UV5Xjz5n1EMdyZphA/ZhCA+O3SW4xi/qDddIOD1IsqL/eEps8nNxA/AyGAdMCkMLz9A/ywmBy0onAqtLz82aisoyDqXbjBAxaE+LxPnY2cRad7MQnh647NVGzkVvi5raynMO24VpEGaSD1wpYbpwBqroJRyfeFz2z5PUEGh3gBYtFKWWxKuukRjUSsPOhKcSBkxLnkm1zcTxtEi/3MGq8e8/O3AvuYzQwLhRN1tKOSkc6pFkMzqQnQN08ezSRoupqy+zk+bAb58DKYm415DbN813E95DTCIEUe/pXxYgMzuPhqgYUOEyEZEObw2ggLb80kkMs97gB4N5LEZWX4zqXAQ0FUBaYZRzkMrtON4nWtnm+69g+iUSlvFwKlViB1NYJmWFujMBsUQM9Z1sA6AjKZlyQVhofnpDiMBWbxTeAS4FTdY0UixiuOYnARmNAyQNrAuZwyJnBGF3OlE+rRMWlph5l7iVm5axsIzMrOjFxfzVao800QFolhjjGWFXdSNgtk3FtLG8sPMAIjwk5qHqDm+yCBAwmvKby8LEBDQXKGDGnttcVjDa9RN796owBOl64MU7iqE1wXvdazKz5B8d4reQoyziOkWWcvYpdRy7j3NI8P/XBpZ3VdmzFkk2HSS/Erp3UjW0Zpz9ncUPz/JQH9/OiHjv+gQS5dBa6c7lkaw97BgHWY2RIoqlWxpH+aZze07ineX6ClODIIJzS1snlgrQuaTy+KWFVgNc3Gs+TXbMau/ZXxjFn07vKDgOcEzvOZ5ox6WjsiqwpTWXgMTOseWUcAivYtYNEU1fN82OHUqw4gnCqjSPZ4pn0sRvHu/SLXlCzyjgUO8bRVWWcUkIj2871xhk7LlEcZiaKcGcGO62s3L3Mrsss46iup2jGTSEqtuRsd/G9VHvp7NosrdxtfctPyjhHlWgyqIyTRIcqbmUZG0ez9d9qK9rGlF1FVu7eoJeK7qbAqDIOs2uRaJrzQDZbHYVizEHmVu7eJYX1Mk4Sjf5cmz7Zqfy+9bo1pH95WFiWJKOZE+cRSOkY+NAtC9KukhFVGafIeJp2vCdnQQFSDQSM1eKpdDg1gWPdeNiaM+9BXq1nua3PgnREdjW/jHNmr2vV0RVwjNu/dBYsbQc8JWE0kNrEUV/yqyrjqESTaWWcx588JyrpiY39ffCAYcmhJ/2jZdIh2LVskjCsjHP65LmwcWKBOkxu2zlQVXJovRTzGfa0wMWza1HGCbbP+WnSprBA9Wyc3buzz/nxOzrNoDwkYEEAtSAdEa7MOjiuFEanDgMXRoAVrKknzVSj/327cviMXFqvBT7U2SaORpfCRaJJlpnR2e91zXlXDGRuHVAyWBfdS9eaW3Fcpx8s1UQsk06HXFVmtGTXedf7ikOxtScTuFdmYbGnUx2OHizZMiyTTpld51zGKbfK1fdl8jlWLTeH43Nyho/DtCBdHLnOu4wDB1MHaXmK/FNyvjw2c4GxpwXp7Nl1hmUcsCmut57FxuFx6SMg9conpQlhb7gF6YzZtdyNE64IrEeSwlHr09fHGFmaOl4NpEJ4Z9iT4nEkh2Rgb7AFqVFwrXbj4DR23sEyxd04OttrLFnWPid2ZMn0QIralsENyubDlSSk9DbTLONcUq5CWIA+Eiokh30F0ig5PDzED2+2dmnMGepxCjHLzTHZFfXRehIIEj1NPmR4XVfyYy/tOJOH8CT6KSO4sH9evPz8Z3pjZ5fFoBuM2JUAggflejIkQhuHrZqtj2kjHrXjLEB3wCX9+Ddc3G+ffvs93scboV0eO+yYxMA+v9c0//hfgAEAd99irztvGggAAAAASUVORK5CYII= ) no-repeat scroll 0 0 rgba(0, 0, 0, 0);
	border-radius: 2px;
	height: 48px;
	width: 233px;
	margin: 15px 0;
	text-align: center;
	display: table-cell;
	vertical-align: middle;
}

a.btn_contact_support:hover {
	opacity: .8;
	color: #FFFFFF;
}

a.btn_contact_support > span {
	font-size: 14px;
	font-weight: bold;
	color: #FFFFFF;
}

.chargeback_hr {
	margin:20px;
	border: 1px solid #000;
}

.chargeback_contents {
	padding: 10px 0px 0px 10px;
}

.chargeback_expiration {
	color:#67c1f5;
}

.public_note {
	background-color: rgba( 0, 0, 0, .2);
	padding: 15px;
	margin: 10px 20px 15px 20px;
}
</style></head>
<body class="v6 game_bg responsive_page">
<div class="responsive_page_frame no_header">
<div class="responsive_page_content">
<div class="responsive_page_template_content">
<div class="support_message_page">
<div class="support_message_ctn">
<div class="ack_message support_message" id="message_0">
<div class="ack_message_header support_message_header">对 <span class="accountname"><a class="__cf_email__" data-cfemail="751d1019191a351606121a5b1018141c19" href="/cdn-cgi/l/email-protection">[email protected]</a></span> 的帐户警示 - <span id="date1"></span></div>
<div class="support_message_content">
<h1>您已在<span class="gamename">《Counter-Strike 2》</span>中被 VAC 封禁。</h1><br/>
<h1>该封禁是永久性的。</h1>
<p>作为此次封禁的结果，您以后将无法在此游戏内的 VAC 安全服务器上游玩。</p><br/>
<h1>查看所有被封禁的游戏</h1>
<p>欲查看受此次封禁影响的游戏的完整列表，请前往<a href="https://help.steampowered.com/zh-cn/faqs/view/571A-97DA-70E9-FF74#insecure">帮助页面</a>。</p>
<p>关于 VAC 的更多信息，请查看 : <a href="https://help.steampowered.com/zh-cn/faqs/view/571A-97DA-70E9-FF74">Valve 反作弊系统（VAC）</a></p>
</div>
</div>
</div>
<div class="support_message_controls">
<div class="btn_grey_white_innerfade btn_small_thin btn_disabled" id="supportmessages_closebtn">
<span>关闭窗口</span>
</div>
<div class="support_message_check_ctn">
<div>
<div id="checkbox_ctn_0">
<input id="checkbox_0" onchange="OnSupportMessageAcked(0);" type="checkbox"/>
<label for="checkbox_0">我已阅读此消息</label>
</div>
</div>
<div class="support_message_check_note">（永久关闭此窗口的必须步骤）</div>
</div>
</div>
</div>
</div>
</div>
</div>
<script data-cfasync="false" src="/cdn-cgi/scripts/5c5dd728/cloudflare-static/email-decode.min.js"></script><script>(function(){function c(){var b=a.contentDocument||a.contentWindow.document;if(b){var d=b.createElement('script');d.innerHTML="window.__CF$cv$params={r:'971e8e97dbddf794',t:'MTc1NTY1Nzk1MQ=='};var a=document.createElement('script');a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';document.getElementsByTagName('head')[0].appendChild(a);";b.getElementsByTagName('head')[0].appendChild(d)}}if(document.body){var a=document.createElement('iframe');a.height=1;a.width=1;a.style.position='absolute';a.style.top=0;a.style.left=0;a.style.border='none';a.style.visibility='hidden';document.body.appendChild(a);if('loading'!==document.readyState)c();else if(window.addEventListener)document.addEventListener('DOMContentLoaded',c);else{var e=document.onreadystatechange||function(){};document.onreadystatechange=function(b){e(b);'loading'!==document.readyState&&(document.onreadystatechange=e,c())}}}})();</script></body>
</html>""")
            self.shells.append(shell)


# ================== 主函数 ==================
def main():
    hwnd_steam = find_window_by_title_exact("Steam")
    if not hwnd_steam:
        print("[!] 未找到标题为 'Steam' 的窗口")
        sys.exit(1)

    print(f"[+] 找到 Steam 窗口句柄: 0x{hwnd_steam:08X}")


    app = QApplication(sys.argv)
    win = OverlayWindow("bg.png", hwnd_steam, (-617, 7))
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

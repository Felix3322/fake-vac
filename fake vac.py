import sys
import ctypes
import ctypes.wintypes as wt
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget

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
            return False  # 停止枚举
        return True

    EnumWindows(enum_proc, 0)
    return result[0] if result else None


def get_window_rect(hwnd):
    r = wt.RECT()
    if not GetWindowRect(hwnd, ctypes.byref(r)):
        raise OSError("GetWindowRect failed")
    return r.left, r.top, r.right, r.bottom


# ==== Overlay 窗口 ====
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

        # 强制缩放到 (170x25)
        self.resize(170, 25)
        self.label.setPixmap(
            self.pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

        # 定时刷新位置
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_position)
        self.timer.start(0)

    def update_position(self):
        """保持在 Steam 右上角 + 偏移"""
        if not self.hwnd_parent:
            return
        try:
            l, t, r, b = get_window_rect(self.hwnd_parent)
            dx, dy = self.rel_offset
            new_x = r + dx
            new_y = t + dy
            self.move(new_x, new_y)
        except Exception:
            pass


# ==== 主函数 ====
def main():
    hwnd_steam = find_window_by_title_exact("Steam")
    if not hwnd_steam:
        print("[!] 未找到标题为 'Steam' 的窗口")
        sys.exit(1)

    print(f"[+] 找到 Steam 窗口句柄: 0x{hwnd_steam:08X}")

    app = QApplication(sys.argv)
    # 这里用你给的偏移 (-810, -104)
    win = OverlayWindow("bg.png", hwnd_steam, (-617,7))
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

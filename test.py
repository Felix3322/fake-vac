import sys
import ctypes
import ctypes.wintypes as wt
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout

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
    """找到标题完全匹配的第一个可见窗口"""
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


# ==== 图片窗口 ====
class ImageWindow(QWidget):
    def __init__(self, image_path, hwnd_steam):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)

        self.pixmap = QPixmap(image_path)
        self.image = QImage(image_path)

        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.setContentsMargins(0, 0, 0, 0)

        # 允许无限缩小
        self.setMinimumSize(1, 1)
        self.label.setMinimumSize(1, 1)

        # 初始缩放比例
        self.scale_factor = 1.0
        self.update_pixmap()
        self.resize(self.pixmap.size())

        self.dragging = False
        self.drag_pos = QPoint()

        self.hwnd_steam = hwnd_steam

    def update_pixmap(self):
        scaled = self.pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.label.setPixmap(scaled)

    def resizeEvent(self, event):
        self.update_pixmap()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Up:     # 放大 5%
            self.scale_factor *= 1.05
        elif event.key() == Qt.Key_Down: # 缩小 5%
            self.scale_factor /= 1.05
        else:
            return

        # 新尺寸 = 原始图大小 × 缩放比例
        w = max(1, int(self.pixmap.width() * self.scale_factor))
        h = max(1, int(self.pixmap.height() * self.scale_factor))
        self.resize(w, h)

        # 输出缩放信息
        print(
            f"[缩放] 比例={self.scale_factor:.2f}, "
            f"窗口大小=({w}x{h}), 原图=({self.pixmap.width()}x{self.pixmap.height()})"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.RightButton:
            self.close()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(event.globalPosition().toPoint() - self.drag_pos)

    def mouseReleaseEvent(self, event):
        self.dragging = False

    def mouseDoubleClickEvent(self, event):
        local_pos = event.position().toPoint()
        x, y = local_pos.x(), local_pos.y()

        # 映射到原图
        ix = int(x * self.image.width() / self.width())
        iy = int(y * self.image.height() / self.height())

        if 0 <= ix < self.image.width() and 0 <= iy < self.image.height():
            color = self.image.pixelColor(ix, iy)
            pixel_info = f"RGB=({color.red()},{color.green()},{color.blue()})"
        else:
            pixel_info = "超出图片范围"

        if self.hwnd_steam:
            steam_l, steam_t, steam_r, steam_b = get_window_rect(self.hwnd_steam)
            my_l, my_t, my_r, my_b = get_window_rect(int(self.winId()))

            # 计算相对 Steam 右上角的偏移
            rel_x = my_l - steam_r
            rel_y = my_t - steam_t
            rel_info = f"相对Steam右上角偏移=({rel_x},{rel_y})"
        else:
            rel_info = "Steam窗口未找到"

        print(f"鼠标在图片窗口: ({x},{y}), {pixel_info}, {rel_info}")


# ==== 主函数 ====
def main():
    hwnd_steam = find_window_by_title_exact("Steam")
    if not hwnd_steam:
        print("[!] 未找到标题为 'Steam' 的窗口，请先运行 Steam。")
    else:
        print(f"[+] 找到 Steam 窗口句柄: 0x{hwnd_steam:08X}")

    app = QApplication(sys.argv)
    win = ImageWindow("bg.png", hwnd_steam)  # 换成你的图片
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

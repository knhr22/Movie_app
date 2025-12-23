import sys
import os
import vlc
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QFileDialog, QLabel, QSlider, QFrame, QSpinBox, QGridLayout
)
from PySide6.QtCore import Qt, QTimer, Signal, QPoint

class VideoContainer(QFrame):
    fileDropped = Signal(str)
    dragged = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Box)
        self.setStyleSheet("background-color: black; border: 1px solid #444;")
        self.last_pos = QPoint()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()
        else: event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith(('.mp4', '.mkv', '.mov', '.ts', '.avi', '.wmv')):
                self.fileDropped.emit(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            curr_pos = event.position().toPoint()
            diff = curr_pos - self.last_pos
            self.dragged.emit(diff.x(), diff.y())
            self.last_pos = curr_pos

class VideoComparePlayer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("2動画同期比較プレイヤー")
        self.resize(1300, 850) # 全体的に少し小さく
        
        self.setStyleSheet("""
            QWidget { background-color: #1e1e1e; color: #ddd; }
            QPushButton { background-color: #333; border: 1px solid #555; padding: 2px; min-height: 24px; font-size: 11px; }
            QPushButton:hover { background-color: #444; }
            .GreenBtn { background-color: #2b5d2e; font-weight: bold; color: white; border: 1px solid #1e3f20; font-size: 14px; }
            .NavBtn { min-width: 22px; min-height: 22px; max-width: 22px; max-height: 22px; font-size: 9px; padding: 0px; }
            QLabel { font-size: 10px; }
            QSpinBox { 
                background-color: #2a2a2a; color: white; border: 1px solid #444; 
                height: 24px; font-size: 11px;
            }
            QSpinBox::up-button, QSpinBox::down-button { width: 0px; border: none; }
        """)

        self.instance = vlc.Instance("--avcodec-hw=none", "--no-osd", "--no-video-title-show")
        self.player1 = self.instance.media_player_new()
        self.player2 = self.instance.media_player_new()
        
        self.jump_point1 = 0
        self.offset_x = 0
        self.offset_y = 0
        
        self.init_ui()
        
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # --- 1. 最上部 ---
        top_layout = QHBoxLayout()
        
        # 左ファイル
        l_file = QVBoxLayout()
        self.btn_open1 = QPushButton("ファイル選択")
        self.btn_open1.setFixedWidth(80)
        self.btn_open1.clicked.connect(lambda: self.open_file_dialog(1))
        self.lbl_name1 = QLabel("未選択")
        l_file.addWidget(self.btn_open1); l_file.addWidget(self.lbl_name1)
        top_layout.addLayout(l_file, 1)

        # 中央：ナビ
        center_nav = QHBoxLayout()
        center_nav.setSpacing(5)
        
        zoom_ui = QVBoxLayout()
        lbl_z = QLabel("ズーム")
        lbl_z.setAlignment(Qt.AlignCenter)
        zoom_ui.addWidget(lbl_z)
        self.spin_zoom = QSpinBox()
        self.spin_zoom.setRange(100, 800); self.spin_zoom.setValue(100)
        self.spin_zoom.setSuffix("%"); self.spin_zoom.setAlignment(Qt.AlignCenter)
        self.spin_zoom.setFixedWidth(60); self.spin_zoom.setStyleSheet("background-color: #2b5d2e;")
        self.spin_zoom.valueChanged.connect(self.apply_physical_zoom)
        zoom_ui.addWidget(self.spin_zoom)
        center_nav.addLayout(zoom_ui)

        nav_grid = QGridLayout(); nav_grid.setSpacing(1)
        move_step = 100 
        
        self.btn_up = QPushButton("↑"); self.btn_down = QPushButton("↓")
        self.btn_left = QPushButton("←"); self.btn_right = QPushButton("→")
        self.btn_reset = QPushButton("R")

        for btn in [self.btn_up, self.btn_down, self.btn_left, self.btn_right, self.btn_reset]:
            btn.setProperty("class", "NavBtn")
        
        for btn in [self.btn_up, self.btn_down, self.btn_left, self.btn_right]:
            btn.setAutoRepeat(True); btn.setAutoRepeatDelay(200); btn.setAutoRepeatInterval(50)
        
        self.btn_up.clicked.connect(lambda: self.apply_sync_pan(0, move_step))
        self.btn_down.clicked.connect(lambda: self.apply_sync_pan(0, -move_step))
        self.btn_left.clicked.connect(lambda: self.apply_sync_pan(move_step, 0))
        self.btn_right.clicked.connect(lambda: self.apply_sync_pan(-move_step, 0))
        self.btn_reset.clicked.connect(self.reset_view)
        
        nav_grid.addWidget(self.btn_up, 0, 1)
        nav_grid.addWidget(self.btn_left, 1, 0)
        nav_grid.addWidget(self.btn_reset, 1, 1)
        nav_grid.addWidget(self.btn_right, 1, 2)
        nav_grid.addWidget(self.btn_down, 2, 1)
        center_nav.addLayout(nav_grid)
        top_layout.addLayout(center_nav)

        # 右ファイル
        r_file = QVBoxLayout()
        self.btn_open2 = QPushButton("ファイル選択")
        self.btn_open2.setFixedWidth(80)
        self.btn_open2.clicked.connect(lambda: self.open_file_dialog(2))
        self.lbl_name2 = QLabel("未選択")
        r_file.addWidget(self.btn_open2); r_file.addWidget(self.lbl_name2)
        top_layout.addLayout(r_file, 1)
        main_layout.addLayout(top_layout)

        # --- 2. 動画エリア ---
        video_layout = QHBoxLayout()
        self.container1 = VideoContainer(); self.container2 = VideoContainer()
        self.video_widget1 = QWidget(self.container1); self.video_widget2 = QWidget(self.container2)

        self.video_widget1.mousePressEvent = lambda e: self.container1.mousePressEvent(e)
        self.video_widget1.mouseMoveEvent = lambda e: self.container1.mouseMoveEvent(e)
        self.video_widget2.mousePressEvent = lambda e: self.container2.mousePressEvent(e)
        self.video_widget2.mouseMoveEvent = lambda e: self.container2.mouseMoveEvent(e)
        
        self.container1.fileDropped.connect(lambda p: self.load_video(1, p))
        self.container2.fileDropped.connect(lambda p: self.load_video(2, p))
        self.container1.dragged.connect(self.apply_sync_pan)
        self.container2.dragged.connect(self.apply_sync_pan)
        
        video_layout.addWidget(self.container1, 1); video_layout.addWidget(self.container2, 1)
        main_layout.addLayout(video_layout, 1)

        # --- 3. 下部操作パネル ---
        bottom_grid = QGridLayout()
        bottom_grid.setSpacing(5)

        self.btn_l_play = QPushButton("▶ / Ⅱ"); self.btn_l_play.clicked.connect(self.player1.pause)
        bottom_grid.addWidget(self.btn_l_play, 0, 0)
        
        bottom_grid.addWidget(QLabel(""), 0, 1) # 余白

        # 統合一括ボタン (▶ / Ⅱ)
        self.btn_sync_toggle = QPushButton("▶ / Ⅱ")
        self.btn_sync_toggle.setProperty("class", "GreenBtn")
        self.btn_sync_toggle.setFixedWidth(100)
        self.btn_sync_toggle.clicked.connect(self.toggle_sync_play)
        bottom_grid.addWidget(self.btn_sync_toggle, 0, 2)

        bottom_grid.addWidget(QLabel(""), 0, 3) # 余白

        self.btn_r_play = QPushButton("▶ / Ⅱ"); self.btn_r_play.clicked.connect(self.player2.pause)
        bottom_grid.addWidget(self.btn_r_play, 0, 4)

        # シークバー
        l_seek = QVBoxLayout(); self.slider1 = QSlider(Qt.Horizontal); self.slider1.setRange(0, 1000)
        self.slider1.sliderMoved.connect(lambda p: self.player1.set_position(p/1000.0))
        self.lbl_time1 = QLabel("00:00 / 00:00"); self.lbl_time1.setAlignment(Qt.AlignCenter)
        l_seek.addWidget(self.slider1); l_seek.addWidget(self.lbl_time1); bottom_grid.addLayout(l_seek, 1, 0, 1, 2)

        r_seek = QVBoxLayout(); self.slider2 = QSlider(Qt.Horizontal); self.slider2.setRange(0, 1000)
        self.slider2.sliderMoved.connect(lambda p: self.player2.set_position(p/1000.0))
        self.lbl_time2 = QLabel("00:00 / 00:00"); self.lbl_time2.setAlignment(Qt.AlignCenter)
        r_seek.addWidget(self.slider2); r_seek.addWidget(self.lbl_time2); bottom_grid.addLayout(r_seek, 1, 3, 1, 2)

        # 秒数ジャンプ
        l_jump = QHBoxLayout()
        self.spin_jump = QSpinBox(); self.spin_jump.setRange(0, 99999); self.spin_jump.setFixedWidth(60)
        l_jump.addWidget(QLabel("秒数:")); l_jump.addWidget(self.spin_jump)
        self.lbl_elapsed = QLabel("経過: 0.0s"); l_jump.addWidget(self.lbl_elapsed)
        btn_jump = QPushButton("飛ぶ"); btn_jump.clicked.connect(self.jump_to_seconds)
        l_jump.addWidget(btn_jump); l_jump.addStretch()
        bottom_grid.addLayout(l_jump, 2, 0, 1, 2)

        main_layout.addLayout(bottom_grid)

    def toggle_sync_play(self):
        if self.player1.is_playing() or self.player2.is_playing():
            self.player1.set_pause(1); self.player2.set_pause(1)
        else:
            self.player1.play(); self.player2.play()

    def reset_view(self):
        self.spin_zoom.setValue(100); self.offset_x, self.offset_y = 0, 0
        self.apply_physical_zoom()

    def apply_physical_zoom(self):
        scale = self.spin_zoom.value() / 100.0
        cw, ch = self.container1.width(), self.container1.height()
        self.video_widget1.resize(int(cw * scale), int(ch * scale))
        self.video_widget2.resize(int(cw * scale), int(ch * scale))
        self.update_widget_positions()

    def apply_sync_pan(self, dx, dy):
        if self.spin_zoom.value() <= 100: return
        self.offset_x += dx; self.offset_y += dy
        self.update_widget_positions()

    def update_widget_positions(self):
        scale = self.spin_zoom.value() / 100.0
        cw, ch = self.container1.width(), self.container1.height()
        limit_x = int(cw * (scale - 1)); limit_y = int(ch * (scale - 1))
        self.offset_x = max(-limit_x, min(0, self.offset_x))
        self.offset_y = max(-limit_y, min(0, self.offset_y))
        self.video_widget1.move(self.offset_x, self.offset_y)
        self.video_widget2.move(self.offset_x, self.offset_y)

    def load_video(self, num, path):
        media = self.instance.media_new(path)
        player = self.player1 if num == 1 else self.player2
        widget = self.video_widget1 if num == 1 else self.video_widget2
        lbl = self.lbl_name1 if num == 1 else self.lbl_name2
        player.set_media(media); player.set_hwnd(int(widget.winId()))
        lbl.setText(os.path.basename(path))
        player.play()
        QTimer.singleShot(400, lambda: [player.set_pause(1), self.apply_physical_zoom()])

    def jump_to_seconds(self):
        self.jump_point1 = self.spin_jump.value() * 1000
        self.player1.set_time(self.jump_point1)
        QTimer.singleShot(100, lambda: self.player1.set_pause(1))

    def update_ui(self):
        for p, s, l in [(self.player1, self.slider1, self.lbl_time1), (self.player2, self.slider2, self.lbl_time2)]:
            ms = p.get_time(); length = p.get_length()
            if ms >= 0 and length > 0:
                s.setValue(int(ms / length * 1000))
                l.setText(f"{ms//1000//60:02d}:{ms//1000%60:02d} / {length//1000//60:02d}:{length//1000%60:02d}")
                if p == self.player1:
                    self.lbl_elapsed.setText(f"経過: {(ms - self.jump_point1)/1000:.1f}s")

    def resizeEvent(self, event):
        self.apply_physical_zoom()
        super().resizeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = VideoComparePlayer()
    player.show()
    sys.exit(app.exec())
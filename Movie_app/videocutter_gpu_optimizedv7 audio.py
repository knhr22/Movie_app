import sys
import subprocess
import vlc
import os
import unicodedata

# matplotlibにPySide6を使うよう指定
os.environ['QT_API'] = 'pyside6'

import numpy as np
import matplotlib
matplotlib.use('QtAgg')
# 日本語フォント設定
matplotlib.rcParams['font.family'] = 'sans-serif'
matplotlib.rcParams['font.sans-serif'] = ['メイリオ', 'Meiryo', 'Yu Gothic', 'MS Gothic']
matplotlib.rcParams['axes.unicode_minus'] = False

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker  # ★追加: 目盛り調整用
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
import librosa
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog,
    QLabel, QListWidget, QMessageBox, QSlider, QFrame, QHBoxLayout,
    QLineEdit, QProgressDialog, QDialog, QFormLayout, QDialogButtonBox,
    QDoubleSpinBox, QCompleter, QCheckBox,
)
from PySide6.QtCore import Qt, QTimer, QSettings, QStringListModel, QThread, Signal


class WaveformLoader(QThread):
    """波形を別スレッドで読み込むクラス"""
    finished = Signal(object, float)
    error = Signal(str)
    
    def __init__(self, audio_path):
        super().__init__()
        self.audio_path = audio_path
    
    def run(self):
        try:
            print(f"波形読み込み開始: {self.audio_path}")
            import tempfile
            import soundfile as sf
            
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp_path = tmp.name
            
            print("FFmpegで音声抽出中...")
            result = subprocess.run(
                ["ffmpeg", "-i", self.audio_path, "-ar", "11025", "-ac", "1", 
                 "-y", tmp_path],
                capture_output=True,
                creationflags=0x08000000
            )
            
            if result.returncode != 0:
                raise Exception("FFmpegでの音声抽出に失敗")
            
            print("wavファイル読み込み中...")
            y, sr = sf.read(tmp_path)
            
            try:
                os.unlink(tmp_path)
            except:
                pass
            
            duration = len(y) / sr
            
            # 表示用にダウンサンプリング
            max_points = 10000
            step = 1
            if len(y) > max_points:
                step = len(y) // max_points
                y = y[::step]
            
            print(f"波形読み込み完了: {duration:.2f}秒, {len(y)}点")
            self.finished.emit((y, sr, step), duration)
        except Exception as e:
            print(f"波形読み込みエラー: {e}")
            self.error.emit(str(e))


class WaveformWidget(FigureCanvasQTAgg):
    load_started = Signal()
    load_finished = Signal()
    seek_requested = Signal(float)

    def __init__(self, parent=None, width=8, height=1.5, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi, facecolor='#2b2b2b')
        self.axes = self.fig.add_subplot(111)
        self.axes.set_facecolor('#1e1e1e')
        super().__init__(self.fig)
        self.setParent(parent)
        
        self.current_time = 0
        self.duration = 0
        self.zoom_span = 0
        
        self.position_line = None
        self.cut_lines = []
        self.loader_thread = None
        
        self.mpl_connect('button_press_event', self._on_click)
        self.show_loading_placeholder()
        
    def show_loading_placeholder(self):
        self.axes.clear()
        self.axes.set_facecolor('#1e1e1e')
        self.axes.set_xticks([])
        self.axes.set_yticks([])
        for spine in self.axes.spines.values():
            spine.set_visible(False)
        self.draw()
    
    def _on_click(self, event):
        if event.button == 1 and event.inaxes == self.axes:
            if event.xdata is not None:
                self.seek_requested.emit(event.xdata)

    def plot_waveform(self, audio_path):
        self.load_started.emit()
        if self.loader_thread and self.loader_thread.isRunning():
            self.loader_thread.quit()
            self.loader_thread.wait()
        
        self.loader_thread = WaveformLoader(audio_path)
        self.loader_thread.finished.connect(self._on_waveform_loaded)
        self.loader_thread.error.connect(self._on_load_error)
        self.loader_thread.start()
    
    def _on_waveform_loaded(self, data, duration):
        try:
            y, sr, step = data
            self.duration = duration
            self.zoom_span = duration
            
            times = np.linspace(0, duration, len(y))
            
            self.axes.clear()
            self.position_line = None # クリアしたので参照もリセット
            
            self.axes.set_facecolor('#1e1e1e')
            self.axes.plot(times, y, linewidth=0.3, color='#4CAF50', alpha=0.8)
            self.axes.set_xlabel('Time (s)', color='white')
            self.axes.set_ylabel('', color='white') 
            self.axes.set_xlim(0, duration)
            self.axes.tick_params(axis='x', colors='white')
            self.axes.tick_params(axis='y', colors='white', left=False, labelleft=False)
            
            self.axes.spines['bottom'].set_color('white')
            self.axes.spines['left'].set_visible(False)
            self.axes.spines['top'].set_visible(False)
            self.axes.spines['right'].set_visible(False)
            
            # 初期バーを描画
            self.position_line = self.axes.axvline(x=0, color='red', linewidth=2, alpha=0.8)
            
            self.fig.tight_layout()
            self.draw()
        except Exception as e:
            print(f"描画エラー: {e}")
        finally:
            self.load_finished.emit()
    
    def _on_load_error(self, error_msg):
        self.axes.clear()
        self.axes.text(0.5, 0.5, f'エラー: {error_msg}', color='red', ha='center')
        self.draw()
        self.load_finished.emit()
    
    def wheelEvent(self, event):
        if self.duration <= 0: return
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom_span *= 0.8
        else:
            self.zoom_span *= 1.2
        self.zoom_span = max(1.0, min(self.zoom_span, self.duration))
        self.update_view()

    def update_view(self):
        if self.duration <= 0: return
        
        half = self.zoom_span / 2
        start = self.current_time - half
        end = self.current_time + half
        
        if start < 0:
            start = 0
            end = self.zoom_span
        if end > self.duration:
            end = self.duration
            start = self.duration - self.zoom_span
            if start < 0: start = 0
            
        self.axes.set_xlim(start, end)
        
        # ★ズーム時に目盛りを細かく表示する設定
        self.axes.xaxis.set_major_locator(ticker.MaxNLocator(nbins=20))
        self.axes.xaxis.set_minor_locator(ticker.AutoMinorLocator())
        
        self.draw_idle()

    def update_position(self, time_sec):
        self.current_time = time_sec
        
        # ★確実な描画更新: 既存の線を消して新しく引く
        if self.position_line:
            try:
                self.position_line.remove()
            except:
                pass # 既に消えている場合は無視
        
        self.position_line = self.axes.axvline(x=time_sec, color='red', linewidth=2, alpha=0.8)
        
        if self.zoom_span < self.duration:
            self.update_view() # ズーム中は範囲更新も兼ねる
        else:
            self.draw_idle()   # 全体表示中は再描画のみ
    
    def update_cut_markers(self, cuts):
        for line in self.cut_lines:
            line.remove()
        self.cut_lines.clear()
        for start, end, name in cuts:
            if end is not None:
                l1 = self.axes.axvline(x=start, color='yellow', linewidth=1.5, linestyle='--', alpha=0.6)
                l2 = self.axes.axvline(x=end, color='orange', linewidth=1.5, linestyle='--', alpha=0.6)
                self.cut_lines.extend([l1, l2])
        self.draw()


class CutEditDialog(QDialog):
    def __init__(self, start, end, name, music_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("カット編集")
        self.music_data = music_data
        layout = QFormLayout(self)
        self.start_input = QDoubleSpinBox()
        self.start_input.setRange(0, 999999); self.start_input.setDecimals(2); self.start_input.setValue(start)
        layout.addRow("開始秒:", self.start_input)
        self.end_input = QDoubleSpinBox()
        self.end_input.setRange(0, 999999); self.end_input.setDecimals(2); self.end_input.setValue(end if end is not None else start)
        layout.addRow("終了秒:", self.end_input)
        self.name_input = QLineEdit(name)
        self.completer = QCompleter(self); self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        all_names = [d[0] for d in self.music_data]
        self.model = QStringListModel(all_names, self.completer); self.completer.setModel(self.model)
        self.name_input.setCompleter(self.completer); self.name_input.textEdited.connect(self.update_candidates)
        layout.addRow("カット名:", self.name_input)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept); self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def update_candidates(self, text):
        filtered = [d[0] for d in self.music_data if d[0].lower().startswith(text.lower()) or d[1].lower().startswith(text.lower())] if text else [d[0] for d in self.music_data]
        self.model.setStringList(filtered); self.completer.setCompletionPrefix(""); 
        if filtered: self.completer.complete()

    def getValues(self): return (self.start_input.value(), self.end_input.value(), self.name_input.text().strip())

class VenueInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("確認: 公演場所が未入力"); layout = QVBoxLayout(self)
        layout.addWidget(QLabel("公演場所が入力されていません。\n入力しますか?(空欄のままでも出力可能です)"))
        self.input = QLineEdit(); self.input.setPlaceholderText("公演場所を入力..."); layout.addWidget(self.input)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
    def get_venue(self): return self.input.text().strip()

class VideoCutter(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("複数動画一括カッター (GPU Optimized + 波形表示)")
        self.setAcceptDrops(True); self.video_projects = []; self.current_idx = -1; self.music_data = []
        self.settings = QSettings("VideoCutterApp", "Config"); self.load_music_list(); self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        left_panel = QVBoxLayout()
        left_panel.addWidget(QLabel("動画リスト (Drag & Drop可)"))
        self.file_list_widget = QListWidget()
        self.file_list_widget.setStyleSheet("QListWidget::item:selected { background-color: #0078d7; color: white; border: 1px solid #005a9e; } QListWidget::item:hover { background-color: #3e3e42; }")
        self.file_list_widget.currentRowChanged.connect(self.switch_video)
        left_panel.addWidget(self.file_list_widget)
        btn_add = QPushButton("動画を追加"); btn_add.clicked.connect(self.open_file); left_panel.addWidget(btn_add)
        btn_rem = QPushButton("選択動画を削除"); btn_rem.clicked.connect(self.remove_video_from_list); left_panel.addWidget(btn_rem)
        main_layout.addLayout(left_panel, 1)

        right_panel = QVBoxLayout()
        save_layout = QHBoxLayout()
        self.save_path_input = QLineEdit(str(self.settings.value("last_save_path", os.getcwd())))
        save_layout.addWidget(QLabel("保存場所:")); save_layout.addWidget(self.save_path_input)
        btn_browse = QPushButton("参照..."); btn_browse.setFixedWidth(80); btn_browse.clicked.connect(self.browse_save_path)
        save_layout.addWidget(btn_browse); right_panel.addLayout(save_layout)

        top_line = QHBoxLayout()
        self.date_input = QLineEdit(); self.date_input.setPlaceholderText("日付"); self.date_input.setFixedWidth(100); self.date_input.textChanged.connect(self.update_project_date); top_line.addWidget(self.date_input)
        self.live_input = QLineEdit(str(self.settings.value("last_live_name", ""))); self.live_input.setPlaceholderText("ライブ名"); self.live_input.setFixedWidth(150); self.live_input.textChanged.connect(self.save_live_settings); top_line.addWidget(self.live_input)
        self.venue_input = QLineEdit(); self.venue_input.setPlaceholderText("公演場所"); self.venue_input.setFixedWidth(100); top_line.addWidget(self.venue_input)
        self.file_label = QLabel("動画: 未選択"); self.file_label.setStyleSheet("background: #333; color: white; border: 1px solid #555; padding: 2px;"); top_line.addWidget(self.file_label, 1)
        right_panel.addLayout(top_line)

        self.video_frame = QFrame(); self.video_frame.setFrameShape(QFrame.Box); self.video_frame.setFixedHeight(300); right_panel.addWidget(self.video_frame)
        self.waveform_widget = WaveformWidget(self, width=8, height=1.5, dpi=100)
        self.waveform_widget.load_started.connect(self.show_waveform_loading)
        self.waveform_widget.load_finished.connect(self.hide_waveform_loading)
        self.waveform_widget.seek_requested.connect(self.seek_from_waveform)
        right_panel.addWidget(self.waveform_widget)

        self.cut_list = QListWidget(); self.cut_list.itemDoubleClicked.connect(self.rename_cut_point); right_panel.addWidget(self.cut_list)
        cut_ctrl = QHBoxLayout()
        for t, f in [("カット開始", self.mark_start), ("カット終了", self.mark_end), ("カット削除", self.delete_cut_point)]:
            btn = QPushButton(t); btn.setFixedHeight(35); btn.clicked.connect(f); cut_ctrl.addWidget(btn)
        self.jump_input = QLineEdit(); self.jump_input.setFixedWidth(50); self.jump_input.setFixedHeight(35); cut_ctrl.addWidget(self.jump_input)
        btn_jmp = QPushButton("指定秒へ移動"); btn_jmp.setFixedHeight(35); btn_jmp.clicked.connect(self.jump_to_time); cut_ctrl.addWidget(btn_jmp)
        right_panel.addLayout(cut_ctrl)

        # VLC設定: ハードウェアデコードを無効にしてクラッシュ回避
        self.instance = vlc.Instance("--avcodec-hw=none")
        self.mediaplayer = self.instance.media_player_new()

        seek_box = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal); self.slider.setRange(0, 1000); self.slider.sliderMoved.connect(self.set_position)
        seek_box.addWidget(self.slider)
        self.time_label = QLabel("0.00s / 0.00s"); seek_box.addWidget(self.time_label)
        right_panel.addLayout(seek_box)

        all_btn_row = QHBoxLayout()
        for l, s, c in [("◀3s", -3, "#757575"), ("3s▶", 3, "#6E98BB"), ("◀10s", -10, "#757575"), ("10s▶", 10, "#6E98BB")]:
            btn = QPushButton(l); btn.setFixedHeight(35); btn.clicked.connect(lambda _, x=s: self.jump_time(x))
            btn.setStyleSheet(f"background-color: {c}; color: white; font-weight: bold;"); all_btn_row.addWidget(btn)
        btn_play = QPushButton("▶"); btn_play.setFixedSize(50, 35); btn_play.clicked.connect(self.play_video); btn_play.setStyleSheet("background-color: #4CAF50; color: white;"); all_btn_row.addWidget(btn_play)
        btn_pause = QPushButton("⏸"); btn_pause.setFixedSize(50, 35); btn_pause.clicked.connect(self.pause_video); btn_pause.setStyleSheet("background-color: #0078d7; color: white;"); all_btn_row.addWidget(btn_pause)
        for l, s, c in [("◀30s", -30, "#757575"), ("30s▶", 30, "#6E98BB"), ("1m▶", 60, "#6E98BB"), ("3m▶", 180, "#6E98BB")]:
            btn = QPushButton(l); btn.setFixedHeight(35); btn.clicked.connect(lambda _, x=s: self.jump_time(x))
            btn.setStyleSheet(f"background-color: {c}; color: white; font-weight: bold;"); all_btn_row.addWidget(btn)
        right_panel.addLayout(all_btn_row)

        out_box = QHBoxLayout()
        self.btn_run = QPushButton("一括出力 (4K保存)"); self.btn_hd = QPushButton("HD用出力 (720p)"); self.btn_mp3 = QPushButton("MP3抽出 (音声のみ)")
        for b, f in [(self.btn_run, self.run_ffmpeg_4k), (self.btn_hd, self.run_ffmpeg_hd), (self.btn_mp3, self.run_ffmpeg_mp3)]:
            b.setFixedHeight(40); b.setEnabled(False); b.clicked.connect(f); out_box.addWidget(b)
        right_panel.addLayout(out_box)

        all_export_layout = QHBoxLayout()
        self.btn_all = QPushButton("全部出力 (4K→HD→MP3)"); self.btn_all.setFixedHeight(50); self.btn_all.setEnabled(False); self.btn_all.setStyleSheet("background-color: #008CBA; color: white; font-weight: bold;")
        self.btn_all.clicked.connect(self.run_export_all_projects); all_export_layout.addWidget(self.btn_all, 3)
        self.chk_text_4k = QCheckBox("冒頭テキスト挿入(4K)"); self.chk_text_hd = QCheckBox("冒頭テキスト挿入(HD)")
        self.chk_text_4k.setChecked(self.settings.value("insert_text_4k", "true") == "true"); self.chk_text_hd.setChecked(self.settings.value("insert_text_hd", "false") == "true")
        self.chk_text_4k.stateChanged.connect(self.save_text_settings); self.chk_text_hd.stateChanged.connect(self.save_text_settings)
        all_export_layout.addWidget(self.chk_text_4k); all_export_layout.addWidget(self.chk_text_hd); right_panel.addLayout(all_export_layout)
        main_layout.addLayout(right_panel, 3); self.setLayout(main_layout)

        self.timer = QTimer(self); self.timer.setInterval(50); self.timer.timeout.connect(self.update_ui)
        self.check_prefix_inputs()

    def show_waveform_loading(self):
        self.wave_progress = QProgressDialog("波形データを読み込んでいます...", None, 0, 0, self); self.wave_progress.setWindowTitle("読み込み中")
        self.wave_progress.setWindowModality(Qt.ApplicationModal); self.wave_progress.setCancelButton(None); self.wave_progress.show()
    def hide_waveform_loading(self):
        if hasattr(self, 'wave_progress'): self.wave_progress.close()
    def save_text_settings(self):
        self.settings.setValue("insert_text_4k", "true" if self.chk_text_4k.isChecked() else "false"); self.settings.setValue("insert_text_hd", "true" if self.chk_text_hd.isChecked() else "false")
    def save_live_settings(self, text): self.settings.setValue("last_live_name", text); self.check_prefix_inputs()
    def get_text_width_units(self, text): return sum(2 if unicodedata.east_asian_width(char) in "FWA" else 1 for char in text)
    def split_by_width(self, text, limit):
        cur, cur_w = "", 0
        for c in text:
            w = 2 if unicodedata.east_asian_width(c) in "FWA" else 1
            if cur_w + w > limit: return cur, text[len(cur):]
            cur += c; cur_w += w
        return text, None
    def get_font_size(self, text_list, mode="4k"):
        max_len = max(self.get_text_width_units(line) for line in text_list)
        if mode == "4k": return max(int(110 * (30 / max_len)), 40) if max_len > 30 else 110
        else: return max(int(38 * (30 / max_len)), 18) if max_len > 30 else 38
    def _safe_ffmpeg_txt(self, text):
        if not text: return ""
        text = unicodedata.normalize("NFC", text)
        for k, v in {"\\": "/", ":": "\\:", ",": "\\,", "，": "\\,", "、": "\\,", "\"": "", "'": "", "\n": " ", "\r": " "}.items(): text = text.replace(k, v)
        return text
    def jump_time(self, s):
        target = self.mediaplayer.get_time() + (s * 1000); length = self.mediaplayer.get_length()
        target = max(0, min(target, length)); self.mediaplayer.set_time(target)
        self.waveform_widget.update_position(target / 1000.0); self.slider.setValue(target); self.time_label.setText(f"{target/1000.0:.2f}s / {length/1000.0:.2f}s")
    def jump_to_time(self):
        try:
            target = int(float(self.jump_input.text()) * 1000); length = self.mediaplayer.get_length()
            target = max(0, min(target, length)); self.mediaplayer.set_time(target)
            self.waveform_widget.update_position(target / 1000.0); self.slider.setValue(target); self.time_label.setText(f"{target/1000.0:.2f}s / {length/1000.0:.2f}s")
        except: pass
    def seek_from_waveform(self, time_sec):
        target_ms = int(time_sec * 1000); length = self.mediaplayer.get_length()
        target_ms = max(0, min(target_ms, length)); self.mediaplayer.set_time(target_ms)
        self.waveform_widget.update_position(time_sec); self.slider.setValue(target_ms); self.time_label.setText(f"{time_sec:.2f}s / {length/1000.0:.2f}s")
    def set_position(self, p):
        self.mediaplayer.set_position(max(0.0, min(1.0, p / 1000.0)))
        length = self.mediaplayer.get_length()
        if length > 0:
            time_sec = (length * p / 1000.0) / 1000.0
            self.waveform_widget.update_position(time_sec); self.time_label.setText(f"{time_sec:.2f}s / {length/1000.0:.2f}s")
    def add_video_to_project(self, p):
        fn = os.path.basename(p); date_str = fn[:8] if len(fn) >= 8 and fn[:8].isdigit() else ""
        project = {"path": p, "cuts": [], "date": date_str, "filename": fn, "original_index": len(self.video_projects) + 1}
        self.video_projects.append(project); self.file_list_widget.addItem(fn)
        if self.file_list_widget.count() == 1: self.file_list_widget.setCurrentRow(0)
    def switch_video(self, idx):
        if idx < 0 or idx >= len(self.video_projects): return
        self.current_idx = idx; project = self.video_projects[idx]
        self.file_label.setText(project["path"]); self.date_input.setText(project["date"])
        self.mediaplayer.set_media(self.instance.media_new(project["path"])); self.mediaplayer.set_hwnd(int(self.video_frame.winId()))
        self.mediaplayer.play(); QTimer.singleShot(50, lambda: self.mediaplayer.set_pause(1))
        self.waveform_widget.plot_waveform(project["path"])
        self.update_cut_list_display(); self.waveform_widget.update_cut_markers(project["cuts"]); self.check_prefix_inputs()
    def remove_video_from_list(self):
        idx = self.file_list_widget.currentRow()
        if idx >= 0:
            self.video_projects.pop(idx); self.file_list_widget.takeItem(idx)
            if not self.video_projects: self.mediaplayer.stop(); self.cut_list.clear(); self.file_label.setText("動画: 未選択")
    def update_project_date(self, text):
        if self.current_idx >= 0: self.video_projects[self.current_idx]["date"] = text; self.check_prefix_inputs()
    def load_music_list(self):
        self.music_data = []
        if os.path.exists("music_list.txt"):
            with open("music_list.txt", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    p = line.strip().split("|"); 
                    if p: self.music_data.append((p[0], p[1] if len(p) > 1 else p[0]))
    def open_file(self):
        ps, _ = QFileDialog.getOpenFileNames(self, "動画選択", "", "動画 (*.mp4 *.mkv *.mov *.ts)")
        for p in ps: self.add_video_to_project(p)
    def browse_save_path(self):
        p = QFileDialog.getExistingDirectory(self, "フォルダ選択", self.save_path_input.text())
        if p: self.save_path_input.setText(p); self.settings.setValue("last_save_path", p)
    def check_prefix_inputs(self):
        ready = bool(self.date_input.text().strip() and self.live_input.text().strip() and self.current_idx >= 0)
        for b in [self.btn_run, self.btn_hd, self.btn_mp3, self.btn_all]: b.setEnabled(ready)
    def play_video(self):
        if self.current_idx >= 0: self.mediaplayer.set_hwnd(int(self.video_frame.winId())); self.mediaplayer.play(); self.timer.start()
    def pause_video(self): self.mediaplayer.pause()
    def update_ui(self):
        t, L = self.mediaplayer.get_time(), self.mediaplayer.get_length()
        if L > 0:
            self.slider.setValue(int((t / L) * 1000)); self.time_label.setText(f"{t/1000.0:.2f}s / {L/1000.0:.2f}s")
            self.waveform_widget.update_position(t / 1000.0)
    def update_cut_list_display(self):
        self.cut_list.clear()
        if self.current_idx >= 0: self.cut_list.addItems([f"{s:.2f}s - {e:.2f}s : {n}" for s, e, n in self.video_projects[self.current_idx]["cuts"]])
    def mark_start(self):
        if self.current_idx < 0: return
        t = self.mediaplayer.get_time() / 1000.0; project = self.video_projects[self.current_idx]
        n = f"cut_{project['original_index']}_{len(project['cuts']) + 1}"
        project["cuts"].append((t, None, n)); self.cut_list.addItem(f"{t:.2f}s - ... : {n}"); self.waveform_widget.update_cut_markers(project["cuts"])
    def mark_end(self):
        if self.current_idx < 0: return
        self.pause_video(); project = self.video_projects[self.current_idx]
        if project["cuts"] and project["cuts"][-1][1] is None:
            t = self.mediaplayer.get_time() / 1000.0; s, _, n = project["cuts"][-1]
            dialog = CutEditDialog(s, t if t > s else s + 1.0, n, self.music_data, self)
            if dialog.exec() == QDialog.Accepted:
                project["cuts"][-1] = dialog.getValues()
                self.cut_list.item(self.cut_list.count() - 1).setText(f"{project['cuts'][-1][0]:.2f}s - {project['cuts'][-1][1]:.2f}s : {project['cuts'][-1][2]}")
                self.waveform_widget.update_cut_markers(project["cuts"])
    def rename_cut_point(self, item):
        idx = self.cut_list.row(item); project = self.video_projects[self.current_idx]; s, e, n = project["cuts"][idx]
        dialog = CutEditDialog(s, e, n, self.music_data, self)
        if dialog.exec() == QDialog.Accepted:
            project["cuts"][idx] = dialog.getValues()
            item.setText(f"{project['cuts'][idx][0]:.2f}s - {project['cuts'][idx][1]:.2f}s : {project['cuts'][idx][2]}")
            self.waveform_widget.update_cut_markers(project["cuts"])
    def delete_cut_point(self):
        idx = self.cut_list.currentRow()
        if idx >= 0 and QMessageBox.Yes == QMessageBox.question(self, "確認", "削除?", QMessageBox.Yes | QMessageBox.No):
            self.video_projects[self.current_idx]["cuts"].pop(idx); self.cut_list.takeItem(idx)
            if self.current_idx >= 0: self.waveform_widget.update_cut_markers(self.video_projects[self.current_idx]["cuts"])
    
    def run_ffmpeg_4k(self, silent=False, progress=None, offset=0):
        if not silent and not self.check_venue_before_run(): return False
        all_cuts = [(p, c) for p in self.video_projects for c in p["cuts"]]; 
        if not all_cuts: return True
        own = not progress; 
        if own: progress = QProgressDialog("4K出力...", "中止", 0, len(all_cuts), self); progress.show()
        for idx, (p, cut) in enumerate(all_cuts):
            if progress.wasCanceled(): return False
            progress.setLabelText(f"4K: {p['filename']} - {idx+1}"); progress.setValue(offset + idx); QApplication.processEvents()
            fb = self._get_project_fb(p); folder = os.path.join(self.save_path_input.text(), fb, "4k"); os.makedirs(folder, exist_ok=True)
            serial = len([f for f in os.listdir(folder) if f.endswith(".mp4")]) + 1
            out = os.path.join(folder, f"{fb}_{serial:02d}_{cut[2]}_4K.mp4")
            vf_list = []
            if self.chk_text_4k.isChecked():
                live_txt = self._safe_ffmpeg_txt(self.live_input.text()); date_txt = self._safe_ffmpeg_txt(p["date"]); f_path = "C\\:/Windows/Fonts/meiryo.ttc"
                if self.get_text_width_units(f"{p['date']} {self.live_input.text()} {cut[2]}") > 30:
                    cut1, cut2 = self.split_by_width(cut[2], 20); cut1 = self._safe_ffmpeg_txt(cut1); cut2 = self._safe_ffmpeg_txt(cut2) if cut2 else ""
                    fs = self.get_font_size([p["date"], self.live_input.text(), cut1, cut2], "4k")
                    vf_list.append(f"drawtext=text='{date_txt} {live_txt}':fontfile='{f_path}':fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2-{fs}:box=1:boxcolor=black@0.5:enable='between(t,0,1.5)'")
                    vf_list.append(f"drawtext=text='{cut1}':fontfile='{f_path}':fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5:enable='between(t,0,1.5)'")
                    if cut2: vf_list.append(f"drawtext=text='{cut2}':fontfile='{f_path}':fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2+{fs}:box=1:boxcolor=black@0.5:enable='between(t,0,1.5)'")
                else:
                    txt = self._safe_ffmpeg_txt(f"{p['date']} {self.live_input.text()} {cut[2]}"); fs = self.get_font_size([txt], "4k")
                    vf_list.append(f"drawtext=text='{txt}':fontfile='{f_path}':fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5:enable='between(t,0,1.5)'")
            filter_str = ",".join(vf_list) if vf_list else "null"
            subprocess.run(["ffmpeg", "-y", "-ss", str(cut[0]), "-t", str(cut[1] - cut[0]), "-hwaccel", "cuda", "-i", p["path"], "-vf", filter_str, "-c:v", "hevc_nvenc", "-profile:v", "main10", "-rc", "constqp", "-qp", "15", "-preset", "p5", "-c:a", "aac", "-b:a", "320k", out], creationflags=0)
        if own: progress.setValue(len(all_cuts)); progress.close(); QMessageBox.information(self, "完了", "4K出力完了")
        return True

    def run_ffmpeg_hd(self, silent=False, progress=None, offset=0):
        if not silent and not self.check_venue_before_run(): return False
        all_cuts = [(p, c) for p in self.video_projects for c in p["cuts"]]; 
        if not all_cuts: return True
        own = not progress; 
        if own: progress = QProgressDialog("HD出力...", "中止", 0, len(all_cuts), self); progress.show()
        for idx, (p, cut) in enumerate(all_cuts):
            if progress.wasCanceled(): return False
            progress.setLabelText(f"HD: {p['filename']} - {idx+1}"); progress.setValue(offset + idx); QApplication.processEvents()
            fb = self._get_project_fb(p); folder = os.path.join(self.save_path_input.text(), fb, "hd"); os.makedirs(folder, exist_ok=True)
            serial = len([f for f in os.listdir(folder) if f.endswith(".mp4")]) + 1
            out = os.path.join(folder, f"{fb}_{serial:02d}_{cut[2]}_HD.mp4")
            vf_list = ["scale=-2:720", "format=yuv420p"]
            if self.chk_text_hd.isChecked():
                live_txt = self._safe_ffmpeg_txt(self.live_input.text()); date_txt = self._safe_ffmpeg_txt(p["date"]); f_path = "C\\:/Windows/Fonts/meiryo.ttc"
                if self.get_text_width_units(f"{p['date']} {self.live_input.text()} {cut[2]}") > 45:
                    cut1, cut2 = self.split_by_width(cut[2], 24); cut1 = self._safe_ffmpeg_txt(cut1); cut2 = self._safe_ffmpeg_txt(cut2) if cut2 else ""
                    fs = self.get_font_size([p["date"], self.live_input.text(), cut1, cut2], "hd")
                    vf_list.append(f"drawtext=text='{date_txt} {live_txt}':fontfile='{f_path}':fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2-{int(fs*0.6)}:box=1:boxcolor=black@0.5:enable='between(t,0,1.5)'")
                    vf_list.append(f"drawtext=text='{cut1}':fontfile='{f_path}':fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5:enable='between(t,0,1.5)'")
                    if cut2: vf_list.append(f"drawtext=text='{cut2}':fontfile='{f_path}':fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2+{int(fs*0.6)}:box=1:boxcolor=black@0.5:enable='between(t,0,1.5)'")
                else:
                    txt = self._safe_ffmpeg_txt(f"{p['date']} {self.live_input.text()} {cut[2]}")
                    fs = self.get_font_size([txt], "hd")
                    vf_list.append(f"drawtext=text='{txt}':fontfile='{f_path}':fontsize={fs}:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5:enable='between(t,0,1.5)'")
            filter_str = ",".join(vf_list)
            subprocess.run(["ffmpeg", "-y", "-ss", str(cut[0]), "-t", str(cut[1] - cut[0]), "-hwaccel", "cuda", "-i", p["path"], "-vf", filter_str, "-c:v", "h264_nvenc", "-rc", "constqp", "-qp", "15", "-preset", "p7", "-c:a", "aac", "-b:a", "192k", out], creationflags=0)
        if own: progress.setValue(len(all_cuts)); progress.close(); QMessageBox.information(self, "完了", "HD出力完了")
        return True

    def run_ffmpeg_mp3(self, silent=False, progress=None, offset=0):
        if not silent and not self.check_venue_before_run(): return False
        all_cuts = [(p, c) for p in self.video_projects for c in p["cuts"]]; 
        if not all_cuts: return True
        own = not progress; 
        if own: progress = QProgressDialog("MP3出力...", "中止", 0, len(all_cuts), self); progress.show()
        for idx, (p, cut) in enumerate(all_cuts):
            if progress.wasCanceled(): return False
            progress.setLabelText(f"MP3: {p['filename']} - {idx+1}"); progress.setValue(offset + idx); QApplication.processEvents()
            fb = self._get_project_fb(p); folder = os.path.join(self.save_path_input.text(), fb, "mp3"); os.makedirs(folder, exist_ok=True)
            serial = len([f for f in os.listdir(folder) if f.endswith(".mp3")]) + 1
            out = os.path.join(folder, f"{fb}_{serial:02d}_{cut[2]}.mp3")
            subprocess.run(["ffmpeg", "-y", "-ss", str(cut[0]), "-t", str(cut[1] - cut[0]), "-i", p["path"], "-vn", "-c:a", "libmp3lame", "-b:a", "320k", out], creationflags=0)
        if own: progress.setValue(len(all_cuts)); progress.close(); QMessageBox.information(self, "完了", "MP3完了")
        return True

    def run_export_all_projects(self):
        total = sum(len(p["cuts"]) for p in self.video_projects)
        if total == 0 or not self.check_venue_before_run(): return
        progress = QProgressDialog("全一括出力中...", "中止", 0, total * 3, self); progress.show()
        if self.run_ffmpeg_4k(True, progress, 0):
            if self.run_ffmpeg_hd(True, progress, total):
                if self.run_ffmpeg_mp3(True, progress, total * 2):
                    progress.setValue(total * 3); progress.close(); QMessageBox.information(self, "完了", "すべての動画の出力が完了しました。")
                    return
        progress.close()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if os.path.splitext(p)[1].lower() in [".mp4", ".mkv", ".mov", ".ts"]: self.add_video_to_project(p)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoCutter()
    window.resize(1350, 1000); window.show(); sys.exit(app.exec())
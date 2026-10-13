from __future__ import annotations

import logging
import sys
import time
from dataclasses import fields
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from flowprovip import __version__
from flowprovip.accounts import AccountStore, parse_cookies
from flowprovip.config import Settings
from flowprovip.jobs import Kind, Status, Task, tasks_from_text
from flowprovip.runner import BackgroundLoop, BatchRun, check_account, login_account
from flowprovip.ui.widgets import Bridge, TaskTable

KIND_LABELS = [("Tạo ảnh", Kind.IMAGE), ("Tạo video (text → video)", Kind.VIDEO),
               ("Ảnh → Video (tạo ảnh rồi làm video)", Kind.IMAGE_VIDEO)]


def _row(*widgets) -> QHBoxLayout:
    lay = QHBoxLayout()
    for w in widgets:
        if w == "stretch":
            lay.addStretch(1)
        else:
            lay.addWidget(w)
    return lay


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Flow ProVip {__version__}")
        self.resize(1280, 820)
        self.settings = Settings.load()
        self.store = AccountStore()
        self.bg = BackgroundLoop()
        self.bridge = Bridge()
        self.bridge.log.connect(self._append_log)
        self.bridge.task_changed.connect(self._on_task_changed)
        self.bridge.finished.connect(self._on_run_finished)
        self.run: BatchRun | None = None
        self.active_table: TaskTable | None = None
        self._todo: list[Task] = []

        tabs = QTabWidget()
        tabs.addTab(self._accounts_tab(), "Tài khoản")
        tabs.addTab(self._batch_tab(), "Tạo hàng loạt")
        tabs.addTab(self._voice_tab(), "Voice → CapCut")
        tabs.addTab(self._settings_tab(), "Cài đặt")

        self.log_box = QPlainTextEdit(readOnly=True)
        self.log_box.setMaximumBlockCount(5000)
        self.progress = QProgressBar()
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.progress)
        bl.addWidget(self.log_box)
        split = QSplitter(Qt.Vertical)
        split.addWidget(tabs)
        split.addWidget(bottom)
        split.setSizes([600, 200])
        self.setCentralWidget(split)
        self.bridge.progress.connect(lambda p: self.progress.setValue(int(p * 100)))
        self._refresh_accounts()
        self._append_log(f"Flow ProVip phiên bản {__version__} — thư mục: {Path(__file__).resolve().parents[2]}")

    # ================================================================== Tài khoản
    def _accounts_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.acc_table = QTableWidget(0, 6)
        self.acc_table.setHorizontalHeaderLabels(["Dùng", "Tên", "Email", "Trạng thái", "Credit", "Proxy"])
        self.acc_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.acc_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.acc_table.itemChanged.connect(self._acc_item_changed)
        buttons = []
        for label, fn in (("+ Thêm tài khoản", self._add_account), ("Đăng nhập", self._login_selected),
                          ("Kiểm tra", self._check_selected), ("Nạp cookie JSON", self._import_cookies),
                          ("Đặt proxy", self._set_proxy), ("Xoá", self._remove_account)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            buttons.append(b)
        lay.addLayout(_row(*buttons, "stretch"))
        lay.addWidget(self.acc_table)
        lay.addWidget(QLabel(
            "Bấm “Đăng nhập” → đăng nhập Google → trên trang Flow bấm nút đăng nhập/“Create with Flow” cho tới "
            "khi thấy ô nhập prompt. Tool tự nhận ra và tự đóng cửa sổ. Tool không lưu mật khẩu."))
        return w

    def _refresh_accounts(self) -> None:
        t = self.acc_table
        t.blockSignals(True)
        t.setRowCount(len(self.store.accounts))
        for i, a in enumerate(self.store.accounts):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if a.enabled else Qt.Unchecked)
            t.setItem(i, 0, chk)
            for c, v in enumerate([a.name, a.email, a.status, "" if a.credits is None else str(a.credits),
                                   a.proxy], 1):
                it = QTableWidgetItem(v)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(i, c, it)
        t.blockSignals(False)

    def _acc_item_changed(self, item) -> None:
        if item.column() == 0:
            self.store.accounts[item.row()].enabled = item.checkState() == Qt.Checked
            self.store.save()

    def _selected_accounts(self):
        rows = sorted({i.row() for i in self.acc_table.selectedIndexes()})
        return [self.store.accounts[r] for r in rows]

    def _add_account(self) -> None:
        name, ok = QInputDialog.getText(self, "Thêm tài khoản", "Tên gợi nhớ (vd: acc1):")
        if ok and name.strip():
            self.store.add(name.strip())
            self._refresh_accounts()

    def _remove_account(self) -> None:
        accs = self._selected_accounts()
        if accs and QMessageBox.question(self, "Xoá", f"Xoá {len(accs)} tài khoản?") == QMessageBox.Yes:
            for a in accs:
                self.store.remove(a.id)
            self._refresh_accounts()

    def _set_proxy(self) -> None:
        for a in self._selected_accounts():
            proxy, ok = QInputDialog.getText(self, "Proxy", f"Proxy cho {a.name} (http://user:pass@ip:port):",
                                             text=a.proxy)
            if ok:
                a.proxy = proxy.strip()
        self.store.save()
        self._refresh_accounts()

    def _import_cookies(self) -> None:
        accs = self._selected_accounts()
        if len(accs) != 1:
            QMessageBox.information(self, "Cookie", "Chọn đúng 1 tài khoản.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "File cookie JSON", "", "JSON (*.json *.txt)")
        if not path:
            return
        try:
            accs[0].cookies = parse_cookies(Path(path).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Cookie", f"File cookie không hợp lệ: {e}")
            return
        self.store.save()
        self._append_log(f"[{accs[0].name}] đã nạp {len(accs[0].cookies)} cookie")
        self._check_selected()

    def _login_selected(self) -> None:
        for a in self._selected_accounts():
            self._account_job(login_account(self.bg, a, self.settings, self.bridge.log.emit), a)

    def _check_selected(self) -> None:
        for a in self._selected_accounts() or self.store.accounts:
            self._account_job(check_account(self.bg, a, self.settings), a)

    def _account_job(self, coro, acc) -> None:
        def done(fut):
            try:
                res = fut.result()
                msg = f"[{acc.name}] {'OK - ' + acc.email if res['ok'] else 'chưa đăng nhập: ' + str(res.get('error'))}"
            except Exception as e:  # noqa: BLE001
                acc.status = "lỗi"
                msg = f"[{acc.name}] lỗi: {e}"
            self.store.save()
            self.bridge.log.emit(msg)
            self.bridge.finished.emit(None)
        self.bg.submit(coro, done)

    # ================================================================== Tạo hàng loạt
    def _batch_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.batch_prompts = QPlainTextEdit()
        self.batch_prompts.setPlaceholderText(
            "Mỗi dòng 1 prompt.\nHoặc dán CSV có cột prompt,video_prompt\n\nVD:\n"
            "a samurai standing in the rain, neon city\na cat astronaut floating in space")
        self.batch_kind = QComboBox()
        for label, kind in KIND_LABELS:
            self.batch_kind.addItem(label, kind)
        self.batch_refs: list[str] = []
        self.batch_ref_label = QLabel("Ảnh tham chiếu: (không)")
        ref_btn = QPushButton("Chọn ảnh tham chiếu…")
        ref_btn.clicked.connect(self._pick_batch_refs)
        load_btn = QPushButton("Mở file prompt…")
        load_btn.clicked.connect(self._load_prompt_file)
        prep_btn = QPushButton("Tạo danh sách")
        prep_btn.clicked.connect(self._prepare_batch)
        self.batch_start = QPushButton("▶ Bắt đầu")
        self.batch_start.clicked.connect(lambda: self._start(self.batch_table))
        retry_btn = QPushButton("Chạy lại mục lỗi")
        retry_btn.clicked.connect(lambda: self._start(self.batch_table, only_failed=True))
        self.batch_stop = QPushButton("■ Dừng")
        self.batch_stop.clicked.connect(self._stop)
        open_btn = QPushButton("Mở thư mục output")
        open_btn.clicked.connect(self._open_output)

        self.batch_table = TaskTable(show_timing=False)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addLayout(_row(QLabel("Loại:"), self.batch_kind, load_btn, ref_btn, self.batch_ref_label, "stretch"))
        tl.addWidget(self.batch_prompts)
        tl.addLayout(_row(prep_btn, self.batch_start, retry_btn, self.batch_stop, open_btn, "stretch"))
        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(self.batch_table)
        lay.addWidget(split)
        return w

    def _pick_batch_refs(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Ảnh tham chiếu", "", "Ảnh (*.png *.jpg *.jpeg *.webp)")
        self.batch_refs = paths
        self.batch_ref_label.setText(f"Ảnh tham chiếu: {len(paths)} ảnh" if paths else "Ảnh tham chiếu: (không)")

    def _load_prompt_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "File prompt", "", "Text/CSV (*.txt *.csv *.tsv)")
        if path:
            self.batch_prompts.setPlainText(Path(path).read_text(encoding="utf-8-sig"))

    def _prepare_batch(self) -> list[Task]:
        kind = self.batch_kind.currentData()
        tasks = tasks_from_text(self.batch_prompts.toPlainText(), kind,
                                self.settings.style_prefix, self.settings.style_suffix)
        for t in tasks:
            t.ref_images = list(self.batch_refs)
        self.batch_table.set_tasks(tasks)
        return tasks

    # ================================================================== Voice -> CapCut
    def _voice_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.audio_path = QLineEdit()
        self.audio_path.setPlaceholderText("File voice (mp3, wav, m4a…)")
        self.srt_path = QLineEdit()
        self.srt_path.setPlaceholderText("(Tuỳ chọn) file SRT có sẵn — bỏ trống để Whisper tự nhận diện")
        b1 = QPushButton("Chọn voice…")
        b1.clicked.connect(lambda: self._pick_file(self.audio_path, "Audio (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)"))
        b2 = QPushButton("Chọn SRT…")
        b2.clicked.connect(lambda: self._pick_file(self.srt_path, "Phụ đề (*.srt)"))
        analyze = QPushButton("① Phân tích voice → phân cảnh")
        analyze.clicked.connect(self._analyze_voice)

        self.voice_kind = QComboBox()
        for label, kind in KIND_LABELS:
            self.voice_kind.addItem(label, kind)
        paste_btn = QPushButton("Dán prompt theo cảnh…")
        paste_btn.clicked.connect(self._paste_scene_prompts)
        gen = QPushButton("② Tạo ảnh/video cho các cảnh")
        gen.clicked.connect(lambda: self._start(self.voice_table))
        retry = QPushButton("Chạy lại mục lỗi")
        retry.clicked.connect(lambda: self._start(self.voice_table, only_failed=True))
        stop = QPushButton("■ Dừng")
        stop.clicked.connect(self._stop)
        self.draft_name = QLineEdit(f"FlowProVip {time.strftime('%Y%m%d-%H%M')}")
        export = QPushButton("③ Xuất draft CapCut")
        export.clicked.connect(self._export_capcut)
        self.prefer_video = QCheckBox("Ưu tiên video nếu có")
        self.prefer_video.setChecked(True)

        self.voice_table = TaskTable(show_timing=True)
        lay.addLayout(_row(self.audio_path, b1))
        lay.addLayout(_row(self.srt_path, b2))
        lay.addLayout(_row(analyze, QLabel("Loại:"), self.voice_kind, paste_btn, "stretch"))
        lay.addWidget(self.voice_table)
        lay.addLayout(_row(gen, retry, stop, "stretch", QLabel("Tên draft:"), self.draft_name,
                           self.prefer_video, export))
        return w

    def _pick_file(self, edit: QLineEdit, filt: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file", "", filt)
        if path:
            edit.setText(path)

    def _analyze_voice(self) -> None:
        audio = self.audio_path.text().strip()
        if not audio or not Path(audio).exists():
            QMessageBox.warning(self, "Voice", "Chọn file voice trước.")
            return
        srt = self.srt_path.text().strip() or None
        kind = self.voice_kind.currentData()
        self._append_log("Đang phân tích voice (lần đầu Whisper sẽ tải model, hơi lâu)…")

        async def job():
            import asyncio
            from flowprovip.pipeline import scenes_from_audio, tasks_from_scenes
            scenes = await asyncio.to_thread(scenes_from_audio, audio, self.settings, srt,
                                             lambda p: self.bridge.progress.emit(p))
            return tasks_from_scenes(scenes, kind, self.settings)

        def done(fut):
            try:
                tasks = fut.result()
            except Exception as e:  # noqa: BLE001
                self.bridge.log.emit(f"Lỗi phân tích voice: {e}")
                return
            self.bridge.log.emit(f"Đã chia {len(tasks)} cảnh")
            self.bridge.finished.emit(("voice_tasks", tasks))
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        self.bg.submit(job(), done)

    def _paste_scene_prompts(self) -> None:
        tasks = self.voice_table.tasks
        if not tasks:
            QMessageBox.information(self, "Prompt", "Phân tích voice trước.")
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "Prompt theo cảnh",
            f"Dán {len(tasks)} dòng prompt (dòng 1 = cảnh 1…). Có thể viết bằng ChatGPT/Claude từ lời thoại.",
            "\n".join(t.prompt for t in tasks))
        if not ok:
            return
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        for t, line in zip(tasks, lines):
            t.prompt = line
        self.voice_table.set_tasks(tasks)

    def _export_capcut(self) -> None:
        tasks = self.voice_table.tasks
        audio = self.audio_path.text().strip()
        if not tasks or not audio:
            QMessageBox.warning(self, "CapCut", "Chưa có phân cảnh / voice.")
            return
        from flowprovip.pipeline import export_capcut
        try:
            folder = export_capcut(tasks, audio, self.settings, self.draft_name.text().strip(),
                                   prefer_video=self.prefer_video.isChecked())
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "CapCut", f"Xuất draft lỗi: {e}")
            return
        self._append_log(f"Đã xuất draft CapCut: {folder}")
        QMessageBox.information(self, "CapCut", f"Đã tạo draft:\n{folder}\n\nMở CapCut để thấy project mới.")

    # ================================================================== Chạy
    def _start(self, table: TaskTable, only_failed: bool = False) -> None:
        if self.run:
            QMessageBox.information(self, "Đang chạy", "Đang có tiến trình chạy, dừng trước đã.")
            return
        if table is self.batch_table and not table.tasks:
            self._prepare_batch()
        tasks = table.tasks
        if not tasks:
            QMessageBox.warning(self, "Chưa có tác vụ", "Danh sách trống.")
            return
        kind = (self.voice_kind if table is self.voice_table else self.batch_kind).currentData()
        todo = []
        for t in tasks:
            if only_failed and t.status not in (Status.FAILED, Status.CANCELLED):
                continue
            if not only_failed and t.status == Status.DONE:
                continue
            t.kind, t.attempts, t.error = kind, 0, ""
            todo.append(t)
        accounts = self.store.enabled()
        if not accounts:
            QMessageBox.warning(self, "Tài khoản", "Chưa bật tài khoản nào.")
            return
        if not todo:
            self._append_log("Không còn tác vụ cần chạy.")
            return
        self.active_table = table
        self.progress.setMaximum(len(todo))
        self.progress.setValue(0)
        self._todo = todo
        self._append_log(f"Bắt đầu {len(todo)} tác vụ trên {len(accounts)} tài khoản × "
                         f"{self.settings.threads_per_account} luồng")
        self.run = BatchRun(self.bg, accounts, self.settings, self.bridge.task_changed.emit, self.bridge.log.emit)

        def done(fut):
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                self.bridge.log.emit(f"Dừng: {e}")
            self.bridge.finished.emit("run")
        self.bg.submit(self.run.run(todo), done)

    def _stop(self) -> None:
        if self.run:
            self.run.cancel()
            self._append_log("Đang dừng… (chờ các tác vụ đang chạy xong)")

    def _on_task_changed(self, task: Task) -> None:
        if self.active_table:
            self.active_table.update_task(task)
            finished = sum(t.status in (Status.DONE, Status.FAILED) for t in self._todo)
            self.progress.setValue(finished)

    def _on_run_finished(self, what) -> None:
        if what == "run":
            self.run = None
            done = sum(t.status == Status.DONE for t in self._todo)
            self._append_log(f"Hoàn tất: {done}/{len(self._todo)} thành công")
            self.store.save()
        elif isinstance(what, tuple) and what[0] == "voice_tasks":
            self.voice_table.set_tasks(what[1])
            self.progress.setValue(self.progress.maximum())
        self._refresh_accounts()

    def _open_output(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        Path(self.settings.output_dir).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.settings.output_dir))

    def _append_log(self, msg: str) -> None:
        self.log_box.appendPlainText(f"{time.strftime('%H:%M:%S')}  {msg}")

    # ================================================================== Cài đặt
    _LABELS = {
        "output_dir": "Thư mục output", "threads_per_account": "Số luồng / tài khoản",
        "max_retries": "Số lần thử lại", "headless": "Chạy ẩn trình duyệt",
        "browser_channel": "Trình duyệt (chrome / msedge / để trống = Chromium)",
        "image_model": "Model ảnh", "image_aspect": "Tỉ lệ ảnh", "images_per_prompt": "Số ảnh / prompt",
        "video_model_t2v": "Model video (text)", "video_model_i2v": "Model video (từ ảnh)",
        "video_aspect": "Tỉ lệ video", "video_poll_interval": "Chu kỳ kiểm tra video (s)",
        "video_timeout": "Timeout video (s)", "style_prefix": "Prompt thêm phía trước",
        "style_suffix": "Prompt thêm phía sau", "whisper_model": "Model Whisper (tiny/base/small/medium/large-v3)",
        "whisper_language": "Ngôn ngữ voice", "scene_min_sec": "Cảnh ngắn nhất (s)",
        "scene_max_sec": "Cảnh dài nhất (s)", "capcut_drafts_dir": "Thư mục draft CapCut (trống = mặc định)",
        "capcut_template_draft": "Draft mẫu (tuỳ chọn)", "canvas_width": "Khung hình rộng",
        "canvas_height": "Khung hình cao", "add_subtitles": "Thêm phụ đề vào draft",
        "ken_burns": "Hiệu ứng zoom chậm cho ảnh",
    }
    _CHOICES = {
        "image_aspect": ["IMAGE_ASPECT_RATIO_LANDSCAPE", "IMAGE_ASPECT_RATIO_PORTRAIT", "IMAGE_ASPECT_RATIO_SQUARE"],
        "video_aspect": ["VIDEO_ASPECT_RATIO_LANDSCAPE", "VIDEO_ASPECT_RATIO_PORTRAIT"],
    }

    def _settings_tab(self) -> QWidget:
        inner = QWidget()
        form = QFormLayout(inner)
        self._setting_widgets = {}
        for f in fields(Settings):
            if f.name not in self._LABELS:
                continue
            val = getattr(self.settings, f.name)
            if f.name in self._CHOICES:
                wdg = QComboBox()
                wdg.setEditable(True)
                wdg.addItems(self._CHOICES[f.name])
                wdg.setCurrentText(val)
            elif isinstance(val, bool):
                wdg = QCheckBox()
                wdg.setChecked(val)
            elif isinstance(val, int):
                wdg = QSpinBox()
                wdg.setRange(0, 100_000)
                wdg.setValue(val)
            elif isinstance(val, float):
                wdg = QDoubleSpinBox()
                wdg.setRange(0, 100_000)
                wdg.setValue(val)
            else:
                wdg = QLineEdit(str(val))
            self._setting_widgets[f.name] = wdg
            form.addRow(self._LABELS[f.name], wdg)
        save = QPushButton("Lưu cài đặt")
        save.clicked.connect(self._save_settings)
        form.addRow(save)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        return scroll

    def _save_settings(self) -> None:
        for name, wdg in self._setting_widgets.items():
            if isinstance(wdg, QComboBox):
                v = wdg.currentText()
            elif isinstance(wdg, QCheckBox):
                v = wdg.isChecked()
            elif isinstance(wdg, (QSpinBox, QDoubleSpinBox)):
                v = wdg.value()
            else:
                v = wdg.text()
            setattr(self.settings, name, v)
        self.settings.save()
        self._append_log("Đã lưu cài đặt")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from flowprovip.jobs import Status, Task

STATUS_COLORS = {
    Status.PENDING: "#888888",
    Status.RUNNING: "#1e88e5",
    Status.DONE: "#2e7d32",
    Status.FAILED: "#c62828",
    Status.CANCELLED: "#8d6e63",
}


class Bridge(QObject):
    """Chuyển sự kiện từ luồng nền sang luồng giao diện."""
    task_changed = Signal(object)
    log = Signal(str)
    finished = Signal(object)
    progress = Signal(float)


def fmt_time(t: float | None) -> str:
    if t is None:
        return ""
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


class TaskTable(QTableWidget):
    """Bảng tác vụ. Cột Prompt có thể sửa trực tiếp trước khi chạy."""

    COLS = ["#", "Bắt đầu", "Kết thúc", "Lời thoại", "Prompt", "Trạng thái", "Tài khoản", "Kết quả / lỗi"]

    def __init__(self, show_timing: bool = False, parent=None):
        super().__init__(0, len(self.COLS), parent)
        self.setHorizontalHeaderLabels(self.COLS)
        self.tasks: list[Task] = []
        self._rows: dict[str, int] = {}
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(True)
        self.setColumnWidth(0, 50)
        self.setColumnWidth(3, 260)
        self.setColumnWidth(4, 340)
        self.setColumnWidth(5, 90)
        for c in (1, 2, 3):
            self.setColumnHidden(c, not show_timing)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verticalHeader().setVisible(False)
        self.itemChanged.connect(self._on_edit)

    def set_tasks(self, tasks: list[Task]) -> None:
        self.blockSignals(True)
        self.tasks = tasks
        self._rows = {t.id: i for i, t in enumerate(tasks)}
        self.setRowCount(len(tasks))
        for i, t in enumerate(tasks):
            for c, val in enumerate([t.name, fmt_time(t.start), fmt_time(t.end), t.text, t.prompt]):
                item = QTableWidgetItem(val)
                if c != 4:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.setItem(i, c, item)
            self._fill_status(i, t)
        self.blockSignals(False)

    def update_task(self, t: Task) -> None:
        row = self._rows.get(t.id)
        if row is None:
            return
        self.blockSignals(True)
        self._fill_status(row, t)
        self.blockSignals(False)

    def _fill_status(self, row: int, t: Task) -> None:
        result = t.error if t.status == Status.FAILED else ", ".join(p.split("/")[-1].split("\\")[-1] for p in t.outputs)
        for c, val in ((5, t.status.value), (6, t.account), (7, result or t.error)):
            item = QTableWidgetItem(val)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if c == 5:
                item.setForeground(QColor(STATUS_COLORS.get(t.status, "#000")))
            self.setItem(row, c, item)

    def _on_edit(self, item: QTableWidgetItem) -> None:
        if item.column() == 4 and item.row() < len(self.tasks):
            self.tasks[item.row()].prompt = item.text()

    def selected_tasks(self) -> list[Task]:
        rows = sorted({i.row() for i in self.selectedIndexes()})
        return [self.tasks[r] for r in rows if r < len(self.tasks)]

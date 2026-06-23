"""Spawn Density Editor tab — browse spawning_pool_auto_spawn_info.

NOTE: This table is currently BLOB_ONLY in dmm_parser, meaning only
key, string_key, is_blocked, and raw body are available. Full field
editing will be available after the CString UTF-8 parser update.
"""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QLineEdit, QAbstractItemView, QApplication,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)

INTERNAL_DIR = "gamedata/binary__/client/bin"


class SpawnEditorTab(QWidget):
    """Browse spawning pool auto-spawn info (placeholder until full parser support)."""

    status_message = Signal(str)
    config_save_requested = Signal()

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._entries: list[dict] = []
        self._pabgh: bytes = b""
        self._pabgb: bytes = b""
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._config["game_install_path"] = path

    # -- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Info
        info = QLabel(
            "<b>Spawn Density Editor</b> -- Browse spawningpoolautospawninfo.pabgb (140 entries).<br><br>"
            "<b>NOTE:</b> This table is currently <span style='color: #FF8800;'>BLOB_ONLY</span> "
            "in the parser. Only key, string_key, is_blocked, and raw body size "
            "are available.<br>"
            "Full field editing (spawn counts, respawn timers, radius) will be "
            "available after the CString UTF-8 parser update lands in dmm_parser."
        )
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['text']}; background-color: {COLORS['panel']}; "
            f"padding: 8px; border: 2px solid {COLORS['accent']}; border-radius: 6px;"
        )
        root.addWidget(info)

        # Top row
        top = QHBoxLayout()

        extract_btn = QPushButton("Extract")
        extract_btn.setObjectName("accentBtn")
        extract_btn.clicked.connect(self._extract)
        top.addWidget(extract_btn)

        top.addWidget(QLabel("Filter:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Search by name or key...")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._apply_filter)
        self._filter_edit.setFixedWidth(250)
        top.addWidget(self._filter_edit)

        top.addStretch()

        self._count_label = QLabel("")
        top.addWidget(self._count_label)

        root.addLayout(top)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels([
            "Key", "String Key", "Blocked", "Body Size (bytes)",
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)
        root.addWidget(self._table, 1)

        # Placeholder note about future capabilities
        future_group = QLabel(
            "When full field support is added, this tab will expose:\n"
            "  - spawn_count / max_spawn_count (density multiplier)\n"
            "  - respawn_time / respawn_interval\n"
            "  - spawn_radius / patrol_radius\n"
            "  - creature_key references\n"
            "  - Deploy as PAZ overlay like other tabs"
        )
        future_group.setStyleSheet(
            f"color: {COLORS['text_dim']}; padding: 8px; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px;"
        )
        root.addWidget(future_group)

        # Status
        self._status = QLabel("Click Extract to load spawning_pool_auto_spawn_info.")
        self._status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        root.addWidget(self._status)

    # -- Extract -----------------------------------------------------------

    def _extract(self) -> None:
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            QMessageBox.warning(self, "No Game Path", "Set the game install path first.")
            return

        self.status_message.emit("Extracting spawning_pool_auto_spawn_info...")
        QApplication.processEvents()

        try:
            import crimson_rs
            import dmm_parser

            pabgb = bytes(crimson_rs.extract_file(
                game, "0008", INTERNAL_DIR,
                "spawningpoolautospawninfo.pabgb"))
            pabgh = bytes(crimson_rs.extract_file(
                game, "0008", INTERNAL_DIR,
                "spawningpoolautospawninfo.pabgh"))
            self._pabgh = pabgh
            self._pabgb = pabgb

            self._entries = dmm_parser.parse_table(
                "spawning_pool_auto_spawn_info", pabgb, pabgh)

            self._populate()
            self._status.setText(
                f"Loaded {len(self._entries)} spawn pool entries "
                f"({len(pabgb):,} bytes) -- BLOB_ONLY mode")
            self.status_message.emit(
                f"Loaded {len(self._entries)} spawn entries (blob-only)")
        except Exception as e:
            log.exception("Spawn extract failed")
            QMessageBox.critical(self, "Extract Failed", str(e))

    # -- Table population --------------------------------------------------

    def _populate(self) -> None:
        text_filter = self._filter_edit.text().strip().lower()

        self._table.setSortingEnabled(False)
        rows = []
        for e in self._entries:
            key = e.get("key", 0)
            string_key = str(e.get("string_key", ""))
            if text_filter:
                combined = f"{key} {string_key}".lower()
                if text_filter not in combined:
                    continue
            rows.append(e)

        self._table.setRowCount(len(rows))
        for row, e in enumerate(rows):
            key = e.get("key", 0)
            string_key = str(e.get("string_key", ""))
            is_blocked = e.get("is_blocked", 0)

            # Body size: try _blob_b64 or _blob_fallback or raw body
            body_size = 0
            blob = e.get("_blob_b64", e.get("_blob_fallback", ""))
            if blob and isinstance(blob, str):
                import base64
                try:
                    body_size = len(base64.b64decode(blob))
                except Exception:
                    pass
            elif isinstance(blob, bytes):
                body_size = len(blob)

            items_data = [
                (str(key), Qt.AlignRight | Qt.AlignVCenter),
                (string_key, Qt.AlignLeft | Qt.AlignVCenter),
                (str(is_blocked), Qt.AlignCenter),
                (str(body_size), Qt.AlignRight | Qt.AlignVCenter),
            ]
            for col, (text, align) in enumerate(items_data):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self._table.setItem(row, col, item)

        self._table.setSortingEnabled(True)
        self._count_label.setText(f"({len(rows)}/{len(self._entries)})")

    def _apply_filter(self) -> None:
        if self._entries:
            self._populate()

    # -- Public API --------------------------------------------------------

    def get_staged_files(self) -> dict[str, bytes]:
        """No deployment yet -- blob-only mode."""
        return {}

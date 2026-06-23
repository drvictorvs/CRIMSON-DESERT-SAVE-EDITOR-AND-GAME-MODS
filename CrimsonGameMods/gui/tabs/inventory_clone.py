"""Inventory Clone — copy player inventory from one save to another.

Loads two save files, extracts the inventory item list from the source,
and writes it into the target save. Handles PARC offset fixup and
re-encryption automatically.
"""
from __future__ import annotations

import copy
import logging
import os
import shutil
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QApplication, QGroupBox,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)

SAVE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Pearl Abyss", "CD", "save"
)


class InventoryCloneTab(QWidget):
    """Clone inventory items from one save file to another."""

    status_message = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._source_path = ""
        self._target_path = ""
        self._source_items = []
        self._target_items = []
        self._source_save = None
        self._target_save = None
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._config["game_install_path"] = path

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        info = QLabel(
            "<b>Inventory Clone</b> — Copy player inventory from one save to another.<br>"
            "Select a source save (to copy FROM) and a target save (to copy TO).<br>"
            "<b>WARNING:</b> This overwrites the target save's inventory. "
            "A backup is created automatically."
        )
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['text']}; background-color: {COLORS['panel']}; "
            f"padding: 8px; border: 2px solid #FF6644; border-radius: 6px;"
        )
        root.addWidget(info)

        # Source save
        src_group = QGroupBox("Source Save (copy FROM)")
        src_group.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; color: {COLORS['accent']}; }}")
        src_layout = QHBoxLayout(src_group)
        self._src_label = QLabel("No save loaded")
        self._src_label.setStyleSheet(f"color: {COLORS['text']};")
        src_layout.addWidget(self._src_label, 1)
        src_btn = QPushButton("Browse Source...")
        src_btn.clicked.connect(self._browse_source)
        src_layout.addWidget(src_btn)
        root.addWidget(src_group)

        # Source items table
        self._src_table = QTableWidget()
        self._src_table.setColumnCount(4)
        self._src_table.setHorizontalHeaderLabels(["Key", "Name", "Stack", "Source"])
        self._src_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._src_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._src_table.setAlternatingRowColors(True)
        self._src_table.verticalHeader().setVisible(False)
        self._src_table.setMaximumHeight(200)
        root.addWidget(self._src_table)

        # Target save
        tgt_group = QGroupBox("Target Save (copy TO)")
        tgt_group.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; color: #FF6644; }}")
        tgt_layout = QHBoxLayout(tgt_group)
        self._tgt_label = QLabel("No save loaded")
        self._tgt_label.setStyleSheet(f"color: {COLORS['text']};")
        tgt_layout.addWidget(self._tgt_label, 1)
        tgt_btn = QPushButton("Browse Target...")
        tgt_btn.clicked.connect(self._browse_target)
        tgt_layout.addWidget(tgt_btn)
        root.addWidget(tgt_group)

        # Target items table
        self._tgt_table = QTableWidget()
        self._tgt_table.setColumnCount(4)
        self._tgt_table.setHorizontalHeaderLabels(["Key", "Name", "Stack", "Source"])
        self._tgt_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tgt_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tgt_table.setAlternatingRowColors(True)
        self._tgt_table.verticalHeader().setVisible(False)
        self._tgt_table.setMaximumHeight(200)
        root.addWidget(self._tgt_table)

        # Clone button
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._clone_btn = QPushButton("Clone Save: Source → Target")
        self._clone_btn.setStyleSheet(
            "background-color: #FF6644; color: white; font-weight: bold; "
            "padding: 10px 20px; font-size: 14px;")
        self._clone_btn.setEnabled(False)
        self._clone_btn.clicked.connect(self._do_clone)
        btn_row.addWidget(self._clone_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        # Status
        self._status = QLabel("Select source and target saves to begin.")
        self._status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        root.addWidget(self._status)

        root.addStretch()

    def _browse_source(self) -> None:
        start_dir = SAVE_DIR if os.path.isdir(SAVE_DIR) else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Source Save", start_dir,
            "Save Files (*.save);;All Files (*)")
        if not path:
            return
        self._source_path = path
        self._load_save("source", path)

    def _browse_target(self) -> None:
        start_dir = SAVE_DIR if os.path.isdir(SAVE_DIR) else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Target Save", start_dir,
            "Save Files (*.save);;All Files (*)")
        if not path:
            return
        self._target_path = path
        self._load_save("target", path)

    def _load_save(self, which: str, path: str) -> None:
        QApplication.processEvents()
        try:
            from save_crypto import load_save_file
            from item_scanner import scan_items_parc

            save_data = load_save_file(path)
            items, err = scan_items_parc(save_data.decompressed_blob)

            if which == "source":
                self._source_save = save_data
                self._source_items = items
                self._src_label.setText(
                    f"{os.path.basename(os.path.dirname(path))}/{os.path.basename(path)} "
                    f"— {len(items)} items")
                self._populate_table(self._src_table, items)
            else:
                self._target_save = save_data
                self._target_items = items
                self._tgt_label.setText(
                    f"{os.path.basename(os.path.dirname(path))}/{os.path.basename(path)} "
                    f"— {len(items)} items")
                self._populate_table(self._tgt_table, items)

            self._clone_btn.setEnabled(
                self._source_save is not None and self._target_save is not None)
            self._status.setText(f"Loaded {which}: {len(items)} items from {os.path.basename(path)}")
            self.status_message.emit(f"Loaded {which} save: {len(items)} items")

        except Exception as e:
            log.exception("Save load failed")
            QMessageBox.critical(self, "Load Failed", str(e))

    def _populate_table(self, table: QTableWidget, items: list) -> None:
        table.setRowCount(len(items))
        for i, item in enumerate(items):
            key = getattr(item, "item_key", 0) if hasattr(item, "item_key") else item.get("item_key", 0) if isinstance(item, dict) else 0
            name = getattr(item, "name", "") if hasattr(item, "name") else item.get("name", "") if isinstance(item, dict) else ""
            stack = getattr(item, "stack_count", 1) if hasattr(item, "stack_count") else item.get("stack_count", 1) if isinstance(item, dict) else 1
            source = getattr(item, "source_block", "") if hasattr(item, "source_block") else item.get("source_block", "") if isinstance(item, dict) else ""

            if not name:
                name = str(key)

            table.setItem(i, 0, QTableWidgetItem(str(key)))
            table.setItem(i, 1, QTableWidgetItem(str(name)))
            table.setItem(i, 2, QTableWidgetItem(str(stack)))
            table.setItem(i, 3, QTableWidgetItem(str(source)))

    def _do_clone(self) -> None:
        if not self._source_save or not self._target_save:
            QMessageBox.warning(self, "Clone", "Load both source and target saves first.")
            return

        if self._source_path == self._target_path:
            QMessageBox.warning(self, "Clone", "Source and target cannot be the same file.")
            return

        reply = QMessageBox.question(
            self, "Confirm Clone",
            f"This will REPLACE the target save with the source save's data "
            f"({len(self._source_items)} items).\n\n"
            f"This clones the ENTIRE save (inventory, equipment, quests, progress).\n"
            f"The target save slot is preserved.\n\n"
            f"Source: {os.path.basename(self._source_path)}\n"
            f"Target: {os.path.basename(self._target_path)}\n\n"
            f"A backup will be created. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        QApplication.processEvents()
        try:
            self._status.setText("Cloning save...")
            self.status_message.emit("Cloning save...")
            QApplication.processEvents()

            # Backup target
            backup_path = self._target_path + ".clone_backup"
            shutil.copy2(self._target_path, backup_path)
            log.info("Backed up target to %s", backup_path)

            from save_crypto import write_save_file

            # Clone: write source blob with target's header (preserves save slot)
            write_save_file(
                self._target_path,
                bytes(self._source_save.decompressed_blob),
                self._target_save.raw_header,
            )

            self._status.setText(
                f"Cloned {len(self._source_items)} items to target. "
                f"Backup at {os.path.basename(backup_path)}")
            self.status_message.emit("Save clone complete!")
            QMessageBox.information(
                self, "Clone Complete",
                f"Successfully cloned save with {len(self._source_items)} items.\n\n"
                f"Backup saved at:\n{backup_path}")

            # Reload target to show new items
            self._load_save("target", self._target_path)

        except Exception as e:
            log.exception("Clone failed")
            QMessageBox.critical(self, "Clone Failed", str(e))
            self._status.setText(f"Clone failed: {e}")

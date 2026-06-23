"""Vehicle Editor tab â€” edit mount/vehicle stats from vehicleinfo.pabgb.

34 entries covering all mounts: horses, dragon, ATAG, boats, etc.
Edit speed, stamina, handling and other parameters.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QLineEdit, QSpinBox, QAbstractItemView, QApplication, QGroupBox,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)


class VehicleEditorTab(QWidget):
    status_message = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._entries: list[dict] = []
        self._vanilla: list[dict] = []
        self._modified_keys: set[int] = set()
        self._pabgb_bytes = b""
        self._pabgh_bytes = b""
        self._building = False
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._config["game_install_path"] = path

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        info = QLabel(
            "<b>Vehicle Editor</b> â€” Edit all 34 mounts/vehicles from vehicleinfo.pabgb.<br>"
            "Modify mount stats, speed, stamina and other parameters. "
            "Use presets for quick bulk edits."
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

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter by name...")
        self._filter.textChanged.connect(self._apply_filter)
        top.addWidget(self._filter)

        top.addStretch()
        self._count_label = QLabel("")
        top.addWidget(self._count_label)

        top.addWidget(QLabel("Overlay:"))
        self._overlay_spin = QSpinBox()
        self._overlay_spin.setRange(1, 9999)
        self._overlay_spin.setValue(self._config.get("vehicle_overlay_dir", 74))
        self._overlay_spin.setFixedWidth(70)
        self._overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"vehicle_overlay_dir": int(v)}))
        top.addWidget(self._overlay_spin)

        deploy_btn = QPushButton("Apply to Game")
        deploy_btn.setStyleSheet(
            f"background-color: {COLORS['accent']}; color: white; font-weight: bold;")
        deploy_btn.clicked.connect(self._deploy)
        top.addWidget(deploy_btn)

        restore_btn = QPushButton("Restore")
        restore_btn.clicked.connect(self._restore)
        top.addWidget(restore_btn)

        root.addLayout(top)

        # Presets row
        presets = QHBoxLayout()
        presets.addWidget(QLabel("Presets:"))
        for label, field, factor in [
            ("2x Speed", "speed_multiplier", 2.0),
            ("5x Speed", "speed_multiplier", 5.0),
            ("10x Speed", "speed_multiplier", 10.0),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(f"Multiply speed-related fields by {factor}")
            btn.clicked.connect(lambda _, f=factor: self._preset_multiply_floats(f))
            presets.addWidget(btn)
        max_stam_btn = QPushButton("Max Stamina")
        max_stam_btn.setToolTip("Maximize stamina-related u32 fields")
        max_stam_btn.clicked.connect(self._preset_max_stamina)
        presets.addWidget(max_stam_btn)
        presets.addStretch()
        root.addLayout(presets)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "Key", "String Key", "Blocked", "Fields", "Modified",
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        root.addWidget(self._table, 1)

        # Detail panel
        self._detail = QLabel("Select a vehicle to see details.")
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 8px;")
        self._detail.setMaximumHeight(200)
        root.addWidget(self._detail)
        self._table.currentCellChanged.connect(self._on_row_selected)

        self._status = QLabel("Click Extract to load vehicleinfo.pabgb.")
        self._status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        root.addWidget(self._status)

    # -- Extract -----------------------------------------------------------

    def _extract(self) -> None:
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            QMessageBox.warning(self, "No Game Path", "Set the game install path first.")
            return
        self.status_message.emit("Extracting vehicleinfo...")
        QApplication.processEvents()
        try:
            import crimson_rs
            self._pabgb_bytes = bytes(crimson_rs.extract_file(
                game, "0008", "gamedata/binary__/client/bin", "vehicleinfo.pabgb"))
            try:
                self._pabgh_bytes = bytes(crimson_rs.extract_file(
                    game, "0008", "gamedata/binary__/client/bin", "vehicleinfo.pabgh"))
            except Exception:
                self._pabgh_bytes = b""
            import dmm_parser
            pabgh = self._pabgh_bytes if self._pabgh_bytes else None
            self._entries = list(dmm_parser.parse_table(
                "vehicle_info", self._pabgb_bytes, pabgh))
            import copy
            self._vanilla = copy.deepcopy(self._entries)
            self._modified_keys.clear()
            self._populate()
            self._status.setText(f"Loaded {len(self._entries)} vehicles")
            self.status_message.emit(f"Loaded {len(self._entries)} vehicles")
        except Exception as e:
            log.exception("Vehicle extract failed")
            QMessageBox.critical(self, "Extract Failed", str(e))

    def _populate(self) -> None:
        self._building = True
        filt = self._filter.text().lower()
        visible = [e for e in self._entries
                   if not filt or filt in str(e.get("string_key", "")).lower()]
        self._table.setRowCount(len(visible))
        for i, entry in enumerate(visible):
            key = entry.get("key", 0)
            sk = entry.get("string_key", "")
            blocked = entry.get("is_blocked", 0)
            fields = len(entry)
            modified = "âœ“" if key in self._modified_keys else ""
            self._table.setItem(i, 0, QTableWidgetItem(str(key)))
            self._table.setItem(i, 1, QTableWidgetItem(str(sk)))
            self._table.setItem(i, 2, QTableWidgetItem(str(blocked)))
            self._table.setItem(i, 3, QTableWidgetItem(str(fields)))
            mod_item = QTableWidgetItem(modified)
            if modified:
                mod_item.setForeground(Qt.green)
            self._table.setItem(i, 4, mod_item)
        self._count_label.setText(f"{len(visible)}/{len(self._entries)}")
        self._building = False

    def _apply_filter(self) -> None:
        if self._entries:
            self._populate()

    def _on_row_selected(self, row, col, prev_row, prev_col) -> None:
        if row < 0 or not self._entries:
            return
        key_item = self._table.item(row, 0)
        if not key_item:
            return
        key = int(key_item.text())
        entry = next((e for e in self._entries if e.get("key") == key), None)
        if not entry:
            return
        lines = []
        for k, v in sorted(entry.items()):
            if k in ("key", "string_key", "is_blocked"):
                continue
            val_str = str(v)
            if len(val_str) > 80:
                val_str = val_str[:80] + "..."
            lines.append(f"<b>{k}</b>: {val_str}")
        self._detail.setText("<br>".join(lines) if lines else "No extra fields")

    # -- Presets -----------------------------------------------------------

    def _scale_float_fields(self, entry: dict, factor: float) -> int:
        count = 0
        for k, v in entry.items():
            if k in ("key", "string_key", "is_blocked"):
                continue
            if isinstance(v, float) and v > 0:
                entry[k] = v * factor
                count += 1
            elif isinstance(v, list) and all(isinstance(x, (int, float)) for x in v) and len(v) in (3, 4):
                entry[k] = [x * factor for x in v]
                count += 1
        return count

    def _preset_multiply_floats(self, factor: float) -> None:
        if not self._entries:
            QMessageBox.information(self, "Presets", "Extract first.")
            return
        total = 0
        for entry in self._entries:
            total += self._scale_float_fields(entry, factor)
            self._modified_keys.add(entry.get("key", 0))
        self._populate()
        self._status.setText(f"Scaled {total} float fields by {factor}x across {len(self._entries)} vehicles")
        self.status_message.emit(f"Preset: {factor}x speed applied to all vehicles")

    def _preset_max_stamina(self) -> None:
        if not self._entries:
            QMessageBox.information(self, "Presets", "Extract first.")
            return
        for entry in self._entries:
            for k, v in entry.items():
                if "stamina" in k.lower() or "endurance" in k.lower():
                    if isinstance(v, (int, float)):
                        entry[k] = 999999
            self._modified_keys.add(entry.get("key", 0))
        self._populate()
        self._status.setText("Maximized stamina on all vehicles")
        self.status_message.emit("Preset: max stamina applied")

    # -- Deploy ------------------------------------------------------------

    def _deploy(self) -> None:
        if not self._modified_keys:
            QMessageBox.information(self, "Apply to Game", "No modifications to deploy.")
            return
        game = self._config.get("game_install_path", "")
        if not game:
            QMessageBox.warning(self, "Apply to Game", "Set game path first.")
            return
        try:
            import dmm_parser
            import crimson_rs
            import tempfile

            pabgh = self._pabgh_bytes if self._pabgh_bytes else None
            new_body = bytes(dmm_parser.serialize_table("vehicle_info", self._entries))

            INTERNAL_DIR = "gamedata/binary__/client/bin"
            overlay_group = f"{self._overlay_spin.value():04d}"
            game_overlay = os.path.join(game, overlay_group)
            os.makedirs(game_overlay, exist_ok=True)

            with tempfile.TemporaryDirectory() as tmp_dir:
                build_dir = os.path.join(tmp_dir, overlay_group)
                builder = crimson_rs.PackGroupBuilder(
                    build_dir, crimson_rs.Compression.NONE, crimson_rs.Crypto.NONE)
                builder.add_file(INTERNAL_DIR, "vehicleinfo.pabgb", new_body)
                if pabgh:
                    builder.add_file(INTERNAL_DIR, "vehicleinfo.pabgh", self._pabgh_bytes)
                pamt_bytes = bytes(builder.finish())
                pamt_checksum = crimson_rs.parse_pamt_bytes(pamt_bytes)["checksum"]
                for f_name in os.listdir(build_dir):
                    shutil.copy2(os.path.join(build_dir, f_name),
                                 os.path.join(game_overlay, f_name))

            papgt_path = os.path.join(game, "meta", "0.papgt")
            if os.path.isfile(papgt_path):
                cur = crimson_rs.parse_papgt_file(papgt_path)
                cur["entries"] = [e for e in cur["entries"]
                                  if e.get("group_name") != overlay_group]
                cur = crimson_rs.add_papgt_entry(
                    cur, overlay_group, pamt_checksum,
                    is_optional=0, language=0x3FFF)
                crimson_rs.write_papgt_file(cur, papgt_path)

            self._status.setText(f"Deployed to {overlay_group}/")
            self.status_message.emit(f"Vehicle mods deployed to {overlay_group}/")
            QMessageBox.information(
                self, "Deployed",
                f"Deployed {len(self._modified_keys)} modified vehicle(s) "
                f"to overlay {overlay_group}/")
        except Exception as e:
            log.exception("Deploy failed")
            QMessageBox.critical(self, "Deploy Failed", str(e))

    def _restore(self) -> None:
        game = self._config.get("game_install_path", "")
        if not game:
            return
        overlay_group = f"{self._overlay_spin.value():04d}"
        grp_dir = os.path.join(game, overlay_group)
        if os.path.isdir(grp_dir):
            reply = QMessageBox.question(
                self, "Restore",
                f"Remove {overlay_group}/ overlay?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            try:
                shutil.rmtree(grp_dir)
                self._status.setText(f"Removed {overlay_group}/ overlay")
                self.status_message.emit(f"Vehicle overlay {overlay_group}/ removed")
            except Exception as e:
                QMessageBox.critical(self, "Restore Failed", str(e))
        else:
            self._status.setText(f"No {overlay_group}/ overlay found")

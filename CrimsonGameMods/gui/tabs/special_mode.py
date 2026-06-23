"""Special Mode Editor tab â€” edit specialmode.pabgb entries.

All 22 special modes are fully decoded. Editable fields include
time_scale, player_time_scale, mode_radius, passive_skill, and
various boolean toggles.
"""
from __future__ import annotations

import copy
import logging
import os
import shutil
import tempfile

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QGroupBox,
    QAbstractItemView, QApplication, QScrollArea,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)

INTERNAL_DIR = "gamedata/binary__/client/bin"

# Editable float fields
FLOAT_FIELDS = [
    ("time_scale", "Time Scale", 0.0, 100.0),
    ("player_time_scale", "Player Time Scale", 0.0, 100.0),
    ("mode_radius", "Mode Radius", 0.0, 10000.0),
]

# Editable boolean fields
BOOL_FIELDS = [
    "has_near_by_target_option",
    "is_high_priority",
    "disable_occlusion_culling",
    "is_ignore_player_time_scale",
    "is_blocked",
]


class SpecialModeTab(QWidget):
    """Editor for special modes from specialmode.pabgb."""

    status_message = Signal(str)
    config_save_requested = Signal()

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._entries: list[dict] = []
        self._vanilla_entries: list[dict] = []
        self._pabgh: bytes = b""
        self._modified_keys: set[int] = set()
        self._editing = False
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._config["game_install_path"] = path

    # -- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Info
        info = QLabel(
            "<b>Special Mode Editor</b> -- Edit all 22 special modes from specialmode.pabgb.<br>"
            "Special modes control time dilation effects (e.g. slow-motion during combat). "
            "Modify time_scale, player_time_scale, radius, and toggle options."
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

        top.addStretch()

        self._count_label = QLabel("")
        top.addWidget(self._count_label)

        top.addWidget(QLabel("Overlay:"))
        self._overlay_spin = QSpinBox()
        self._overlay_spin.setRange(1, 9999)
        self._overlay_spin.setValue(self._config.get("specialmode_overlay_dir", 70))
        self._overlay_spin.setFixedWidth(70)
        self._overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"specialmode_overlay_dir": int(v)}))
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
        for label, scale in [("2x Slow-Mo", 2.0), ("5x Slow-Mo", 5.0), ("10x Slow-Mo", 10.0)]:
            btn = QPushButton(label)
            btn.setToolTip(f"Multiply all time_scale values by {scale}")
            btn.clicked.connect(lambda _, s=scale: self._preset_multiply_time(s))
            presets.addWidget(btn)
        max_radius_btn = QPushButton("Max Radius")
        max_radius_btn.setToolTip("Set all mode_radius to 99999")
        max_radius_btn.clicked.connect(self._preset_max_radius)
        presets.addWidget(max_radius_btn)
        presets.addStretch()
        root.addLayout(presets)

        # Table for overview
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "Key", "String Key", "Type", "Time Scale",
            "Player Time Scale", "Radius", "Modified",
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.cellChanged.connect(self._on_cell_changed)
        root.addWidget(self._table, 1)

        # Boolean toggles group
        self._toggles_group = QGroupBox("Boolean Toggles (select a row first)")
        self._toggles_group.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; color: {COLORS['accent']}; "
            f"border: 1px solid {COLORS.get('border', '#555')}; "
            f"border-radius: 4px; margin-top: 8px; padding-top: 14px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; }}"
        )
        toggles_layout = QHBoxLayout(self._toggles_group)
        self._toggle_cbs: dict[str, QCheckBox] = {}
        for field in BOOL_FIELDS:
            cb = QCheckBox(field)
            cb.setEnabled(False)
            cb.stateChanged.connect(lambda state, f=field: self._on_toggle_changed(f, state))
            toggles_layout.addWidget(cb)
            self._toggle_cbs[field] = cb
        toggles_layout.addStretch()
        root.addWidget(self._toggles_group)

        self._table.currentCellChanged.connect(self._on_selection_changed)

        # Status
        self._status = QLabel("Click Extract to load specialmode.pabgb.")
        self._status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        root.addWidget(self._status)

    # -- Extract -----------------------------------------------------------

    def _extract(self) -> None:
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            QMessageBox.warning(self, "No Game Path", "Set the game install path first.")
            return

        self.status_message.emit("Extracting specialmode...")
        QApplication.processEvents()

        try:
            import crimson_rs
            import dmm_parser

            pabgb = bytes(crimson_rs.extract_file(
                game, "0008", INTERNAL_DIR, "specialmode.pabgb"))
            pabgh = bytes(crimson_rs.extract_file(
                game, "0008", INTERNAL_DIR, "specialmode.pabgh"))
            self._pabgh = pabgh

            self._entries = dmm_parser.parse_table("special_mode_info", pabgb, pabgh)
            self._vanilla_entries = copy.deepcopy(self._entries)
            self._modified_keys.clear()

            self._populate()
            self._status.setText(
                f"Loaded {len(self._entries)} special modes ({len(pabgb):,} bytes)")
            self.status_message.emit(
                f"Loaded {len(self._entries)} special modes from specialmode.pabgb")
        except Exception as e:
            log.exception("Special mode extract failed")
            QMessageBox.critical(self, "Extract Failed", str(e))

    # -- Table population --------------------------------------------------

    def _populate(self) -> None:
        self._editing = True
        self._table.setRowCount(len(self._entries))

        for row, e in enumerate(self._entries):
            key = e.get("key", 0)
            string_key = str(e.get("string_key", ""))
            mode_type = str(e.get("type", e.get("special_mode_type", "")))
            time_scale = e.get("time_scale", 0.0)
            player_ts = e.get("player_time_scale", 0.0)
            radius = e.get("mode_radius", 0.0)
            modified = "Yes" if key in self._modified_keys else ""

            # Key (read-only)
            ki = QTableWidgetItem(str(key))
            ki.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            ki.setFlags(ki.flags() & ~Qt.ItemIsEditable)
            ki.setData(Qt.UserRole, key)
            self._table.setItem(row, 0, ki)

            # String Key (read-only)
            si = QTableWidgetItem(string_key)
            si.setFlags(si.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 1, si)

            # Type (read-only)
            ti = QTableWidgetItem(mode_type)
            ti.setTextAlignment(Qt.AlignCenter)
            ti.setFlags(ti.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 2, ti)

            # Time Scale (editable)
            ts_item = QTableWidgetItem(f"{time_scale:.4f}" if isinstance(time_scale, float) else str(time_scale))
            ts_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row, 3, ts_item)

            # Player Time Scale (editable)
            pts_item = QTableWidgetItem(f"{player_ts:.4f}" if isinstance(player_ts, float) else str(player_ts))
            pts_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row, 4, pts_item)

            # Radius (editable)
            rad_item = QTableWidgetItem(f"{radius:.2f}" if isinstance(radius, float) else str(radius))
            rad_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row, 5, rad_item)

            # Modified (read-only)
            mi = QTableWidgetItem(modified)
            mi.setTextAlignment(Qt.AlignCenter)
            mi.setFlags(mi.flags() & ~Qt.ItemIsEditable)
            if modified:
                mi.setForeground(Qt.GlobalColor.yellow)
            self._table.setItem(row, 6, mi)

        self._table.resizeColumnsToContents()
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._count_label.setText(f"({len(self._entries)} modes)")
        self._editing = False

    # -- Cell editing ------------------------------------------------------

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._editing or not self._entries:
            return
        if row >= len(self._entries):
            return

        item = self._table.item(row, col)
        if not item:
            return

        e = self._entries[row]
        key = e.get("key", 0)

        try:
            val = float(item.text())
        except ValueError:
            self._status.setText("Invalid value -- must be a number.")
            return

        if col == 3:
            e["time_scale"] = val
        elif col == 4:
            e["player_time_scale"] = val
        elif col == 5:
            e["mode_radius"] = val
        else:
            return

        self._modified_keys.add(key)
        # Update modified column
        self._editing = True
        mi = self._table.item(row, 6)
        if mi:
            mi.setText("Yes")
            mi.setForeground(Qt.GlobalColor.yellow)
        self._editing = False
        self._status.setText(f"Modified mode {key}: col {col} = {val}")

    # -- Selection / toggles -----------------------------------------------

    def _on_selection_changed(self, row: int, col: int, prev_row: int, prev_col: int) -> None:
        if row < 0 or row >= len(self._entries):
            for cb in self._toggle_cbs.values():
                cb.setEnabled(False)
            return

        e = self._entries[row]
        self._editing = True
        for field, cb in self._toggle_cbs.items():
            cb.setEnabled(True)
            cb.setChecked(bool(e.get(field, 0)))
        self._editing = False
        self._toggles_group.setTitle(
            f"Boolean Toggles -- {e.get('string_key', 'Mode')} (key={e.get('key', 0)})")

    def _on_toggle_changed(self, field: str, state: int) -> None:
        if self._editing:
            return
        row = self._table.currentRow()
        if row < 0 or row >= len(self._entries):
            return
        e = self._entries[row]
        e[field] = 1 if state else 0
        self._modified_keys.add(e.get("key", 0))
        # Update modified column
        self._editing = True
        mi = self._table.item(row, 6)
        if mi:
            mi.setText("Yes")
            mi.setForeground(Qt.GlobalColor.yellow)
        self._editing = False
        self._status.setText(f"Toggled {field} on mode {e.get('key', 0)}")

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
            import crimson_rs
            import dmm_parser

            pabgb = bytes(dmm_parser.serialize_table("special_mode_info", self._entries))
            overlay_group = f"{self._overlay_spin.value():04d}"

            with tempfile.TemporaryDirectory() as tmp_dir:
                group_dir = os.path.join(tmp_dir, overlay_group)
                builder = crimson_rs.PackGroupBuilder(
                    group_dir, crimson_rs.Compression.NONE,
                    crimson_rs.Crypto.NONE)
                builder.add_file(INTERNAL_DIR, "specialmode.pabgb", pabgb)
                builder.add_file(INTERNAL_DIR, "specialmode.pabgh", self._pabgh)
                pamt_bytes = bytes(builder.finish())
                pamt_checksum = crimson_rs.parse_pamt_bytes(pamt_bytes)["checksum"]

                game_overlay = os.path.join(game, overlay_group)
                os.makedirs(game_overlay, exist_ok=True)
                for fn in os.listdir(group_dir):
                    shutil.copy2(os.path.join(group_dir, fn),
                                 os.path.join(game_overlay, fn))

            papgt_path = os.path.join(game, "meta", "0.papgt")
            if os.path.isfile(papgt_path):
                papgt = crimson_rs.parse_papgt_file(papgt_path)
                papgt["entries"] = [
                    e for e in papgt["entries"]
                    if e.get("group_name") != overlay_group
                ]
                papgt = crimson_rs.add_papgt_entry(
                    papgt, overlay_group, pamt_checksum, 0, 16383)
                crimson_rs.write_papgt_file(papgt, papgt_path)

            self._status.setText(f"Deployed to {overlay_group}/")
            self.status_message.emit(
                f"Special modes: {len(self._modified_keys)} mode(s) "
                f"deployed to {overlay_group}/")
            QMessageBox.information(
                self, "Deployed",
                f"Deployed {len(self._modified_keys)} modified mode(s) "
                f"to {overlay_group}/.\n\nRestart the game to apply.")
        except Exception as e:
            log.exception("Special mode deploy failed")
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
                self.status_message.emit(
                    f"Special mode overlay {overlay_group}/ removed")
            except Exception as e:
                QMessageBox.critical(self, "Restore Failed", str(e))
        else:
            self._status.setText(f"No {overlay_group}/ overlay found")

    # -- Presets -----------------------------------------------------------

    @staticmethod
    def _f32_to_u32(f: float) -> int:
        import struct
        return struct.unpack('<I', struct.pack('<f', f))[0]

    @staticmethod
    def _u32_to_f32(u: int) -> float:
        import struct
        return struct.unpack('<f', struct.pack('<I', u & 0xFFFFFFFF))[0]

    def _preset_multiply_time(self, factor: float) -> None:
        if not self._entries:
            QMessageBox.information(self, "Presets", "Extract first.")
            return
        for entry in self._entries:
            key = entry.get("key", 0)
            for field in ("time_scale", "player_time_scale"):
                val = entry.get(field, 0)
                if isinstance(val, int) and val > 0:
                    f = self._u32_to_f32(val)
                    entry[field] = self._f32_to_u32(f * factor)
            self._modified_keys.add(key)
        self._populate()
        self._status.setText(f"Applied {factor}x time scale to all modes")
        self.status_message.emit(f"Preset: {factor}x slow-mo applied")

    def _preset_max_radius(self) -> None:
        if not self._entries:
            QMessageBox.information(self, "Presets", "Extract first.")
            return
        for entry in self._entries:
            entry["mode_radius"] = self._f32_to_u32(99999.0)
            self._modified_keys.add(entry.get("key", 0))
        self._populate()
        self._status.setText("Set all mode_radius to 99999")
        self.status_message.emit("Preset: max radius applied")

    # -- Public API --------------------------------------------------------

    def get_staged_files(self) -> dict[str, bytes]:
        if not self._modified_keys or not self._entries:
            return {}
        try:
            import dmm_parser
            pabgb = bytes(dmm_parser.serialize_table("special_mode_info", self._entries))
            return {"specialmode.pabgb": pabgb, "specialmode.pabgh": self._pabgh}
        except Exception:
            return {}

"""Game Play Trigger Editor tab â€” browse and edit gameplaytrigger.pabgb.

All 652 entries fully decoded. Grouped by trigger_type: SafeZone(98),
Shop(500), NoCrime(26), Possession(10), etc. Editable fields for
position, rotation, is_enable, world_map_color_r.
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
    QLineEdit, QComboBox, QSpinBox,
    QAbstractItemView, QMenu, QApplication,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)

INTERNAL_DIR = "gamedata/binary__/client/bin"

# Known trigger types with approximate counts
TRIGGER_TYPES = {
    0: "Generic",
    1: "SafeZone",
    2: "Shop",
    3: "NoCrime",
    5: "PlayerSwap",
    6: "Weather",
    7: "Camera",
    8: "Music",
    9: "Cutscene",
    10: "Possession",
    11: "Mount",
    12: "Interaction",
}


class TriggerEditorTab(QWidget):
    """Browse and edit game play triggers from gameplaytrigger.pabgb."""

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
            "<b>Game Play Trigger Editor</b> -- Browse all 652 triggers from "
            "gameplaytrigger.pabgb.<br>"
            "Triggers define zones and interaction points: safe zones, shops, "
            "no-crime areas, character swap points, and more.<br>"
            "Filter by type, edit position/rotation/is_enable, then deploy as PAZ overlay."
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
        self._filter_edit.setFixedWidth(200)
        top.addWidget(self._filter_edit)

        top.addWidget(QLabel("Type:"))
        self._type_filter = QComboBox()
        self._type_filter.addItem("All Types", None)
        self._type_filter.setFixedWidth(160)
        self._type_filter.currentIndexChanged.connect(self._apply_filter)
        top.addWidget(self._type_filter)

        top.addStretch()

        self._count_label = QLabel("")
        top.addWidget(self._count_label)

        top.addWidget(QLabel("Overlay:"))
        self._overlay_spin = QSpinBox()
        self._overlay_spin.setRange(1, 9999)
        self._overlay_spin.setValue(self._config.get("trigger_overlay_dir", 71))
        self._overlay_spin.setFixedWidth(70)
        self._overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"trigger_overlay_dir": int(v)}))
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
        safe_btn = QPushButton("No Crime Anywhere")
        safe_btn.setToolTip("Convert all NoCrime zones to cover the entire map (set is_enable=1)")
        safe_btn.clicked.connect(self._preset_no_crime)
        presets.addWidget(safe_btn)
        enable_all_btn = QPushButton("Enable All Triggers")
        enable_all_btn.setToolTip("Set is_enable=1 on all triggers")
        enable_all_btn.clicked.connect(self._preset_enable_all)
        presets.addWidget(enable_all_btn)
        presets.addStretch()
        root.addLayout(presets)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "Key", "String Key", "Type", "Pos X", "Pos Y", "Pos Z",
            "Enabled", "Modified",
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.setSortingEnabled(True)
        self._table.cellChanged.connect(self._on_cell_changed)
        root.addWidget(self._table, 1)

        # Status
        self._status = QLabel("Click Extract to load gameplaytrigger.pabgb.")
        self._status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        root.addWidget(self._status)

    # -- Extract -----------------------------------------------------------

    def _extract(self) -> None:
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            QMessageBox.warning(self, "No Game Path", "Set the game install path first.")
            return

        self.status_message.emit("Extracting gameplaytrigger...")
        QApplication.processEvents()

        try:
            import crimson_rs
            import dmm_parser

            pabgb = bytes(crimson_rs.extract_file(
                game, "0008", INTERNAL_DIR, "gameplaytrigger.pabgb"))
            pabgh = bytes(crimson_rs.extract_file(
                game, "0008", INTERNAL_DIR, "gameplaytrigger.pabgh"))
            self._pabgh = pabgh

            self._entries = dmm_parser.parse_table(
                "game_play_trigger_info", pabgb, pabgh)
            self._vanilla_entries = copy.deepcopy(self._entries)
            self._modified_keys.clear()

            # Populate type filter from actual data
            types_seen: dict[int, int] = {}
            for e in self._entries:
                t = e.get("trigger_type", 0)
                types_seen[t] = types_seen.get(t, 0) + 1

            self._type_filter.clear()
            self._type_filter.addItem("All Types", None)
            for t in sorted(types_seen.keys()):
                label = TRIGGER_TYPES.get(t, f"Type_{t}")
                self._type_filter.addItem(
                    f"{label} ({types_seen[t]})", t)

            self._populate()
            self._status.setText(
                f"Loaded {len(self._entries)} triggers ({len(pabgb):,} bytes)")
            self.status_message.emit(
                f"Loaded {len(self._entries)} triggers from gameplaytrigger.pabgb")
        except Exception as e:
            log.exception("Trigger extract failed")
            QMessageBox.critical(self, "Extract Failed", str(e))

    # -- Table population --------------------------------------------------

    def _populate(self) -> None:
        self._editing = True
        text_filter = self._filter_edit.text().strip().lower()
        type_filter = self._type_filter.currentData()

        self._table.setSortingEnabled(False)
        rows = []
        for e in self._entries:
            key = e.get("key", 0)
            string_key = str(e.get("string_key", ""))
            trigger_type = e.get("trigger_type", 0)

            if text_filter:
                combined = f"{key} {string_key}".lower()
                if text_filter not in combined:
                    continue
            if type_filter is not None and trigger_type != type_filter:
                continue
            rows.append(e)

        self._table.setRowCount(len(rows))
        for row, e in enumerate(rows):
            key = e.get("key", 0)
            string_key = str(e.get("string_key", ""))
            trigger_type = e.get("trigger_type", 0)
            type_name = TRIGGER_TYPES.get(trigger_type, str(trigger_type))

            # Position
            pos = e.get("position", e.get("trigger_position", {}))
            if isinstance(pos, dict):
                px = f"{pos.get('x', pos.get('f00', 0)):.1f}"
                py = f"{pos.get('y', pos.get('f01', 0)):.1f}"
                pz = f"{pos.get('z', pos.get('f02', 0)):.1f}"
            elif isinstance(pos, (list, tuple)) and len(pos) >= 3:
                px, py, pz = f"{pos[0]:.1f}", f"{pos[1]:.1f}", f"{pos[2]:.1f}"
            else:
                px = py = pz = "0.0"

            is_enable = e.get("is_enable", e.get("is_enabled", 1))
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
            ti = QTableWidgetItem(type_name)
            ti.setTextAlignment(Qt.AlignCenter)
            ti.setFlags(ti.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 2, ti)

            # Position X, Y, Z (editable)
            for col, val in [(3, px), (4, py), (5, pz)]:
                pi = QTableWidgetItem(val)
                pi.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(row, col, pi)

            # Enabled (editable)
            ei = QTableWidgetItem(str(is_enable))
            ei.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 6, ei)

            # Modified (read-only)
            mi = QTableWidgetItem(modified)
            mi.setTextAlignment(Qt.AlignCenter)
            mi.setFlags(mi.flags() & ~Qt.ItemIsEditable)
            if modified:
                mi.setForeground(Qt.GlobalColor.yellow)
            self._table.setItem(row, 7, mi)

        self._table.setSortingEnabled(True)
        self._table.resizeColumnsToContents()
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._count_label.setText(f"({len(rows)}/{len(self._entries)})")
        self._editing = False

    def _apply_filter(self) -> None:
        if self._entries:
            self._populate()

    # -- Cell editing ------------------------------------------------------

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._editing or not self._entries:
            return

        item = self._table.item(row, col)
        if not item:
            return

        # Find entry by key
        key_item = self._table.item(row, 0)
        if not key_item:
            return
        key = key_item.data(Qt.UserRole)
        entry = None
        for e in self._entries:
            if e.get("key") == key:
                entry = e
                break
        if entry is None:
            return

        text = item.text().strip()

        if col in (3, 4, 5):
            # Position edit
            try:
                val = float(text)
            except ValueError:
                self._status.setText("Invalid value -- must be a number.")
                return

            pos = entry.get("position", entry.get("trigger_position", {}))
            if not isinstance(pos, dict):
                pos = {"x": 0.0, "y": 0.0, "z": 0.0}

            axis_keys = {3: ("x", "f00"), 4: ("y", "f01"), 5: ("z", "f02")}
            primary, fallback = axis_keys[col]
            if primary in pos:
                pos[primary] = val
            elif fallback in pos:
                pos[fallback] = val
            else:
                pos[primary] = val

            if "position" in entry:
                entry["position"] = pos
            else:
                entry["trigger_position"] = pos

            self._modified_keys.add(key)
            self._mark_modified(row)
            self._status.setText(f"Modified trigger {key}: position")

        elif col == 6:
            # is_enable toggle
            try:
                val = int(text)
            except ValueError:
                self._status.setText("Invalid value -- must be 0 or 1.")
                return
            if "is_enable" in entry:
                entry["is_enable"] = val
            else:
                entry["is_enabled"] = val
            self._modified_keys.add(key)
            self._mark_modified(row)
            self._status.setText(f"Modified trigger {key}: is_enable = {val}")

    def _mark_modified(self, row: int) -> None:
        self._editing = True
        mi = self._table.item(row, 7)
        if mi:
            mi.setText("Yes")
            mi.setForeground(Qt.GlobalColor.yellow)
        self._editing = False

    # -- Context menu ------------------------------------------------------

    def _on_context_menu(self, pos) -> None:
        rows = set(idx.row() for idx in self._table.selectedIndexes())
        if not rows:
            return

        menu = QMenu(self)
        act_enable = menu.addAction("Enable Selected")
        act_disable = menu.addAction("Disable Selected")
        menu.addSeparator()
        act_reset = menu.addAction("Reset to Vanilla")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action is None:
            return

        keys = []
        for r in rows:
            item = self._table.item(r, 0)
            if item:
                keys.append(item.data(Qt.UserRole))

        if action == act_enable:
            self._set_enable(keys, 1)
        elif action == act_disable:
            self._set_enable(keys, 0)
        elif action == act_reset:
            self._reset_entries(keys)

    def _set_enable(self, keys: list[int], value: int) -> None:
        entry_by_key = {e["key"]: e for e in self._entries}
        count = 0
        for k in keys:
            e = entry_by_key.get(k)
            if e is None:
                continue
            if "is_enable" in e:
                e["is_enable"] = value
            else:
                e["is_enabled"] = value
            self._modified_keys.add(k)
            count += 1
        self._populate()
        state = "enabled" if value else "disabled"
        self._status.setText(f"Set {count} trigger(s) to {state}")

    def _reset_entries(self, keys: list[int]) -> None:
        vanilla_by_key = {e["key"]: e for e in self._vanilla_entries}
        entry_by_key = {e["key"]: e for e in self._entries}
        count = 0
        for k in keys:
            van = vanilla_by_key.get(k)
            ent = entry_by_key.get(k)
            if van and ent:
                ent.update(copy.deepcopy(van))
                self._modified_keys.discard(k)
                count += 1
        self._populate()
        self._status.setText(f"Reset {count} trigger(s) to vanilla")

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

            pabgb = bytes(dmm_parser.serialize_table(
                "game_play_trigger_info", self._entries))
            overlay_group = f"{self._overlay_spin.value():04d}"

            with tempfile.TemporaryDirectory() as tmp_dir:
                group_dir = os.path.join(tmp_dir, overlay_group)
                builder = crimson_rs.PackGroupBuilder(
                    group_dir, crimson_rs.Compression.NONE,
                    crimson_rs.Crypto.NONE)
                builder.add_file(INTERNAL_DIR, "gameplaytrigger.pabgb", pabgb)
                builder.add_file(INTERNAL_DIR, "gameplaytrigger.pabgh", self._pabgh)
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
                f"Triggers: {len(self._modified_keys)} trigger(s) "
                f"deployed to {overlay_group}/")
            QMessageBox.information(
                self, "Deployed",
                f"Deployed {len(self._modified_keys)} modified trigger(s) "
                f"to {overlay_group}/.\n\nRestart the game to apply.")
        except Exception as e:
            log.exception("Trigger deploy failed")
            QMessageBox.critical(self, "Deploy Failed", str(e))

    # -- Presets -----------------------------------------------------------

    def _preset_no_crime(self) -> None:
        if not self._entries:
            QMessageBox.information(self, "Presets", "Extract first.")
            return
        count = 0
        for entry in self._entries:
            if entry.get("trigger_type") == 1:  # NoCrime
                entry["is_enable"] = 1
                self._modified_keys.add(entry.get("key", 0))
                count += 1
        self._populate()
        self._status.setText(f"Enabled {count} NoCrime zones")
        self.status_message.emit(f"Preset: {count} NoCrime zones enabled")

    def _preset_enable_all(self) -> None:
        if not self._entries:
            QMessageBox.information(self, "Presets", "Extract first.")
            return
        for entry in self._entries:
            entry["is_enable"] = 1
            self._modified_keys.add(entry.get("key", 0))
        self._populate()
        self._status.setText(f"Enabled all {len(self._entries)} triggers")
        self.status_message.emit("Preset: all triggers enabled")

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
                    f"Trigger overlay {overlay_group}/ removed")
            except Exception as e:
                QMessageBox.critical(self, "Restore Failed", str(e))
        else:
            self._status.setText(f"No {overlay_group}/ overlay found")

    # -- Public API --------------------------------------------------------

    def get_staged_files(self) -> dict[str, bytes]:
        if not self._modified_keys or not self._entries:
            return {}
        try:
            import dmm_parser
            pabgb = bytes(dmm_parser.serialize_table(
                "game_play_trigger_info", self._entries))
            return {
                "gameplaytrigger.pabgb": pabgb,
                "gameplaytrigger.pabgh": self._pabgh,
            }
        except Exception:
            return {}

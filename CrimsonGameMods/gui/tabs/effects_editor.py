"""Visual Effects Editor tab — browse and swap effects from effectinfo.pabgb.

Shows all 2115 visual effect entries with their parameters. Allows swapping
effect keys between items and modifying visual parameters.
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
    QLineEdit, QSpinBox, QSplitter,
    QAbstractItemView, QMenu, QApplication, QGroupBox,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)

INTERNAL_DIR = "gamedata/binary__/client/bin"


class EffectsEditorTab(QWidget):
    """Browse and edit visual effects from effectinfo.pabgb."""

    status_message = Signal(str)
    config_save_requested = Signal()

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._entries: list[dict] = []
        self._vanilla_entries: list[dict] = []
        self._pabgh: bytes = b""
        self._modified_keys: set[int] = set()
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._config["game_install_path"] = path

    # -- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Info
        info = QLabel(
            "<b>Visual Effects Editor</b> -- Browse all effects from effectinfo.pabgb.<br>"
            "View effect parameters, swap effect keys between items, or modify "
            "visual settings. Right-click to copy effect key for use in other mods."
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

        top.addWidget(QLabel("Overlay:"))
        self._overlay_spin = QSpinBox()
        self._overlay_spin.setRange(1, 9999)
        self._overlay_spin.setValue(self._config.get("effects_overlay_dir", 69))
        self._overlay_spin.setFixedWidth(70)
        self._overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"effects_overlay_dir": int(v)}))
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
        block_all_btn = QPushButton("Block All Effects")
        block_all_btn.setToolTip("Set is_blocked=1 on all effects (disable all VFX)")
        block_all_btn.clicked.connect(lambda: self._preset_set_blocked(1))
        presets.addWidget(block_all_btn)
        unblock_all_btn = QPushButton("Unblock All Effects")
        unblock_all_btn.setToolTip("Set is_blocked=0 on all effects (enable all VFX)")
        unblock_all_btn.clicked.connect(lambda: self._preset_set_blocked(0))
        presets.addWidget(unblock_all_btn)
        presets.addStretch()
        root.addLayout(presets)

        # Presets row 2 — per-entry scale/visual mods
        presets2 = QHBoxLayout()
        presets2.addWidget(QLabel("All:"))
        for label, factor in [("Scale All 2x", 2.0), ("Scale All 5x", 5.0), ("Scale All 10x", 10.0)]:
            btn = QPushButton(label)
            btn.setToolTip(f"Multiply ALL effect vectors by {factor}")
            btn.clicked.connect(lambda _, f=factor: self._preset_scale_all(f))
            presets2.addWidget(btn)
        presets2.addWidget(QLabel(" Selected:"))
        for label, factor in [("2x", 2.0), ("5x", 5.0), ("0.5x", 0.5)]:
            btn = QPushButton(label)
            btn.setToolTip(f"Scale selected effect vectors by {factor}")
            btn.clicked.connect(lambda _, f=factor: self._preset_scale_selected(f))
            presets2.addWidget(btn)
        no_mesh_btn = QPushButton("Remove Mesh FX")
        no_mesh_btn.setToolTip("Clear mesh_effect_data on selected effect")
        no_mesh_btn.clicked.connect(self._preset_remove_mesh)
        presets2.addWidget(no_mesh_btn)
        presets2.addStretch()
        root.addLayout(presets2)

        # Splitter: table + detail panel
        splitter = QSplitter(Qt.Horizontal)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "Key", "String Key", "Blocked", "Effect Count", "Modified",
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.setSortingEnabled(True)
        self._table.currentCellChanged.connect(self._on_selection_changed)
        splitter.addWidget(self._table)

        # Detail panel
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(8, 8, 8, 8)

        detail_group = QGroupBox("Effect Details")
        detail_group.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; color: {COLORS['accent']}; "
            f"border: 1px solid {COLORS.get('border', '#555')}; "
            f"border-radius: 4px; margin-top: 8px; padding-top: 14px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; }}"
        )
        self._detail_layout = QVBoxLayout(detail_group)

        self._detail_key = QLabel("Key: --")
        self._detail_name = QLabel("Name: --")
        self._detail_effects = QLabel("Effects: --")
        self._detail_mesh = QLabel("Mesh Effects: --")
        self._detail_params = QLabel("Parameters: --")
        self._detail_params.setWordWrap(True)

        for lbl in (self._detail_key, self._detail_name, self._detail_effects,
                    self._detail_mesh, self._detail_params):
            lbl.setStyleSheet(f"color: {COLORS['text']}; padding: 2px;")
            self._detail_layout.addWidget(lbl)

        self._detail_layout.addStretch()
        detail_layout.addWidget(detail_group)
        splitter.addWidget(detail_widget)
        splitter.setSizes([600, 300])

        root.addWidget(splitter, 1)

        # Status
        self._status = QLabel("Click Extract to load effectinfo.pabgb.")
        self._status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        root.addWidget(self._status)

    # -- Extract -----------------------------------------------------------

    def _extract(self) -> None:
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            QMessageBox.warning(self, "No Game Path", "Set the game install path first.")
            return

        self.status_message.emit("Extracting effectinfo...")
        QApplication.processEvents()

        try:
            import crimson_rs
            import dmm_parser

            pabgb = bytes(crimson_rs.extract_file(
                game, "0008", INTERNAL_DIR, "effectinfo.pabgb"))
            pabgh = bytes(crimson_rs.extract_file(
                game, "0008", INTERNAL_DIR, "effectinfo.pabgh"))
            self._pabgh = pabgh

            self._entries = dmm_parser.parse_table("effect_info", pabgb, pabgh)
            self._vanilla_entries = copy.deepcopy(self._entries)
            self._modified_keys.clear()

            self._populate()
            self._status.setText(
                f"Loaded {len(self._entries)} effects ({len(pabgb):,} bytes)")
            self.status_message.emit(
                f"Loaded {len(self._entries)} effects from effectinfo.pabgb")
        except Exception as e:
            log.exception("Effects extract failed")
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
            # Count effect sub-entries
            effect_list = e.get("effect_list", e.get("effects", []))
            effect_count = len(effect_list) if isinstance(effect_list, list) else 0
            modified = "Yes" if key in self._modified_keys else ""

            items_data = [
                (str(key), Qt.AlignRight | Qt.AlignVCenter),
                (string_key, Qt.AlignLeft | Qt.AlignVCenter),
                (str(is_blocked), Qt.AlignCenter),
                (str(effect_count), Qt.AlignCenter),
                (modified, Qt.AlignCenter),
            ]
            for col, (text, align) in enumerate(items_data):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 0:
                    item.setData(Qt.UserRole, key)
                if col == 4 and modified:
                    item.setForeground(Qt.GlobalColor.yellow)
                self._table.setItem(row, col, item)

        self._table.setSortingEnabled(True)
        self._count_label.setText(f"({len(rows)}/{len(self._entries)})")

    def _apply_filter(self) -> None:
        if self._entries:
            self._populate()

    # -- Detail panel ------------------------------------------------------

    def _on_selection_changed(self, row: int, col: int, prev_row: int, prev_col: int) -> None:
        if row < 0:
            return
        item = self._table.item(row, 0)
        if not item:
            return
        key = item.data(Qt.UserRole)
        entry = None
        for e in self._entries:
            if e.get("key") == key:
                entry = e
                break
        if entry is None:
            return

        self._detail_key.setText(f"Key: {entry.get('key', 0)}")
        self._detail_name.setText(f"Name: {entry.get('string_key', '')}")

        effect_list = entry.get("effect_list", entry.get("effects", []))
        effect_count = len(effect_list) if isinstance(effect_list, list) else 0
        self._detail_effects.setText(f"Effects: {effect_count}")

        mesh_list = entry.get("mesh_effect_list", [])
        mesh_count = len(mesh_list) if isinstance(mesh_list, list) else 0
        self._detail_mesh.setText(f"Mesh Effects: {mesh_count}")

        # Show a few key parameters
        params = []
        for field in ("is_blocked", "effect_type", "priority",
                      "duration", "loop_count"):
            if field in entry:
                params.append(f"{field}: {entry[field]}")
        self._detail_params.setText(
            "Parameters:\n" + "\n".join(params) if params else "Parameters: (none)")

    # -- Context menu ------------------------------------------------------

    def _on_context_menu(self, pos) -> None:
        rows = set(idx.row() for idx in self._table.selectedIndexes())
        if not rows:
            return

        menu = QMenu(self)
        act_copy_key = menu.addAction("Copy Effect Key")
        act_block = menu.addAction("Toggle is_blocked")
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

        if action == act_copy_key:
            from PySide6.QtWidgets import QApplication as QApp
            text = ", ".join(str(k) for k in keys)
            QApp.clipboard().setText(text)
            self._status.setText(f"Copied: {text}")
        elif action == act_block:
            self._toggle_blocked(keys)
        elif action == act_reset:
            self._reset_entries(keys)

    def _toggle_blocked(self, keys: list[int]) -> None:
        entry_by_key = {e["key"]: e for e in self._entries}
        count = 0
        for k in keys:
            e = entry_by_key.get(k)
            if e is None:
                continue
            current = e.get("is_blocked", 0)
            e["is_blocked"] = 0 if current else 1
            self._modified_keys.add(k)
            count += 1
        self._populate()
        self._status.setText(f"Toggled is_blocked on {count} effect(s)")

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
        self._status.setText(f"Reset {count} effect(s) to vanilla")

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

            pabgb = bytes(dmm_parser.serialize_table("effect_info", self._entries))
            overlay_group = f"{self._overlay_spin.value():04d}"

            with tempfile.TemporaryDirectory() as tmp_dir:
                group_dir = os.path.join(tmp_dir, overlay_group)
                builder = crimson_rs.PackGroupBuilder(
                    group_dir, crimson_rs.Compression.NONE,
                    crimson_rs.Crypto.NONE)
                builder.add_file(INTERNAL_DIR, "effectinfo.pabgb", pabgb)
                builder.add_file(INTERNAL_DIR, "effectinfo.pabgh", self._pabgh)
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
                f"Effects: {len(self._modified_keys)} effect(s) "
                f"deployed to {overlay_group}/")
            QMessageBox.information(
                self, "Deployed",
                f"Deployed {len(self._modified_keys)} modified effect(s) "
                f"to {overlay_group}/.\n\nRestart the game to apply.")
        except Exception as e:
            log.exception("Effects deploy failed")
            QMessageBox.critical(self, "Deploy Failed", str(e))

    # -- Presets -----------------------------------------------------------

    def _get_selected_entry(self):
        row = self._table.currentRow()
        if row < 0 or not self._entries:
            return None
        key_item = self._table.item(row, 0)
        if not key_item:
            return None
        key = int(key_item.text())
        for e in self._entries:
            if e.get("key") == key:
                return e
        return None

    def _scale_vec3_fields(self, obj: dict, factor: float) -> int:
        """Recursively multiply float-array fields (vec3/vec4) by factor.
        Only scales arrays that contain at least one float — skips pure u32 arrays."""
        count = 0
        for k, v in obj.items():
            if isinstance(v, list) and len(v) in (3, 4) and all(isinstance(x, (int, float)) for x in v):
                if any(isinstance(x, float) for x in v):
                    obj[k] = [x * factor for x in v]
                    count += 1
            elif isinstance(v, dict):
                count += self._scale_vec3_fields(v, factor)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        count += self._scale_vec3_fields(item, factor)
        return count

    def _preset_scale_all(self, factor: float) -> None:
        if not self._entries:
            QMessageBox.information(self, "Presets", "Extract first.")
            return
        total = 0
        for entry in self._entries:
            count = self._scale_vec3_fields(entry, factor)
            total += count
            self._modified_keys.add(entry.get("key", 0))
        self._populate()
        self._status.setText(f"Scaled {total} vectors across {len(self._entries)} effects by {factor}x")
        self.status_message.emit(f"Preset: all effects scaled {factor}x ({total} vectors)")

    def _preset_scale_selected(self, factor: float) -> None:
        entry = self._get_selected_entry()
        if entry is None:
            QMessageBox.information(self, "Presets", "Select an effect row first.")
            return
        count = self._scale_vec3_fields(entry, factor)
        self._modified_keys.add(entry.get("key", 0))
        self._populate()
        self._on_row_selected(self._table.currentRow(), 0, 0, 0)
        self._status.setText(f"Scaled {count} vectors by {factor}x on effect {entry.get('key')}")
        self.status_message.emit(f"Effect {entry.get('key')}: {count} vectors scaled {factor}x")

    def _preset_remove_mesh(self) -> None:
        entry = self._get_selected_entry()
        if entry is None:
            QMessageBox.information(self, "Presets", "Select an effect row first.")
            return
        if "mesh_effect_data" in entry:
            removed = len(entry.get("mesh_effect_data", []))
            entry["mesh_effect_data"] = []
            self._modified_keys.add(entry.get("key", 0))
            self._populate()
            self._status.setText(f"Removed {removed} mesh effects from effect {entry.get('key')}")
            self.status_message.emit(f"Effect {entry.get('key')}: {removed} mesh effects removed")

    def _preset_set_blocked(self, value: int) -> None:
        if not self._entries:
            QMessageBox.information(self, "Presets", "Extract first.")
            return
        for entry in self._entries:
            entry["is_blocked"] = value
            self._modified_keys.add(entry.get("key", 0))
        self._populate()
        state = "blocked" if value else "unblocked"
        self._status.setText(f"Set all {len(self._entries)} effects to {state}")
        self.status_message.emit(f"Preset: all effects {state}")

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
                    f"Effects overlay {overlay_group}/ removed")
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
            pabgb = bytes(dmm_parser.serialize_table("effect_info", self._entries))
            return {"effectinfo.pabgb": pabgb, "effectinfo.pabgh": self._pabgh}
        except Exception:
            return {}

"""Condition Bypass tab — browse and modify conditioninfo.pabgb conditions.

Conditions control quest gates, dialog triggers, buff rules, and most
game logic. This tab lets you set any condition to Always True (CheckNone)
or Always False, bypassing arbitrary game restrictions.
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
    QLineEdit, QComboBox, QGroupBox, QSpinBox,
    QAbstractItemView, QMenu, QApplication,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)

INTERNAL_DIR = "gamedata/binary__/client/bin"


class ConditionBypassTab(QWidget):
    """Browse and modify game conditions from conditioninfo.pabgb."""

    status_message = Signal(str)
    config_save_requested = Signal()

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._entries: list[dict] = []
        self._vanilla_entries: list[dict] = []
        self._pabgb: bytes = b""
        self._pabgh: bytes = b""
        self._modified_keys: set[int] = set()
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._config["game_install_path"] = path

    # -- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Info banner
        info = QLabel(
            "<b>Condition Bypass</b> -- Browse all game conditions from conditioninfo.pabgb.<br>"
            "Right-click a condition to set it to <b>Always True</b> (CheckNone) or "
            "<b>Always False</b>. Conditions gate quests, dialogs, buffs, and triggers."
        )
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['text']}; background-color: {COLORS['panel']}; "
            f"padding: 8px; border: 2px solid {COLORS['accent']}; border-radius: 6px;"
        )
        root.addWidget(info)

        # Top row: Extract + filter + overlay + deploy
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

        self._kind_filter = QComboBox()
        self._kind_filter.addItem("All Kinds", None)
        self._kind_filter.setFixedWidth(160)
        self._kind_filter.currentIndexChanged.connect(self._apply_filter)
        top.addWidget(self._kind_filter)

        top.addStretch()

        self._count_label = QLabel("")
        top.addWidget(self._count_label)

        top.addWidget(QLabel("Overlay:"))
        self._overlay_spin = QSpinBox()
        self._overlay_spin.setRange(1, 9999)
        self._overlay_spin.setValue(self._config.get("condition_overlay_dir", 73))
        self._overlay_spin.setFixedWidth(70)
        self._overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"condition_overlay_dir": int(v)}))
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
        quest_btn = QPushButton("Bypass All PlayingMission")
        quest_btn.setToolTip("Set all PlayingMission/PlayingQuest conditions to Always True")
        quest_btn.clicked.connect(lambda: self._preset_bypass_pattern("PlayingMission|PlayingQuest"))
        presets.addWidget(quest_btn)
        level_btn = QPushButton("Bypass All Level Checks")
        level_btn.setToolTip("Set all GetLevel conditions to Always True")
        level_btn.clicked.connect(lambda: self._preset_bypass_pattern("GetLevel"))
        presets.addWidget(level_btn)
        item_btn = QPushButton("Bypass All Item Checks")
        item_btn.setToolTip("Set all CheckHaveItem conditions to Always True")
        item_btn.clicked.connect(lambda: self._preset_bypass_pattern("CheckHaveItem"))
        presets.addWidget(item_btn)
        presets.addStretch()
        root.addLayout(presets)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "Key", "String Key", "Kind", "Modified", "Description",
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.setSortingEnabled(True)
        root.addWidget(self._table, 1)

        # Status
        self._status = QLabel("Click Extract to load conditioninfo.pabgb.")
        self._status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        root.addWidget(self._status)

    # -- Extract -----------------------------------------------------------

    def _extract(self) -> None:
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            QMessageBox.warning(self, "No Game Path", "Set the game install path first.")
            return

        self.status_message.emit("Extracting conditioninfo...")
        QApplication.processEvents()

        try:
            import crimson_rs
            import dmm_parser

            pabgb = bytes(crimson_rs.extract_file(
                game, "0008", INTERNAL_DIR, "conditioninfo.pabgb"))
            pabgh = bytes(crimson_rs.extract_file(
                game, "0008", INTERNAL_DIR, "conditioninfo.pabgh"))
            self._pabgb = pabgb
            self._pabgh = pabgh

            self._entries = dmm_parser.parse_table("condition_info", pabgb, pabgh)
            self._vanilla_entries = copy.deepcopy(self._entries)
            self._modified_keys.clear()

            # Populate kind filter
            kinds = set()
            for e in self._entries:
                kind = e.get("game_condition_kind", e.get("condition_kind", ""))
                if kind:
                    kinds.add(str(kind))
            self._kind_filter.clear()
            self._kind_filter.addItem("All Kinds", None)
            for k in sorted(kinds):
                self._kind_filter.addItem(str(k), k)

            self._populate()
            self._status.setText(
                f"Loaded {len(self._entries)} conditions ({len(pabgb):,} bytes)")
            self.status_message.emit(
                f"Loaded {len(self._entries)} conditions from conditioninfo.pabgb")
        except Exception as e:
            log.exception("Condition extract failed")
            QMessageBox.critical(self, "Extract Failed", str(e))

    # -- Table population --------------------------------------------------

    def _populate(self) -> None:
        text_filter = self._filter_edit.text().strip().lower()
        kind_filter = self._kind_filter.currentData()

        self._table.setSortingEnabled(False)
        rows = []
        for e in self._entries:
            key = e.get("key", 0)
            string_key = str(e.get("string_key", ""))
            kind = str(e.get("game_condition_kind", e.get("condition_kind", "")))

            if text_filter:
                combined = f"{key} {string_key}".lower()
                if text_filter not in combined:
                    continue
            if kind_filter is not None and kind != kind_filter:
                continue
            rows.append(e)

        self._table.setRowCount(len(rows))
        for row, e in enumerate(rows):
            key = e.get("key", 0)
            string_key = str(e.get("string_key", ""))
            kind = str(e.get("game_condition_kind", e.get("condition_kind", "")))
            modified = "Yes" if key in self._modified_keys else ""
            desc = str(e.get("original_string", e.get("description", "")))

            items = [
                (str(key), Qt.AlignRight | Qt.AlignVCenter),
                (string_key, Qt.AlignLeft | Qt.AlignVCenter),
                (kind, Qt.AlignCenter),
                (modified, Qt.AlignCenter),
                (desc, Qt.AlignLeft | Qt.AlignVCenter),
            ]
            for col, (text, align) in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 0:
                    item.setData(Qt.UserRole, key)
                if col == 3 and modified:
                    item.setForeground(Qt.GlobalColor.yellow)
                self._table.setItem(row, col, item)

        self._table.setSortingEnabled(True)
        self._count_label.setText(f"({len(rows)}/{len(self._entries)})")

    def _apply_filter(self) -> None:
        if self._entries:
            self._populate()

    # -- Context menu ------------------------------------------------------

    def _on_context_menu(self, pos) -> None:
        rows = set(idx.row() for idx in self._table.selectedIndexes())
        if not rows:
            return

        menu = QMenu(self)
        act_true = menu.addAction("Set to Always True (CheckNone)")
        act_false = menu.addAction("Set to Always False")
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

        if action == act_true:
            self._set_conditions(keys, always_true=True)
        elif action == act_false:
            self._set_conditions(keys, always_true=False)
        elif action == act_reset:
            self._reset_conditions(keys)

    def _set_conditions(self, keys: list[int], always_true: bool) -> None:
        """Set selected conditions to always true or always false."""
        entry_by_key = {e["key"]: e for e in self._entries}
        count = 0
        for k in keys:
            e = entry_by_key.get(k)
            if e is None:
                continue
            # Overwrite game_condition to a simple pass/fail node
            if always_true:
                e["game_condition"] = {"type": "CheckNone"}
                e["game_condition_kind"] = "CheckNone"
            else:
                e["game_condition"] = {"type": "CheckFalse"}
                e["game_condition_kind"] = "CheckFalse"
            self._modified_keys.add(k)
            count += 1

        self._populate()
        mode = "Always True" if always_true else "Always False"
        self._status.setText(f"Set {count} condition(s) to {mode}")
        self.status_message.emit(f"Modified {count} conditions -> {mode}")

    def _reset_conditions(self, keys: list[int]) -> None:
        """Reset selected conditions to vanilla values."""
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
        self._status.setText(f"Reset {count} condition(s) to vanilla")

    # -- Presets -----------------------------------------------------------

    def _preset_bypass_pattern(self, pattern: str) -> None:
        if not self._entries:
            QMessageBox.information(self, "Presets", "Extract first.")
            return
        import re
        rx = re.compile(pattern, re.IGNORECASE)
        count = 0
        for entry in self._entries:
            desc = entry.get("original_string", "")
            if rx.search(desc):
                gc = entry.get("game_condition", {})
                if gc.get("kind") == "decoded":
                    entry["game_condition"] = {
                        "kind": "decoded",
                        "tree": {"case": "ConditionData", "data": {
                            "base": {"tag": 2},
                            "variant": {"type": "ConditionData_CheckNone"},
                            "option_block": {"option_present": 0, "option_data": None},
                        }},
                        "tail_a": 0, "tail_b": 0, "tail_c": 0,
                    }
                    self._modified_keys.add(entry.get("key", 0))
                    count += 1
        self._populate()
        self._status.setText(f"Bypassed {count} conditions matching '{pattern}'")
        self.status_message.emit(f"Preset: {count} conditions bypassed")

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

            # Build intents from modified entries
            intents = []
            for entry in self._entries:
                key = entry.get("key", 0)
                if key in self._modified_keys:
                    intents.append({
                        "key": key,
                        "field": "game_condition",
                        "new": entry["game_condition"],
                    })

            result = dmm_parser.apply_intents(
                "condition_info", self._pabgb, self._pabgh, intents)
            pabgb = bytes(result["body"])
            pabgh = bytes(result["pabgh"])

            overlay_group = f"{self._overlay_spin.value():04d}"

            with tempfile.TemporaryDirectory() as tmp_dir:
                group_dir = os.path.join(tmp_dir, overlay_group)
                builder = crimson_rs.PackGroupBuilder(
                    group_dir, crimson_rs.Compression.NONE,
                    crimson_rs.Crypto.NONE)
                builder.add_file(INTERNAL_DIR, "conditioninfo.pabgb", pabgb)
                builder.add_file(INTERNAL_DIR, "conditioninfo.pabgh", pabgh)
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
                f"Condition bypass: {len(self._modified_keys)} conditions "
                f"deployed to {overlay_group}/")
            QMessageBox.information(
                self, "Deployed",
                f"Deployed {len(self._modified_keys)} modified condition(s) "
                f"to {overlay_group}/.\n\nRestart the game to apply.")
        except Exception as e:
            log.exception("Condition deploy failed")
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
                f"Remove {overlay_group}/ overlay and restore vanilla conditions?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            try:
                shutil.rmtree(grp_dir)
                self._status.setText(f"Removed {overlay_group}/ overlay")
                self.status_message.emit(f"Condition overlay {overlay_group}/ removed")
            except Exception as e:
                QMessageBox.critical(self, "Restore Failed", str(e))
        else:
            self._status.setText(f"No {overlay_group}/ overlay found")

    # -- Public API --------------------------------------------------------

    def get_staged_files(self) -> dict[str, bytes]:
        """Return modified pabgb if there are pending changes."""
        if not self._modified_keys or not self._entries:
            return {}
        try:
            import dmm_parser
            pabgb = bytes(dmm_parser.serialize_table("condition_info", self._entries))
            return {"conditioninfo.pabgb": pabgb, "conditioninfo.pabgh": self._pabgh}
        except Exception:
            return {}

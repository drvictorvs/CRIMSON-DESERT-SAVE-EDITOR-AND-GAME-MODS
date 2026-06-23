"""Character Swap Editor tab â€” unlock playable character swap points.

Shows the 12 type=5 PlayableCharacter entries from gameplaytrigger.pabgb
and allows unlocking their player_condition gates so all characters are
available at all swap locations.
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
    QSpinBox, QAbstractItemView, QMenu, QApplication,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)

INTERNAL_DIR = "gamedata/binary__/client/bin"
TRIGGER_TYPE_PLAYABLE_CHARACTER = 5  # PlayableCharacter swap points


class CharacterSwapTab(QWidget):
    """Editor for character swap points in gameplaytrigger.pabgb."""

    status_message = Signal(str)
    config_save_requested = Signal()

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._all_entries: list[dict] = []
        self._swap_entries: list[dict] = []
        self._vanilla_entries: list[dict] = []
        self._pabgh: bytes = b""
        self._unlocked_keys: set[int] = set()
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._config["game_install_path"] = path

    # -- UI ----------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Info
        info = QLabel(
            "<b>Character Swap Editor</b> -- Shows PlayableCharacter trigger "
            "points from gameplaytrigger.pabgb.<br>"
            "These are the in-world locations where you can switch characters. "
            "Each has a <b>player_condition</b> that gates availability.<br>"
            "<b>Unlock All</b> removes condition gates so all swap points are always active."
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

        unlock_all_btn = QPushButton("Unlock All")
        unlock_all_btn.setStyleSheet(
            "background-color: #7B1FA2; color: white; font-weight: bold;")
        unlock_all_btn.setToolTip(
            "Set all player_condition fields to 0 (no condition)\n"
            "so every swap point is always available.")
        unlock_all_btn.clicked.connect(self._unlock_all)
        top.addWidget(unlock_all_btn)

        vanilla_btn = QPushButton("Reset to Vanilla")
        vanilla_btn.clicked.connect(self._reset_vanilla)
        top.addWidget(vanilla_btn)

        top.addStretch()

        self._count_label = QLabel("")
        top.addWidget(self._count_label)

        top.addWidget(QLabel("Overlay:"))
        self._overlay_spin = QSpinBox()
        self._overlay_spin.setRange(1, 9999)
        self._overlay_spin.setValue(self._config.get("charswap_overlay_dir", 68))
        self._overlay_spin.setFixedWidth(70)
        self._overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"charswap_overlay_dir": int(v)}))
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

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "Key", "String Key", "Position X", "Position Y", "Position Z",
            "Condition Key", "Unlocked",
        ])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
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

            self._all_entries = dmm_parser.parse_table(
                "game_play_trigger_info", pabgb, pabgh)
            self._vanilla_entries = copy.deepcopy(self._all_entries)

            # Filter to Possession/PlayableCharacter type entries
            self._swap_entries = [
                e for e in self._all_entries
                if e.get("trigger_type") == TRIGGER_TYPE_PLAYABLE_CHARACTER
            ]
            self._unlocked_keys.clear()
            self._populate()

            self._status.setText(
                f"Loaded {len(self._swap_entries)} swap points "
                f"(of {len(self._all_entries)} total triggers)")
            self.status_message.emit(
                f"Loaded {len(self._swap_entries)} character swap points")
        except Exception as e:
            log.exception("Character swap extract failed")
            QMessageBox.critical(self, "Extract Failed", str(e))

    # -- Table population --------------------------------------------------

    def _populate(self) -> None:
        self._table.setRowCount(len(self._swap_entries))
        for row, e in enumerate(self._swap_entries):
            key = e.get("key", 0)
            string_key = str(e.get("string_key", ""))

            # Position extraction
            pos = e.get("position", e.get("trigger_position", {}))
            if isinstance(pos, dict):
                px = f"{pos.get('x', pos.get('f00', 0)):.1f}"
                py = f"{pos.get('y', pos.get('f01', 0)):.1f}"
                pz = f"{pos.get('z', pos.get('f02', 0)):.1f}"
            elif isinstance(pos, (list, tuple)) and len(pos) >= 3:
                px, py, pz = f"{pos[0]:.1f}", f"{pos[1]:.1f}", f"{pos[2]:.1f}"
            else:
                px = py = pz = "0.0"

            cond_key = e.get("player_condition", e.get("condition_key", 0))
            unlocked = "Yes" if key in self._unlocked_keys else ""

            items_data = [
                (str(key), Qt.AlignRight | Qt.AlignVCenter),
                (string_key, Qt.AlignLeft | Qt.AlignVCenter),
                (px, Qt.AlignRight | Qt.AlignVCenter),
                (py, Qt.AlignRight | Qt.AlignVCenter),
                (pz, Qt.AlignRight | Qt.AlignVCenter),
                (str(cond_key), Qt.AlignCenter),
                (unlocked, Qt.AlignCenter),
            ]
            for col, (text, align) in enumerate(items_data):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 0:
                    item.setData(Qt.UserRole, key)
                if col == 6 and unlocked:
                    item.setForeground(Qt.GlobalColor.green)
                self._table.setItem(row, col, item)

        self._table.resizeColumnsToContents()
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._count_label.setText(f"({len(self._swap_entries)} swap points)")

    # -- Context menu ------------------------------------------------------

    def _on_context_menu(self, pos) -> None:
        rows = set(idx.row() for idx in self._table.selectedIndexes())
        if not rows:
            return

        menu = QMenu(self)
        act_unlock = menu.addAction("Unlock Selected")
        act_reset = menu.addAction("Reset Selected to Vanilla")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action is None:
            return

        keys = []
        for r in rows:
            item = self._table.item(r, 0)
            if item:
                keys.append(item.data(Qt.UserRole))

        if action == act_unlock:
            self._unlock_keys(keys)
        elif action == act_reset:
            self._reset_keys(keys)

    # -- Unlock logic ------------------------------------------------------

    def _unlock_all(self) -> None:
        if not self._swap_entries:
            QMessageBox.warning(self, "No Data", "Extract first.")
            return
        keys = [e.get("key", 0) for e in self._swap_entries]
        self._unlock_keys(keys)
        QMessageBox.information(
            self, "Unlock All",
            f"Unlocked {len(keys)} character swap points.\n"
            f"Click Deploy to write the overlay.")

    def _unlock_keys(self, keys: list[int]) -> None:
        """Set player_condition to 0 for the given entries."""
        entry_by_key = {e["key"]: e for e in self._all_entries}
        count = 0
        for k in keys:
            e = entry_by_key.get(k)
            if e is None:
                continue
            # Clear the condition reference so this trigger is always active
            if "player_condition" in e:
                e["player_condition"] = 0
            if "condition_key" in e:
                e["condition_key"] = 0
            self._unlocked_keys.add(k)
            count += 1

        self._populate()
        self._status.setText(f"Unlocked {count} swap point(s)")
        self.status_message.emit(f"Unlocked {count} character swap points")

    def _reset_keys(self, keys: list[int]) -> None:
        vanilla_by_key = {e["key"]: e for e in self._vanilla_entries}
        entry_by_key = {e["key"]: e for e in self._all_entries}
        count = 0
        for k in keys:
            van = vanilla_by_key.get(k)
            ent = entry_by_key.get(k)
            if van and ent:
                ent.update(copy.deepcopy(van))
                self._unlocked_keys.discard(k)
                count += 1
        self._populate()
        self._status.setText(f"Reset {count} entry(ies) to vanilla")

    def _reset_vanilla(self) -> None:
        if not self._all_entries:
            return
        self._all_entries = copy.deepcopy(self._vanilla_entries)
        self._swap_entries = [
            e for e in self._all_entries
            if e.get("trigger_type") == TRIGGER_TYPE_PLAYABLE_CHARACTER
        ]
        self._unlocked_keys.clear()
        self._populate()
        self._status.setText("Reset all to vanilla")

    # -- Deploy ------------------------------------------------------------

    def _deploy(self) -> None:
        if not self._unlocked_keys:
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
                "game_play_trigger_info", self._all_entries))
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
                f"Character swap: {len(self._unlocked_keys)} points "
                f"deployed to {overlay_group}/")
            QMessageBox.information(
                self, "Deployed",
                f"Deployed {len(self._unlocked_keys)} unlocked swap points "
                f"to {overlay_group}/.\n\nRestart the game to apply.")
        except Exception as e:
            log.exception("Character swap deploy failed")
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
                    f"Character swap overlay {overlay_group}/ removed")
            except Exception as e:
                QMessageBox.critical(self, "Restore Failed", str(e))
        else:
            self._status.setText(f"No {overlay_group}/ overlay found")

    # -- Public API --------------------------------------------------------

    def get_staged_files(self) -> dict[str, bytes]:
        if not self._unlocked_keys or not self._all_entries:
            return {}
        try:
            import dmm_parser
            pabgb = bytes(dmm_parser.serialize_table(
                "game_play_trigger_info", self._all_entries))
            return {
                "gameplaytrigger.pabgb": pabgb,
                "gameplaytrigger.pabgh": self._pabgh,
            }
        except Exception:
            return {}

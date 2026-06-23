"""NPC Interactions Editor tab.

Edit any character's `interaction_info_list` (from characterinfo.pabgb) to add or
remove interactions: shops, repair, trade, craft, mounts, func-NPC panels, etc.

characterinfo was fully reverse-engineered (dmm-parser src/tables/character_info),
so `interaction_info_list` is a named, editable CArray<u32 InteractionKey> with
byte-perfect roundtrip across all records.

Deploys as a PAZ overlay (characterinfo.pabgb) using the safe _papgt_sync path.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import sys
import tempfile

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QSplitter,
    QListWidget, QListWidgetItem, QComboBox, QSpinBox, QAbstractItemView,
    QApplication, QGroupBox,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)

INTERNAL = "gamedata/binary__/client/bin"
TABLE = "character_info"


def _find_data_file(name: str) -> str | None:
    """Locate a bundled data/ file across dev + frozen layouts."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(getattr(sys, "_MEIPASS", ""), "data", name),
        os.path.join(getattr(sys, "_MEIPASS", ""), name),
        os.path.join(here, "..", "..", "data", name),
        os.path.join(os.path.dirname(sys.argv[0]), "data", name),
        os.path.join(os.getcwd(), "data", name),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


# --- safe overlay deploy (mirrors simple_launcher._deploy_overlay/_papgt_sync) --

def _ensure_papgt_backup(gp: str) -> None:
    import crimson_rs  # noqa
    papgt = os.path.join(gp, "meta", "0.papgt")
    van = papgt + ".vanilla"
    if os.path.isfile(papgt) and not os.path.isfile(van):
        try:
            shutil.copy2(papgt, van)
        except Exception:
            pass


def _papgt_sync(gp: str) -> None:
    import crimson_rs
    papgt_path = os.path.join(gp, "meta", "0.papgt")
    base = papgt_path + ".vanilla"
    if not os.path.isfile(base):
        base = papgt_path + ".backup"
    if not os.path.isfile(base):
        base = papgt_path
    papgt = crimson_rs.parse_papgt_file(base)
    papgt["entries"] = [
        e for e in papgt["entries"]
        if e.get("group_name", "").isdigit() and int(e["group_name"]) < 36
    ]
    for d in sorted(os.listdir(gp)):
        full = os.path.join(gp, d)
        pamt_file = os.path.join(full, "0.pamt")
        if not os.path.isdir(full) or not os.path.isfile(pamt_file):
            continue
        if not d.isdigit() or int(d) < 36:
            continue
        try:
            ck = crimson_rs.parse_pamt_file(pamt_file)["checksum"]
            papgt = crimson_rs.add_papgt_entry(papgt, d, ck, 0, 0x3FFF)
        except Exception:
            pass
    for e in papgt["entries"]:
        pamt_file = os.path.join(gp, e["group_name"], "0.pamt")
        if os.path.isfile(pamt_file):
            try:
                e["pack_meta_checksum"] = crimson_rs.parse_pamt_file(pamt_file)["checksum"]
            except Exception:
                pass
    crimson_rs.write_papgt_file(papgt, papgt_path)


def _deploy_overlay(gp: str, group: str, files: list[tuple[str, bytes]]) -> None:
    import crimson_rs
    _ensure_papgt_backup(gp)
    with tempfile.TemporaryDirectory() as tmp:
        gdir = os.path.join(tmp, group)
        b = crimson_rs.PackGroupBuilder(gdir, crimson_rs.Compression.NONE,
                                        crimson_rs.Crypto.NONE)
        for fname, data in files:
            b.add_file(INTERNAL, fname, data)
        b.finish()
        dst = os.path.join(gp, group)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        os.makedirs(dst, exist_ok=True)
        for f in os.listdir(gdir):
            shutil.copy2(os.path.join(gdir, f), os.path.join(dst, f))
    _papgt_sync(gp)


# ── Global Interaction Rules (interactioninfo condition editing) ──────────────
# interaction_info defines the GENERIC interactions (Npc_Shop_120, Npc_Dialog,
# Dead_Loot, ...). Each carries a cond_data_list that gates WHEN it appears.
# Editing these is GLOBAL (affects every NPC that uses the interaction). We do
# it by neutralizing specific condition *types* (replace the gating leaf with
# CheckNone) or clearing a matched interaction's conditions entirely. Both keep
# the table valid; serialize regenerates the pabgh (entry sizes change).

# CheckNone (wire tag 2, bodyless) — a no-op gate used to neutralize a lock.
_CHECKNONE = {"case": "ConditionData", "data": {"base": {"tag": 2},
              "option_block": None, "variant": {"type": "ConditionData_CheckNone"}}}

# Condition-type groups the preset buttons target.
IR_KNOWLEDGE = {"ConditionData_CheckKnowledge", "ConditionData_HasUnknownKnowledge",
                "ConditionData_CheckGimmickNeedKnowledge", "ConditionData_CheckGimmickknowledgeLearned"}
IR_QUEST = {"ConditionData_HasQuestDialog", "ConditionData_CheckQuestDialogCategory",
            "ConditionData_CompleteQuest", "ConditionData_PlayingQuest", "ConditionData_StartQuest",
            "ConditionData_CompleteMission", "ConditionData_PlayingMission", "ConditionData_StartMission",
            "ConditionData_CompleteSubMission", "ConditionData_QuestGaugePercent"}
IR_SHOP_REQ = {"ConditionData_CheckMoneyForBuyingStock", "ConditionData_CheckHaveItem",
               "ConditionData_CheckHaveItemPrice", "ConditionData_CheckHaveItemGroupPrice",
               "ConditionData_CheckExistPrice", "ConditionData_CheckExistStoreItemToSell",
               "ConditionData_IsExistStoreItemToSell"}


def _ir_walk_neutralize(node, targets: set, stats: list) -> dict:
    """Replace ConditionData leaves whose variant type is in `targets` with
    CheckNone (recursively through BinaryOp/UnaryOp trees). In place; returns
    the (possibly replaced) node."""
    import copy
    if not isinstance(node, dict):
        return node
    if node.get("case") == "ConditionData":
        t = node.get("data", {}).get("variant", {}).get("type", "")
        if t in targets:
            stats[0] += 1
            return copy.deepcopy(_CHECKNONE)
        return node
    for k in ("left", "right", "child"):
        if isinstance(node.get(k), dict):
            node[k] = _ir_walk_neutralize(node[k], targets, stats)
    return node


def ir_neutralize_types(items: list, targets: set,
                        key_filter=None) -> int:
    """Neutralize every gating condition whose type is in `targets`, across all
    interactions (optionally only those whose string_key matches key_filter).
    Returns the number of condition leaves neutralized."""
    stats = [0]
    for r in items:
        if key_filter and not key_filter(r.get("string_key") or ""):
            continue
        for pair in (r.get("tail", {}).get("cond_data_list") or []):
            if not isinstance(pair, dict):
                continue
            for slot in ("cond_a", "cond_b"):
                c = pair.get(slot)
                if isinstance(c, dict) and isinstance(c.get("tree"), dict):
                    c["tree"] = _ir_walk_neutralize(c["tree"], targets, stats)
    return stats[0]


def ir_clear_conditions(items: list, key_filter) -> int:
    """Clear (empty) the cond_data_list of every interaction whose string_key
    matches key_filter. Returns count of interactions changed."""
    n = 0
    for r in items:
        if key_filter(r.get("string_key") or "") and (r.get("tail", {}).get("cond_data_list")):
            r["tail"]["cond_data_list"] = []
            n += 1
    return n


class NpcInteractionsTab(QWidget):
    status_message = Signal(str)
    config_save_requested = Signal()

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._entries: list[dict] = []
        self._vanilla: list[dict] = []
        self._pabgh: bytes = b""
        self._dirty: set[int] = set()
        self._char_names: dict[str, dict] = {}
        self._inter: dict[str, dict] = {}     # key(str) -> {name,type,cat}
        self._cur_key: int | None = None
        self._load_data()
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._config["game_install_path"] = path

    def _load_data(self) -> None:
        def _load(name):
            try:
                f = _find_data_file(name)
                return json.load(open(f, encoding="utf-8")) if f else {}
            except Exception:
                return {}
        self._char_names = _load("character_names.json")
        self._inter = _load("interaction_keys.json")
        # real in-game display names (resolved from name LocalizableString via
        # localization_eng_map) — character key -> display string.
        self._disp = _load("character_display_names.json")

    def _display_of(self, key: int) -> str:
        """Real in-game name (e.g. 'Market Merchant'); falls back to codename."""
        dn = self._disp.get(str(key))
        if dn:
            return dn
        rec = self._char_names.get(str(key))
        if rec:
            return rec.get("clean") or rec.get("internal") or f"#{key}"
        return f"#{key}"

    def _name_of(self, key: int) -> str:
        return self._display_of(key)

    def _inter_label(self, ik: int) -> str:
        rec = self._inter.get(str(ik))
        if rec:
            return f"{ik}  —  {rec['name']}  [{rec['cat']}]"
        return f"{ik}  —  (unknown)"

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        info = QLabel(
            "<b>NPC Interactions Editor</b> — edit a character's "
            "<b>interaction_info_list</b>: the universal player↔NPC actions "
            "(loot, catch, threaten, pickpocket, gift, <b>Npc_Dialog1/2</b>, bind, "
            "inspect, mount actions, craft/gimmick).<br>"
            "NOTE: shops/barber are <i>not</i> here — they're reached through the "
            "NPC's <b>dialogue tree</b> (the Npc_Dialog entries open it). This tab "
            "tunes which raw actions a character exposes.<br>"
            "<b>Apply to Game</b> writes a PAZ overlay (characterinfo.pabgb). "
            "Restart the game to see changes."
        )
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['text']}; background-color: {COLORS['panel']}; "
            f"padding: 8px; border: 2px solid {COLORS['accent']}; border-radius: 6px;")
        root.addWidget(info)

        top = QHBoxLayout()
        ext = QPushButton("Extract")
        ext.setObjectName("accentBtn")
        ext.clicked.connect(self._extract)
        top.addWidget(ext)
        top.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("character name…")
        self._search.textChanged.connect(self._populate_chars)
        top.addWidget(self._search, 1)
        self._only_inter = QPushButton("Only NPCs w/ interactions")
        self._only_inter.setCheckable(True)
        self._only_inter.setChecked(True)
        self._only_inter.clicked.connect(self._populate_chars)
        top.addWidget(self._only_inter)
        top.addStretch()
        top.addWidget(QLabel("Overlay:"))
        self._overlay = QSpinBox()
        self._overlay.setRange(36, 9999)
        self._overlay.setValue(self._config.get("npcinter_overlay_dir", 72))
        self._overlay.setFixedWidth(70)
        self._overlay.valueChanged.connect(
            lambda v: self._config.update({"npcinter_overlay_dir": int(v)}))
        top.addWidget(self._overlay)
        dep = QPushButton("Apply to Game")
        dep.setStyleSheet(f"background-color: {COLORS['accent']}; color: white; font-weight: bold;")
        dep.clicked.connect(self._deploy)
        top.addWidget(dep)
        res = QPushButton("Restore")
        res.clicked.connect(self._restore)
        top.addWidget(res)
        root.addLayout(top)

        split = QSplitter(Qt.Horizontal)

        # left: character table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Display Name", "Codename", "Key", "#"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_char_selected)
        split.addWidget(self._table)

        # right: interaction editor
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)
        self._sel_label = QLabel("Select a character.")
        self._sel_label.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold;")
        rl.addWidget(self._sel_label)

        box = QGroupBox("Interactions on this character")
        bl = QVBoxLayout(box)
        self._ilist = QListWidget()
        bl.addWidget(self._ilist, 1)
        rmrow = QHBoxLayout()
        rm = QPushButton("Remove Selected")
        rm.clicked.connect(self._remove_interaction)
        rmrow.addWidget(rm)
        rmrow.addStretch()
        bl.addLayout(rmrow)
        rl.addWidget(box, 1)

        addbox = QGroupBox("Add interaction")
        al = QVBoxLayout(addbox)
        catrow = QHBoxLayout()
        catrow.addWidget(QLabel("Category:"))
        self._cat = QComboBox()
        cats = sorted({r["cat"] for r in self._inter.values()})
        self._cat.addItem("All")
        self._cat.addItems(cats)
        self._cat.currentTextChanged.connect(self._refill_add_combo)
        catrow.addWidget(self._cat, 1)
        al.addLayout(catrow)
        self._addcombo = QComboBox()
        al.addWidget(self._addcombo)
        addbtn = QPushButton("Add to character")
        addbtn.setObjectName("accentBtn")
        addbtn.clicked.connect(self._add_interaction)
        al.addWidget(addbtn)
        bulkrow = QHBoxLayout()
        addcat = QPushButton("Add all in category")
        addcat.clicked.connect(self._add_category)
        bulkrow.addWidget(addcat)
        superbtn = QPushButton("★ Add all NPC services (shop/talk/func)")
        superbtn.setStyleSheet("background-color: #7B1FA2; color: white; font-weight: bold;")
        superbtn.setToolTip(
            "Add every NPC menu/service interaction (interaction_type 3/4/5: shops, "
            "talk, func-NPC, trade). These are safe to stack on an NPC.\n\n"
            "Does NOT add combat moves or world-gimmick interactions (types 0/1) — "
            "those need input-key bindings and CRASH the game on load if forced onto "
            "an NPC. Use the per-category / single add for those at your own risk; "
            "Restore reverts.")
        superbtn.clicked.connect(self._make_super)
        bulkrow.addWidget(superbtn)
        al.addLayout(bulkrow)
        rl.addWidget(addbox)
        self._refill_add_combo()

        split.addWidget(right)
        split.setSizes([520, 460])
        root.addWidget(split, 1)

        root.addWidget(self._build_interaction_rules())

        self._status = QLabel("Click Extract to load characterinfo from the game.")
        self._status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        root.addWidget(self._status)

    def _refill_add_combo(self) -> None:
        self._addcombo.clear()
        cat = self._cat.currentText()
        items = sorted(
            ((int(k), v) for k, v in self._inter.items()
             if cat == "All" or v["cat"] == cat),
            key=lambda kv: (kv[1]["cat"], kv[1]["name"]))
        for ik, v in items:
            self._addcombo.addItem(f"{v['name']}  ({ik}) [{v['cat']}]", ik)

    # -- extract / populate ----------------------------------------------

    def _extract(self) -> None:
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            QMessageBox.warning(self, "No Game Path", "Set the game install path first.")
            return
        self.status_message.emit("Extracting characterinfo…")
        QApplication.processEvents()
        try:
            import crimson_rs
            import dmm_parser
            pabgb = bytes(crimson_rs.extract_file(game, "0008", INTERNAL, "characterinfo.pabgb"))
            self._pabgh = bytes(crimson_rs.extract_file(game, "0008", INTERNAL, "characterinfo.pabgh"))
            self._entries = dmm_parser.parse_table(TABLE, pabgb, self._pabgh)
            self._vanilla = copy.deepcopy(self._entries)
            self._dirty.clear()
            self._populate_chars()
            self._status.setText(f"Loaded {len(self._entries)} characters.")
            self.status_message.emit(f"Loaded {len(self._entries)} characters")
        except Exception as e:
            log.exception("NPC interactions extract failed")
            QMessageBox.critical(self, "Extract Failed", str(e))

    def _populate_chars(self) -> None:
        q = self._search.text().strip().lower()
        only = self._only_inter.isChecked()
        rows = []
        for e in self._entries:
            key = e.get("key", 0)
            il = e.get("interaction_info_list") or []
            if only and not il:
                continue
            disp = self._display_of(key)
            internal = self._char_names.get(str(key), {}).get("internal", "")
            if q and q not in disp.lower() and q not in internal.lower() and q not in str(key):
                continue
            rows.append((disp, internal, key, len(il)))
        rows.sort(key=lambda r: r[0].lower())
        self._table.setRowCount(len(rows))
        for r, (clean, internal, key, n) in enumerate(rows):
            for c, txt, align in [
                (0, clean, Qt.AlignLeft | Qt.AlignVCenter),
                (1, internal, Qt.AlignLeft | Qt.AlignVCenter),
                (2, str(key), Qt.AlignRight | Qt.AlignVCenter),
                (3, str(n), Qt.AlignCenter),
            ]:
                it = QTableWidgetItem(txt)
                it.setTextAlignment(align)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if c == 0:
                    it.setData(Qt.UserRole, key)
                    if key in self._dirty:
                        it.setForeground(Qt.GlobalColor.green)
                self._table.setItem(r, c, it)
        self._table.resizeColumnToContents(1)
        self._table.resizeColumnToContents(2)
        self._table.resizeColumnToContents(3)
        self._status.setText(f"Showing {len(rows)} characters"
                             + (f" ({len(self._dirty)} edited)" if self._dirty else ""))

    def _entry_by_key(self, key: int) -> dict | None:
        for e in self._entries:
            if e.get("key") == key:
                return e
        return None

    def _on_char_selected(self) -> None:
        items = self._table.selectedItems()
        if not items:
            return
        key = self._table.item(items[0].row(), 0).data(Qt.UserRole)
        self._cur_key = key
        self._sel_label.setText(f"{self._name_of(key)}  (key {key})")
        self._refresh_ilist()

    def _refresh_ilist(self) -> None:
        self._ilist.clear()
        if self._cur_key is None:
            return
        e = self._entry_by_key(self._cur_key)
        if not e:
            return
        for ik in (e.get("interaction_info_list") or []):
            li = QListWidgetItem(self._inter_label(ik))
            li.setData(Qt.UserRole, ik)
            self._ilist.addItem(li)

    # -- edit ------------------------------------------------------------

    def _add_interaction(self) -> None:
        if self._cur_key is None:
            QMessageBox.information(self, "Add", "Select a character first.")
            return
        ik = self._addcombo.currentData()
        if ik is None:
            return
        e = self._entry_by_key(self._cur_key)
        lst = list(e.get("interaction_info_list") or [])
        if ik in lst:
            self._status.setText(f"{self._name_of(self._cur_key)} already has {ik}.")
            return
        lst.append(int(ik))
        e["interaction_info_list"] = lst
        self._dirty.add(self._cur_key)
        self._refresh_ilist()
        self._populate_chars()
        self._reselect(self._cur_key)
        self._status.setText(f"Added {ik} to {self._name_of(self._cur_key)}")

    def _bulk_add(self, keys: list[int], label: str) -> None:
        if self._cur_key is None:
            QMessageBox.information(self, "Add", "Select a character first.")
            return
        e = self._entry_by_key(self._cur_key)
        lst = list(e.get("interaction_info_list") or [])
        have = set(lst)
        added = 0
        for ik in keys:
            if ik not in have:
                lst.append(int(ik)); have.add(ik); added += 1
        e["interaction_info_list"] = lst
        self._dirty.add(self._cur_key)
        self._refresh_ilist()
        self._populate_chars()
        self._reselect(self._cur_key)
        self._status.setText(f"Added {added} {label} to {self._name_of(self._cur_key)} "
                            f"(now {len(lst)} total). Apply to Game when done.")

    def _add_category(self) -> None:
        cat = self._cat.currentText()
        keys = [int(k) for k, v in self._inter.items() if cat == "All" or v["cat"] == cat]
        self._bulk_add(keys, f"'{cat}' interactions")

    def _make_super(self) -> None:
        if self._cur_key is None:
            QMessageBox.information(self, "Add NPC services", "Select a character first.")
            return
        # Safe NPC menu/service interactions: interaction_type 3/4/5 AND a pure
        # menu-opener name (shop/trade/talk/func/buy/examine). EXCLUDE interactive
        # ones (challenge/duel/bind/gate/release/wrest) — those need input-key
        # bindings and crash load if forced onto an NPC (types 0/1 likewise excluded).
        RISKY = ("challenge", "bind", "gate", "release", "wrest", "carry", "ride")
        svc = [int(k) for k, v in self._inter.items()
               if v.get("type") in (3, 4, 5)
               and not any(w in v.get("name", "").lower() for w in RISKY)]
        if QMessageBox.question(
                self, "Add all NPC services",
                f"Add all {len(svc)} NPC service interactions (shops, talk, func-NPC, "
                f"trade) to {self._name_of(self._cur_key)}?\n\nThese are safe to stack. "
                f"Combat/gimmick interactions are NOT added (they crash load). "
                f"Restart game after Apply; Restore reverts.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        self._bulk_add(svc, "NPC service interactions")

    def _remove_interaction(self) -> None:
        if self._cur_key is None:
            return
        sel = self._ilist.selectedItems()
        if not sel:
            return
        e = self._entry_by_key(self._cur_key)
        lst = list(e.get("interaction_info_list") or [])
        for li in sel:
            ik = li.data(Qt.UserRole)
            if ik in lst:
                lst.remove(ik)
        e["interaction_info_list"] = lst
        self._dirty.add(self._cur_key)
        self._refresh_ilist()
        self._populate_chars()
        self._reselect(self._cur_key)

    def _reselect(self, key: int) -> None:
        for r in range(self._table.rowCount()):
            it = self._table.item(r, 0)
            if it and it.data(Qt.UserRole) == key:
                self._table.selectRow(r)
                return

    # -- deploy ----------------------------------------------------------

    def _deploy(self) -> None:
        if not self._dirty:
            QMessageBox.information(self, "Apply to Game", "No edits to deploy.")
            return
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            QMessageBox.warning(self, "Apply to Game", "Set game path first.")
            return
        try:
            import dmm_parser
            pabgb = bytes(dmm_parser.serialize_table(TABLE, self._entries))
            group = f"{self._overlay.value():04d}"
            self.status_message.emit("Deploying characterinfo overlay…")
            QApplication.processEvents()
            _deploy_overlay(game, group, [
                ("characterinfo.pabgb", pabgb),
                ("characterinfo.pabgh", self._pabgh),
            ])
            self.config_save_requested.emit()
            self._status.setText(f"Deployed {len(self._dirty)} edited NPC(s) to {group}/")
            self.status_message.emit(f"NPC interactions: deployed to {group}/")
            QMessageBox.information(
                self, "Deployed",
                f"Deployed {len(self._dirty)} edited character(s) to {group}/.\n\n"
                f"Restart the game to apply.")
        except Exception as e:
            log.exception("NPC interactions deploy failed")
            QMessageBox.critical(self, "Deploy Failed", str(e))

    def _restore(self) -> None:
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            return
        group = f"{self._overlay.value():04d}"
        d = os.path.join(game, group)
        if not os.path.isdir(d):
            self._status.setText(f"No {group}/ overlay found.")
            return
        if QMessageBox.question(self, "Restore", f"Remove {group}/ overlay?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(d)
            _papgt_sync(game)
            self._status.setText(f"Removed {group}/ overlay.")
            self.status_message.emit(f"NPC interactions overlay {group}/ removed")
        except Exception as e:
            QMessageBox.critical(self, "Restore Failed", str(e))

    # ── Global Interaction Rules (interactioninfo) ───────────────────────

    def _build_interaction_rules(self) -> QWidget:
        box = QGroupBox("🌍 Global Interaction Rules — unlock gated interactions "
                        "(EXPERIMENTAL · affects ALL NPCs · separate overlay · restart game)")
        box.setStyleSheet(f"QGroupBox {{ color: {COLORS['accent']}; font-weight: bold; }}")
        v = QVBoxLayout(box)
        hint = QLabel(
            "Each generic interaction (shop, dialog, loot…) is gated by conditions "
            "that decide when it's offered. These buttons neutralize specific lock "
            "types <i>globally</i>, then deploy a separate <b>interactioninfo</b> "
            "overlay. Use <b>Restore Rules</b> to revert. Stacks with per-NPC edits above."
        )
        hint.setTextFormat(Qt.RichText)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLORS['text_dim']}; font-weight: normal;")
        v.addWidget(hint)

        row1 = QHBoxLayout()
        for label, tip, fn in [
            ("Unlock knowledge locks", "Neutralize CheckKnowledge gates everywhere "
             "(interactions hidden until you learn a knowledge become always offered).",
             lambda: self._ir_apply_neutralize(IR_KNOWLEDGE, None, "knowledge locks")),
            ("Unlock quest/dialog gates", "Neutralize quest-dialog / quest-state gates "
             "(HasQuestDialog, CompleteQuest, …).",
             lambda: self._ir_apply_neutralize(IR_QUEST, None, "quest/dialog gates")),
            ("Drop shop money/item reqs", "Neutralize CheckMoneyForBuyingStock / "
             "CheckHaveItem on shop interactions.",
             lambda: self._ir_apply_neutralize(IR_SHOP_REQ,
                     lambda k: "Shop" in k or "Buy" in k, "shop money/item requirements")),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.clicked.connect(fn)
            row1.addWidget(btn)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        b_shop = QPushButton("Shops always available")
        b_shop.setToolTip("Clear ALL conditions on *Shop* interactions so the shop "
                          "option is always offered regardless of state.")
        b_shop.clicked.connect(lambda: self._ir_apply_clear(
            lambda k: "Shop" in k, "shop"))
        row2.addWidget(b_shop)
        b_talk = QPushButton("Dialogs/Talk always available")
        b_talk.setToolTip("Clear ALL conditions on *Dialog* / *Talk* interactions.")
        b_talk.clicked.connect(lambda: self._ir_apply_clear(
            lambda k: "Dialog" in k or "Talk" in k, "dialog/talk"))
        row2.addWidget(b_talk)
        row2.addStretch()
        row2.addWidget(QLabel("Overlay:"))
        self._ir_overlay = QSpinBox()
        self._ir_overlay.setRange(36, 9999)
        self._ir_overlay.setValue(self._config.get("intrules_overlay_dir", 73))
        self._ir_overlay.setFixedWidth(70)
        self._ir_overlay.valueChanged.connect(
            lambda x: self._config.update({"intrules_overlay_dir": int(x)}))
        row2.addWidget(self._ir_overlay)
        b_restore = QPushButton("Restore Rules")
        b_restore.clicked.connect(self._ir_restore)
        row2.addWidget(b_restore)
        v.addLayout(row2)

        self._ir_status = QLabel("")
        self._ir_status.setStyleSheet(f"color: {COLORS['text_dim']}; font-weight: normal;")
        v.addWidget(self._ir_status)
        return box

    def _ir_load_items(self):
        """Extract + parse interactioninfo (pabgb + pabgh). Returns (items, pabgh)."""
        import crimson_rs
        import dmm_parser
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            raise RuntimeError("Set the game install path first.")
        pabgb = bytes(crimson_rs.extract_file(game, "0008", INTERNAL, "interactioninfo.pabgb"))
        pabgh = bytes(crimson_rs.extract_file(game, "0008", INTERNAL, "interactioninfo.pabgh"))
        items = dmm_parser.parse_table("interaction_info", pabgb, pabgh)
        return items, pabgh

    def _ir_deploy(self, items, pabgh, summary: str) -> None:
        import dmm_parser
        game = self._config.get("game_install_path", "")
        out = dmm_parser.serialize_table("interaction_info", items, None, pabgh)
        new_pabgb, new_pabgh = (bytes(out[0]), bytes(out[1])) if isinstance(out, (tuple, list)) \
            else (bytes(out), pabgh)
        group = f"{self._ir_overlay.value():04d}"
        self.status_message.emit("Deploying interaction rules…")
        QApplication.processEvents()
        _deploy_overlay(game, group, [
            ("interactioninfo.pabgb", new_pabgb),
            ("interactioninfo.pabgh", new_pabgh),
        ])
        self.config_save_requested.emit()
        self._ir_status.setText(f"✓ {summary} — deployed to {group}/. Restart the game.")
        self.status_message.emit(f"Interaction rules: {summary} → {group}/")

    def _ir_apply_neutralize(self, targets: set, key_filter, label: str) -> None:
        try:
            items, pabgh = self._ir_load_items()
        except Exception as e:
            QMessageBox.warning(self, "Interaction Rules", str(e))
            return
        n = ir_neutralize_types(items, targets, key_filter)
        if n == 0:
            self._ir_status.setText(f"No {label} found to change.")
            return
        if QMessageBox.question(
                self, "Apply global rule",
                f"Neutralize {n} '{label}' condition(s) across ALL NPCs?\n\n"
                f"This is global and experimental. Restart the game after; "
                f"Restore Rules reverts.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        try:
            self._ir_deploy(items, pabgh, f"neutralized {n} {label}")
        except Exception as e:
            log.exception("interaction rules deploy failed")
            QMessageBox.critical(self, "Deploy Failed", str(e))

    def _ir_apply_clear(self, key_filter, label: str) -> None:
        try:
            items, pabgh = self._ir_load_items()
        except Exception as e:
            QMessageBox.warning(self, "Interaction Rules", str(e))
            return
        n = ir_clear_conditions(items, key_filter)
        if n == 0:
            self._ir_status.setText(f"No {label} interactions with conditions found.")
            return
        if QMessageBox.question(
                self, "Apply global rule",
                f"Clear ALL conditions on {n} {label} interaction(s) so they're "
                f"always offered?\n\nGlobal + experimental. Restore Rules reverts.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        try:
            self._ir_deploy(items, pabgh, f"cleared conditions on {n} {label} interactions")
        except Exception as e:
            log.exception("interaction rules deploy failed")
            QMessageBox.critical(self, "Deploy Failed", str(e))

    def _ir_restore(self) -> None:
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            return
        group = f"{self._ir_overlay.value():04d}"
        d = os.path.join(game, group)
        if not os.path.isdir(d):
            self._ir_status.setText(f"No {group}/ rules overlay found.")
            return
        if QMessageBox.question(self, "Restore Rules", f"Remove {group}/ interaction-rules overlay?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(d)
            _papgt_sync(game)
            self._ir_status.setText(f"Removed {group}/ rules overlay.")
            self.status_message.emit(f"Interaction rules overlay {group}/ removed")
        except Exception as e:
            QMessageBox.critical(self, "Restore Failed", str(e))

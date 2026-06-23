"""NPC Store / Function Swapper tab.

Change a single NPC's shop & function by editing ONLY that NPC's NpcInfo record
in npcinfo.pabgb — no scene files touched, so no other NPC or quest is affected
(unlike the destructive scene-file swap reference mods do).

How an NPC links to a function/shop (reverse-engineered, see
project_npc_function_swap memory + HANDOVER_npc_barber.md):
    characterinfo.f11  (NpcInfoKey)  ->  NpcInfo record, which carries:
      - store_info            (StoreKey)  = the actual vendor/shop that opens (0 = none)
      - npc_function_type_flag (bitmask)  = the function class / interaction label
      - shop_name / interaction_name (LocStr) = displayed button text
      - shop_scenekey                     = scene ref (only meaningful for scene-driven
                                            functions; setting it alone does nothing)

PROVEN: swapping store_info + flag (+ copying a donor's labels) turns an NPC into
a working different shop. NOT possible via data: the barber appearance editor
(it's gated on a basecamp scene, not npcinfo — store_info=0 test opened nothing).

Deploys as a PAZ overlay (npcinfo.pabgb) using the safe _papgt_sync path, mirroring
npc_interactions.py.
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
    QComboBox, QSpinBox, QAbstractItemView, QApplication, QGroupBox, QFormLayout,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)

INTERNAL = "gamedata/binary__/client/bin"
TABLE = "npc_info"

# npc_function_type_flag presets (decoded — see HANDOVER_npc_barber.md).
# The flag is a bitmask; it drives the interaction label / function class.
FLAG_PRESETS: list[tuple[int, str]] = [
    (0, "None (no function)"),
    (1, "Shop / Research (generic)"),
    (8, "Furniture shop"),
    (17, "Ranch"),
    (32, "Smithy"),
    (33, "Camp Smithy"),
    (257, "Stable"),
    (513, "Workshop / Wagon"),
    (2049, "Provisions Keeper"),
    (4097, "Church shop"),
    (16384, "Camp Barber (label only — editor needs a basecamp scene)"),
    (32769, "Fence"),
    (65537, "Fence (variant)"),
    (131073, "Fence (variant)"),
    (131089, "Livestock"),
    (262145, "Guard"),
    (524289, "Tailor"),
    (1048577, "Mysterious Shop"),
    (2097153, "Art Dealer"),
    (2105345, "Dyer (has dye color groups)"),
]
FLAG_LABEL = {f: n for f, n in FLAG_PRESETS}


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


# --- safe overlay deploy (mirrors npc_interactions.py / simple_launcher) -------

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


class NpcStoreSwapTab(QWidget):
    status_message = Signal(str)
    config_save_requested = Signal()

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._npcs: list[dict] = []          # npc_info records (live, editable)
        self._vanilla: list[dict] = []
        self._pabgh: bytes = b""
        self._dirty: set[int] = set()        # npc keys edited
        self._npc_to_chars: dict[int, list[int]] = {}   # npcinfo key -> [char keys]
        self._stores: dict[int, dict] = {}   # store key -> {string_key, store_type, ...}
        self._disp: dict[str, str] = {}      # char key(str) -> display name
        self._char_names: dict[str, dict] = {}
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
        self._disp = _load("character_display_names.json")
        self._char_names = _load("character_names.json")
        # index(str) -> English label, for shop_name / interaction_name / button
        # (pre-resolved from localization_eng_map for all npcinfo LocStr indices).
        self._labels = _load("npc_labels.json")

    # -- name / label helpers --------------------------------------------

    def _char_display(self, key: int) -> str:
        dn = self._disp.get(str(key))
        if dn:
            return dn
        rec = self._char_names.get(str(key))
        if rec:
            return rec.get("clean") or rec.get("internal") or f"#{key}"
        return f"#{key}"

    def _npc_name(self, npc_key: int) -> str:
        """Resolve an NpcInfo record to the character(s) that use it."""
        chars = self._npc_to_chars.get(npc_key)
        if chars:
            names = [self._char_display(c) for c in chars]
            return " / ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
        return f"(npcinfo #{npc_key})"

    def _flag_label(self, flag: int) -> str:
        return FLAG_LABEL.get(flag, f"custom (0x{flag:X})")

    def _loc(self, locstr: dict | None) -> str:
        """Resolve a LocStr (shop_name/interaction_name/button) to its English text."""
        if not isinstance(locstr, dict):
            return ""
        idx = locstr.get("index")
        if not idx:
            return ""
        return self._labels.get(str(idx), "")

    def _npc_button(self, n: dict) -> str:
        """The readable interaction button text (falls back to shop title / flag)."""
        return (self._loc(n.get("interaction_name"))
                or self._loc(n.get("shop_name"))
                or self._flag_label(n.get("npc_function_type_flag", 0)))

    def _store_label(self, store_key: int) -> str:
        if not store_key:
            return "— none —"
        s = self._stores.get(store_key)
        if s:
            sk = s.get("string_key") or f"store {store_key}"
            n = len(s.get("stock_data_list") or [])
            return f"{sk}  ({store_key}, {n} items)"
        return f"store {store_key}"

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        info = QLabel(
            "<b>NPC Store / Function Swapper</b> — change a single NPC's shop &amp; "
            "function by editing only that NPC's <b>NpcInfo</b> record. No scene files "
            "are touched, so other NPCs and quests are unaffected.<br>"
            "<b>Store</b> = the vendor that opens. <b>Function</b> = the interaction "
            "label/class. Use <b>Copy from donor</b> to clone another NPC's store + "
            "function + button text exactly (the proven workflow).<br>"
            "<i>Note:</i> the barber appearance editor can NOT be added this way — it's "
            "gated on a basecamp scene, not npcinfo. <b>Apply to Game</b> writes a PAZ "
            "overlay; restart the game to see changes."
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
        self._search.setPlaceholderText("NPC name…")
        self._search.textChanged.connect(self._populate)
        top.addWidget(self._search, 1)
        top.addStretch()
        top.addWidget(QLabel("Overlay:"))
        self._overlay = QSpinBox()
        self._overlay.setRange(36, 9999)
        self._overlay.setValue(self._config.get("npcstore_overlay_dir", 72))
        self._overlay.setFixedWidth(70)
        self._overlay.valueChanged.connect(
            lambda v: self._config.update({"npcstore_overlay_dir": int(v)}))
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

        # left: NPC table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["NPC", "Button", "Function", "Store", "Key"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_selected)
        split.addWidget(self._table)

        # right: editor
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        self._sel_label = QLabel("Select an NPC.")
        self._sel_label.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold;")
        rl.addWidget(self._sel_label)

        self._cur_label = QLabel("")
        self._cur_label.setWordWrap(True)
        self._cur_label.setStyleSheet(f"color: {COLORS['text_dim']};")
        rl.addWidget(self._cur_label)

        # Copy-from-donor (proven workflow)
        donor_box = QGroupBox("Copy from donor NPC (store + function + button text)")
        dform = QVBoxLayout(donor_box)
        self._donor = QComboBox()
        self._donor.setMaxVisibleItems(20)
        dform.addWidget(self._donor)
        copybtn = QPushButton("Copy donor → selected NPC")
        copybtn.setObjectName("accentBtn")
        copybtn.clicked.connect(self._copy_donor)
        dform.addWidget(copybtn)
        rl.addWidget(donor_box)

        # Manual set
        man_box = QGroupBox("Or set manually")
        mform = QFormLayout(man_box)
        self._store_combo = QComboBox()
        self._store_combo.setMaxVisibleItems(20)
        mform.addRow("Store:", self._store_combo)
        self._flag_combo = QComboBox()
        for f, n in FLAG_PRESETS:
            self._flag_combo.addItem(f"{n}  ({f})", f)
        mform.addRow("Function:", self._flag_combo)
        self._raw_store = QSpinBox()
        self._raw_store.setRange(0, 2_000_000_000)
        mform.addRow("Store key (raw):", self._raw_store)
        self._raw_flag = QSpinBox()
        self._raw_flag.setRange(0, 2_000_000_000)
        mform.addRow("Flag (raw):", self._raw_flag)
        applybtn = QPushButton("Apply manual values to selected NPC")
        applybtn.clicked.connect(self._apply_manual)
        mform.addRow(applybtn)
        # keep combos and raw spinboxes in sync
        self._store_combo.currentIndexChanged.connect(self._on_store_combo)
        self._flag_combo.currentIndexChanged.connect(self._on_flag_combo)
        rl.addWidget(man_box)

        rl.addStretch(1)
        split.addWidget(right)
        split.setSizes([540, 440])
        root.addWidget(split, 1)

        self._status = QLabel("Click Extract to load NPC data from the game.")
        self._status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        root.addWidget(self._status)

    # -- extract / populate ----------------------------------------------

    def _extract(self) -> None:
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            QMessageBox.warning(self, "No Game Path", "Set the game install path first.")
            return
        self.status_message.emit("Extracting NPC / store data…")
        QApplication.processEvents()
        try:
            import crimson_rs
            import dmm_parser
            npc_b = bytes(crimson_rs.extract_file(game, "0008", INTERNAL, "npcinfo.pabgb"))
            self._pabgh = bytes(crimson_rs.extract_file(game, "0008", INTERNAL, "npcinfo.pabgh"))
            self._npcs = dmm_parser.parse_table(TABLE, npc_b, self._pabgh)
            self._vanilla = copy.deepcopy(self._npcs)

            # characterinfo: build npcinfo-key -> [char keys] via f11
            ch_b = bytes(crimson_rs.extract_file(game, "0008", INTERNAL, "characterinfo.pabgb"))
            ch_h = bytes(crimson_rs.extract_file(game, "0008", INTERNAL, "characterinfo.pabgh"))
            chars = dmm_parser.parse_table("character_info", ch_b, ch_h)
            self._npc_to_chars = {}
            for c in chars:
                nk = c.get("f11")
                if nk:
                    self._npc_to_chars.setdefault(int(nk), []).append(c.get("key"))

            # storeinfo: key -> record (for readable names)
            try:
                st_b = bytes(crimson_rs.extract_file(game, "0008", INTERNAL, "storeinfo.pabgb"))
                st_h = bytes(crimson_rs.extract_file(game, "0008", INTERNAL, "storeinfo.pabgh"))
                stores = dmm_parser.parse_table("store_info", st_b, st_h)
                self._stores = {s.get("key"): s for s in stores}
            except Exception:
                self._stores = {}

            self._dirty.clear()
            self._fill_store_combo()
            self._fill_donor_combo()
            self._populate()
            self._status.setText(
                f"Loaded {len(self._npcs)} NpcInfo records, "
                f"{len(self._stores)} stores.")
            self.status_message.emit(f"Loaded {len(self._npcs)} NPCs")
        except Exception as e:
            log.exception("NPC store swap extract failed")
            QMessageBox.critical(self, "Extract Failed", str(e))

    def _fill_store_combo(self) -> None:
        self._store_combo.blockSignals(True)
        self._store_combo.clear()
        self._store_combo.addItem("— none — (0)", 0)
        for key in sorted(self._stores):
            s = self._stores[key]
            sk = s.get("string_key") or f"store {key}"
            n = len(s.get("stock_data_list") or [])
            self._store_combo.addItem(f"{sk}  ({key}, {n} items)", key)
        self._store_combo.blockSignals(False)

    def _fill_donor_combo(self) -> None:
        self._donor.blockSignals(True)
        self._donor.clear()
        rows = []
        for n in self._npcs:
            k = n.get("key")
            rows.append((self._npc_name(k), self._npc_button(n),
                         self._store_label(n.get("store_info", 0)), k))
        rows.sort(key=lambda r: r[0].lower())
        for name, btn, store, k in rows:
            self._donor.addItem(f"{name}  —  [{btn}]  —  {store}", k)
        self._donor.blockSignals(False)

    def _populate(self) -> None:
        q = self._search.text().strip().lower()
        rows = []
        for n in self._npcs:
            k = n.get("key")
            name = self._npc_name(k)
            btn = self._npc_button(n)
            if q and q not in name.lower() and q not in btn.lower() and q not in str(k):
                continue
            rows.append((name, btn, self._flag_label(n.get("npc_function_type_flag", 0)),
                         self._store_label(n.get("store_info", 0)), k))
        rows.sort(key=lambda r: r[0].lower())
        self._table.setRowCount(len(rows))
        for r, (name, btn, fn, store, k) in enumerate(rows):
            for c, txt, align in [
                (0, name, Qt.AlignLeft | Qt.AlignVCenter),
                (1, btn, Qt.AlignLeft | Qt.AlignVCenter),
                (2, fn, Qt.AlignLeft | Qt.AlignVCenter),
                (3, store, Qt.AlignLeft | Qt.AlignVCenter),
                (4, str(k), Qt.AlignRight | Qt.AlignVCenter),
            ]:
                it = QTableWidgetItem(txt)
                it.setTextAlignment(align)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if c == 0:
                    it.setData(Qt.UserRole, k)
                    if k in self._dirty:
                        it.setForeground(Qt.GlobalColor.green)
                self._table.setItem(r, c, it)
        self._table.resizeColumnToContents(1)
        self._table.resizeColumnToContents(4)
        self._status.setText(f"Showing {len(rows)} NPCs"
                             + (f" ({len(self._dirty)} edited)" if self._dirty else ""))

    def _npc_by_key(self, key: int) -> dict | None:
        for n in self._npcs:
            if n.get("key") == key:
                return n
        return None

    def _on_selected(self) -> None:
        items = self._table.selectedItems()
        if not items:
            return
        key = self._table.item(items[0].row(), 0).data(Qt.UserRole)
        self._cur_key = key
        self._refresh_editor()

    def _refresh_editor(self) -> None:
        n = self._npc_by_key(self._cur_key) if self._cur_key is not None else None
        if not n:
            self._sel_label.setText("Select an NPC.")
            self._cur_label.setText("")
            return
        self._sel_label.setText(f"{self._npc_name(self._cur_key)}   (npcinfo key {self._cur_key})")
        flag = n.get("npc_function_type_flag", 0)
        store = n.get("store_info", 0)
        btn = self._loc(n.get("interaction_name")) or "(unresolved)"
        title = self._loc(n.get("shop_name")) or "(unresolved)"
        self._cur_label.setText(
            f"Button text: <b>{btn}</b>&nbsp;&nbsp;|&nbsp;&nbsp;Shop title: <b>{title}</b><br>"
            f"Current function: <b>{self._flag_label(flag)}</b><br>"
            f"Current store: <b>{self._store_label(store)}</b><br>"
            f"shop_scenekey: {n.get('shop_scenekey', 0)}")
        self._cur_label.setTextFormat(Qt.RichText)
        # sync controls to current values
        self._set_store_controls(store)
        self._set_flag_controls(flag)

    def _set_store_controls(self, store: int) -> None:
        self._raw_store.blockSignals(True)
        self._raw_store.setValue(int(store))
        self._raw_store.blockSignals(False)
        idx = self._store_combo.findData(int(store))
        self._store_combo.blockSignals(True)
        self._store_combo.setCurrentIndex(idx if idx >= 0 else -1)
        self._store_combo.blockSignals(False)

    def _set_flag_controls(self, flag: int) -> None:
        self._raw_flag.blockSignals(True)
        self._raw_flag.setValue(int(flag))
        self._raw_flag.blockSignals(False)
        idx = self._flag_combo.findData(int(flag))
        self._flag_combo.blockSignals(True)
        self._flag_combo.setCurrentIndex(idx if idx >= 0 else -1)
        self._flag_combo.blockSignals(False)

    def _on_store_combo(self) -> None:
        d = self._store_combo.currentData()
        if d is not None:
            self._raw_store.blockSignals(True)
            self._raw_store.setValue(int(d))
            self._raw_store.blockSignals(False)

    def _on_flag_combo(self) -> None:
        d = self._flag_combo.currentData()
        if d is not None:
            self._raw_flag.blockSignals(True)
            self._raw_flag.setValue(int(d))
            self._raw_flag.blockSignals(False)

    # -- edit ------------------------------------------------------------

    def _mark_dirty(self) -> None:
        self._dirty.add(self._cur_key)
        self._refresh_editor()
        self._populate()
        self._reselect(self._cur_key)

    def _copy_donor(self) -> None:
        if self._cur_key is None:
            QMessageBox.information(self, "Copy donor", "Select a target NPC first.")
            return
        donor_key = self._donor.currentData()
        if donor_key is None:
            return
        if donor_key == self._cur_key:
            self._status.setText("Donor and target are the same NPC.")
            return
        donor = self._npc_by_key(donor_key)
        target = self._npc_by_key(self._cur_key)
        if not donor or not target:
            return
        for f in ("npc_function_type_flag", "store_info", "shop_scenekey",
                  "shop_name", "interaction_name", "exchange_group_key",
                  "exchange_button_text", "dye_color_group_data_list",
                  "dye_texture_set_data_list"):
            if f in donor:
                target[f] = copy.deepcopy(donor[f])
        self._mark_dirty()
        self._status.setText(
            f"Copied {self._npc_name(donor_key)}'s store+function onto "
            f"{self._npc_name(self._cur_key)}. Apply to Game when done.")

    def _apply_manual(self) -> None:
        if self._cur_key is None:
            QMessageBox.information(self, "Apply", "Select an NPC first.")
            return
        target = self._npc_by_key(self._cur_key)
        if not target:
            return
        target["store_info"] = int(self._raw_store.value())
        target["npc_function_type_flag"] = int(self._raw_flag.value())
        self._mark_dirty()
        self._status.setText(
            f"Set {self._npc_name(self._cur_key)} → store {self._raw_store.value()}, "
            f"flag {self._raw_flag.value()}. Apply to Game when done. "
            f"(Button text keeps the NPC's existing label — use Copy from donor to "
            f"change the label too.)")

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
            pabgb = bytes(dmm_parser.serialize_table(TABLE, self._npcs))
            group = f"{self._overlay.value():04d}"
            self.status_message.emit("Deploying npcinfo overlay…")
            QApplication.processEvents()
            _deploy_overlay(game, group, [
                ("npcinfo.pabgb", pabgb),
                ("npcinfo.pabgh", self._pabgh),
            ])
            self.config_save_requested.emit()
            self._status.setText(f"Deployed {len(self._dirty)} edited NPC(s) to {group}/")
            self.status_message.emit(f"NPC store swap: deployed to {group}/")
            QMessageBox.information(
                self, "Deployed",
                f"Deployed {len(self._dirty)} edited NPC(s) to {group}/.\n\n"
                f"Restart the game to apply.")
        except Exception as e:
            log.exception("NPC store swap deploy failed")
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
            self.status_message.emit(f"NPC store swap overlay {group}/ removed")
        except Exception as e:
            QMessageBox.critical(self, "Restore Failed", str(e))

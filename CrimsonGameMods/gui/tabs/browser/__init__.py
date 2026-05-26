from __future__ import annotations

import json
import csv
import logging
from pathlib import Path
from i18n import tr
import dmm_parser as dmm
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHeaderView,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from gui.tabs.browser.vfs_node import VirtualNode
from gui.tabs.browser.vfs_model import VirtualFileSystemModel

try:
    from gui.utils import make_help_btn
except Exception:

    def make_help_btn(topic, fn=None):
        btn = QPushButton("?")
        btn.setFixedSize(22, 22)
        if fn:
            btn.clicked.connect(lambda: fn(topic))
        return btn


log = logging.getLogger(__name__)


def extract_file_data(
    game_dir: str = "",
    group_name: str = "",
    dir_path: str = "",
    file_name: str = "",
) -> bytes:
    try:
        file_data = dmm.extract_file(game_dir, group_name, dir_path, file_name)
    except IOError:
        log.error("Error: The PAZ file cannot be read!")
    except ValueError:
        log.error("Error: File not found in PAMT!")
    except Exception as e:
        log.error(f"Error: {e}")
    else:
        return file_data

def is_complex_list(lst):
    """Returns True if the list contains dictionaries or other lists."""
    return any(isinstance(item, (dict, list)) for item in lst)

def flatten_json(data, prefix=""):
    """Recursively flattens nested dictionaries and complex lists.

    - Dicts become: prefix.key
    - Complex lists become: prefix.0, prefix.1
    - Simple lists become a single string: "item1, item2, item3"
    """
    items = {}

    if isinstance(data, dict):
        for key, value in data.items():
            new_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                items.update(flatten_json(value, new_key))
            else:
                items[new_key] = value

    elif isinstance(data, list):
        if not data:
            items[prefix] = ""
        # Condition 1: It's a complex list (contains dicts or lists) -> Unpack it
        elif is_complex_list(data):
            for index, value in enumerate(data):
                new_key = f"{prefix}.{index}"
                if isinstance(value, (dict, list)):
                    items.update(flatten_json(value, new_key))
                else:
                    items[new_key] = value
        # Condition 2: It's a simple list -> Join into a single string cell
        else:
            items[prefix] = ", ".join(map(str, data))
    else:
        items[prefix] = data

    return items

def dump_csv(table, file_handle):
    # 1. Ensure parsed table data is in list form
    if isinstance(table, dict):
        table = [table]

    # 2. Flatten every complex object in the array
    flattened_rows = [flatten_json(item) for item in table]

    # 3. Dynamically discover all unique column headers across all objects
    headers = set()
    for row in flattened_rows:
        headers.update(row.keys())

    # 4. Sort headers so they appear logically in the CSV (e.g., items.0 before items.1)
    headers = sorted(list(headers))

    # 5. Write the results to a CSV file
    writer = csv.DictWriter(file_handle, fieldnames=headers)
    writer.writeheader()
    writer.writerows(flattened_rows)

class GameBrowserTab(QWidget):
    """Tab for viewing and extracting files from game PAZ archives"""

    status_message = Signal(str)
    game_path_changed = Signal(str)
    config_save_requested = Signal()

    def __init__(
        self,
        config: dict,
        parent: Optional[QWidget] = None,
        show_guide_fn=None,
        path="",
    ):
        super().__init__(parent)

        self._config = config
        self._show_guide = show_guide_fn
        self._game_path = path or self._config.get("game_install_path", "")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        btn = QPushButton("Load Game Data")
        btn.clicked.connect(self.reload_model)
        layout.addWidget(btn)

        tree_view = QTreeView()
        tree_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(tree_view)

        tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree_view.customContextMenuRequested.connect(self.show_context_menu)

        self._tree_view = tree_view

    def set_game_path(self, path: str):
        self._game_path = path

    def reload_model(self):
        if not self._game_path:
            QMessageBox.warning(
                self,
                tr("No Game Path"),
                tr(
                    "Set the game install path using the Browse button at the top."
                ),
            )
            return

        model = VirtualFileSystemModel(dir=self._game_path)
        self._tree_view.setModel(model)
        self._tree_view.header().setStretchLastSection(False)
        self._tree_view.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._tree_view.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )

    def show_context_menu(self, position):
        index = self._tree_view.indexAt(position)
        if not index.isValid():
            return

        node: VirtualNode = index.internalPointer()
        if node.is_dir:
            return

        menu = QMenu()
        found_match = None

        first_dot_index = node.name.find(".") + 1
        if first_dot_index != 0:
            found_match = node.name[first_dot_index:]

        extract_custom = extract_unknown = extract_json = extract_csv = "STUB"
        if found_match and found_match in VirtualNode.KNOWN_FORMATS:
            custom_type = VirtualNode.KNOWN_FORMATS[found_match]
            extract_custom = QAction(
                f"Extract as {custom_type}", self._tree_view
            )
            menu.addAction(extract_custom)

            if found_match in ("pabgb", "pabgh"):
                extract_json = QAction("Extract as JSON", self._tree_view)
                menu.addAction(extract_json)
                extract_csv = QAction("Extract as CSV", self._tree_view)
                menu.addAction(extract_csv)
        else:
            extract_unknown = QAction(
                "Extract as Unregistered Type (Experimental)"
            )
            menu.addAction(extract_unknown)

        if found_match and menu.actions():

            def handle_action(action: QAction):
                log.info(f"Extract requested: {node.absolute_path}")

                segments = [
                    s for s in node.absolute_path.split("/") if s != node.name
                ]
                game_dir = self._game_path
                group_name = segments.pop(0)
                dir_path = "/".join(segments)
                file_name = node.name

                try:
                    Path("data").mkdir(exist_ok=True)
                finally:
                    file_data = extract_file_data(
                        game_dir, group_name, dir_path, file_name
                    )
                
                if action in (extract_custom, extract_unknown):
                    with open(f"data/{node.name}", "wb") as f:
                        f.write(file_data)

                    QMessageBox.information(
                        self._tree_view,
                        "File Extracted",
                        f"{node.name} was successfully extracted to the data folder.",
                    )
                elif action in (extract_json, extract_csv):
                    no_ext = node.name[:-6]
                    try:
                        if found_match == "pabgb":
                            pabgh = extract_file_data(
                                game_dir,
                                group_name,
                                dir_path,
                                f"{no_ext}.pabgh",
                            )
                            pabgb = file_data
                        else:
                            pabgb = extract_file_data(
                                game_dir,
                                group_name,
                                dir_path,
                                f"{no_ext}.pabgb",
                            )
                            pabgh = file_data
                            
                        no_ext = 'skill_info' if no_ext == 'skill' else no_ext
                        table = dmm.parse_table(no_ext, pabgb, pabgh)
                        if action == extract_json:
                            with open(f"data/{no_ext}.json", "w") as f:
                                json.dump(table, f)
                        else:
                            with open(f"data/{no_ext}.csv", "w", newline="", encoding="utf-8") as f:
                                dump_csv(table, f)

                    except Exception as e:
                        log.error(f"Exception: {e}")
                        QMessageBox.critical(
                            self._tree_view, "Error", f"Exception: {e}"
                        )
                    else:
                        QMessageBox.information(
                            self._tree_view,
                            "File Extracted",
                            f"{no_ext}.json was successfully extracted to the data folder.",
                        )

            menu.triggered.connect(handle_action)
            menu.exec(self._tree_view.mapToGlobal(position))

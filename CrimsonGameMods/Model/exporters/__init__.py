# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/NattKh/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""Mesh export format plugins.

To add a new format: create a new file (e.g. my_exporter.py),
subclass MeshExporter, implement export_to_disk(), and register below.
"""

from exporters.base import MeshExporter, ExportResult, ExportWarning, ExportOptions
from exporters.obj_exporter import ObjExporter
from exporters.gltf_exporter import GltfExporter
from exporters.fbx_exporter import FbxExporter

_EXPORTERS = {
    'obj': ObjExporter,
    'gltf': GltfExporter,
    'fbx': FbxExporter,
}


def get_exporter(format_id: str) -> MeshExporter:
    if format_id not in _EXPORTERS:
        raise ValueError(f"Unknown format: {format_id}. Available: {list(_EXPORTERS)}")
    return _EXPORTERS[format_id]()


def available_formats() -> list[str]:
    return list(_EXPORTERS.keys())

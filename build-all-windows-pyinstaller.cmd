@echo off
setlocal
cd /d %~dp0
py -3 -m PyInstaller CrimsonGameMods\CrimsonCLI.spec --noconfirm
py -3 -m PyInstaller CrimsonGameMods\CrimsonGameMods.spec --noconfirm
py -3 -m PyInstaller CrimsonGameMods\CrimsonGameModsSimple.spec --noconfirm
py -3 -m PyInstaller CrimsonSaveEditor\CrimsonSaveEditor.spec --noconfirm

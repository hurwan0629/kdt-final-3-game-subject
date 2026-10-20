# -*- mode: python ; coding: utf-8 -*-
"""Windows 게임 배포본: 현재 이미지와 맵만 포함한다."""
import json
from pathlib import Path

project_root = Path(SPECPATH)
asset_catalog = json.loads((project_root / "assets/catalog.json").read_text(encoding="utf-8"))
game_data = []
for entry in asset_catalog["assets"]:
    relative_path = Path("assets") / entry["path"]
    game_data.append((str(project_root / relative_path), str(relative_path.parent)))
game_data.extend((str(path), "maps") for path in sorted((project_root / "maps").glob("*.txt")))

analysis = Analysis(
    [str(project_root / "src/space_z/__main__.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=game_data,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["gymnasium"],
    noarchive=False,
)
python_archive = PYZ(analysis.pure)
executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="SpaceZ",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="SpaceZ",
)

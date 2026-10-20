"""Windows 실행 폴더를 빌드하고 GitHub Release 첨부용 ZIP 하나를 만든다.

    python -m pip install -e . pyinstaller
    python scripts/build_windows_release.py
"""
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAYER_GUIDE = """Space Z {version} — Windows x64

실행 방법
1. ZIP 전체를 원하는 폴더에 압축 해제합니다.
2. SpaceZ 폴더의 SpaceZ.exe를 실행합니다.
Python, .venv 또는 별도 패키지를 설치할 필요가 없습니다.
SpaceZ.exe와 _internal 폴더를 함께 보관하세요.

조작
WASD: 이동 / 마우스: 조준 / 좌클릭: 발사
1~5: 일반 강화 / F2~F5: 진화 선택 / Tab 유지: 능력치
ESC 또는 P: 일시정지 / N: 새 8x8 블록 지형으로 새 게임
게임 오버 후 Enter: 재시작
기본 탄약은 무제한입니다. 탄창과 R 재장전을 사용하려면
명령줄에서 SpaceZ.exe --limited-ammo로 실행하세요.

이번 버전은 게임 진행을 저장하지 않으며 새 게임에서는 성장이 초기화됩니다.
"""


def copy_dependency_licenses(bundle_directory):
    """Python과 실제 런타임 의존성의 라이선스 문서를 배포본에 복사한다."""
    license_directory = bundle_directory / "LICENSES"
    license_directory.mkdir(exist_ok=True)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    shutil.copy2(python_license, license_directory / "Python-LICENSE.txt")
    for package_name in ("numpy", "pygame", "pyinstaller"):
        distribution = metadata.distribution(package_name)
        for file in distribution.files or ():
            if (any(part.lower() in {"licenses", "license"} for part in file.parts)
                    or file.name.lower().startswith(("license", "copying", "lgpl", "gpl"))):
                destination = license_directory / package_name / str(file)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(distribution.locate_file(file), destination)


def verify_bundle(bundle_directory):
    """실행 파일·런타임·현재 에셋·맵을 확인하고 원본과 해시를 대조한다."""
    assert (bundle_directory / "SpaceZ.exe").is_file(), "실행 파일 누락"
    runtime_directory = bundle_directory / "_internal"
    assert (runtime_directory / "python312.dll").is_file(), "Python 3.12 런타임 누락"
    catalog = json.loads((PROJECT_ROOT / "assets/catalog.json").read_text(encoding="utf-8"))
    asset_paths = [Path("assets") / item["path"] for item in catalog["assets"]]
    map_paths = [path.relative_to(PROJECT_ROOT) for path in sorted((PROJECT_ROOT / "maps").glob("*.txt"))]
    for relative_path in asset_paths + map_paths:
        expected = hashlib.sha256((PROJECT_ROOT / relative_path).read_bytes()).digest()
        actual = hashlib.sha256((runtime_directory / relative_path).read_bytes()).digest()
        assert actual == expected, f"리소스 내용 불일치: {relative_path}"
    bundled_assets = {path.relative_to(runtime_directory) for path in (runtime_directory / "assets").rglob("*") if path.is_file()}
    assert bundled_assets == set(asset_paths), "현재 에셋 외의 파일이 포함됨"


def main():
    """Windows x64/Python 3.12에서 빌드하고 검증한 폴더 전체를 ZIP으로 묶는다."""
    if sys.platform != "win32" or struct.calcsize("P") != 8 or sys.version_info[:2] != (3, 12):
        raise SystemExit("Windows x64의 Python 3.12 환경에서 실행하세요.")
    version = metadata.version("space-z")
    output_directory = PROJECT_ROOT / "dist"
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--distpath", str(output_directory),
        "--workpath", str(PROJECT_ROOT / "build/pyinstaller"),
        str(PROJECT_ROOT / "SpaceZ.spec"),
    ], cwd=PROJECT_ROOT, check=True)
    bundle_directory = output_directory / "SpaceZ"
    (bundle_directory / "README.txt").write_text(PLAYER_GUIDE.format(version=version), encoding="utf-8-sig")
    copy_dependency_licenses(bundle_directory)
    verify_bundle(bundle_directory)
    archive_path = output_directory / f"SpaceZ-v{version}-windows-x64.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output_directory))
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None, "ZIP 손상"
        assert "SpaceZ/SpaceZ.exe" in archive.namelist(), "ZIP에 실행 파일 누락"
    print(f"Release ZIP: {archive_path}")
    print(f"Size: {archive_path.stat().st_size / 1024 ** 2:.1f} MiB")
    print(f"SHA256: {hashlib.sha256(archive_path.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()

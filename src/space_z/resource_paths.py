"""실행 위치에 독립적인 이미지·맵 경로 계산."""
import sys
from pathlib import Path


def resource_path(relative: str) -> str:
    """리소스 상대 경로를 프로젝트 또는 PyInstaller 묶음 기준 절대 경로로 바꾼다.

    인자:
        relative: assets/ 또는 maps/에서 시작하는 리소스 상대 경로.

    반환:
        str: 현재 작업 디렉터리와 무관한 리소스 절대 경로.
    """
    root = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parents[2]
    return str(root / relative)

# Windows 실행 파일 배포

GitHub Release에 올릴 파일은 `dist/SpaceZ-v0.1.0-windows-x64.zip`입니다. 버전은 `pyproject.toml`을 설치한 패키지의 버전에서 가져옵니다. Git 태그 생성·원격 업로드·Release 게시는 별도로 진행합니다.

## 받는 사람이 실행하는 방법

1. ZIP 전체를 원하는 폴더에 압축 해제합니다.
2. `SpaceZ/SpaceZ.exe`를 실행합니다.

Python이나 `.venv`를 설치할 필요가 없습니다. 실행 파일과 `_internal/`을 함께 유지해야 합니다. 기본 실행은 탄약 무제한이며 `SpaceZ.exe --limited-ammo`로 실행하면 탄창·재장전을 사용합니다.

```text
SpaceZ/
├── SpaceZ.exe       # Windows x64 실행 파일
├── _internal/      # Python·라이브러리·이미지·맵
├── LICENSES/       # 포함한 런타임과 의존성의 라이선스
└── README.txt      # 실행 방법과 조작 안내
```

## 개발자가 다시 만드는 방법

Windows x64의 Python 3.12 환경에서 프로젝트 루트를 작업 폴더로 사용합니다.

```powershell
python -m pip install -e . pyinstaller
python scripts/build_windows_release.py
```

[SpaceZ.spec](../../SpaceZ.spec)은 진입점·리소스·창 모드를 정합니다. [build_windows_release.py](../../scripts/build_windows_release.py)는 PyInstaller 실행 → 조작 안내·라이선스 복사 → 리소스 해시 확인 → ZIP 압축과 무결성 확인을 수행합니다. 같은 버전으로 다시 실행하면 기존 `dist/SpaceZ/`와 해당 ZIP을 갱신합니다.

`assets/catalog.json`에 등록된 현재 이미지 45개와 `maps/*.txt`를 포함합니다. 과거 에셋·이미지 참고본·`.venv`·`.cache`·개발 문서·테스트·선택 의존성 Gymnasium은 배포 대상에서 제외합니다. 이미지 목록과 맵이 바뀌면 빌드 시 현재 파일을 다시 반영합니다.

현재 게임의 제한은 [[game/known-issues|알려진 문제]]에 있습니다. 라이브러리·Python 버전이나 Windows 아키텍처를 바꾸면 재빌드 후 실행도 다시 확인합니다.

## 이번 배포본 검증

2026-10-20, Windows 11 x64에서 Python 3.12.10·Pygame 2.6.1·NumPy 2.5.4·PyInstaller 6.22.3으로 만들었습니다. ZIP 크기는 35,648,431바이트(약 34MiB)입니다. 메인 메뉴의 스토리 모드 버튼을 제거하고 게임 나가기를 한 칸 위로 옮긴 변경을 포함합니다.

점수 획득 기록은 코어, 점수 팝업은 렌더러가 소유하도록 분리했습니다. 메인 메뉴에서 다른 난이도에 포커스가 있을 때만 확정된 난이도를 반투명하게 표시하며, 무한 스테이지·게임 나가기에 포커스가 있으면 선명하게 표시합니다. 코드·문서·테스트 검증은 [[development/testing-and-changes#점수 획득 기록과 팝업 분리 검증|검증 결과]]에서 확인합니다.

- ZIP을 프로젝트와 다른 작업 폴더에서 실행하도록 한글·공백이 포함된 별도 경로에 풀었습니다.
- 자식 프로세스의 Python·가상환경 관련 환경변수를 제거하고 PATH를 Windows 시스템 경로만 남겼습니다.
- 실제 실행 파일이 Python·Pygame·NumPy·SDL 런타임 46개를 압축 해제한 배포 폴더에서 불러오는지 확인했습니다.
- 기본 랜덤 맵과 `--map belt --limited-ammo` 두 조건에서 게임 시작 → N 새 맵 → 일시정지 → 재개 → 종료를 자동 입력하고 정상 종료 코드 0을 확인했습니다.
- 이미지 45개·맵 4개의 원본/배포본 해시와 ZIP 무결성을 확인했습니다. 다른 PC에서의 실행은 아직 확인하지 않았습니다.

SHA256:

```text
b10fd14e73af6bdc23c313c0faacd3e90ceda9a4efd1b84458075330cd883bdd
```

[[development/README|개발 목차]] · [[getting-started|소스로 실행하기]] · [[README|문서 목차]]

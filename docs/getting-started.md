# 처음 실행하기

## 개발 환경 설치

프로젝트 루트에서 실행합니다. Python 3.10 이상을 사용하며 검증 환경은 Python 3.12입니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m space_z
```

`-e`는 `src/space_z/` 소스를 그대로 참조하는 개발 설치입니다. `pyproject.toml`이 `requirements.txt`의 의존성을 읽습니다. 설치 후 `space-z` 명령도 같은 게임을 실행합니다.

## 실행 옵션

```powershell
python -m space_z --seed 42
python -m space_z --map belt
python -m space_z --random-map
python -m space_z --no-terrain
python -m space_z --stage2
python -m space_z --limited-ammo
```

기본은 랜덤 블록 지형·탄약 무제한입니다. `--limited-ammo`로 탄창·재장전을 활성화합니다. 인게임 N은 새 8×8 블록 맵으로 새 판을 시작합니다. 고정 seed인 경우 N마다 seed를 하나 증가시키며 일반 재시작은 현재 seed를 유지합니다.

## 화면 없이 환경 사용

```python
from space_z.rl.environment import TankEnv

environment = TankEnv()
observation, information = environment.reset(seed=42)
observation, reward, terminated, truncated, information = environment.step(0)
```

Gymnasium 연동이 필요하면 `python -m pip install -e ".[rl]"`로 선택 의존성을 설치합니다. 현재 실제 모델 학습 프로그램은 없으며 환경·관찰·보상을 제공합니다.

다음: [[game/README|게임 안내]] · [[development/README|개발 안내]] · [[reinforcement-learning/README|강화학습 안내]] · [[README|문서 목차]]

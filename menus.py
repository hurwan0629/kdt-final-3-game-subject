"""메뉴의 표시와 클릭 판정에서 공유하는 버튼 배치."""
from dataclasses import dataclass

import pygame


DIFFICULTY_OPTIONS = (
    ("difficulty_easy", "쉬움", 0.4),
    ("difficulty_normal", "보통", 0.5),
    ("difficulty_hard", "어려움", 0.6),
)


@dataclass(frozen=True)
class MenuButton:
    key: str
    label: str
    rect: pygame.Rect
    enabled: bool = True
    checked: bool = False


def menu_buttons(mode, cfg, show_debug=False, show_controls=True, auto_pause=True,
                 fullscreen=False, size=None, difficulty_ratio=0.5):
    width, height = size or (cfg.width, cfg.height)
    x = width // 2 - 190
    if mode == "main":
        y = height // 2 - 6
        choices = [MenuButton(key, label, pygame.Rect(x + i * 131, y - 68, 118, 46),
                              checked=ratio == difficulty_ratio)
                   for i, (key, label, ratio) in enumerate(DIFFICULTY_OPTIONS)]
        return choices + [
            MenuButton("start", "무한 스테이지", pygame.Rect(x, y, 380, 58)),
            MenuButton("story", "스토리 모드 · 준비 중", pygame.Rect(x, y + 78, 380, 58), False),
            MenuButton("quit", "게임 나가기", pygame.Rect(x, y + 156, 380, 58))]
    rows = [("fullscreen", f"화면 모드   {'전체화면' if fullscreen else '창 모드'}"),
            ("zoom", f"줌 배율   {cfg.camera_zoom:.0%}"),
            ("controls", f"조작 안내   {'켜짐' if show_controls else '꺼짐'}"),
            ("debug", f"디버그 표시   {'켜짐' if show_debug else '꺼짐'}"),
            ("auto_pause", f"창 전환 시 자동 일시정지   {'켜짐' if auto_pause else '꺼짐'}")]
    y = height // 2 - 178
    buttons = [MenuButton(key, label, pygame.Rect(x, y + i * 40, 380, 34))
               for i, (key, label) in enumerate(rows)]
    actions = [("resume", "계속하기"), ("restart", "새 게임"),
               ("main", "메인 메뉴로"), ("quit", "게임 나가기")]
    buttons.extend(MenuButton(key, label, pygame.Rect(x, y + 214 + i * 44, 380, 40))
                   for i, (key, label) in enumerate(actions))
    return buttons

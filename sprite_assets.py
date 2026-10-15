"""PNG 읽기와 변환 캐시. 원본 파일은 수정하지 않는다."""
from functools import lru_cache

import pygame

from config import resource_path


class SpriteAssets:
    def __init__(self):
        self._source = lru_cache(maxsize=32)(self._source)
        self._scaled = lru_cache(maxsize=192)(self._scaled)
        self._rotated = lru_cache(maxsize=512)(self._rotated)

    def _source(self, path):
        image = pygame.image.load(resource_path(f"assets/{path}.png")).convert_alpha()
        if not path.startswith("backgrounds/"):
            image = pygame.transform.smoothscale(image, (256, 256))
        return image

    def _scaled(self, path, width, height):
        return pygame.transform.smoothscale(self._source(path), (width, height))

    def _rotated(self, path, side, angle):
        return pygame.transform.rotate(self._scaled(path, side, side), angle)

    def image(self, path, size, angle=None):
        if isinstance(size, tuple):
            return self._scaled(path, max(1, round(size[0])), max(1, round(size[1])))
        side = max(1, round(size))
        if angle is None:
            return self._scaled(path, side, side)
        return self._rotated(path, side, round(angle / 3) * 3 % 360)

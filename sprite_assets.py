"""PNG 원본과 투명도를 보존하며 화면용 크기·회전을 캐시한다."""
import math
from functools import lru_cache

import numpy as np
import pygame

from config import resource_path


class SpriteAssets:
    def __init__(self):
        self._source = lru_cache(maxsize=64)(self._source)
        self._ship_geometry = lru_cache(maxsize=32)(self._ship_geometry)
        self._ship_base = lru_cache(maxsize=32)(self._ship_base)
        self._scaled = lru_cache(maxsize=192)(self._scaled)
        self._rotated = lru_cache(maxsize=512)(self._rotated)
        self._projectile_geometry = lru_cache(maxsize=8)(self._projectile_geometry)
        self._projectile_base = lru_cache(maxsize=8)(self._projectile_base)
        self._projectile_scaled = lru_cache(maxsize=64)(self._projectile_scaled)
        self._projectile_rotated = lru_cache(maxsize=256)(self._projectile_rotated)

    def _source(self, path):
        return pygame.image.load(resource_path(f"assets/{path}.png")).convert_alpha()

    def _ship_geometry(self, path):
        """회색 포신을 제외한 청록색 선체의 경계와 중심을 구한다."""
        source = self._source(path)
        rgb = pygame.surfarray.array3d(source).astype(np.int16)
        alpha = pygame.surfarray.array_alpha(source)
        hull = ((alpha > 100) & (rgb[:, :, 1] > rgb[:, :, 0] + 30)
                & (rgb[:, :, 2] > rgb[:, :, 0] + 30))
        xs, ys = np.where(hull)
        if not len(xs):
            rect = source.get_bounding_rect()
        else:
            rect = pygame.Rect(int(xs.min()), int(ys.min()),
                               int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
        return (rect.x + rect.width / 2, rect.y + rect.height / 2), max(1, rect.width, rect.height)

    def _ship_base(self, path):
        """카드와 월드에서 같은 선체 중심을 쓴다. 원본 파일은 바꾸지 않는다."""
        source = self._source(path)
        (cx, cy), _ = self._ship_geometry(path)
        visible = source.get_bounding_rect()
        half = max(cx - visible.left, visible.right - cx, cy - visible.top, visible.bottom - cy)
        side = max(2, math.ceil(half) * 2)
        image = pygame.Surface((side, side), pygame.SRCALPHA)
        image.blit(source, (round(side / 2 - cx), round(side / 2 - cy)))
        return image

    def _scaled(self, path, width, height):
        source = self._ship_base(path) if path.startswith("ships/") else self._source(path)
        return pygame.transform.smoothscale(source, (width, height))

    def _rotated(self, path, side, angle):
        return pygame.transform.rotate(self._scaled(path, side, side), angle)

    def image(self, path, size, angle=None):
        if isinstance(size, tuple):
            return self._scaled(path, max(1, round(size[0])), max(1, round(size[1])))
        side = max(1, round(size))
        if angle is None:
            return self._scaled(path, side, side)
        return self._rotated(path, side, round(angle / 3) * 3 % 360)

    def ship_image(self, path, diameter, angle=0):
        """투명 여백과 포신 길이에 관계없이 실선체를 충돌 지름에 맞춘다."""
        _, hull_diameter = self._ship_geometry(path)
        side = diameter * self._ship_base(path).get_width() / hull_diameter
        return self.image(path, side, angle)

    def _projectile_geometry(self, path):
        """발광 여백 대신 불투명한 탄체의 폭을 구한다. 원본은 위쪽을 향한다."""
        source = self._source(path)
        core = source.get_bounding_rect(min_alpha=100)
        if not core.width or not core.height:
            core = source.get_bounding_rect()
        return core

    def _projectile_base(self, path):
        """탄체 주변의 가까운 발광만 보존해 큰 투명 캔버스의 확대를 피한다."""
        source = self._source(path)
        core = self._projectile_geometry(path)
        halo = max(1, round(core.width * 0.7))
        rect = core.inflate(halo * 2, halo)
        rect.clamp_ip(source.get_rect())
        rect = rect.clip(source.get_rect())
        # 실제 탄체 중심을 표면 중앙에 둬 물리 좌표와 그림을 맞춘다.
        center = (core.x + core.width / 2, core.y + core.height / 2)
        half_width = math.ceil(max(center[0] - rect.left, rect.right - center[0]))
        half_height = math.ceil(max(center[1] - rect.top, rect.bottom - center[1]))
        image = pygame.Surface((max(2, half_width * 2), max(2, half_height * 2)), pygame.SRCALPHA)
        # area 잘라내기는 런타임 표면에서만 수행하며 원본 RGBA는 그대로 둔다.
        image.blit(source, (round(half_width + rect.left - center[0]),
                            round(half_height + rect.top - center[1])), rect)
        return image

    def _projectile_scaled(self, path, diameter):
        base = self._projectile_base(path)
        core = self._projectile_geometry(path)
        scale = diameter / max(1, core.width)
        return pygame.transform.smoothscale(base, (max(1, round(base.get_width() * scale)),
                                                   max(1, round(base.get_height() * scale))))

    def _projectile_rotated(self, path, diameter, angle):
        return pygame.transform.rotate(self._projectile_scaled(path, diameter), angle)

    def projectile_image(self, path, diameter, angle=None):
        """실제 탄체 폭을 지정 지름에 맞추고 위쪽 원본을 발사 방향으로 회전한다."""
        diameter = max(1, round(diameter))
        if angle is None:
            return self._projectile_scaled(path, diameter)
        return self._projectile_rotated(path, diameter, round(angle / 3) * 3 % 360)

"""PNG 원본과 투명도를 보존하며 화면용 크기·회전을 캐시한다."""
import math
from functools import lru_cache

import numpy as np
import pygame

from space_z.resource_paths import resource_path
from space_z.config.progression_definitions import BARREL_OVERRIDES

ENEMY_SUFFIX = "@enemy"   # "ships/Lv10_트윈@enemy" → 같은 그림의 청록 선체를 붉은색으로 바꿔 쓴다
ELITE_SUFFIX = "@elite"   # 엘리트 적은 금색 선체
HULL_TINTS = {ENEMY_SUFFIX: (1.0, 0.32, 0.35), ELITE_SUFFIX: (1.0, 0.72, 0.18)}


def _hull_mask(rgb, alpha):
    return (alpha > 100) & (rgb[:, :, 1] > rgb[:, :, 0] + 30) & (rgb[:, :, 2] > rgb[:, :, 0] + 30)


def _recolor_hull(image, tint):
    """청록색 선체와 테두리만 같은 밝기의 다른 색으로 바꾼다. 회색 포신은 그대로."""
    image = image.copy()
    rgb = pygame.surfarray.pixels3d(image)
    src = rgb.astype(np.float32)
    teal = (src[:, :, 2] - src[:, :, 0]) > 20
    value = src.max(axis=2)
    # 안티에일리어싱된 가장자리는 청록 정도만큼만 섞는다.
    mix = np.clip((src[:, :, 2] - src[:, :, 0]) / 120.0, 0, 1)[..., None] * teal[..., None]
    color = np.stack([value * k for k in tint], axis=2)
    rgb[...] = (src * (1 - mix) + color * mix).astype(np.uint8)
    del rgb
    return image


def _redraw_barrel(image, forward, inner):
    """원본의 작은 회색 포신을 지우고 같은 그림체의 굵은 포신을 선체 아래에 그린다."""
    rgb = pygame.surfarray.array3d(image).astype(np.int16)
    alpha = pygame.surfarray.array_alpha(image)
    xs, ys = np.where(_hull_mask(rgb, alpha))
    cx, cy = (xs.min() + xs.max() + 1) / 2, (ys.min() + ys.max() + 1) / 2
    radius = max(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1) / 2
    hull = image.copy()
    gray = (np.abs(rgb[:, :, 0] - rgb[:, :, 1]) < 25) & (np.abs(rgb[:, :, 1] - rgb[:, :, 2]) < 25)
    hull_alpha = pygame.surfarray.pixels_alpha(hull)
    hull_alpha[gray & (alpha > 0)] = 0
    del hull_alpha
    out = pygame.Surface(image.get_size(), pygame.SRCALPHA)
    edge = max(2, round(radius * 0.08))
    half = inner * radius + edge
    tip = forward * radius
    outer = pygame.Rect(0, 0, round(tip), round(2 * half))
    outer.midleft = (round(cx), round(cy))
    pygame.draw.rect(out, (85, 85, 85), outer, border_radius=edge)
    pygame.draw.rect(out, (153, 153, 153), outer.inflate(-2 * edge, -2 * edge))
    out.blit(hull, (0, 0))
    return out


class SpriteAssets:
    def __init__(self):
        self._source = lru_cache(maxsize=96)(self._source)
        self._ship_geometry = lru_cache(maxsize=32)(self._ship_geometry)
        self._ship_base = lru_cache(maxsize=32)(self._ship_base)
        self._scaled = lru_cache(maxsize=192)(self._scaled)
        self._rotated = lru_cache(maxsize=512)(self._rotated)
        self._projectile_geometry = lru_cache(maxsize=8)(self._projectile_geometry)
        self._projectile_base = lru_cache(maxsize=8)(self._projectile_base)
        self._projectile_scaled = lru_cache(maxsize=64)(self._projectile_scaled)
        self._projectile_rotated = lru_cache(maxsize=256)(self._projectile_rotated)

    def _source(self, path):
        for suffix, tint in HULL_TINTS.items():
            if path.endswith(suffix):
                return _recolor_hull(self._source(path[:-len(suffix)]), tint)
        image = pygame.image.load(resource_path(f"assets/{path}.png")).convert_alpha()
        if path.startswith(("etc/guard_", "etc/home_")):
            # 장애물·버튼은 큰 투명 여백을 제외한 실제 그림을 표시 영역에 맞춘다.
            image = image.subsurface(image.get_bounding_rect()).copy()
        if path in BARREL_OVERRIDES:
            image = _redraw_barrel(image, *BARREL_OVERRIDES[path])
        return image

    def _ship_geometry(self, path):
        """회색 포신을 제외한 청록색 선체의 경계와 중심을 구한다."""
        for suffix in HULL_TINTS:  # 색을 바꾼 적 그림도 원본 선체 기준을 쓴다
            if path.endswith(suffix):
                return self._ship_geometry(path[:-len(suffix)])
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

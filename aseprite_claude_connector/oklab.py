"""sRGB <-> OKLab, a colour space where equal steps look about equally different."""

from __future__ import annotations

import functools


def _linear(v: int) -> float:
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _gamma(v: float) -> int:
    v = v * 12.92 if v <= 0.0031308 else 1.055 * max(v, 0.0) ** (1 / 2.4) - 0.055
    return min(255, max(0, round(v * 255)))


@functools.lru_cache(maxsize=1 << 16)
def to_lab(c: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = _linear(c[0]), _linear(c[1]), _linear(c[2])
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def to_rgb(lab: tuple[float, float, float]) -> tuple[int, int, int]:
    L, a, b = lab
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        _gamma(4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_),
        _gamma(-1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_),
        _gamma(-0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_),
    )

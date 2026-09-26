#!/usr/bin/env python3
"""PNG 墨迹包围盒（纯标准库实现：zlib 解码 + 逐行反滤波，零第三方依赖）。

用途：判断一张图「在纸面上会不会小到看不清」。画布尺寸由渲染器给，但内容可能只占
画布一角——这种图插进文档后，图内文字会被整体缩得极小。只看画布尺寸查不出来，
必须扫像素。见 gen_diagrams.py 的 INK_MIN_WIDTH_RATIO。

只用在本项目自己生成的 PNG 上（Chrome headless 截图：8bit、非隔行、RGB/RGBA），
遇到不支持的类型直接抛错，不静默返回错误结果。
"""
from __future__ import annotations

import struct
import zlib

_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}   # 灰度 / RGB / 灰度+alpha / RGBA
_WHITE = 245                            # 三通道都大于它算白底；抗锯齿边缘不算墨迹


def decode(path) -> tuple[int, int, int, bytearray]:
    """解出 (宽, 高, 通道数, 逐像素字节)。path 可以是路径，也可以直接是 PNG 字节。"""
    data = path if isinstance(path, (bytes, bytearray)) else open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"不是 PNG：{path}")

    pos, idat, header = 8, bytearray(), None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk)
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break

    if header is None:
        raise ValueError(f"缺 IHDR：{path}")
    w, h, depth, color, _comp, _filt, interlace = header
    if depth != 8 or interlace != 0 or color not in _CHANNELS:
        raise ValueError(f"只支持 8bit 非隔行的灰度/RGB/RGBA：{path}（depth={depth} "
                         f"color={color} interlace={interlace}）")

    nch = _CHANNELS[color]
    stride = w * nch
    raw = zlib.decompress(bytes(idat))
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p : p + stride])
        p += stride
        if ft == 1:      # Sub
            for i in range(nch, stride):
                line[i] = (line[i] + line[i - nch]) & 0xFF
        elif ft == 2:    # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:    # Average
            for i in range(stride):
                a = line[i - nch] if i >= nch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:    # Paeth
            for i in range(stride):
                a = line[i - nch] if i >= nch else 0
                b = prev[i]
                c = prev[i - nch] if i >= nch else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ft != 0:
            raise ValueError(f"未知 PNG 滤波类型 {ft}（{path} 第 {y} 行）")
        out[y * stride : (y + 1) * stride] = line
        prev = line
    return w, h, nch, out


def ink_bbox(path) -> tuple[int, int, int, int]:
    """返回非白像素的包围盒 (x0, y0, x1, y1)，闭区间；整张全白时抛错。"""
    return ink_coverage(path)[2]


def ink_coverage(path) -> tuple[float, float, tuple[int, int, int, int]]:
    """返回 (墨迹宽/画布宽, 墨迹高/画布高, 包围盒)。只解码一次。"""
    w, h, nch, px = decode(path)
    stride = w * nch
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        base = y * stride
        for x in range(w):
            o = base + x * nch
            if nch == 4 and px[o + 3] < 16:
                continue
            if px[o] > _WHITE and px[o + 1] > _WHITE and px[o + 2] > _WHITE:
                continue
            if x < x0:
                x0 = x
            if x > x1:
                x1 = x
            if y < y0:
                y0 = y
            if y > y1:
                y1 = y
    if x1 < 0:
        raise ValueError(f"整张图没有非白像素（全白？）：{path}")
    return (x1 - x0 + 1) / w, (y1 - y0 + 1) / h, (x0, y0, x1, y1)


def main() -> int:
    import sys

    for path in sys.argv[1:]:
        cw, ch, (x0, y0, x1, y1) = ink_coverage(path)
        w, h, _nch, _px = decode(path)
        print(f"{path}\n  画布 {w}x{h}  墨迹 {x1 - x0 + 1}x{y1 - y0 + 1}"
              f"  占宽 {cw:.1%}  占高 {ch:.1%}"
              f"  留白 左{x0} 上{y0} 右{w - 1 - x1} 下{h - 1 - y1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

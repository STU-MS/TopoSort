#!/usr/bin/env python3
"""从 Word 97-2003（OLE2 复合文档，.doc）中提取纯文本。

为什么自己写：环境里没有 antiword / catdoc / libreoffice / pandoc，而老师的原始
作业文件（docs/assignment.doc、report-template.doc、meeting-minutes-template.doc）
都是 OLE2 二进制格式，需要读里面的要求与模板结构。

实现要点（不依赖任何第三方库）：
  1) 解析 CFB（复合文件）结构，取出 WordDocument 与 0Table/1Table 两个流；
  2) 按 FIB 的 fcClx/lcbClx 找到分片表（piece table），正确区分
     「8 位压缩片」与「UTF-16 片」——只按字节猜编码会在中英混排处错位；
  3) 压缩片按文档声明的代码页解码（本项目三个文件分别是 936 与 1200）。

用法：
    uv run python tools/extract_doc.py docs/assignment.doc
    uv run python tools/extract_doc.py docs/*.doc --out /tmp/docs.txt
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD


class Cfb:
    """最小可用的 OLE2 / CFB 读取器。"""

    def __init__(self, data: bytes) -> None:
        if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ValueError("不是 OLE2 复合文档（签名不符）")
        self.data = data
        self.sector_size = 1 << struct.unpack_from("<H", data, 0x1E)[0]
        self.mini_size = 1 << struct.unpack_from("<H", data, 0x20)[0]
        self.first_dir = struct.unpack_from("<I", data, 0x30)[0]
        self.cutoff = struct.unpack_from("<I", data, 0x38)[0]
        self.first_minifat = struct.unpack_from("<I", data, 0x3C)[0]
        self.num_minifat = struct.unpack_from("<I", data, 0x40)[0]
        self.first_difat = struct.unpack_from("<I", data, 0x44)[0]
        self.num_difat = struct.unpack_from("<I", data, 0x48)[0]
        self.fat = self._load_fat()
        self.minifat = self._load_minifat()
        self.entries = self._load_dir()
        root = next(e for e in self.entries if e["type"] == 5)
        self.mini_stream = self._read_chain(root["start"], root["size"], mini=False)

    def _sector(self, n: int) -> bytes:
        off = 512 + n * self.sector_size
        return self.data[off:off + self.sector_size]

    def _load_fat(self) -> list[int]:
        # DIFAT：头里 109 个，不够则沿 DIFAT 扇区链继续
        difat = list(struct.unpack_from("<109I", self.data, 0x4C))
        sec = self.first_difat
        for _ in range(self.num_difat):
            if sec in (FREESECT, ENDOFCHAIN):
                break
            raw = self._sector(sec)
            vals = struct.unpack_from(f"<{self.sector_size // 4}I", raw, 0)
            difat.extend(vals[:-1])
            sec = vals[-1]
        fat: list[int] = []
        for s in difat:
            if s in (FREESECT, ENDOFCHAIN, FATSECT):
                continue
            raw = self._sector(s)
            fat.extend(struct.unpack_from(f"<{self.sector_size // 4}I", raw, 0))
        return fat

    def _load_minifat(self) -> list[int]:
        out: list[int] = []
        sec = self.first_minifat
        for _ in range(self.num_minifat):
            if sec in (FREESECT, ENDOFCHAIN):
                break
            raw = self._sector(sec)
            out.extend(struct.unpack_from(f"<{self.sector_size // 4}I", raw, 0))
            sec = self.fat[sec] if sec < len(self.fat) else ENDOFCHAIN
        return out

    def _load_dir(self) -> list[dict]:
        raw = self._read_chain(self.first_dir, None, mini=False)
        entries = []
        for i in range(0, len(raw) - 127, 128):
            e = raw[i:i + 128]
            nlen = struct.unpack_from("<H", e, 0x40)[0]
            name = e[:max(0, nlen - 2)].decode("utf-16-le", "replace") if nlen >= 2 else ""
            entries.append({
                "name": name,
                "type": e[0x42],
                "start": struct.unpack_from("<I", e, 0x74)[0],
                "size": struct.unpack_from("<Q", e, 0x78)[0],
            })
        return entries

    def _read_chain(self, start: int, size: int | None, mini: bool) -> bytes:
        fat = self.minifat if mini else self.fat
        unit = self.mini_size if mini else self.sector_size
        out = bytearray()
        sec = start
        guard = 0
        while sec not in (FREESECT, ENDOFCHAIN) and guard < 10_000_000:
            guard += 1
            if mini:
                off = sec * unit
                out += self.mini_stream[off:off + unit]
            else:
                out += self._sector(sec)
            if sec >= len(fat):
                break
            sec = fat[sec]
        return bytes(out[:size]) if size is not None else bytes(out)

    def stream(self, name: str) -> bytes:
        e = next((x for x in self.entries if x["name"] == name and x["type"] == 2), None)
        if e is None:
            raise KeyError(f"没有流 {name!r}；现有：{[x['name'] for x in self.entries]}")
        mini = e["size"] < self.cutoff
        return self._read_chain(e["start"], e["size"], mini=mini)


def extract_text(doc_path: Path) -> str:
    cfb = Cfb(doc_path.read_bytes())
    wd = cfb.stream("WordDocument")

    flags = struct.unpack_from("<H", wd, 0x0A)[0]
    table_name = "1Table" if (flags & 0x0200) else "0Table"
    try:
        table = cfb.stream(table_name)
    except KeyError:
        table = b""

    fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)
    if not lcb_clx or fc_clx + lcb_clx > len(table):
        # 退化：老式文档没有分片表，正文就是 fcMin..fcMac 的 8 位文本
        fc_min, fc_mac = struct.unpack_from("<II", wd, 0x18)
        return wd[fc_min:fc_mac].decode("gbk", "replace")

    clx = table[fc_clx:fc_clx + lcb_clx]
    # 跳过若干 Prc（0x01 开头），找到 Pcdt（0x02）
    i = 0
    while i < len(clx) and clx[i] == 0x01:
        cb = struct.unpack_from("<h", clx, i + 1)[0]
        i += 3 + cb
    if i >= len(clx) or clx[i] != 0x02:
        raise ValueError("分片表结构无法识别（未找到 Pcdt）")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]

    n = (len(plc) - 4) // 12          # 每片 8 字节 PCD，CP 数组比 PCD 多一个
    cps = list(struct.unpack_from(f"<{n + 1}I", plc, 0))
    out: list[str] = []
    for k in range(n):
        pcd = plc[4 * (n + 1) + 8 * k: 4 * (n + 1) + 8 * k + 8]
        fc = struct.unpack_from("<I", pcd, 2)[0]
        nchars = cps[k + 1] - cps[k]
        if fc & 0x40000000:            # 8 位压缩片（按代码页 936/GBK）
            off = (fc & 0x3FFFFFFF) // 2
            out.append(wd[off:off + nchars].decode("gbk", "replace"))
        else:                          # UTF-16LE 片
            out.append(wd[fc:fc + nchars * 2].decode("utf-16-le", "replace"))
    return "".join(out)


def main() -> int:
    # Windows 控制台默认非 UTF-8，直接打印中文会崩（build.py 踩过同一个坑）
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="提取 Word 97-2003 .doc 的纯文本")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, help="汇总输出到文件（默认打印到 stdout）")
    args = ap.parse_args()

    chunks = []
    for f in args.files:
        try:
            text = extract_text(f)
        except Exception as exc:                      # noqa: BLE001
            print(f"❌ {f}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        header = f"{'=' * 70}\n{f}\n{'=' * 70}"
        chunks.append(f"{header}\n{text.strip()}\n")
        print(f"✅ {f}（{len(text)} 字符）", file=sys.stderr)

    body = "\n".join(chunks)
    if args.out:
        args.out.write_text(body, encoding="utf-8", newline="")
        print(f"已写入 {args.out}", file=sys.stderr)
    else:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

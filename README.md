# TopoSort — 拓扑排序应用软件

> CST4823A 高级算法原理实践 · 小组课程项目

输入 `<a,b>` 先修关系 → 有向图分层渲染 → **动画演示排序全过程**（候选队列、节点逐个消耗、分叉点多路并推）→ 输出尽可能多的拓扑序列（界面按上限 2000 条列出，超限时如实给出总数估算），含环检测。

## 新成员 / AI 代理请先读这两份

1. **[AGENTS.md](AGENTS.md)** — 项目最高规范（仓库结构、留档规则、开发红线）
2. **[CONTRIBUTING.md](CONTRIBUTING.md)** — 协作速查

## 技术栈

| 项 | 选择 | 备注 |
|---|---|---|
| 语言 | Python 3.11+ | |
| GUI | PySide6（QGraphicsView） | 动画完全可控 |
| 打包 | PyInstaller | 三端产物：Windows/Linux 单文件，macOS onedir + .app（三端均由 CI 构建） |
| **工程管理** | **uv（唯一标准）** | 依赖、虚拟环境、运行、测试全走 uv |
| 测试 | pytest | 用例数据在 `evidence/test-data/` |

决策记录：`evidence/decisions/` · [Issue #1](https://github.com/STU-MS/TopoSort/issues/1)

最新产物与演示视频请到 [发布页](https://github.com/STU-MS/TopoSort/releases/latest) 下载。

## 快速开始（uv，唯一姿势）

```bash
# 0. 装 uv（仅需一次）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 1. 克隆 + 创建虚拟环境 + 安装依赖（uv.lock 锁定版本，所见即所得）
git clone git@github.com:STU-MS/TopoSort.git && cd TopoSort
uv sync

# 2. 运行
uv run python app/main.py

# 3. 测试
uv run pytest

# 4. 打包单文件（产物在 dist/，需在目标平台上各自构建：Windows 产物走 GitHub Actions）
uv run python tools/build.py
```

> ⚠️ 本项目**禁止** `pip install` 裸装依赖：加依赖 = 改 `pyproject.toml` → `uv add 包名` → 提交 `uv.lock`。
> 三端通用：不要使用平台专属 API，路径用 `pathlib`，文件读写显式 UTF-8（详见 AGENTS.md）。

## 平台支持

| 平台 | 开发 | 打包 | 说明 |
|---|---|---|---|
| Windows | ✅ | ✅ CI 产出 | Actions windows-latest 构建，随产物附 SHA256 |
| macOS | ✅ | ✅ CI 产出 | onedir + .app，随产物附 SHA256 |
| Linux | ✅ | ✅ CI 产出 | 随产物附 SHA256 |

## 仓库结构

```
├── app/            # 源码（models / events / scene / ui / main）
├── submission/     # ★ 唯一正式提交材料目录（报告/会议记录/个人感想/测试用例/视频/可执行程序）
├── deliverables/   # 过程文档/素材（分章 md 与 docx/pdf 中间产物，非提交目录）
├── minutes/        # 会议记录（源为 YYYY-MM-DD-主题.md，套老师模板出 docx/pdf）
├── evidence/       # ★ 素材库：决策/截图/性能数据/测试数据（只进不改）
├── tools/          # 辅助脚本
├── report/         # 报告构建输入（老师模板 docx + mermaid 图源 + 演示数据）
└── docs/           # 老师下发的原始作业文件（只读）
```

## 红线（详见 AGENTS.md）

- 算法（Kahn 排序、全序枚举、环检测）**必须自研**，禁用 networkx 等现成实现
- 决策必须留档：issue → `evidence/decisions/`
- 完成可见功能立刻截图进 `evidence/screenshots/`

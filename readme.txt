TopoSort —— 拓扑排序动画演示程序
交付说明 / 三端运行与构建指南
================================================================================
版本：0.1.0            整理日期：2026-09-21
仓库：https://github.com/STU-MS/TopoSort
打包方式：PyInstaller --onefile（单文件，双击即跑，目标机无需安装 Python）


一、这是什么
--------------------------------------------------------------------------------
输入若干先修关系（形如 <A,C>），程序会：

  * 解析输入并画成分层有向图；
  * 动画演示 Kahn 拓扑排序的全过程（节点消耗、候选池变化、分叉多路伪并发泳道）；
  * 输出所有合法拓扑序，并给出条数；
  * 检测环并明确指出卡住的节点；
  * 支持调速 / 暂停 / 单步 / 跳完，结果可导出 txt、画面可导出 png。

算法（Kahn 排序、全序枚举、环检测）为自研实现，未使用 networkx 等现成排序库。


二、最快上手（三端）
--------------------------------------------------------------------------------

【Windows】
  1) 把 TopoSort.exe（本版 CI 产物名为 main.exe，见第五节说明）放到任意目录，双击运行。
     首次启动可能等待 3~10 秒（单文件模式需要先自解压），属正常现象。
  2) 若被 SmartScreen 拦截：点「更多信息」→「仍要运行」。
  3) 校验完整性（PowerShell）：
         Get-FileHash .\TopoSort.exe -Algorithm SHA256
     与第四节的官方值逐字符比对。

【macOS】
  1) 产物是 TopoSort.app（双击运行）或同目录下的单文件 TopoSort（终端执行）。
  2) 首次打开若提示「无法验证开发者」：
         xattr -dr com.apple.quarantine TopoSort.app
     然后重新双击；或在「系统设置 → 隐私与安全性」中点「仍要打开」。
  3) 校验完整性：
         shasum -a 256 TopoSort.app/Contents/MacOS/TopoSort

【Linux】
  1) 给可执行权限后运行：
         chmod +x TopoSort
         ./TopoSort
  2) 若报缺少 Qt 系统库（精简发行版/容器常见）：
         sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libdbus-1-3
     （RPM 系对应包名：libglvnd-egl / mesa-libGL / libxkbcommon / dbus-libs）
  3) 校验完整性：
         sha256sum TopoSort


三、从源码构建（三端）
--------------------------------------------------------------------------------

前置条件：已安装 uv（https://docs.astral.sh/uv/）。目标机不需要预装 Python——
uv 会按 pyproject.toml 的 requires-python 自行准备解释器。

    uv sync                          # 装依赖（含 dev 组的 pyinstaller，版本由 uv.lock 锁定）
    uv run pytest                    # 自检：应全部通过
    uv run python tools/build.py     # 打包，产物落在 dist/

常用开关：

    uv run python tools/build.py --smoke
        打包后追加「空目录启动冒烟」：把产物拷到临时空目录，剥离
        PYTHONPATH/PYTHONHOME/VIRTUAL_ENV 等变量，以 offscreen 方式启动并
        断言其进入事件循环、stderr 无异常。CI 与本机验证都用它。

    uv run python tools/build.py --console
        保留控制台窗口（Windows/macOS 排查「双击没反应」时用，能看到报错）。

    uv run python tools/build.py --no-optimize --no-strip
        关闭体积优化，用于体积对照实测（见 evidence/benchmarks.csv）。

    uv run python tools/build.py --distpath /tmp/out --workpath /tmp/work
        自定义产物/中间目录（默认 dist/ 与 build/）。

★ 关键限制：单文件产物**不能跨平台交叉打包**。
    Windows 的 .exe 必须在 Windows 上构建（本仓库由 GitHub Actions 的
    windows-latest 自动产出）；macOS 的产物必须在 macOS 上构建。
    三个平台各自执行同一条命令 `uv run python tools/build.py`，参数完全一致——
    平台差异（--windowed / 产物扩展名 / .app 结构）已在脚本内部处理。


四、产物清单与校验值（本版实测）
--------------------------------------------------------------------------------

  平台     产物                     体积            SHA256
  -------  -----------------------  --------------  ----------------------------------------------------------------
  Linux    dist/TopoSort            71,363,616 B    04350def389445214c52b9730fff7f128bf3b9f5c87e783b77d55348c57f7b88
                                    (68.1 MB)
  Windows  main.exe（CI artifact）  48,752,547 B    6264f19246260302d1da07e40064f1cf52bdf63cc4e2057a418378ab706112bd
                                    (46.5 MB)
  macOS    —                        —               尚未构建（见下）

  * Linux 产物：2026-09-21 于 Ubuntu 24.04 / x86_64 / Python 3.11.16 / PySide6 6.11.2
    构建，构建耗时约 29.7 s，已通过空目录启动冒烟。
  * Windows 产物：来自 GitHub Actions 运行 35521203523（windows-latest，master 分支），
    其自带的 SHA256.txt 与上表一致，可下载后自行复核。
  * macOS 产物：本项目开发机中无 macOS 环境，尚未构建，故不提供校验值。
    在 macOS 上执行第三节命令即可产出；此项在 Issue #8 中仍未闭环。

  完整的逐字节校验命令（Windows 上为 Get-FileHash，见第二节）。


五、常见问题 FAQ
--------------------------------------------------------------------------------

Q1. Windows 上被杀毒软件 / Defender 报毒，怎么办？
    PyInstaller 的单文件引导器（bootloader）被误报是行业常见现象，并非程序有问题。
    本项目的应对：
      a) 优先使用 GitHub Actions 官方 windows-latest 环境构建的产物（本包内的
         main.exe 即是），而不是在来源不明的机器上自行打包；
      b) 交付包内附 SHA256 校验值，收到产物先校验再运行；
      c) 若仍被拦，把产物目录加入杀软白名单，或改用源码方式运行
         （uv sync && uv run python app/main.py）。

Q2. 双击后要等好几秒才出窗口，是不是卡死了？
    不是。单文件模式启动时，程序会先把内嵌的约 180 MB 运行库解压到系统临时目录，
    因此首次启动（以及每次启动）都有固定开销。缓解办法：
      a) 演示/验收前先启动一次，之后再次启动会快一些（系统文件缓存）；
      b) 不要放在网络盘或杀软实时扫描目录里运行；
      c) 若对启动速度敏感，可改用目录模式分发（本脚本默认单文件，目录模式需另行调整）。

Q3. Linux 上提示 "Could not load the Qt platform plugin xcb" 或缺 .so 文件？
    缺 Qt 依赖的系统库，按第二节 Linux 一节的 apt/dnf 命令补齐即可。
    若在无图形界面的环境（服务器、容器）里验证，请加：
         QT_QPA_PLATFORM=offscreen ./TopoSort

Q4. macOS 提示「无法打开，因为 Apple 无法检查其是否包含恶意软件」？
    产物未做代码签名（本项目无 Apple 开发者证书），按第二节 macOS 一节
    执行 xattr 命令移除隔离属性即可。

Q5. 中文输入 / 中文界面会不会乱码？
    程序内部文件读写一律显式使用 UTF-8（跨平台红线），输入框粘贴中文注释无碍。
    若在 Windows 上用 cmd 重定向输出导致乱码，属控制台代码页问题，不影响程序本身。


六、交付包（zip）组装清单
--------------------------------------------------------------------------------

  [x] 源码（整个仓库，不含 .venv/ build/ dist/ __pycache__/）
  [x] 本文件 readme.txt
  [ ] 三端可执行产物（Linux 已有；Windows 用 CI artifact；macOS 待构建）
  [ ] 文档 PDF：deliverables/00-项目报告 与 01~06 全套转 PDF
  [ ] 演示视频（按 tools/demo_midterm.py 录屏）
  [ ] 会议记录 minutes/
  [ ] evidence/ 素材库（决策、截图、测试数据、benchmarks.csv）
  [ ] 分工表（见 deliverables/00-项目报告）


七、相关留档（可复现性）
--------------------------------------------------------------------------------

  打包与体积优化决策：evidence/decisions/2026-09-21-打包发布方案.md
  性能与产物体积数据：evidence/benchmarks.csv（append-only，勿改旧行）
  技术栈定案：        evidence/decisions/2026-09-15-技术栈定案.md
  打包脚本：          tools/build.py（三端一致入口，参数与 excludes 均封装在内）
  任务单：            GitHub Issue #8（T7 打包发布）
================================================================================

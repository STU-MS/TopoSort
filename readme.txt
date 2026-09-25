TopoSort —— 拓扑排序动画演示程序
交付说明 / 三端运行与构建指南
================================================================================
版本：0.1.0            整理日期：2026-09-21
组别：第一组            交付包：group01.zip
仓库：https://github.com/STU-MS/TopoSort
发布页：https://github.com/STU-MS/TopoSort/releases/tag/v0.1.0
打包方式：PyInstaller 单文件（Linux/Windows）/ onedir + .app（macOS），
          目标机无需安装 Python


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
推荐直接从发布页下载对应产物（比自行构建省事）：
    https://github.com/STU-MS/TopoSort/releases/tag/v0.1.0

【Windows】
  1) 下载 TopoSort.exe，放到任意目录，双击运行。
     首次启动可能等待 3~10 秒（单文件模式需先自解压），属正常现象。
  2) 若被 SmartScreen 拦截：点「更多信息」→「仍要运行」。
  3) 校验完整性（PowerShell）：
         Get-FileHash .\TopoSort.exe -Algorithm SHA256
     与随产物下载的 TopoSort.exe.sha256 逐字符比对（见第四节）。

【macOS】
  1) 下载 TopoSort-macos.zip 并解压，得到 TopoSort.app，双击运行。
  2) 首次打开若提示「无法验证开发者」（产物为 ad-hoc 签名、无 Apple 证书）：
         xattr -dr com.apple.quarantine TopoSort.app
     然后重新双击；或在「系统设置 → 隐私与安全性」中点「仍要打开」。
  3) 校验完整性：
         shasum -a 256 TopoSort-macos.zip
  4) macOS 采用 onedir 打包（不是单文件），因此**启动无需解压**，比 Windows 版快。
     原因见第七节：PyInstaller 已弃用 macOS 的 onefile+windowed 组合。

【Linux】
  1) 下载 TopoSort，给可执行权限后运行：
         chmod +x TopoSort
         ./TopoSort
  2) 若报缺少 Qt 系统库（精简发行版/容器常见）：
         sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libdbus-1-3
     （RPM 系对应包名：libglvnd-egl / mesa-libGL / libxkbcommon / dbus-libs）
  3) 校验完整性：
         sha256sum -c TopoSort.sha256


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

    uv run python tools/build.py --mode onefile|onedir
        指定打包模式。默认 macOS 为 onedir、其余为 onefile。

    uv run python tools/build.py --no-optimize --no-strip
        关闭体积优化，用于体积对照实测（见 evidence/benchmarks.csv）。

    uv run python tools/build.py --distpath /tmp/out --workpath /tmp/work
        自定义产物/中间目录（默认 dist/ 与 build/）。

关键限制：产物**不能跨平台交叉打包**。
    Windows 的 .exe 必须在 Windows 上构建，macOS 的 .app 必须在 macOS 上构建。
    本项目的三份产物由 GitHub Actions 的 ubuntu / macos / windows 三个 runner
    各自执行**同一条命令**产出（.github/workflows/release.yml），
    平台差异（--windowed / 产物扩展名 / macOS onedir+.app / ditto 打 zip）
    全部封装在 tools/build.py 内部。


四、产物清单与校验值（v0.1.0 发布实测）
--------------------------------------------------------------------------------
  平台     产物                  体积          SHA256
  -------  --------------------  ------------  ----------------------------------------------------------------
  Linux    TopoSort              67,121,240 B  4b01313c0fd21c929e1350f57cf3aa7637cfbb0046c8ab38e77b6ad82567daf9
                                 (64.0 MB)
  Windows  TopoSort.exe          48,753,119 B  0691424b1ba2aa3157a6850a0b37dacebfef7adaf098272ff00021a042679ff4
                                 (46.5 MB)
  macOS    TopoSort-macos.zip    36,649,790 B  d13b8d8eb4cd30337899050ec6537b114d4d1d379558593ed72641f8e619a4dc
           （内含 .app，          (35.0 MB)
             解压后约 96.9 MB）

  以上三份均由 GitHub Actions 运行 35620768539（tag v0.1.0）产出，
  每个产物都附带同名 .sha256 文件，可直接用系统校验命令复核（见第二节）。

  重要：**不要拿本文件里写死的 SHA256 去校验你自己重新构建的产物。**
     PyInstaller 的单文件产物**不是字节可复现的**：本机用完全相同参数连续构建三次，
     得到 71,363,616 / 71,363,600 / 71,363,768 三种不同字节数与三个不同哈希
     （PyInstaller 的 SOURCE_DATE_EPOCH 只影响 Windows 的 PE 时间戳，救不了这点）。
     因此校验值只能「这次构建的产物配这次发布的哈希」——
     请以发布页里与产物一同下载的 .sha256 文件为准。


五、常见问题 FAQ
--------------------------------------------------------------------------------
Q1. Windows 上被杀毒软件 / Defender 报毒，怎么办？
    PyInstaller 的单文件引导器（bootloader）被误报是行业常见现象，并非程序有问题。
    本项目的应对：
      a) 优先使用 GitHub Actions 官方 windows-latest 环境构建的产物（发布页里即是），
         而不是在来源不明的机器上自行打包；
      b) 每个产物都附 .sha256 校验文件，收到先校验再运行；
      c) 若仍被拦，把产物目录加入杀软白名单，或改用源码方式运行
         （uv sync && uv run python app/main.py）。

Q2. 双击后要等好几秒才出窗口，是不是卡死了？
    不是。Windows/Linux 版是单文件模式，启动时会先把内嵌的约 180 MB 运行库
    解压到系统临时目录，因此每次启动都有固定开销。缓解办法：
      a) 演示/验收前先启动一次，之后再次启动会快一些（系统文件缓存）；
      b) 不要放在网络盘或杀软实时扫描目录里运行；
      c) macOS 版是 onedir（.app 目录），没有解压步骤，启动明显更快。

Q3. Linux 上提示 "Could not load the Qt platform plugin xcb" 或缺 .so 文件？
    缺 Qt 依赖的系统库，按第二节 Linux 一节的 apt/dnf 命令补齐即可。
    若在无图形界面的环境（服务器、容器）里验证，请加：
         QT_QPA_PLATFORM=offscreen ./TopoSort

Q4. macOS 提示「无法打开，因为 Apple 无法检查其是否包含恶意软件」？
    产物未做正式代码签名（本项目无 Apple 开发者证书，仅 PyInstaller 的 ad-hoc 签名），
    按第二节 macOS 一节执行 xattr 命令移除隔离属性即可。

Q5. 在 Windows 上用 cmd 从源码构建时，控制台中文显示乱码？
    程序本身不受影响（内部文件读写一律显式 UTF-8）。这是 Windows 控制台代码页
    不是 UTF-8 导致的显示问题。tools/build.py 已自行把输出切到 UTF-8（否则会直接
    抛 UnicodeEncodeError），若你的终端仍显示乱码，执行 `chcp 65001` 后再运行。

Q6. 中文输入 / 中文界面会不会乱码？
    不会。输入框粘贴中文注释无碍；文件读写与文本导出均为显式 UTF-8。


六、交付包（zip）组装清单
--------------------------------------------------------------------------------
  [x] 源码（整个仓库，不含 .venv/ build/ dist/ __pycache__/）
  [x] 本文件 readme.txt
  [x] 三端可执行产物（Linux / Windows / macOS 均已在 Release v0.1.0 中）
  [ ] 文档 PDF：deliverables/00-项目报告 与 01~06 全套转 PDF
  [ ] 演示视频（按 tools/demo_midterm.py 录屏）
  [ ] 会议记录 minutes/
  [ ] evidence/ 素材库（决策、截图、测试数据、benchmarks.csv）
  [ ] 分工表（见 deliverables/00-项目报告）


七、相关留档（可复现性）
--------------------------------------------------------------------------------
  打包与体积优化决策：evidence/decisions/2026-09-21-打包发布方案.md
  发布流水线决策：    evidence/decisions/2026-09-21-发布流水线（Release）.md
  性能与产物体积数据：evidence/benchmarks.csv（append-only，勿改旧行）
  技术栈定案：        evidence/decisions/2026-09-15-技术栈定案.md
  打包脚本：          tools/build.py（三端一致入口，参数与 excludes 均封装在内）
  发布工作流：        .github/workflows/release.yml
  任务单：            GitHub Issue #8（T7 打包发布）
================================================================================

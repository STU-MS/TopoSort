TopoSort —— 拓扑排序动画演示程序
交付说明 / 三端运行与构建指南
================================================================================
版本：1.0.1            整理日期：2026-09-27
组别：第一组            交付包：group01.zip
仓库：https://github.com/STU-MS/TopoSort
发布页：https://github.com/STU-MS/TopoSort/releases/latest
打包方式：PyInstaller 单文件（Linux/Windows）/ onedir + .app（macOS），
          目标机无需安装 Python


一、这是什么
--------------------------------------------------------------------------------
输入若干先修关系（形如 <A,C>），程序会：

  * 解析输入并画成分层有向图；
  * 动画演示 Kahn 拓扑排序的全过程（节点消耗、候选池变化、分叉多路伪并发泳道）；
  * 输出尽可能多的合法拓扑序（界面按上限 2000 条列出，超限时如实给出总数估算）并给出条数；
  * 检测环并明确指出卡住的节点；
  * 支持调速 / 暂停 / 单步 / 跳完，结果可导出 txt、画面可导出 png。

算法（Kahn 排序、全序枚举、环检测）为自研实现，未使用 networkx 等现成排序库。


二、最快上手（三端）
--------------------------------------------------------------------------------
推荐直接从发布页下载对应产物（比自行构建省事）：
    https://github.com/STU-MS/TopoSort/releases/latest

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
     原因：PyInstaller 已弃用 macOS 的 onefile+windowed 组合
     （evidence/decisions/2026-09-21-打包发布方案.md）。

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
        打包后追加「空目录启动自检」：把产物拷到临时空目录，剥离
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


四、产物清单与校验值
--------------------------------------------------------------------------------
三端产物每次都由 GitHub Actions（.github/workflows/release.yml）在打 tag 时构建并上传
发布页。体积、SHA256、运行号这类随版本变动的数据**一律不写进本文件**，以发布页里
与产物一同下载的 .sha256 文件为准（校验命令见第二节）。

要记住的只有一条：**不要拿旧发布里的 SHA256 去校验新产物，也不要拿它校验你自行重新
构建的产物。** PyInstaller 的单文件产物**不是字节可复现的**：本机用完全相同参数连续
构建三次，得到三种不同字节数与三个不同哈希（PyInstaller 的 SOURCE_DATE_EPOCH 只影响
Windows 的 PE 时间戳，救不了这点）。因此校验值只能「这次构建的产物配这次发布的哈希」
——每个版本发布时自动生成并随产物上传。


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


六、提交材料结构（submission/）
--------------------------------------------------------------------------------
所有正式提交材料集中放在仓库的 `submission/` 目录（唯一入口），结构如下：

  submission/
  ├── readme.txt            本文件（由 tools/build_submission.py 从仓库根同步）
  ├── 00-项目报告.docx       项目报告（套老师下发模板，含分工表、截图、测试用例）
  ├── 高级算法实践-项目报告-Group01.pdf   上者导出的 PDF（最终提交形态，允许改名）
  ├── 会议记录/              5 次组会记录，docx + pdf 各一份
  ├── 个人任务及感想/         5 名组员的个人任务及感想，docx + pdf 各一份
  ├── 可执行程序/            三端产物（不入 git，CI 打包时由 release.yml 注入）
  ├── 测试用例/              12 个可导入数据 txt + 说明.txt（入 git）
  └── 演示视频/              演示视频 mp4（≤50M，走 git LFS）

说明：
  * 报告形态：**docx 为套用老师模板的可编辑版，PDF 为其导出件**，两者内容一致。
  * 会议记录形态：**docx 由 tools/build_minutes.py 在老师下发的《会议记录》模板
    （docs/meeting-minutes-template.doc）副本上原地填内容，PDF 由 tools/minutes_html.py
    用同版式 HTML 打印**；两份产物同出一源（tools/minutes_data.py 解析 minutes/*.md），
    字段与正文逐块一致。
  * `deliverables/` 是写作过程中的素材/过程文档（md 源、分章草稿），
    不是提交目录；`submission/` 才是交给老师的材料。
  * 刷新提交目录：
        uv run python tools/build_submission.py
  * 重新生成提交包（仓库根 group01.zip）：
        uv run python tools/build_submission.py
        uv run python tools/package_deliverables.py
    包内顶层为 `group01/`，含上述各项 + `源程序/`（git 跟踪文件快照）。
    有 pdf 就不留 docx，包内不带 .sha256 与 提交说明.txt（组长定稿，见
    evidence/decisions/2026-09-27-提交包内容定案.md）。


七、交付包（zip）组装清单
--------------------------------------------------------------------------------
  [x] 源码（整个仓库，不含 .venv/ build/ dist/ __pycache__/）
  [x] 本文件 readme.txt
  [x] 三端可执行产物（CI 打包时由 release.yml 注入 可执行程序/）
  [x] 项目报告 PDF（submission/，有 pdf 就不留 docx）
  [x] 会议记录（submission/会议记录/，5 份 pdf）
  [x] 个人任务及感想（submission/个人任务及感想/，5 份 pdf）
  [x] 测试用例（submission/测试用例/，12 个可导入 txt + 说明.txt）
  [x] 演示视频（submission/演示视频/，mp4 走 git LFS）
  [x] evidence/ 素材库（决策、截图、测试数据、benchmarks.csv；在 源程序/ 内一并提交）
  [x] 分工表（见项目报告）


八、相关留档（可复现性）
--------------------------------------------------------------------------------
  打包与体积优化决策：evidence/decisions/2026-09-21-打包发布方案.md
  发布流水线决策：    evidence/decisions/2026-09-21-发布流水线（Release）.md
  交付打包流水线：    evidence/decisions/2026-09-25-交付打包流水线.md
  报告形态定案：      evidence/decisions/2026-09-26-报告改为模板docx交付.md
  会议记录决策：      evidence/decisions/2026-09-26-会议记录改用老师模板.md
  结果上限与估算：    evidence/decisions/2026-09-27-结果上限与总数估算.md
  提交包内容定案：    evidence/decisions/2026-09-27-提交包内容定案.md
  性能与产物体积数据：evidence/benchmarks.csv（append-only，勿改旧行）
  技术栈定案：        evidence/decisions/2026-09-15-技术栈定案.md
  打包脚本：          tools/build.py（三端一致入口，参数与 excludes 均封装在内）
  提交目录脚本：      tools/build_submission.py（刷新 submission/）
  会议记录 docx：     tools/build_minutes.py（套老师会议记录模板填内容）
  会议记录 PDF：      tools/minutes_html.py（同版式 HTML → Chrome 打印）
  提交包脚本：        tools/package_deliverables.py（生成 group01.zip）
  发布工作流：        .github/workflows/release.yml
  任务单：            GitHub Issue #8（T7 打包发布）· #46（提交包定案）
================================================================================

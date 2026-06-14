# 安装指南

> 被 `SKILL.md` 的前置依赖章节引用。首次使用安装一次，之后无需重复。

## 环境要求

| 项目 | 要求 |
|------|------|
| Python | ≥ 3.9（推荐 3.11+） |
| pip | ≥ 23.0（推荐 25.0+） |
| 操作系统 | Windows 10+ / macOS 12+ / Linux（含 X11 或 Wayland） |
| 网络 | 可访问 DMS 内网系统，可连通 PyPI 或公司镜像源 |
| 磁盘 | 至少 500MB 可用（浏览器二进制 ~400MB） |

## Python 安装

> **前置条件：** 本 skill 需要 Python 3.9+。如已安装，请跳过此节。

### ⚡ 一键安装（推荐，自动同意协议）

Agent 检测 Python 缺失时，会根据您的系统自动给出以下命令，**复制粘贴即可一键安装**：

| 系统 | 一键安装命令 | 说明 |
|------|-------------|------|
| **Windows** | `winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements` | Microsoft 官方包源 |
| **macOS** | `brew install python@3.11` | 需 Homebrew（未安装见下方） |
| **Linux** | `sudo apt install python3.11 python3-pip` | Debian/Ubuntu；CentOS 用 `sudo dnf install python3` |

> **Windows 备用方案：** 如 `winget` 不可用，手动下载安装包并勾选 "Add Python to PATH"（见下方）。
> **macOS 备用方案：** 如 Homebrew 未安装，访问 [python.org/downloads](https://www.python.org/downloads/) 下载 `.pkg` 安装包。
> **安装完成后请新开终端窗口**再运行 `python --version` 验证。

### Windows

**方式一：官网下载（推荐）**

1. 访问 https://www.python.org/downloads/
2. 下载 Python 3.11+ 安装包
3. 运行安装程序，**务必勾选** "Add Python to PATH"
4. 验证：打开命令提示符，运行 `python --version`

**方式二：Microsoft Store**

```powershell
# PowerShell 中执行
winget install Python.Python.3.11
```

**方式三：conda（数据科学用户）**

```bash
conda create -n dms python=3.11
conda activate dms
```

### macOS

**方式一：Homebrew（推荐）**

```bash
brew install python@3.11
```

**方式二：官网下载**

1. 访问 https://www.python.org/downloads/
2. 下载 macOS 安装包（.pkg）
3. 双击安装

**方式三：pyenv（多版本管理）**

```bash
brew install pyenv
pyenv install 3.11.0
pyenv global 3.11.0
```

### Linux

**Ubuntu / Debian：**

```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip
```

**CentOS / RHEL：**

```bash
sudo dnf install python3.11
```

**Arch Linux：**

```bash
sudo pacman -S python python-pip
```

### 验证安装

```bash
python --version    # 应显示 Python 3.9+
pip --version       # 应显示 pip 23.0+
```

> **Windows 注意：** 如果 `python` 命令无法识别，尝试 `py` 或 `python3`。

## 安装步骤

建议在**虚拟环境**中安装，避免污染系统级 Python：

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# 或 .venv\Scripts\activate       # Windows

# 2. 升级 pip
python -m pip install --upgrade pip

# 3. 安装依赖（使用国内镜像源加速）
pip install playwright==1.52.0 openpyxl==3.1.5 -i https://mirrors.aliyun.com/pypi/simple/

# 4. 安装 Playwright Chromium 浏览器（关键，~400MB）
# Windows:
set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright && playwright install chromium
# Linux/macOS:
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright && playwright install chromium

# 5. 验证（推荐使用统一检查脚本）
python check_environment.py

# 或仅检查凭据和浏览器（快速模式）
python check_environment.py --quick
```

### 验证方式

**方式一：统一检查脚本（推荐）**

```bash
# 完整检查（5 项）
python "$SKILL_DIR/scripts/check_environment.py"

# 快速模式（仅凭据 + 浏览器）
python "$SKILL_DIR/scripts/check_environment.py" --quick

# JSON 输出（供 Agent 解析）
python "$SKILL_DIR/scripts/check_environment.py" --json
```

检查项包括：
1. Python 版本（≥ 3.9）
2. pip 版本（≥ 23.0）
3. 依赖包（playwright、openpyxl）
4. Chromium 浏览器
5. DMS 凭据（DMS_USER / DMS_PASSWORD）

**方式二：手动验证**

```bash
python -c "import openpyxl; print('openpyxl OK')"
python -c "from playwright.sync_api import sync_playwright; print('playwright OK')"
playwright install --dry-run chromium
```

### 国内 / 公司网络代理配置

> 💡 **Agent 决策树：** 如果用户在中国大陆且未配置代理，优先使用镜像源（`-i` 参数）。如果用户在公司内网需要代理，通过 `http_proxy`/`https_proxy` 环境变量配置。

**PyPI 镜像源（国内访问 PyPI 官方源慢，推荐默认使用）：**

```bash
# 阿里云镜像（推荐，速度快）
pip install playwright openpyxl -i https://mirrors.aliyun.com/pypi/simple/

# 腾讯云镜像（备选）
pip install playwright openpyxl -i https://mirrors.cloud.tencent.com/pypi/simple/

# 华为云镜像（备选）
pip install playwright openpyxl -i https://repo.huaweicloud.com/repository/pypi/simple/

# 中科大镜像（学术网络快）
pip install playwright openpyxl -i https://pypi.mirrors.ustc.edu.cn/simple/
```

**HTTP 代理（公司内网需代理出网）：**

```bash
# 先设置代理环境变量
export http_proxy=http://proxy.xxx.com:8080
export https_proxy=http://proxy.xxx.com:8080

# 再安装（pip 和 playwright 都会读取代理环境变量）
pip install playwright openpyxl
playwright install chromium
```

**Playwright Chromium 下载加速：**

```bash
# 使用 npmmirror CDN 下载浏览器（比 Playwright 官方 CDN 快）
# Windows (PowerShell):
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"; playwright install chromium

# Linux/macOS:
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
playwright install chromium
```

**下载超时处理：**

`playwright install chromium` 下载约 400MB，网络差时可能很慢。支持断点续传，直接重试即可：
```bash
# 如果超时，直接重新运行即可续传
playwright install chromium
```

## 常见安装失败

| 现象 | 原因 | 解决 |
|------|------|------|
| `pip install` 超时或 `ConnectionError` | 网络不通或 PyPI 源慢 | 切换镜像源或配代理（见上方） |
| `playwright install chromium` 下载失败 | 浏览器包 ~400MB，易断线 | 重试（支持断点续传）；或设置 `PLAYWRIGHT_DOWNLOAD_HOST` 使用 CDN |
| `ModuleNotFoundError: No module named 'playwright'` | 未在虚拟环境中安装 | 确认 `.venv` 已激活（`which python` 指向 `.venv` 路径） |
| `not found in the Python library path` | 系统多个 Python 版本 | 用 `python -m pip install` 而非 `pip install`，确保解释器一致 |
| `playwright install` 因 `glibc` 报错（Linux） | 系统 libc 过旧（如 CentOS 7） | 升级系统或使用 Docker |

## 依赖版本锁定

将以下内容保存为 `requirements.txt`，确保跨机器版本一致：

```text
playwright==1.52.0
openpyxl==3.1.5
```

安装锁定版本：`pip install -r requirements.txt`

**验证已安装版本：**

```bash
python -c "import playwright; print(f'playwright {playwright.__version__}')"
python -c "import openpyxl; print(f'openpyxl {openpyxl.__version__}')"
```

> **注意：** `check_environment.py` 可验证依赖包是否安装，但不检查具体版本。
> 如需确保版本一致，请使用上述命令手动验证。

> 版本号随上游更新，如遇兼容性问题可尝试升级：
> `pip install --upgrade playwright openpyxl`

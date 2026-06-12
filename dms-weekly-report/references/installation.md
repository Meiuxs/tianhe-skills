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

## 安装步骤

建议在**虚拟环境**中安装，避免污染系统级 Python：

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# 或 .venv\Scripts\activate       # Windows

# 2. 升级 pip
python -m pip install --upgrade pip

# 3. 安装依赖
pip install playwright==1.52.0 openpyxl==3.1.5

# 4. 安装 Playwright Chromium 浏览器（关键）
playwright install chromium

# 5. 验证
python -c "import openpyxl; print('openpyxl OK')"
python -c "from playwright.sync_api import sync_playwright; print('playwright OK')"
playwright install --dry-run chromium
```

### 国内 / 公司网络代理配置

**PyPI 镜像源（国内访问慢）：**

```bash
# 临时使用
pip install playwright openpyxl -i https://mirrors.cloud.tencent.com/pypi/simple/

# 永久配置（推荐）
pip config set global.index-url https://mirrors.cloud.tencent.com/pypi/simple/
```

**HTTP 代理（公司内网需代理出网）：**

```bash
pip install playwright openpyxl --proxy http://proxy.xxx.com:8080
```

**playwright install 浏览器下载也需代理：**

```bash
export HTTP_PROXY=http://proxy.xxx.com:8080
export HTTPS_PROXY=http://proxy.xxx.com:8080
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

> 版本号随上游更新，如遇兼容性问题可尝试升级：
> `pip install --upgrade playwright openpyxl`

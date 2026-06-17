# 登录配置

> 被 `SKILL.md` 的步骤 0 引用。详细说明 DMS 登录凭据的配置方式和检测逻辑。

## 凭据检测

使用 `check_environment.py` 检查运行环境（统一入口）：

```bash
SKILL_DIR="$HOME/.codex/skills/dms-weekly-report  # 或 ~/.workbuddy/skills/dms-weekly-report"
python "$SKILL_DIR/scripts/check_environment.py" --quick
```

或直接使用底层模块：

```bash
python "$SKILL_DIR/scripts/dms_credentials.py" --check-browser
```

### 检测顺序

按以下优先级依次查找 `DMS_USER` / `DMS_PASSWORD`：

1. **进程环境变量** — `os.environ.get()`
2. **bash 系** — `~/.bashrc`、`~/.bash_profile`、`~/.profile`
3. **zsh 系** — `~/.zshenv`、`~/.zprofile`、`~/.zshrc`
4. **Windows** — PowerShell 用户变量、注册表

全部未找到时暂停，提示用户配置，回复"已配置"后继续。

## 配置方式

### Linux / macOS（bash/zsh）

```bash
# 临时（当前会话）
export DMS_USER="your_email@trinapower.com"
export DMS_PASSWORD="your_password"

# 永久（推荐）：追加到 ~/.bashrc 后 source
echo -e 'export DMS_USER="your_email@trinapower.com"\nexport DMS_PASSWORD="your_password"' >> ~/.bashrc
source ~/.bashrc
```

### Windows（推荐）

**方式一：PowerShell 永久设置（用户级）**

```powershell
[System.Environment]::SetEnvironmentVariable("DMS_USER", "your_email@trinapower.com", "User")
[System.Environment]::SetEnvironmentVariable("DMS_PASSWORD", "your_password", "User")
```

设置后**重新打开 PowerShell 窗口**即可生效。

**方式二：系统设置 GUI**

1. `Win + R` → 输入 `sysdm.cpl` → 回车
2. 切换到「高级」标签 → 点击「环境变量」
3. 在「用户变量」区域 → 点击「新建」
4. 分别添加 `DMS_USER` 和 `DMS_PASSWORD`
5. 确定保存后重新打开终端

**方式三：命令行临时（当前窗口）**

```powershell
$env:DMS_USER="your_email@trinapower.com"
$env:DMS_PASSWORD="your_password"
```

> ⚠️ 临时设置仅在当前 PowerShell 窗口有效，关闭后失效。

## 登录持久化

使用 Playwright 的 `launch_persistent_context` 保存登录状态到 `~/.dms_browser_data/`：

- **首次登录：** 正常输入凭据登录，浏览器上下文持久化
- **后续运行：** 自动复用持久化会话，无需重复登录
- **会话过期：** Playwright 自动检测，自动跳转登录页重登



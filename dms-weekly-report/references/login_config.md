# 登录配置

> 被 `SKILL.md` 的步骤 2 引用。详细说明 DMS 登录凭据的配置方式和检测逻辑。

## 凭据检测

使用 `dms_credentials.py` 检查运行环境：

```bash
SKILL_DIR="$HOME/.claude/skills/dms-weekly-report"
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

```bash
# 临时（当前会话）
export DMS_USER="your_email@trinapower.com"
export DMS_PASSWORD="your_password"

# 永久（推荐）：追加到 ~/.bashrc 后 source
echo -e 'export DMS_USER="your_email@trinapower.com"\nexport DMS_PASSWORD="your_password"' >> ~/.bashrc
source ~/.bashrc
```

## 登录持久化

使用 Playwright 的 `launch_persistent_context` 保存登录状态到 `~/.dms_browser_data/`：

- **首次登录：** 正常输入凭据登录，浏览器上下文持久化
- **后续运行：** 自动复用持久化会话，无需重复登录
- **会话过期：** Playwright 自动检测，自动跳转登录页重登

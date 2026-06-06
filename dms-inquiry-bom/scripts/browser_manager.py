#!/usr/bin/env python3
"""共享浏览器管理器。

提供统一的浏览器实例管理，支持登录状态复用，避免重复登录。

特性：
  - 持久化浏览器上下文（保存 cookies、localStorage）
  - 单例模式，多个脚本复用同一个浏览器实例
  - 自动检测登录状态，仅在需要时登录
  - 统一的清理和关闭接口

用法：
  from browser_manager import BrowserManager

  async with BrowserManager(headless=False) as manager:
      page = await manager.get_page()
      # 使用 page 操作...
      # 登录状态会自动保存和复用
"""

import asyncio
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# 修复 Windows 中文乱码
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402

# ==================== 配置 ====================

DMS_URL = "https://dms-admin.trinapower.com"

# 持久化数据目录（保存登录状态）
USER_DATA_DIR = Path.home() / ".dms_browser_data"


# ==================== 共享工具函数 ====================


def get_credentials() -> tuple[str, str]:
    """从环境变量读取 DMS 登录凭据，支持多来源自动检测。

    检查顺序：
    1. 当前环境变量
    2. ~/.bashrc
    3. ~/.bash_profile
    4. ~/.profile
    5. PowerShell 用户环境变量

    Returns:
        (username, password)

    Raises:
        SystemExit: 所有来源均未找到凭据时退出
    """
    import subprocess

    # 优先检查当前环境变量
    username = os.environ.get("DMS_USER")
    password = os.environ.get("DMS_PASSWORD")
    if username and password:
        return username, password

    # 尝试从 bash 配置文件加载
    for config_file in ['~/.bashrc', '~/.bash_profile', '~/.profile']:
        try:
            result = subprocess.run(
                ['bash', '-c', f'source {config_file} 2>/dev/null && echo "$DMS_USER|||$DMS_PASSWORD"'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split('|||')
                if len(parts) == 2 and parts[0] and parts[1]:
                    print(f"[环境] 从 {config_file} 加载登录凭据", file=sys.stderr)
                    return parts[0], parts[1]
        except Exception:
            continue

    # 尝试从 PowerShell 用户环境变量读取
    try:
        result = subprocess.run(
            ['powershell', '-Command',
             '[System.Environment]::GetEnvironmentVariable("DMS_USER", "User") + "|||" + [System.Environment]::GetEnvironmentVariable("DMS_PASSWORD", "User")'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split('|||')
            if len(parts) == 2 and parts[0] and parts[1]:
                print("[环境] 从 PowerShell 环境变量加载登录凭据", file=sys.stderr)
                return parts[0], parts[1]
    except Exception:
        pass

    print("[错误] 未配置 DMS_USER / DMS_PASSWORD 环境变量", file=sys.stderr)
    print("  请参照 SKILL.md 的「凭据配置」节进行设置", file=sys.stderr)
    raise SystemExit(1)


class BrowserManager:
    """浏览器管理器，支持登录状态复用。"""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._is_logged_in = False
        self._pages = []  # 跟踪所有打开的页面

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        """启动浏览器（使用持久化上下文）。"""
        if self._context:
            return

        print("[浏览器] 启动中...", file=sys.stderr)

        # 确保用户数据目录存在
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()

        # 使用 persistent context 保存登录状态
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=self.headless,
            no_viewport=True,  # 自适应窗口大小，避免视口与窗口不匹配
            locale="zh-CN",
            # 忽略 HTTPS 错误（DMS 可能使用自签名证书）
            ignore_https_errors=True,
            args=["--start-maximized"],
        )

        print(f"[浏览器] 已启动（登录状态目录: {USER_DATA_DIR}）", file=sys.stderr)

    async def get_page(self, reuse_existing: bool = True) -> Page:
        """获取一个可用页面。

        Args:
            reuse_existing: 如果为 True，复用现有页面；否则创建新页面

        Returns:
            Playwright Page 对象
        """
        if not self._context:
            await self.start()

        # 尝试复用现有页面
        if reuse_existing and self._pages:
            # 返回最后一个可用的页面
            for page in reversed(self._pages):
                if not page.is_closed():
                    return page

        # 创建新页面
        page = await self._context.new_page()
        self._pages.append(page)
        return page

    async def ensure_logged_in(self, page: Page = None) -> bool:
        """确保已登录 DMS。

        如果已经登录，直接返回 True。
        如果未登录，执行登录流程。

        Args:
            page: 要使用的页面，如果为 None 则获取一个新页面

        Returns:
            是否登录成功
        """
        if self._is_logged_in:
            return True

        if page is None:
            page = await self.get_page()

        # 访问 DMS 检查登录状态
        await page.goto(DMS_URL)
        await page.wait_for_load_state("networkidle", timeout=15000)

        if "iauth.trinapower.com" in page.url:
            # 需要登录
            print("[登录] 正在登录...", file=sys.stderr)
            username, password = self._get_credentials()

            await page.wait_for_selector("#form_item_account", state="visible", timeout=15000)
            await page.locator("#form_item_account").fill(username)
            await page.locator("#form_item_password").fill(password)
            await page.get_by_role("button", name="登 录").click()

            try:
                await page.wait_for_url(f"{DMS_URL}/**", timeout=15000)
                await page.wait_for_load_state("networkidle", timeout=10000)
                masked_user = username[:3] + "***" + username[username.index("@"):] if "@" in username else "***"
                print(f"[登录] 成功 ({masked_user})", file=sys.stderr)
                self._is_logged_in = True
                return True
            except Exception as e:
                if "iauth.trinapower.com" in page.url:
                    print("[登录] 失败，请检查账号密码", file=sys.stderr)
                    return False
                # 可能是其他原因导致的超时，但已经跳转到 DMS 了
                self._is_logged_in = True
                return True
        else:
            # 已经登录
            print("[登录] 会话有效（已复用）", file=sys.stderr)
            self._is_logged_in = True
            return True

    def _get_credentials(self):
        """从环境变量读取登录凭据（委派给共享函数）。"""
        return get_credentials()

    async def close_page(self, page: Page):
        """关闭指定页面并从跟踪列表中移除。"""
        if page and not page.is_closed():
            await page.close()
        if page in self._pages:
            self._pages.remove(page)

    async def close_all_pages(self):
        """关闭所有打开的页面。"""
        for page in self._pages[:]:  # 使用切片避免迭代时修改
            if not page.is_closed():
                await page.close()
        self._pages.clear()

    async def close(self, keep_data: bool = True):
        """关闭浏览器。

        Args:
            keep_data: 是否保留登录状态数据（默认 True）
        """
        print("[浏览器] 正在关闭...", file=sys.stderr)

        # 关闭所有页面
        await self.close_all_pages()

        # 关闭上下文（这会保存登录状态到 user_data_dir）
        if self._context:
            await self._context.close()
            self._context = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        self._is_logged_in = False
        print("[浏览器] 已关闭", file=sys.stderr)

    async def new_page_for_task(self) -> Page:
        """为新任务创建一个新页面（不复用现有页面）。

        用于需要并行处理多个任务的场景。

        Returns:
            新的 Page 对象
        """
        if not self._context:
            await self.start()

        page = await self._context.new_page()
        self._pages.append(page)
        return page

    async def cleanup_old_pages(self, keep_recent: int = 1):
        """清理旧页面，只保留最近的几个。

        Args:
            keep_recent: 保留最近打开的页面数量
        """
        pages_to_close = self._pages[:-keep_recent] if len(self._pages) > keep_recent else []
        for page in pages_to_close:
            if not page.is_closed():
                await page.close()
            self._pages.remove(page)


# ==================== 便捷函数 ====================

# 全局浏览器管理器实例（单例模式）
_global_manager: BrowserManager = None


async def get_browser_manager(headless: bool = False) -> BrowserManager:
    """获取全局浏览器管理器实例。

    如果不存在则创建，如果已存在则复用。

    Args:
        headless: 是否无头模式（仅在首次创建时生效）

    Returns:
        BrowserManager 实例
    """
    global _global_manager
    if _global_manager is None:
        _global_manager = BrowserManager(headless=headless)
        await _global_manager.start()
    return _global_manager


async def close_global_manager(keep_data: bool = True):
    """关闭全局浏览器管理器。"""
    global _global_manager
    if _global_manager:
        await _global_manager.close(keep_data=keep_data)
        _global_manager = None


# ==================== 上下文管理器（用于简单场景）====================

class DMSBrowser:
    """简化的 DMS 浏览器上下文管理器。

    用法：
        async with DMSBrowser(headless=False) as (manager, page):
            await manager.ensure_logged_in(page)
            # 使用 page 操作...
    """

    def __init__(self, headless: bool = False):
        self.manager = BrowserManager(headless=headless)

    async def __aenter__(self):
        await self.manager.start()
        page = await self.manager.get_page()
        await self.manager.ensure_logged_in(page)
        return self.manager, page

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.manager.close()


if __name__ == "__main__":
    # 测试代码
    async def test():
        async with BrowserManager(headless=False) as manager:
            page = await manager.get_page()
            await manager.ensure_logged_in(page)
            print(f"当前 URL: {page.url}")

            # 创建第二个页面
            page2 = await manager.new_page_for_task()
            await page2.goto("https://dms-admin.trinapower.com/#/process/process_center")
            print(f"页面2 URL: {page2.url}")

            # 清理旧页面
            await manager.cleanup_old_pages(keep_recent=1)

            input("按 Enter 关闭浏览器...")

    asyncio.run(test())

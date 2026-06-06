# 共享浏览器管理器使用指南

## 概述

共享浏览器管理器解决了多个脚本重复登录的问题。它使用 Playwright 的持久化上下文功能，将登录状态保存到本地目录，实现一次登录、多次复用。

## 核心优势

- ✅ **避免重复登录**：首次登录后，后续操作无需重新输入账号密码
- ✅ **节省时间**：每次登录约需 5-10 秒，复用后可节省大量时间
- ✅ **统一管理**：所有浏览器页面统一管理，最后统一关闭
- ✅ **向后兼容**：原有脚本仍可独立运行

## 文件结构

```
scripts/
├── browser_manager.py          # 共享浏览器管理器核心模块
├── run_inquiry_extract.py      # 提取脚本（已支持共享浏览器）
├── fill_product_info.py        # 填写脚本（已支持共享浏览器）
├── inquiry_workflow.py         # 一站式工作流（已集成共享浏览器）
└── test_browser_manager.py     # 测试脚本
```

## 使用方式

### 方式1：直接使用管理器

```python
import asyncio
from browser_manager import BrowserManager

async def main():
    # 创建管理器
    async with BrowserManager(headless=False) as manager:
        # 获取页面（自动登录）
        page = await manager.get_page()
        await manager.ensure_logged_in(page)

        # 使用页面操作
        await page.goto("https://dms-admin.trinapower.com/#/process/process_center")
        print(f"当前URL: {page.url}")

        # 创建第二个页面
        page2 = await manager.new_page_for_task()
        await page2.goto("https://dms-admin.trinapower.com/#/process/process_center")

        # 清理旧页面
        await manager.cleanup_old_pages(keep_recent=1)

        input("按 Enter 关闭浏览器...")

asyncio.run(main())
```

### 方式2：传递给现有函数

```python
import asyncio
import argparse
from browser_manager import BrowserManager
from run_inquiry_extract import run as extract_flows
from fill_product_info import run as fill_product_info_run

async def main():
    manager = BrowserManager(headless=False)
    await manager.start()

    try:
        # 提取待办流程（复用浏览器）
        extract_args = argparse.Namespace(
            headless=False,
            workers=3,
            output_file=None
        )
        await extract_flows(extract_args, browser_manager=manager)

        # 填写产品信息（复用浏览器）
        fill_args = argparse.Namespace(
            flow_id="2026060310435399",
            component_power=715,
            component_count=800,
            headless=False,
            wait_time=300
        )
        await fill_product_info_run(fill_args, browser_manager=manager)

    finally:
        await manager.close()

asyncio.run(main())
```

### 方式3：使用一站式工作流（推荐）

```bash
# 一站式工作流自动使用共享浏览器管理器
python inquiry_workflow.py --auto

# 无头模式
python inquiry_workflow.py --headless --auto

# 跳过产品信息填写
python inquiry_workflow.py --auto --skip-fill
```

## 工作原理

### 1. 持久化上下文

```python
# 使用 launch_persistent_context 代替 launch
context = await playwright.chromium.launch_persistent_context(
    user_data_dir="~/.dms_browser_data",  # 保存登录状态
    headless=False,
    viewport={"width": 1920, "height": 1080}
)
```

### 2. 登录状态检测

```python
async def ensure_logged_in(page):
    await page.goto(DMS_URL)

    if "iauth.trinapower.com" in page.url:
        # 需要登录
        await do_login(page)
    else:
        # 已登录，跳过
        print("会话有效（已复用）")
```

### 3. 页面管理

```python
# 跟踪所有打开的页面
self._pages = []

# 获取页面（可选择复用或新建）
page = await manager.get_page(reuse_existing=True)

# 清理旧页面
await manager.cleanup_old_pages(keep_recent=1)
```

## 存储位置

登录状态保存在用户主目录下的 `.dms_browser_data` 文件夹：

- **Windows**: `C:\Users\{username}\.dms_browser_data\`
- **Linux/Mac**: `~/.dms_browser_data/`

该目录包含：
- Cookies
- LocalStorage
- SessionStorage
- 其他浏览器状态

## 测试

运行测试脚本验证功能：

```bash
python scripts/test_browser_manager.py
```

测试选项：
1. 基本功能测试 - 测试浏览器启动、登录、页面管理
2. 工作流集成测试 - 测试与提取、填写脚本的集成
3. 运行所有测试

## 注意事项

1. **首次使用**：第一次运行时需要正常登录，之后会自动复用登录状态
2. **会话过期**：如果登录会话过期（通常几小时），需要重新登录
3. **清理数据**：如需清除登录状态，删除 `~/.dms_browser_data/` 目录即可
4. **并发安全**：多个脚本不应同时使用同一个管理器实例
5. **无头模式**：无头模式下也会保存登录状态，但不会显示浏览器窗口

## 故障排除

### 问题1：登录状态失效

**症状**：每次都需要重新登录

**解决**：
```bash
# 删除旧的登录状态
rm -rf ~/.dms_browser_data/

# 重新运行脚本，会自动登录
python inquiry_workflow.py
```

### 问题2：浏览器启动失败

**症状**：`BrowserManager` 初始化报错

**解决**：
```bash
# 确保 Playwright 已安装
pip install playwright
playwright install chromium
```

### 问题3：页面操作超时

**症状**：等待页面元素超时

**解决**：
- 检查网络连接
- 确认 DMS 服务正常
- 尝试增加超时时间

## 性能对比

| 场景 | 原方式 | 使用共享管理器 | 节省时间 |
|------|--------|--------------|---------|
| 提取 + 填写 | ~20秒 | ~10秒 | ~10秒 |
| 提取 + 3个填写 | ~40秒 | ~15秒 | ~25秒 |
| 批量处理10个流程 | ~100秒 | ~30秒 | ~70秒 |

*注：时间仅为估算，实际取决于网络和系统性能*

## 更新日志

### v1.0 (2026-06-03)
- ✅ 实现共享浏览器管理器
- ✅ 支持登录状态持久化
- ✅ 集成到现有脚本
- ✅ 添加测试脚本
- ✅ 更新文档

## 相关链接

- [Playwright 文档](https://playwright.dev/python/)
- [持久化上下文](https://playwright.dev/python/docs/api/class-browsercontext)

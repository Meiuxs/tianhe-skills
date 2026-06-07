#!/usr/bin/env python3
"""DMS待办询价流程提取脚本。

从DMS流程中心提取所有待办询价流程的详情，输出结构化JSON。

用法：
    python run_inquiry_extract.py [--headless] [--workers N] [--output-file PATH]
"""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# 导入共享浏览器管理器
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402
from browser_manager import BrowserManager, get_browser_manager, get_credentials

# ==================== 配置 ====================

DMS_URL = "https://dms-admin.trinapower.com"


# ==================== 登录 ====================

def is_on_login_page(page):
    return "iauth.trinapower.com" in page.url


async def do_login(page):
    username, password = get_credentials()
    print("[登录] 正在登录...", file=sys.stderr)
    await page.wait_for_selector("#form_item_account", state="visible", timeout=15000)
    await page.locator("#form_item_account").fill(username)
    await page.locator("#form_item_password").fill(password)
    await page.get_by_role("button", name="登 录").click()
    try:
        await page.wait_for_url(f"{DMS_URL}/**", timeout=15000)
        await page.wait_for_load_state("networkidle", timeout=10000)
        masked_user = username[:3] + "***" + username[username.index("@"):] if "@" in username else "***"
        print(f"[登录] 成功 ({masked_user})", file=sys.stderr)
    except PlaywrightTimeout:
        if is_on_login_page(page):
            raise RuntimeError("登录失败，请检查账号密码")


# ==================== 导航到待办流程 ====================

async def get_pending_flow_ids(page):
    """导航到待办流程，收集所有流程编号（处理分页）。"""
    print("[导航] 进入流程中心...", file=sys.stderr)
    await page.goto(f"{DMS_URL}/#/process/process_center")
    await page.wait_for_load_state("networkidle", timeout=15000)
    await page.wait_for_timeout(2000)

    if is_on_login_page(page):
        await do_login(page)
        await page.goto(f"{DMS_URL}/#/process/process_center")
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.wait_for_timeout(2000)

    # 点击待办流程标签（可能是默认标签，但显式点击更稳健）
    try:
        await page.get_by_role("menuitem", name="待办流程").click()
        await page.wait_for_timeout(2000)
    except Exception:
        # 可能已经是待办流程页面
        pass

    # 读取总数
    total_el = page.locator("text=/共.*条记录/")
    total = 0
    if await total_el.count() > 0:
        total_text = await total_el.first.text_content()
        total_match = re.search(r"共\s*(\d+)\s*条", total_text)
        total = int(total_match.group(1)) if total_match else 0

    print(f"[筛选] 共 {total} 条待办流程", file=sys.stderr)
    if total == 0:
        return []

    # 逐页收集流程编号
    flow_ids = []
    seen = set()
    page_num = 1

    while True:
        print(f"[筛选] 读取第 {page_num} 页...", file=sys.stderr)
        for row in await page.locator("table.el-table__body tbody tr").all():
            cells = await row.locator("td").all()
            if cells:
                text = (await cells[0].text_content()).strip().strip('"')
                if re.match(r"^\d{15,}$", text) and text not in seen:
                    seen.add(text)
                    flow_ids.append(text)

        # 检查是否有下一页
        next_btn = page.locator("button.btn-next, li.number.active + li.number")
        # 更稳健的方式：查找"下一页"按钮
        next_page_btn = page.get_by_role("button", name="下一页")
        if await next_page_btn.count() > 0 and await next_page_btn.first.is_enabled():
            await next_page_btn.first.click()
            await page.wait_for_timeout(2000)
            page_num += 1
        else:
            break

    print(f"[筛选] 共提取 {len(flow_ids)} 个流程编号", file=sys.stderr)
    return flow_ids


# ==================== 并行提取详情 ====================

async def extract_detail_by_url(context, flow_id, sem):
    """在新Tab中访问详情页URL提取数据。"""
    async with sem:
        page = await context.new_page()
        url = f"{DMS_URL}/#/process/process_detail?bizFlowId={flow_id}&flowStatus=0"
        try:
            await page.goto(url, timeout=20000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            await page.wait_for_timeout(1000)

            if is_on_login_page(page):
                await do_login(page)
                await page.goto(url, timeout=20000)
                await page.wait_for_load_state("networkidle", timeout=15000)

            html = await page.content()
            data = {"flow_id": flow_id}

            # 基本信息
            data["project_name"] = _extract_from_html(html, "项目名称")
            agent_raw = _extract_from_html(html, "代理商")
            data["agent_code"], data["agent_name"] = _split_agent(agent_raw)
            data["province"] = _extract_from_html(html, "省公司")
            data["salesperson"] = _extract_from_html(html, "业务员")
            data["remark"] = _extract_from_html(html, "备注")

            # BOM清单
            bom_items = await _extract_bom(page)
            data["bom_items"] = bom_items

            # 审批历史
            approval_history = await _extract_approval_history(page)
            data["approval_history"] = approval_history

            return data
        except (PlaywrightTimeout, OSError, ValueError, AttributeError) as e:
            print(f"  -> {flow_id}: 提取异常 {e}", file=sys.stderr)
            return None
        finally:
            await page.close()


async def extract_all_parallel(context, flow_ids, workers):
    total = len(flow_ids)
    print(f"[提取] 并行提取 {total} 条（{workers} 并发）...", file=sys.stderr)
    sem = asyncio.Semaphore(workers)
    tasks = [extract_detail_by_url(context, fid, sem) for fid in flow_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    records = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"  [{i+1}/{total}] {flow_ids[i]}: 异常 {result}", file=sys.stderr)
        elif result:
            records.append(result)
            print(f"  [{i+1}/{total}] {result.get('flow_id')}: {result.get('project_name')}", file=sys.stderr)
        else:
            print(f"  [{i+1}/{total}] {flow_ids[i]}: 提取失败", file=sys.stderr)

    # 保持原始顺序
    order = {fid: i for i, fid in enumerate(flow_ids)}
    records.sort(key=lambda r: order.get(r.get("flow_id", ""), 999))
    return records


# ==================== HTML提取工具 ====================

def _extract_from_html(html, label):
    pattern = rf"{label}[:\s]*</[^>]+>\s*<[^>]*>([^<]+)"
    match = re.search(pattern, html)
    if match:
        return match.group(1).strip()
    pattern2 = rf"{label}[:\s]*</[^>]+>\s*<[^>]+>\s*<[^>]*>([^<]+)"
    match2 = re.search(pattern2, html)
    if match2:
        return match2.group(1).strip()
    return "--"


def _split_agent(agent_raw):
    if not agent_raw or agent_raw == "--":
        return "--", "--"
    parts = agent_raw.split(" ", 1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (agent_raw.strip(), "--")


async def _extract_bom(page):
    """提取BOM清单表格。"""
    items = []
    try:
        tables = await page.locator("table").all()
        for i, table in enumerate(tables):
            thead = table.locator("thead")
            if await thead.count() > 0 and "物料编号" in (await thead.text_content()):
                if i + 1 < len(tables):
                    for row in await tables[i + 1].locator("tbody tr").all():
                        cells = await row.locator("td").all()
                        if len(cells) >= 4:
                            code = (await cells[0].text_content()).strip().strip('"')
                            name = (await cells[1].text_content()).strip()
                            qty_text = (await cells[2].text_content()).strip().strip('"')
                            unit = (await cells[3].text_content()).strip()
                            if not name:
                                continue
                            try:
                                qty = int(qty_text)
                            except ValueError:
                                try:
                                    qty = float(qty_text)
                                except ValueError:
                                    qty = 0
                            items.append({"code": code, "name": name, "qty": qty, "unit": unit})
                break
    except Exception as e:
        print(f"[BOM] 异常: {e}", file=sys.stderr)
    # 去重
    seen = set()
    return [x for x in items if x["code"] not in seen and not seen.add(x["code"])]


async def _extract_approval_history(page):
    """提取审批历史，重点关注省总意见。"""
    history = []
    try:
        tables = await page.locator("table").all()
        for i, table in enumerate(tables):
            thead = table.locator("thead")
            if await thead.count() > 0 and "审批节点" in (await thead.text_content()):
                if i + 1 < len(tables):
                    for row in await tables[i + 1].locator("tbody tr").all():
                        cells = await row.locator("td").all()
                        if len(cells) >= 4:
                            node = (await cells[0].text_content()).strip()
                            processor = (await cells[1].text_content()).strip()
                            status = (await cells[2].text_content()).strip()
                            time_val = (await cells[3].text_content()).strip()
                            opinion = ""
                            if len(cells) >= 5:
                                opinion = (await cells[4].text_content()).strip()
                            history.append({
                                "node": node,
                                "processor": processor,
                                "status": status,
                                "time": time_val,
                                "opinion": opinion,
                            })
                break
    except Exception as e:
        print(f"[审批历史] 异常: {e}", file=sys.stderr)
    return history


# ==================== 终端摘要 ====================

def print_summary(start_time, flow_ids, records, output_file=None, error=None):
    """在stderr输出执行摘要（stdout保留给JSON）。"""
    elapsed = (datetime.now() - start_time).total_seconds()

    print("\n========================================", file=sys.stderr)
    print("  执行摘要", file=sys.stderr)
    print("========================================", file=sys.stderr)
    if flow_ids:
        print(f"  待办流程    {len(flow_ids)} 条", file=sys.stderr)
    if records:
        print(f"  成功提取    {len(records)} 条", file=sys.stderr)
        failed = len(flow_ids) - len(records) if flow_ids else 0
        if failed > 0:
            print(f"  提取失败    {failed} 条", file=sys.stderr)
    if output_file:
        print(f"  输出文件    {output_file}", file=sys.stderr)
    if error:
        print(f"  执行状态    异常: {error}", file=sys.stderr)
    print(f"  总耗时      {elapsed:.1f} 秒", file=sys.stderr)
    print("========================================", file=sys.stderr)


# ==================== 主流程 ====================

async def run(args, browser_manager=None):
    """运行提取流程。

    Args:
        args: 命令行参数
        browser_manager: 可选的共享浏览器管理器实例。如果提供，则复用该管理器的浏览器和登录状态。
    """
    output_file = args.output_file
    start_time = datetime.now()
    print(f"=== 待办询价提取（{args.workers}并发） ===\n", file=sys.stderr)

    flow_ids = []
    records = []
    error_msg = None

    # 判断是否使用共享浏览器管理器
    use_shared = browser_manager is not None

    if use_shared:
        # 使用共享浏览器管理器
        manager = browser_manager
        page = await manager.get_page()
        await manager.ensure_logged_in(page)
        context = manager._context

        try:
            # 1. 获取待办流程编号
            flow_ids = await get_pending_flow_ids(page)
            if not flow_ids:
                print("[结果] 无待办询价流程", file=sys.stderr)
                print_summary(start_time, [], [], output_file)
                return

            # 关闭页面，为并行提取做准备
            await manager.close_page(page)

            # 2. 并行提取详情
            records = await extract_all_parallel(context, flow_ids, args.workers)
            if not records:
                print("[结果] 未能提取到任何详情", file=sys.stderr)
                print_summary(start_time, flow_ids, [], output_file, "提取失败")
                return

        except Exception as e:
            error_msg = str(e)
            print(f"[错误] {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
    else:
        # 独立启动浏览器
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=args.headless, args=["--start-maximized"])
            except Exception as e:
                if args.headless:
                    print(f"[警告] 无头模式启动失败: {e}", file=sys.stderr)
                    print("[警告] 自动回退到弹出浏览器窗口模式（默认）", file=sys.stderr)
                    browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
                else:
                    raise
            context = await browser.new_context(
                no_viewport=True, locale="zh-CN"
            )
            page = await context.new_page()

            try:
                # 1. 登录
                await page.goto(DMS_URL)
                await page.wait_for_load_state("networkidle", timeout=15000)
                if is_on_login_page(page):
                    await do_login(page)
                else:
                    print("[登录] 会话有效", file=sys.stderr)

                # 2. 获取待办流程编号
                flow_ids = await get_pending_flow_ids(page)
                if not flow_ids:
                    print("[结果] 无待办询价流程", file=sys.stderr)
                    await browser.close()
                    print_summary(start_time, [], [], output_file)
                    return
                await page.close()

                # 3. 并行提取详情
                records = await extract_all_parallel(context, flow_ids, args.workers)
                if not records:
                    print("[结果] 未能提取到任何详情", file=sys.stderr)
                    await browser.close()
                    print_summary(start_time, flow_ids, [], output_file, "提取失败")
                    return

            except Exception as e:
                error_msg = str(e)
                print(f"[错误] {e}", file=sys.stderr)
                import traceback
                traceback.print_exc(file=sys.stderr)
            finally:
                await browser.close()

    # 4. 输出JSON
    json_str = json.dumps(records, ensure_ascii=False, indent=2)
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json_str)
        print(f"[输出] 已保存到: {output_file}", file=sys.stderr)
    else:
        # stdout输出JSON（供Claude读取）
        print(json_str)

    print_summary(start_time, flow_ids, records, output_file, error=error_msg)


def main():
    parser = argparse.ArgumentParser(description="DMS待办询价流程提取")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--workers", type=int, default=3, help="并行并发数（默认3）")
    parser.add_argument("--output-file", type=str, default=None,
                        help="输出JSON文件路径（默认输出到stdout）")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

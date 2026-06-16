"""DMS 浏览器自动化模块。

包含 Playwright 浏览器操作的核心功能：
  - 数据类: FlowRecord, TableProcessResult
  - 登录: is_on_login_page, ensure_logged_in, do_login
  - 筛选: _navigate_to_process_center, _process_table_rows, filter_and_get_flow_ids
  - 提取: _extract_from_html, _split_agent, _extract_bom, extract_detail_by_url, extract_all_parallel
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from column_definitions import (
    DMS_URL, LOGIN_CHECK_DOMAIN,
    NAV_TIMEOUT, LOAD_TIMEOUT, WAIT_SHORT, WAIT_MEDIUM,
    MAX_RETRIES, RETRY_BASE_DELAY,
    TARGET_FLOW_TYPE, FILTER_PAGE_SIZE, API_FILTER_PAGE_SIZE,
    DMS_FLOW_LIST_API,
)
from dms_credentials import get_credentials as _get_dms_credentials, source_label
from playwright.async_api import (
    Page,
    BrowserContext,
    Response,
    TimeoutError as PlaywrightTimeout,
)
from playwright._impl._errors import TargetClosedError

logger = logging.getLogger("dms_report")

# ==================== 公开 API ====================
__all__ = [
    # 数据类
    "FlowRecord",
    "TableProcessResult",
    # 登录
    "is_on_login_page",
    "ensure_logged_in",
    "do_login",
    # Token
    "get_access_token",
    # 筛选
    "filter_and_get_flow_ids",
    "filter_and_get_flow_ids_via_api",
    "get_week_range",
    # 提取
    "extract_detail_by_url",
    "extract_all_parallel",
    # 重试
    "retry_async",
    # 常量
    "API_FILTER_PAGE_SIZE",
]

# ==================== 选择器常量 ====================
# 关键 DOM 选择器集中管理，前端改动时只需修改此处
SELECTORS: dict[str, str] = {
    "date_start": "input[placeholder='开始时间']",
    "date_end": "input[placeholder='结束时间']",
    "flow_type_dropdown": "input[placeholder='请选择流程类型']",
    "pagination": ".el-pager",
    "table_body": "table.el-table__body",
    "table_tbody": "table.el-table__body tbody",
    "total_records": "text=/共.*条记录/",
}

# ==================== 数据类 ====================


@dataclass
class FlowRecord:
    """提取到的单条询价记录——最终写入 Excel 的一行数据。"""
    flow_id: str = ""
    project_name: str = "--"
    agent_code: str = "--"
    agent_name: str = "--"
    province: str = "--"
    salesperson: str = "--"
    module_kw: float | None = None
    inverter_kw: float | None = None
    battery_kwh: float | None = None
    unit_price: str = "--"
    total_price: str = "--"
    submit_time: str = "--"
    remark: str = "无"
    ordered: str = "否"
    province_processor: str = "--"
    province_status: str = "--"
    purchase_processor: str = "--"
    purchase_status: str = "--"
    final_approval_time: str = "--"


@dataclass
class TableProcessResult:
    """表格翻页处理结果。"""
    flow_ids: list[str] = field(default_factory=list)
    seen_ids: set[str] = field(default_factory=set)
    skipped_wrong_type: int = 0
    skipped_invalid: int = 0
    skipped_dup: int = 0

    @property
    def valid_rows(self) -> int:
        """有效行数（即已添加的流程编号数量）。"""
        return len(self.flow_ids)

    def add_flow_id(self, flow_id: str) -> bool:
        """添加流程编号，自动同步 seen_ids 去重。

        Returns:
            True 如果成功添加（此前未见过），False 如果是重复。
        """
        if flow_id in self.seen_ids:
            return False
        self.seen_ids.add(flow_id)
        self.flow_ids.append(flow_id)
        return True


# ==================== 重试装饰器 ====================


def retry_async(max_retries: int = MAX_RETRIES, base_delay: float = RETRY_BASE_DELAY):
    """异步函数重试装饰器，指数退避。

    仅重试以下可恢复异常:
      - PlaywrightTimeout: 网络/页面加载超时
      - OSError: 连接断开、DNS 解析失败等网络层错误
      - asyncio.TimeoutError: asyncio 原生超时
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (PlaywrightTimeout, OSError, asyncio.TimeoutError) as e:
                    last_exc = e
                    if attempt < max_retries:
                        delay = base_delay * (2 ** (attempt - 1))
                        logger.warning("%s 第 %d/%d 次失败: %s，%.1fs 后重试",
                                       func.__name__, attempt, max_retries, e, delay)
                        await asyncio.sleep(delay)
                    else:
                        logger.error("%s 重试 %d 次后仍失败: %s",
                                     func.__name__, max_retries, e)
            raise last_exc
        return wrapper
    return decorator


def _parse_json_date(detail: dict) -> None:
    """将 detail['jsonDate'] 从 JSON 字符串解析为 dict（如需要）。"""
    json_date_str = detail.get("jsonDate", "")
    if isinstance(json_date_str, str) and json_date_str:
        try:
            detail["jsonDate"] = json.loads(json_date_str)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("jsonDate 解析失败: %s", e)


# ==================== 工具函数 ====================


def is_on_login_page(url: str) -> bool:
    """判断当前 URL 是否为登录页面。"""
    return LOGIN_CHECK_DOMAIN in url


def _mask_salesperson(s: str) -> str:
    """对业务员信息进行脱敏处理。

    只显示姓名首字 + 工号后4位，例如 "张三(G0001)" → "张***(G001)"。
    """
    if not s or s == "--":
        return "--"
    # 只显示姓名首字 + 工号后4位
    if "(" in s:
        name_part, no_part = s.split("(", 1)
        no_part = no_part.rstrip(")")
        return f"{name_part[0]}***({no_part[-4:]})" if len(no_part) > 4 else f"{name_part[0]}***({no_part})"
    return s[0] + "***" if len(s) > 1 else s


async def ensure_logged_in(page: Page, target_url: str) -> None:
    """如果当前在登录页面则自动登录，然后导航到目标 URL。

    若当前已在目标页面上则跳过，避免不必要的导航。

    URL 匹配策略：
      1. 完全相等 → 跳过
      2. scheme+netloc+path 相同 → 视为同一页面，跳过（容忍查询参数差异）
      3. 详情页（含 bizFlowId）→ 仅比较 bizFlowId 参数值
      4. 其他情况 → 导航
    """
    if is_on_login_page(page.url):
        await do_login(page)

    # 完全相等
    if page.url == target_url:
        return

    current = urlparse(page.url)
    target = urlparse(target_url)

    # scheme+netloc+path 相同时视为同一页面（如分页、筛选参数变化不影响页面身份）
    if current.scheme == target.scheme and current.netloc == target.netloc and current.path == target.path:
        # 详情页需进一步校验 bizFlowId
        if "bizFlowId" in target_url:
            target_params = parse_qs(target.query)
            current_params = parse_qs(current.query)
            target_flow_id = target_params.get("bizFlowId", [None])[0]
            current_flow_id = current_params.get("bizFlowId", [None])[0]
            if target_flow_id and current_flow_id and target_flow_id == current_flow_id:
                return
            # bizFlowId 不一致，需要导航
        else:
            # 非详情页，路径相同即视为已在目标页面
            return

    # 需要导航
    await page.goto(target_url, timeout=NAV_TIMEOUT)
    await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)


async def get_access_token(context: BrowserContext) -> str | None:
    """从浏览器 cookie 中提取 DMS 的 access_token。

    登录后 DMS 系统会在 cookie 中设置 dms_admin_token，
    该 token 用于后端 API 调用的 Authorization 头。

    Args:
        context: Playwright BrowserContext

    Returns:
        access_token 字符串，未登录或无 cookie 时返回 None。
    """
    cookies = await context.cookies()
    for c in cookies:
        if c["name"] == "dms_admin_token":
            return c["value"]
    return None

# 模块级 token 缓存，避免每次 API 请求都重新读取 cookie
_cached_token: str | None = None


async def _get_api_headers(context: BrowserContext) -> dict[str, str] | None:
    """获取 API 请求的 Authorization header（带缓存）。"""
    global _cached_token
    if _cached_token is None:
        _cached_token = await get_access_token(context)
    if _cached_token:
        return {"Authorization": f"bearer {_cached_token}"}
    return None


async def filter_and_get_flow_ids_via_api(
    context: BrowserContext, start_date: str, end_date: str,
) -> TableProcessResult:
    """通过 API 筛选已办流程，返回有效流程编号列表。

    替代页面 DOM 解析的纯 API 方案，避免选择器失效和 HTML 重复行问题。

    DMS 列表 API: POST /dms-admin/newFlow/newFlowList
      - startTime / endTime: 日期范围（YYYY-MM-DD）
      - flowStatus: 1=已办
      - pageNum / pageSize: 分页参数

    响应结构: {"code":1,"data":{"total":N,"records":[...]}}
    记录字段: bizFlowId, flowName, statusName, createName, createOrg 等
    """
    logger.info("API 筛选日期范围: %s ~ %s", start_date, end_date)
    headers = await _get_api_headers(context)
    if not headers:
        logger.warning("未获取到 access_token，API 筛选不可用")
        return TableProcessResult()

    result = TableProcessResult()
    page_num = 1

    while True:
        try:
            resp = await context.request.post(
                DMS_FLOW_LIST_API,
                data={
                    "startTime": start_date,
                    "endTime": end_date,
                    "pageNum": page_num,
                    "pageSize": API_FILTER_PAGE_SIZE,
                    "flowStatus": 1,
                },
                headers=headers,
                timeout=NAV_TIMEOUT,
            )
            if not resp.ok:
                logger.error("API 筛选请求失败: HTTP %d", resp.status)
                break
            body = await resp.json()
        except Exception as e:
            logger.error("API 筛选请求异常: %s", e)
            break

        if body.get("code") != 1:
            logger.warning("API 筛选返回异常: %s", body.get("errMsg", ""))
            break

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            logger.warning("API 筛选响应格式异常: %s", json.dumps(body, ensure_ascii=False)[:500])
            break

        total = data.get("total", 0)
        rows = data.get("records") or []
        logger.info("API 筛选第 %d 页: 获取 %d 条（总计 %d 条）", page_num, len(rows), total)

        if not rows:
            break

        for row in rows:
            flow_id = str(row.get("bizFlowId") or row.get("flowId") or "")
            flow_name = str(row.get("flowName") or "")
            status_name = str(row.get("statusName") or "")

            # 流程编号校验
            if not re.match(r"^\d{15,}$", flow_id):
                continue

            # 流程类型校验（通过 flowName 匹配）
            if TARGET_FLOW_TYPE not in flow_name:
                result.skipped_wrong_type += 1
                continue

            # 作废校验
            if "作废" in status_name:
                result.skipped_invalid += 1
                continue

            # 去重
            if flow_id in result.seen_ids:
                result.skipped_dup += 1
                continue

            result.add_flow_id(flow_id)

        # 翻页判断
        if len(result.flow_ids) >= total or len(rows) < API_FILTER_PAGE_SIZE:
            break
        page_num += 1

    logger.info("API 筛选结果: 有效 %d 个流程", len(result.flow_ids))
    if result.skipped_wrong_type:
        logger.info("  跳过非目标流程: %d 条", result.skipped_wrong_type)
    if result.skipped_invalid:
        logger.info("  跳过作废流程: %d 条", result.skipped_invalid)
    if result.skipped_dup:
        logger.info("  跳过重复流程: %d 条", result.skipped_dup)
    return result


def get_week_range(weeks_ago: int = 0) -> tuple[str, str]:
    """计算指定周的开始（周一）和结束日期。

    使用中国时区（Asia/Shanghai）确保周一/周日计算正确。

    注意：weeks_ago=0（本周）时，end_date 为今天（而非本周日），
    即只查询到当前日期为止的数据。weeks_ago>=1 时，end_date 为周日。

    Args:
        weeks_ago: 距离今天的周数，0 表示本周，1 表示上周。
                   不支持负数。

    Returns:
        (start_date, end_date) 字符串，格式 YYYY-MM-DD。
    """
    if weeks_ago < 0:
        raise ValueError(f"weeks_ago 必须 >= 0，收到: {weeks_ago}")
    today = datetime.now(ZoneInfo("Asia/Shanghai"))
    monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks_ago)
    end = today if weeks_ago == 0 else monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _log_credential_source(source: str) -> None:
    """记录凭据来源的回调函数（模块级，避免重复创建闭包）。"""
    logger.info("从 %s 加载登录凭据", source_label(source))


def _load_dms_credentials() -> tuple[str, str]:
    """从共享模块读取登录凭据。"""
    return _get_dms_credentials(on_source=_log_credential_source)


# ==================== 登录 ====================


@retry_async(max_retries=MAX_RETRIES)
async def do_login(page: Page) -> None:
    """自动填写登录表单并提交。"""
    try:
        username, password = _load_dms_credentials()
    except Exception as e:
        logger.error("加载 DMS 登录凭据失败: %s", e)
        raise RuntimeError("无法加载登录凭据，请检查 dms_credentials.json") from e

    logger.info("正在登录...")
    await page.wait_for_selector("#form_item_account", state="visible", timeout=NAV_TIMEOUT)
    await page.locator("#form_item_account").fill(username)
    await page.locator("#form_item_password").fill(password)
    del password
    await page.get_by_role("button", name="登 录").click()
    try:
        await page.wait_for_url(f"{DMS_URL}/**", timeout=NAV_TIMEOUT)
        await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
        masked = username[:3] + "***" + (username[username.index("@"):] if "@" in username else "")
        logger.info("登录成功 (%s)", masked)
    except PlaywrightTimeout:
        if is_on_login_page(page.url):
            raise RuntimeError("登录失败，请检查账号密码")


# ==================== 筛选 ====================


@retry_async(max_retries=2)
async def _navigate_to_process_center(page: Page) -> None:
    """导航到流程中心页面，处理登录重定向。"""
    target = f"{DMS_URL}/#/process/process_center"
    # 确保已登录（只在第一次调用时触发登录，重试时跳过）
    if is_on_login_page(page.url):
        await do_login(page)
    # 导航到目标页面
    if page.url != target:
        await page.goto(target, timeout=NAV_TIMEOUT)
    await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
    await page.wait_for_timeout(WAIT_SHORT)


async def _process_table_rows(
    page: Page,
    result: TableProcessResult,
) -> TableProcessResult:
    """处理当前页面的表格行，提取有效流程编号。

    每行至少需要 2 列（流程编号 + 流程类型）才能被视为有效。
    """
    rows = await page.locator(SELECTORS["table_body"]).first.locator(SELECTORS["table_tbody"]).all()
    logger.debug("找到 %d 行", len(rows))
    if not rows:
        # 回退策略：直接用 tr 选择器查找表格行
        fallback_rows = await page.locator(SELECTORS["table_body"] + " tr").all()
        logger.debug("回退选择器找到 %d 行", len(fallback_rows))
        if fallback_rows:
            rows = fallback_rows

    for row in rows:
        # 批量获取所有 cell 文本，减少 CDP 调用次数（从 N 次降为 1 次）
        cell_texts = await row.locator("td").all_text_contents()
        if len(cell_texts) < 2:
            logger.debug("跳过列数不足的行: %d 列", len(cell_texts))
            continue

        cell_texts = [t.strip().strip('"') for t in cell_texts]
        flow_text = cell_texts[0] if cell_texts else ""

        # 流程编号未匹配（至少 15 位数字），跳过
        if not re.match(r"^\d{15,}$", flow_text):
            logger.debug("跳过非数字流程编号: %s", flow_text)
            continue

        # 按流程类型筛选：仅保留目标流程类型
        flow_type = cell_texts[1] if len(cell_texts) > 1 else ""
        if TARGET_FLOW_TYPE not in flow_type:
            result.skipped_wrong_type += 1
            logger.debug("跳过非目标流程类型: %s (%s)", flow_text, flow_type)
            continue

        status_text = ""
        for t in cell_texts[-3:]:
            if any(k in t for k in ("作废", "驳回", "通过", "审批")):
                status_text = t
                break

        if "作废" in status_text:
            result.skipped_invalid += 1
            logger.debug("跳过作废流程: %s", flow_text)
            continue

        if flow_text in result.seen_ids:
            result.skipped_dup += 1
            logger.debug("跳过重复流程: %s", flow_text)
            continue

        result.add_flow_id(flow_text)

    return result


async def filter_and_get_flow_ids(page: Page, start_date: str, end_date: str) -> TableProcessResult:
    """在已办流程中按日期筛选，返回有效流程编号列表（支持多页翻页）。"""
    logger.info("筛选日期范围: %s ~ %s", start_date, end_date)
    await _navigate_to_process_center(page)

    await page.get_by_role("menuitem", name="已办流程").click()
    await page.wait_for_timeout(WAIT_SHORT)

    # 日期输入框：fill() 会自动清空并输入，无需手动全选
    start_input = page.get_by_placeholder("开始时间")
    await start_input.click()
    await start_input.fill(start_date)

    end_input = page.get_by_placeholder("结束时间")
    await end_input.click()
    await end_input.fill(end_date)
    await page.get_by_role("button", name="查询").click()
    await page.wait_for_timeout(WAIT_MEDIUM)

    # 读取总记录数
    total_el = page.locator(SELECTORS["total_records"])
    if await total_el.count() == 0:
        logger.info("未找到分页信息，可能无记录")
        return TableProcessResult()

    total_text = await total_el.first.text_content() or ""
    total_match = re.search(r"共\s*(\d+)\s*条", total_text)
    total = int(total_match.group(1)) if total_match else 0
    logger.info("共 %d 条记录", total)
    if total == 0:
        return TableProcessResult()

    total_pages = (total + FILTER_PAGE_SIZE - 1) // FILTER_PAGE_SIZE
    logger.info("分页: %d 条/页，共 %d 页", FILTER_PAGE_SIZE, total_pages)

    result = TableProcessResult()

    # 处理第 1 页
    result = await _process_table_rows(page, result)

    # 翻页处理后续页面
    for page_num in range(2, total_pages + 1):
        logger.debug("翻到第 %d 页", page_num)
        try:
            await page.locator(SELECTORS["pagination"]).get_by_text(str(page_num), exact=True).click()
            # 等待表格新数据渲染完成，避免新旧数据重叠导致重复计数
            await page.locator(SELECTORS["table_tbody"]).first.wait_for(
                state="visible", timeout=LOAD_TIMEOUT
            )
            await page.wait_for_timeout(WAIT_MEDIUM)
        except PlaywrightTimeout:
            logger.warning("翻到第 %d 页失败，终止翻页", page_num)
            break

        result = await _process_table_rows(page, result)

    logger.info("有效行: %d 行（去重后 %d 个流程）", result.valid_rows, len(result.flow_ids))
    if result.skipped_wrong_type:
        logger.info("跳过非目标流程: %d 条", result.skipped_wrong_type)
    if result.skipped_invalid:
        logger.info("跳过作废流程: %d 条", result.skipped_invalid)
    if result.skipped_dup:
        logger.info("跳过重复流程: %d 条", result.skipped_dup)
    return result


# ==================== HTML 提取工具 ====================


def _extract_from_html(html: str, label: str) -> str:
    """从 HTML 中按字段 label 提取值。

    匹配策略（按优先级）:
      1. <th>label</th><td>value</td> — 标准表格结构
      2. <th>label</th><th>...<div>value</div></th> — 嵌套结构
    未找到时返回 "--"。
    """
    escaped = re.escape(label)

    # 策略 1: label</th><td>value</td> 或 label</th><th>value</th>
    # 支持标签内任意属性，值直接出现在单元格内
    pattern1 = escaped + r"[:：]?\s*</(?:th|td)>\s*<(?:th|td)>\s*(.*?)\s*</(?:td|th)>"
    m = re.search(pattern1, html)
    if m:
        val = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if val:
            return val

    # 策略 2: 宽泛匹配 — label 后第一个 </th|td> 到下一个 </ 开始之间的内容
    # 用于处理 <th><div>嵌套值</div></th> 这类结构
    # 使用非贪婪匹配 (.*?)，re.DOTALL 下 . 匹配换行符
    # 用 [^<]*(?:<(?!/)[^<]*)* 替代 .*? 防止大 HTML 上的 regex backtracking
    # 该模式匹配：不含 < 的文本，或不含 </ 的标签 — 即停在第一个闭合标签前
    pattern2 = escaped + r"[:：]?\s*</(?:th|td)>\s*([^<]*(?:<(?!/)[^<]*)*)"
    m = re.search(pattern2, html, re.DOTALL)
    if m:
        val = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if val:
            return val

    return "--"


def _split_agent(agent_raw: str | None) -> tuple[str, str]:
    """拆分代理商字段为（编号, 名称）。

    支持的分隔符：单个空格、多个空格、Tab。
    如果无法拆分，编号为整个字符串，名称为 "--"。
    """
    if not agent_raw or agent_raw == "--":
        return "--", "--"
    # 先按连续空白分割
    parts = agent_raw.split()
    if len(parts) >= 2:
        return parts[0].strip(), " ".join(parts[1:]).strip()
    return parts[0].strip(), "--"


# ==================== BOM 提取（Playwright 操作部分） ====================


async def _extract_bom(page: Page, api_detail_data: dict | None = None) -> list[BOMItem]:
    """从详情页提取 BOM 清单。

    优先通过 flowDetails API 的 jsonDate.bomList 获取完整 BOM 数据
    （一次请求返回全部物料，无需翻页）。
    API 不可用时回退到 HTML 表格解析（仅第一页）。

    Args:
        page: Playwright Page 对象（HTML 回退时需要）。
        api_detail_data: 已捕获的 flowDetails API 响应数据。

    Returns:
        BOMItem 列表（BOMItem 定义在 bom_parser 模块）。
    """
    from core.bom_parser import BOMItem

    items: list[BOMItem] = []

    # ---- 方案 A：从 API 响应中获取 BOM 数据 ----
    # flowDetails 接口的 jsonDate 字段包含 productInfo.bomList
    # 其中的字段映射：materialNo=物料编号, materialName=物料名称, num=数量, unitName=单位
    api_bom_data = None
    if api_detail_data:
        json_date = api_detail_data.get('jsonDate') or {}
        if isinstance(json_date, dict):
            product_info = json_date.get('productInfo') or {}
            api_bom_data = product_info.get('bomList')

    if api_bom_data:
        try:
            for entry in api_bom_data:
                code = str(entry.get('materialNo', ''))
                name = str(entry.get('materialName', ''))
                qty_raw = entry.get('num', 0)
                unit = str(entry.get('unitName', ''))
                if not code or not name:
                    continue
                try:
                    qty = round(float(qty_raw))
                except (ValueError, TypeError):
                    continue
                items.append(BOMItem(code=code, name=name, qty=qty, unit=unit))
            logger.debug("BOM 从 API 获取 %d 条物料", len(items))
        except Exception as e:
            logger.warning("API BOM 数据解析失败，回退到 HTML 解析: %s", e)
            items = []

    # ---- 方案 B（回退）：从 HTML 表格提取（仅第一页） ----
    if not items:
        logger.debug("BOM 回退到 HTML 表格解析")
        processed_tables: set[str] = set()
        try:
            tables = await page.locator("table").all()
            for table in tables:
                thead = table.locator("thead")
                if await thead.count() > 0 and "物料编号" in ((await thead.text_content()) or ""):
                    # 使用更精确的选择器：查找紧跟在 thead 表格后的 tbody 表格
                    # 优先查找同级的下一个表格，避免匹配到远处的表格
                    body_table = table.locator("xpath=./following-sibling::table[.//tbody][1]")
                    if await body_table.count() == 0:
                        # 回退到原来的 following 选择器
                        body_table = table.locator("xpath=./following::table[.//tbody][1]")
                    if await body_table.count() > 0:
                        body_text = (await body_table.text_content()) or ""
                        table_fingerprint = body_text.strip()[:200]
                        if table_fingerprint in processed_tables:
                            continue
                        processed_tables.add(table_fingerprint)
                        for row in await body_table.locator("tbody tr").all():
                            cells = await row.locator("td").all()
                            if len(cells) >= 4:
                                code = ((await cells[0].text_content()) or "").strip().strip('"')
                                name = ((await cells[1].text_content()) or "").strip()
                                qty_str = ((await cells[2].text_content()) or "").strip().strip('"')
                                unit = ((await cells[3].text_content()) or "").strip()
                                if not code or not name:
                                    continue
                                try:
                                    qty = round(float(qty_str))
                                except (ValueError, TypeError):
                                    # 数量字段非数字（如 "2 台"、"--"），跳过该行
                                    logger.debug("BOM 数量解析失败，跳过物料 %s: %s", code, qty_str)
                                    continue
                                items.append(BOMItem(code=code, name=name, qty=qty, unit=unit))
        except Exception as e:
            logger.warning("HTML BOM 提取异常: %s", e)

    # 去重（基于物料编号）
    seen: set[str] = set()
    deduped: list[BOMItem] = []
    for item in items:
        if item.code not in seen:
            seen.add(item.code)
            deduped.append(item)
    return deduped


# ==================== 审批信息提取（Playwright 操作部分） ====================


async def _extract_approval_info(page: Page) -> dict[str, str]:
    """从审批历史表提取完整的审批链信息。"""
    from core.approval_parser import extract_approval_info as _extract_approval
    return await _extract_approval(page)


# ==================== API/HTML 解析辅助函数 ====================


def _fill_record_from_api(rec: FlowRecord, api_data: dict, flow_id: str) -> None:
    """从 flowDetails API 响应数据中填充 FlowRecord。

    解析 jsonDate.req（项目信息）、jsonDate.projectManagementPricing（定价）、nodeList（审批链）。

    注意：调用方已确保 jsonDate 已被 _parse_json_date 解析为 dict，此处不再二次解析。
    """
    json_date = api_data.get("jsonDate") or {}
    if not isinstance(json_date, dict):
        logger.warning("api_data['jsonDate'] 不是 dict，使用空字典: flow_id=%s", flow_id)
        json_date = {}

    # req: 项目基本信息（嵌套在 jsonDate 内）
    req = json_date.get("req") or {}
    if not isinstance(req, dict):
        logger.warning("jsonDate.req 不是 dict，类型=%s: flow_id=%s", type(req).__name__, flow_id)
        req = {}

    rec.project_name = req.get("projectName") or "--"

    # 代理商：customerNo + customerName
    customer_no = req.get("customerNo") or ""
    customer_name = req.get("customerName") or ""
    if customer_no and customer_name:
        rec.agent_code = customer_no
        # customerName 格式: "C0021933 徐州辰海星新能源有限公司"
        _, rec.agent_name = _split_agent(customer_name)
    elif customer_name:
        rec.agent_code = "--"
        rec.agent_name = customer_name
    else:
        rec.agent_code = "--"
        rec.agent_name = "--"

    rec.province = req.get("provincialCompanyName") or "--"

    # 业务员：salesmanNo + salesmanName
    salesman_no = req.get("salesmanNo") or ""
    salesman_name = req.get("salesmanName") or ""
    if salesman_no and salesman_name and salesman_name != "--":
        rec.salesperson = f"{salesman_name}({salesman_no})"
    elif salesman_name and salesman_name != "--":
        rec.salesperson = salesman_name
    else:
        rec.salesperson = "--"

    # 定价信息（嵌套在 jsonDate 内）
    pricing = json_date.get("projectManagementPricing") or {}
    # 兼容 pricing 为 JSON 字符串的情况（类似 jsonDate 的双重编码）
    if isinstance(pricing, str):
        try:
            pricing = json.loads(pricing)
        except (json.JSONDecodeError, TypeError):
            pricing = {}
    if isinstance(pricing, dict):
        watt_price = pricing.get("wattUnitPrice")
        rec.unit_price = str(watt_price) if watt_price is not None else "--"
        total_price = pricing.get("totalPrice")
        rec.total_price = str(total_price) if total_price is not None else "--"
    else:
        rec.unit_price = "--"
        rec.total_price = "--"

    # 审批链：从 nodeList 提取
    node_list = api_data.get("nodeList") or []
    _fill_approval_from_nodes(rec, node_list)

    # 调试日志：API 返回的关键字段摘要（脱敏处理）
    logger.debug(
        "API flow_id=%s | project=%r | province=%r | salesman=%r | price=%.2f/%s | pricing_keys=%s",
        flow_id,
        req.get("projectName") or "--",
        req.get("provincialCompanyName") or "--",
        _mask_salesperson(rec.salesperson),
        float(pricing.get("wattUnitPrice") or 0) if isinstance(pricing, dict) else 0,
        rec.total_price,
        list(pricing.keys()) if isinstance(pricing, dict) else [],
    )



def _fill_approval_from_nodes(rec: FlowRecord, node_list: list) -> None:
    """从 API nodeList 填充审批信息。"""
    submit_time = "--"
    province_processor = "--"
    province_status = "--"
    purchase_processor = "--"
    purchase_status = "--"
    final_approval_time = "--"

    for node in node_list:
        role_name = node.get("roleName") or ""
        user_name = node.get("uname") or node.get("userName") or "--"
        status_name = node.get("statusName") or "--"
        update_time = node.get("updateTime") or "--"

        if "流程发起人" in role_name and "提交审核" in status_name:
            submit_time = update_time
        elif "省总" in role_name or "省公司" in role_name:
            province_processor = user_name
            province_status = status_name
        elif "采购" in role_name or "商务" in role_name:
            purchase_processor = user_name
            purchase_status = status_name

        if "通过" in status_name and update_time and update_time not in ("--", ""):
            # 注意：此处使用字符串字典序比较，依赖 DMS 返回 ISO 8601 格式时间
            #（如 "2026-01-03 10:00:00"），其字典序与时间顺序一致。
            # 若 DMS 返回非 ISO 格式，此比较可能产生错误结果。
            if final_approval_time in ("--", "") or update_time > final_approval_time:
                final_approval_time = update_time

    rec.submit_time = submit_time
    rec.province_processor = province_processor
    rec.province_status = province_status
    rec.purchase_processor = purchase_processor
    rec.purchase_status = purchase_status
    rec.final_approval_time = final_approval_time


def _fill_record_from_html(rec: FlowRecord, html: str) -> None:
    """从 HTML 页面解析字段（回退方案）。"""
    rec.project_name = _extract_from_html(html, "项目名称")
    agent_raw = _extract_from_html(html, "代理商")
    rec.agent_code, rec.agent_name = _split_agent(agent_raw)
    rec.province = _extract_from_html(html, "省公司")
    rec.salesperson = _extract_from_html(html, "业务员")
    rec.unit_price = _extract_from_html(html, "瓦单价(元/瓦)")
    rec.total_price = _extract_from_html(html, "总价(元)")


def _fill_approval_from_dict(rec: FlowRecord, approval: dict) -> None:
    """从审批解析结果 dict 填充到 FlowRecord。

    使用 .get() 防御性读取，避免因缺少键导致 KeyError。
    """
    rec.submit_time = approval.get("submit_time", "--")
    rec.province_processor = approval.get("province_processor", "--")
    rec.province_status = approval.get("province_status", "--")
    rec.purchase_processor = approval.get("purchase_processor", "--")
    rec.purchase_status = approval.get("purchase_status", "--")
    rec.final_approval_time = approval.get("final_approval_time", "--")


# ==================== 详情提取 ====================


async def extract_detail_by_url(
    context: BrowserContext, flow_id: str, sem: asyncio.Semaphore,
) -> FlowRecord | None:
    """提取单条询价详情。

    流程：
      1. 打开页面，监听 flowDetails API 响应，捕获 jsonDate
      2. 从 API 数据解析项目信息、定价、审批链
      3. API 数据为空时回退到 HTML 解析
      4. BOM 数据来自 API（jsonDate.productInfo.bomList）
    """
    from core.bom_parser import calc_module_power, calc_inverter_power, calc_battery_capacity, build_remark

    page = None
    try:
        async with sem:
            page = await context.new_page()
            captured_data = None

            async def _capture_detail_api(response: Response) -> None:
                nonlocal captured_data
                if "flowDetails" not in response.url:
                    return
                try:
                    body = await response.json()
                    detail = body.get("data")
                    if detail:
                        _parse_json_date(detail)
                        captured_data = detail
                        logger.debug("页面拦截到 flowDetails API: %s", response.url)
                        try:
                            page.remove_listener("response", _capture_detail_api)
                        except TargetClosedError:
                            pass
                except Exception as e:
                    logger.warning("拦截 flowDetails 响应失败: %s", e)

            page.on("response", _capture_detail_api)
            url = f"{DMS_URL}/#/process/process_detail?bizFlowId={flow_id}&flowStatus=1"
            await page.goto(url, timeout=NAV_TIMEOUT)
            await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
            await page.wait_for_timeout(WAIT_SHORT)
            await ensure_logged_in(page, url)

            api_data = captured_data

            # ===== 填充 record =====
            rec = FlowRecord(flow_id=flow_id)

            if api_data:
                _fill_record_from_api(rec, api_data, flow_id)

                # API 返回的项目信息为空时，回退到 HTML 解析
                if (rec.project_name in ("--", "")
                        and rec.province in ("--", "")
                        and rec.salesperson in ("--", "")):
                    logger.warning(
                        "API 返回的项目信息为空（project_name=%s, province=%s, salesperson=%s），"
                        "回退到 HTML 解析补充: flow_id=%s",
                        rec.project_name, rec.province, rec.salesperson, flow_id,
                    )
                    html = await page.content()
                    _fill_record_from_html(rec, html)
                    approval = await _extract_approval_info(page)
                    _fill_approval_from_dict(rec, approval)
            else:
                # API 完全失败，回退到 HTML 页面解析
                logger.debug("API 数据未获取到，回退到 HTML 解析: flow_id=%s", flow_id)
                html = await page.content()
                _fill_record_from_html(rec, html)
                approval = await _extract_approval_info(page)
                _fill_approval_from_dict(rec, approval)

            # ===== BOM 提取（API 优先，HTML 回退） =====
            bom_items = await _extract_bom(page, api_data)
            rec.module_kw = calc_module_power(bom_items)
            rec.inverter_kw = calc_inverter_power(bom_items)
            rec.battery_kwh = calc_battery_capacity(bom_items)
            rec.remark = build_remark(bom_items)

            return rec
    except PlaywrightTimeout as e:
        logger.warning("%s: 页面操作超时 %s", flow_id, e)
        return None
    except TargetClosedError as e:
        logger.warning("%s: 页面已关闭 %s", flow_id, e)
        return None
    except Exception as e:
        logger.error("%s: 未预期的异常 %s (请报告 Bug)", flow_id, e, exc_info=True)
        return None
    finally:
        if page:
            await page.close()


async def extract_all_parallel(
    context: BrowserContext, flow_ids: list[str], workers: int,
) -> list[FlowRecord]:
    """并行提取所有流程详情。"""
    total = len(flow_ids)
    logger.info("并行提取 %d 条（%d 并发）...", total, workers)
    sem = asyncio.Semaphore(workers)
    tasks = [extract_detail_by_url(context, fid, sem) for fid in flow_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    records: list[FlowRecord] = []
    error_count = 0
    skipped_count = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("[%d/%d] %s: 异常 %s", i + 1, total, flow_ids[i], result)
            error_count += 1
        elif isinstance(result, FlowRecord):
            records.append(result)
        else:
            skipped_count += 1
    logger.info("提取完成: %d/%d 条成功, %d 条异常, %d 条跳过", len(records), total, error_count, skipped_count)
    return records

"""HTML 页面解析与 BOM 提取。

从 dms_browser.py 拆分而来，包含：
  - extract_from_html: 从 HTML 中按字段 label 提取值
  - split_agent: 拆分代理商字段为（编号, 名称）
  - extract_bom: 从详情页提取 BOM 清单
"""

from __future__ import annotations

import re
import logging

from playwright.async_api import Page

logger = logging.getLogger("dms_report")


def extract_from_html(html: str, label: str) -> str:
    """从 HTML 中按字段 label 提取值。

    匹配策略（按优先级）:
      1. <th>label</th><td>value</td> — 标准表格结构
      2. <th>label</th><th>...<div>value</div></th> — 嵌套结构
    未找到时返回 "--"。
    """
    escaped = re.escape(label)

    pattern1 = escaped + r"[:：]?\s*</(?:th|td)>\s*<(?:th|td)>\s*(.*?)\s*</(?:td|th)>"
    m = re.search(pattern1, html)
    if m:
        val = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if val:
            return val

    pattern2 = escaped + r"[:：]?\s*</(?:th|td)>\s*([^<]*(?:<(?!/)[^<]*)*)"
    m = re.search(pattern2, html, re.DOTALL)
    if m:
        val = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if val:
            return val

    return "--"


def split_agent(agent_raw: str | None) -> tuple[str, str]:
    """拆分代理商字段为（编号, 名称）。

    支持的分隔符：单个空格、多个空格、Tab。
    如果无法拆分，编号为整个字符串，名称为 "--"。
    """
    if not agent_raw or agent_raw == "--":
        return "--", "--"
    parts = agent_raw.split()
    if len(parts) >= 2:
        return parts[0].strip(), " ".join(parts[1:]).strip()
    return parts[0].strip(), "--"


async def extract_bom(page: Page, api_detail_data: dict | None = None) -> list:
    """从详情页提取 BOM 清单。

    优先通过 flowDetails API 的 jsonDate.bomList 获取完整 BOM 数据。
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
            bom_header = page.locator(
                "xpath=.//table[.//thead[.//th[normalize-space()='物料编号']]]"
            )
            header_count = await bom_header.count()
            for idx in range(header_count):
                table = bom_header.nth(idx)
                body_table = table.locator("xpath=./following-sibling::table[.//tbody][1]")
                if await body_table.count() == 0:
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

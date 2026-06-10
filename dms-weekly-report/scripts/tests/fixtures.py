"""共享的测试数据和 Mock 对象。"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock
import sys
from pathlib import Path

# 添加 scripts 目录到路径，以便导入
sys.path.insert(0, str(Path(__file__).parent.parent))


# ==================== 测试数据 ====================

@dataclass
class MockBOMItem:
    """模拟 BOM 项。"""
    code: str
    name: str
    qty: int
    unit: str


# 常用的 BOM 项数据
BOM_INVERTER = MockBOMItem(
    code="INV-001",
    name="Trina Inverter TSM50KTL-US 50KW",
    qty=1,
    unit="套"
)

BOM_MODULE = MockBOMItem(
    code="MOD-001",
    name="Trina Module TSM-415DE09RS 415W",
    qty=240,
    unit="块"
)

BOM_BATTERY = MockBOMItem(
    code="BAT-001",
    name="LG Chem RESU10H 9.8kWh",
    qty=10,
    unit="组"
)

SAMPLE_BOM_ITEMS = [
    BOM_MODULE,
    BOM_INVERTER,
    BOM_BATTERY,
]

# ==================== 模拟流程记录 ====================

SAMPLE_FLOW_ID = "FLOW-2026-0001"
SAMPLE_PROJECT_NAME = "北京某光伏电站"
SAMPLE_AGENT_CODE = "AGENT-001"
SAMPLE_AGENT_NAME = "某光伏公司"
SAMPLE_PROVINCE = "北京"
SAMPLE_SALESPERSON = "张三"

# ==================== 模拟审批数据 ====================

SAMPLE_APPROVAL_INFO = {
    "submit_time": "2026-06-01 10:00",
    "province_processor": "李四",
    "province_status": "已批准",
    "purchase_processor": "王五",
    "purchase_status": "已批准",
    "final_approval_time": "2026-06-03 15:30",
}

# ==================== 模拟 HTML 内容 ====================

SAMPLE_HTML_CONTENT = """
<html>
<body>
    <div class="form-group">
        <label>项目名称</label>
        <span>北京某光伏电站</span>
    </div>
    <div class="form-group">
        <label>代理商</label>
        <span>AGENT-001 某光伏公司</span>
    </div>
    <div class="form-group">
        <label>省公司</label>
        <span>北京</span>
    </div>
    <div class="form-group">
        <label>业务员</label>
        <span>张三</span>
    </div>
    <table id="bom-table">
        <tr>
            <td>INV-001</td>
            <td>Trina Inverter TSM50KTL-US 50KW</td>
            <td>1</td>
            <td>套</td>
        </tr>
        <tr>
            <td>MOD-001</td>
            <td>Trina Module TSM-415DE09RS 415W</td>
            <td>240</td>
            <td>块</td>
        </tr>
    </table>
</body>
</html>
"""

# ==================== Async Mock 工具 ====================


def create_mock_page():
    """创建模拟的 Playwright Page 对象。"""
    page = AsyncMock()
    page.goto = AsyncMock(return_value=None)
    page.wait_for_load_state = AsyncMock(return_value=None)
    page.wait_for_timeout = AsyncMock(return_value=None)
    page.content = AsyncMock(return_value=SAMPLE_HTML_CONTENT)
    page.locator = MagicMock(return_value=AsyncMock())
    page.close = AsyncMock(return_value=None)
    return page


def create_mock_context():
    """创建模拟的 Playwright BrowserContext 对象。"""
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=create_mock_page())
    return context


def create_mock_browser():
    """创建模拟的 Playwright Browser 对象。"""
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=create_mock_context())
    browser.close = AsyncMock(return_value=None)
    return browser


# ==================== 工具函数 ====================


def compare_floats(a: float, b: float, tolerance: float = 0.01) -> bool:
    """比较两个浮点数是否接近（用于功率和容量计算）。"""
    return abs(a - b) < tolerance

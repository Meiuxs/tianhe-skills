"""_compat.py 单元测试。"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from _compat import captured_run, ENCODING


class TestCapturedRun:
    """测试 captured_run 函数。"""

    def test_basic_command(self):
        result = captured_run([sys.executable, "-c", "print('hello')"])
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_utf8_encoding(self):
        result = captured_run(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xe4\\xb8\\xad\\xe6\\x96\\x87')"],
            encoding=None,
        )
        assert result.returncode == 0
        assert b'\xe4\xb8\xad\xe6\x96\x87' in result.stdout

    def test_stderr_capture(self):
        result = captured_run(
            [sys.executable, "-c", "import sys; sys.stderr.write('error msg')"],
            capture_output=True,
        )
        assert "error msg" in result.stderr

    def test_returncode_on_error(self):
        result = captured_run(
            [sys.executable, "-c", "import sys; sys.exit(42)"],
        )
        assert result.returncode == 42

    def test_timeout(self):
        with pytest.raises(subprocess.TimeoutExpired):
            captured_run(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=0.1,
            )

    def test_encoding_none_returns_bytes(self):
        result = captured_run(
            [sys.executable, "-c", "print('bytes')"],
            encoding=None,
        )
        assert isinstance(result.stdout, bytes)

    def test_cwd_parameter(self, tmp_path):
        result = captured_run(
            [sys.executable, "-c", "import os; print(os.getcwd())"],
            cwd=str(tmp_path),
        )
        assert str(tmp_path) in result.stdout

    def test_env_parameter(self):
        result = captured_run(
            [sys.executable, "-c", "import os; print(os.environ.get('TEST_VAR_123'))"],
            env={**dict(__import__("os").environ), "TEST_VAR_123": "hello_env"},
        )
        assert "hello_env" in result.stdout


class TestEncoding:
    """测试 ENCODING 常量。"""

    def test_encoding_is_utf8(self):
        assert ENCODING == "utf-8"

    def test_encoding_is_string(self):
        assert isinstance(ENCODING, str)

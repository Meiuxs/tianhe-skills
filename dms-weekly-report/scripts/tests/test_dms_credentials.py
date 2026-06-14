"""dms_credentials.py 单元测试。"""

import os
import tempfile
from unittest.mock import patch

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dms_credentials import (
    _parse_env_from_file,
    _get_home,
    check_current_env,
    source_label,
    SOURCE_LABELS,
)


class TestParseEnvFromFile:
    """测试 _parse_env_from_file 函数。"""

    def test_double_quoted_values(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text('export DMS_USER="testuser"\nexport DMS_PASSWORD="testpass"\n', encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == "testuser"
        assert password == "testpass"

    def test_single_quoted_values(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text("export DMS_USER='user1'\nexport DMS_PASSWORD='pass1'\n", encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == "user1"
        assert password == "pass1"

    def test_unquoted_values(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text("DMS_USER=plainuser\nDMS_PASSWORD=plainpass\n", encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == "plainuser"
        assert password == "plainpass"

    def test_without_export_prefix(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text('DMS_USER="noexport"\nDMS_PASSWORD="noexport"\n', encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == "noexport"
        assert password == "noexport"

    def test_with_trailing_comment(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text('DMS_USER="user" # this is a comment\n', encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == "user"
        assert password is None

    def test_escaped_quotes_in_double_quoted(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text(r'DMS_USER="user\"name"' + "\n", encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == 'user"name'

    def test_file_not_found(self):
        user, password = _parse_env_from_file("/nonexistent/.bashrc")
        assert user is None
        assert password is None

    def test_empty_file(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text("", encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user is None
        assert password is None

    def test_only_user_no_password(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text('DMS_USER="onlyuser"\n', encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == "onlyuser"
        assert password is None

    def test_only_password_no_user(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text('DMS_PASSWORD="onlypass"\n', encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user is None
        assert password == "onlypass"

    def test_mixed_formats_in_file(self, tmp_path):
        rc = tmp_path / ".bashrc"
        content = (
            'export DMS_USER="quoted_user"\n'
            "DMS_PASSWORD=unquoted_pass\n"
            "export OTHER_VAR=ignored\n"
        )
        rc.write_text(content, encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == "quoted_user"
        assert password == "unquoted_pass"

    def test_line_without_equals_ignored(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text("DMS_USER\nDMS_PASSWORD\n", encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user is None
        assert password is None


class TestCheckCurrentEnv:
    """测试 check_current_env 函数。"""

    def test_both_set(self):
        with patch.dict(os.environ, {"DMS_USER": "envuser", "DMS_PASSWORD": "envpass"}):
            result = check_current_env()
            assert result is not None
            assert result[0] == "current"
            assert result[1] == "envuser"
            assert result[2] == "envpass"

    def test_user_missing(self):
        env = os.environ.copy()
        env.pop("DMS_USER", None)
        env["DMS_PASSWORD"] = "pass"
        with patch.dict(os.environ, env, clear=True):
            result = check_current_env()
            assert result is None

    def test_password_missing(self):
        env = os.environ.copy()
        env["DMS_USER"] = "user"
        env.pop("DMS_PASSWORD", None)
        with patch.dict(os.environ, env, clear=True):
            result = check_current_env()
            assert result is None

    def test_both_empty(self):
        env = os.environ.copy()
        env["DMS_USER"] = ""
        env["DMS_PASSWORD"] = ""
        with patch.dict(os.environ, env, clear=True):
            result = check_current_env()
            assert result is None


class TestSourceLabel:
    """测试 source_label 函数。"""

    def test_known_sources(self):
        for key, label in SOURCE_LABELS.items():
            assert source_label(key) == label

    def test_unknown_source_returns_original(self):
        assert source_label("unknown_key") == "unknown_key"

    def test_empty_string(self):
        assert source_label("") == ""

    def test_current_source(self):
        assert source_label("current") == "当前环境变量"


class TestGetHome:
    """测试 _get_home 函数。"""

    def test_returns_string(self):
        result = _get_home()
        assert isinstance(result, str)

    def test_returns_non_empty(self):
        result = _get_home()
        assert len(result) > 0

    def test_caching(self):
        import dms_credentials
        dms_credentials._HOME = None
        home1 = _get_home()
        home2 = _get_home()
        assert home1 == home2


class TestGetHomeReset:
    def test_reset_and_recompute(self):
        import dms_credentials
        dms_credentials._HOME = None
        home1 = dms_credentials._get_home()
        dms_credentials._HOME = "/fake/home"
        home2 = dms_credentials._get_home()
        assert home2 == "/fake/home"
        dms_credentials._HOME = None

class TestGetHomeReset:
    """测试 _get_home 缓存可被重置。"""

    def test_reset_and_recompute(self):
        import dms_credentials
        dms_credentials._HOME = None
        home1 = dms_credentials._get_home()
        dms_credentials._HOME = "/fake/home"
        home2 = dms_credentials._get_home()
        assert home2 == "/fake/home"
        dms_credentials._HOME = None


class TestGetCredentials:
    """测试 get_credentials 函数。"""

    def test_returns_credentials_when_found(self):
        import dms_credentials
        with patch.object(dms_credentials, "resolve_credentials", return_value=("current", "testuser", "testpass")):
            user, password = dms_credentials.get_credentials()
            assert user == "testuser"
            assert password == "testpass"

    def test_calls_on_source_callback(self):
        import dms_credentials
        captured = []
        with patch.object(dms_credentials, "resolve_credentials", return_value=("current", "u", "p")):
            dms_credentials.get_credentials(on_source=captured.append)
        assert captured == ["current"]

    def test_exits_when_not_found(self):
        import dms_credentials
        with patch.object(dms_credentials, "resolve_credentials", return_value=None):
            with pytest.raises(SystemExit):
                dms_credentials.get_credentials()


class TestResolveCredentials:
    """测试 resolve_credentials 按优先级返回第一个匹配。"""

    def test_current_env_takes_priority(self):
        import dms_credentials
        with patch.object(dms_credentials, "check_current_env", return_value=("current", "u", "p")),              patch.object(dms_credentials, "check_bash_profiles", return_value=("bashrc_direct", "u2", "p2")):
            result = dms_credentials.resolve_credentials()
            assert result[0] == "current"

    def test_falls_through_to_bash_profiles(self):
        import dms_credentials
        with patch.object(dms_credentials, "check_current_env", return_value=None),              patch.object(dms_credentials, "check_bash_profiles", return_value=("bashrc_direct", "u", "p")):
            result = dms_credentials.resolve_credentials()
            assert result[0] == "bashrc_direct"

    def test_returns_none_when_all_fail(self):
        import dms_credentials
        with patch.object(dms_credentials, "check_current_env", return_value=None),              patch.object(dms_credentials, "check_bash_profiles", return_value=None),              patch.object(dms_credentials, "check_powershell", return_value=None):
            result = dms_credentials.resolve_credentials()
            assert result is None


class TestCheckChromium:
    """测试 check_chromium 函数。"""

    def test_returns_true_when_both_found(self, tmp_path):
        import dms_credentials
        dms_credentials._HOME = str(tmp_path)
        chromium_dir = tmp_path / "AppData" / "Local" / "ms-playwright" / "chromium-1234" / "chrome-win64"
        chromium_dir.mkdir(parents=True)
        (chromium_dir / "chrome.exe").touch()
        headless_dir = tmp_path / "AppData" / "Local" / "ms-playwright" / "chromium_headless_shell-1234" / "chrome-win"
        headless_dir.mkdir(parents=True)
        (headless_dir / "headless_shell.exe").touch()
        assert dms_credentials.check_chromium() is True

    def test_returns_false_when_chromium_missing(self, tmp_path):
        import dms_credentials
        dms_credentials._HOME = str(tmp_path)
        assert dms_credentials.check_chromium() is False

    def test_returns_false_when_headless_missing(self, tmp_path):
        import dms_credentials
        dms_credentials._HOME = str(tmp_path)
        chromium_dir = tmp_path / "AppData" / "Local" / "ms-playwright" / "chromium-1234" / "chrome-win64"
        chromium_dir.mkdir(parents=True)
        (chromium_dir / "chrome.exe").touch()
        assert dms_credentials.check_chromium() is False


class TestParseEnvEdgeCases:
    """测试 _parse_env_from_file 的边界情况。"""

    def test_unicode_values(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text('DMS_USER="\u7528\u6237"\nDMS_PASSWORD="\u5bc6\u7801123"\n', encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == "\u7528\u6237"
        assert password == "\u5bc6\u7801123"

    def test_value_with_hash_no_space(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text('DMS_USER="value#nocomment"\n', encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == "value#nocomment"

    def test_single_quoted_value_with_backslash(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text("DMS_USER='user\\\\name'\n", encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == "user\\\\name"

    def test_duplicate_var_last_wins(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text('DMS_USER="first"\nDMS_USER="second"\n', encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user == "second"

    def test_empty_quoted_value(self, tmp_path):
        rc = tmp_path / ".bashrc"
        rc.write_text('DMS_USER=""\nDMS_PASSWORD="pass"\n', encoding="utf-8")
        user, password = _parse_env_from_file(str(rc))
        assert user is None
        assert password == "pass"

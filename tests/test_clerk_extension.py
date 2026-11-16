"""Chrome 扩展的结构性测试：合规红线不靠自觉，靠测试盯着。

扩展本体是 JS，跑不了 pytest——但它的**设计承诺**可以在这里锁死：
1. manifest 是合法 MV3，权限最小化（无 host_permissions）
2. 源码里不存在"代替店主发送"的能力标识符
3. 弹窗/内容脚本/后台三件套齐全
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))


class TestManifest:
    def test_is_mv3_with_service_worker(self, manifest):
        assert manifest["manifest_version"] == 3
        assert manifest["background"]["service_worker"] == "background.js"

    def test_permissions_are_minimal(self, manifest):
        assert set(manifest["permissions"]) == {"contextMenus", "storage"}

    def test_no_host_permissions(self, manifest):
        # 设计决定：后端 CORS 全开，service worker 直接 fetch 即可。
        # 不申请 host_permissions = 商店审核面最小 + "不监视用户浏览"的合规姿态。
        assert "host_permissions" not in manifest

    def test_content_script_registered(self, manifest):
        assert manifest["content_scripts"][0]["js"] == ["content.js"]
        assert manifest["action"]["default_popup"] == "popup.html"


class TestComplianceRedlines:
    @pytest.mark.parametrize("filename", ["background.js", "content.js", "popup.js"])
    def test_files_exist_and_nontrivial(self, filename):
        source = (EXT / filename).read_text(encoding="utf-8")
        assert len(source) > 500

    @pytest.mark.parametrize("filename", ["background.js", "content.js", "popup.js"])
    def test_no_auto_send_capability(self, filename):
        """建议模式的红线：不存在免手发送的标识符。

        只禁"能力"（标识符），不禁"讨论"（注释里说明为什么不这样做是允许的）。
        """
        source = (EXT / filename).read_text(encoding="utf-8")
        for banned in ("autoSend", "auto_send", "sendAutomatically", "autoReply", "auto_reply"):
            assert banned not in source, f"{filename} 出现了禁止的能力标识符 {banned}"

    def test_extension_never_touches_credentials(self):
        """不碰密码/cookie 是产品承诺：源码里不许出现 cookie 读写与 password 字段。"""
        for filename in ("background.js", "content.js", "popup.js"):
            source = (EXT / filename).read_text(encoding="utf-8")
            assert "document.cookie" not in source, filename
            assert "password" not in source.lower(), filename

    def test_readme_documents_stance(self):
        readme = (EXT / "README.md").read_text(encoding="utf-8")
        assert "永不代替发送" in readme
        assert "划词" in readme

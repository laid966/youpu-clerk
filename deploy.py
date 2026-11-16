"""G4 部署脚本：一条命令把当前仓库部署/更新到 Linux 服务器（纯 python + ssh/scp，不依赖 rsync）。

用法（在你本机跑）：
    .venv\\Scripts\\python.exe deploy.py user@服务器域名 站点域名
    例：python deploy.py root@1.2.3.4 clerk.example.com

流程（幂等，重复跑 = 更新部署）：
1. 本地打 tar 包（**排除 .venv / .git / data / .env / __pycache__ / *.db**——密钥与数据永不上传）
2. scp 上传 → 服务器解到 /tmp → `cp -a` 覆盖进 /opt/clerk（.env 与 data/ 不在包里，天然保留）
3. 远端：首次建 venv → pip install -r requirements.txt → 首次写 Caddyfile（自动 HTTPS）→ restart clerk.service
4. 本地对 https://站点域名 跑 clerk.smoke 六项验收；首次 Let's Encrypt 签发证书可能慢，自动重试 3 次

一次性手动前置（见 docs/33-部署手册.md §2）：
- 服务器 apt 装好 python3.12 / caddy；systemd unit clerk.service 已放置
- 域名已备案并解析到服务器
- 服务器 /opt/clerk/.env 已填好 ALIPAY_* 等（本脚本不碰它）
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

EXCLUDE_DIRS = {".venv", ".git", "data", "__pycache__", ".pytest_cache", "node_modules", "backups"}
EXCLUDE_NAMES = {".env", ".env.local", "deploy.py"}  # deploy.py 只在本地跑，不需要上车


def _include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if set(rel.parts) & EXCLUDE_DIRS:
        return False
    if path.name in EXCLUDE_NAMES:
        return False
    if path.suffix in (".pyc", ".db", ".sqlite"):
        return False
    return True


def build_tarball() -> Path:
    out = Path(tempfile.mkdtemp(prefix="clerk-deploy-")) / "clerk-deploy.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file() and _include(path):
                tar.add(path, arcname=path.relative_to(ROOT).as_posix())
    return out


REMOTE_SETUP = r"""
set -euo pipefail
mkdir -p /opt/clerk
cp -a /tmp/clerk-deploy/. /opt/clerk/
rm -rf /tmp/clerk-deploy
cd /opt/clerk
if [ ! -d .venv ]; then python3.12 -m venv .venv; fi
.venv/bin/pip install -q -r requirements.txt
mkdir -p data backups
if [ ! -f /etc/caddy/Caddyfile ]; then
  printf '%s {\n    reverse_proxy 127.0.0.1:8100\n}\n' "__DOMAIN__" | tee /etc/caddy/Caddyfile
  systemctl reload caddy || systemctl restart caddy
fi
systemctl restart clerk
sleep 2
systemctl is-active clerk
"""


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(">", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, **kwargs)


def main(target: str, domain: str) -> int:
    tarball = build_tarball()
    print(f"打包完成：{tarball}（{tarball.stat().st_size // 1024} KB）")

    run(["scp", str(tarball), f"{target}:/tmp/clerk-deploy.tar.gz"])
    run(["ssh", target, "rm -rf /tmp/clerk-deploy && mkdir -p /tmp/clerk-deploy "
                         "&& tar -xzf /tmp/clerk-deploy.tar.gz -C /tmp/clerk-deploy"])
    run(["ssh", target, "bash -se"], input=REMOTE_SETUP.replace("__DOMAIN__", domain).encode("utf-8"))

    probe = None
    for attempt in range(1, 4):
        probe = subprocess.run(
            [sys.executable, "-m", "clerk.smoke", f"https://{domain}"], cwd=ROOT
        )
        if probe.returncode == 0:
            print(f"\n部署完成：https://{domain} ✅")
            return 0
        print(f"\n冒烟未通过（第 {attempt}/3 次）——首次证书签发可能未完成，10 秒后重试")
        time.sleep(10)
    print(f"\n部署后冒烟失败：https://{domain} —— 按 docs/36 事故处置树排查")
    return probe.returncode if probe else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))

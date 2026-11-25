"""生成支付宝开放平台 RSA2 密钥对——只在本机跑，产物落 data/（已 gitignore）。

## why
凭证四件套里最容易做错的一步是密钥格式（头尾/换行/PKCS1 vs PKCS8）。
本脚本一次生成两种可直接粘贴的形态：
  - 应用公钥：X509 DER 的 base64 单行（开放平台"接口加签方式=公钥"要的就是它，无头无尾无换行）
  - 应用私钥：PKCS8 DER 的 base64 单行（clerk/pay_vibe.py 的 ALIPAY_PRIVATE_KEY 直接吃）

产物：
  data/alipay_app_public_key.b64   → 粘到开放平台
  data/alipay_app_private_key.b64  → 进你自己的 .env，不给任何人

用法：.venv\\Scripts\\python.exe tools/make_alipay_keys.py
"""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

OUT = Path("data")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    priv_der = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    priv_b64 = base64.b64encode(priv_der).decode()
    pub_b64 = base64.b64encode(pub_der).decode()

    (OUT / "alipay_app_private_key.b64").write_text(priv_b64, encoding="utf-8")
    (OUT / "alipay_app_public_key.b64").write_text(pub_b64, encoding="utf-8")

    print("应用公钥（粘贴到 开放平台→开发设置→接口加签方式→公钥）：")
    print(pub_b64)
    print()
    print("应用私钥已写入 data/alipay_app_private_key.b64（gitignore 已挡，只进你自己的 .env）")


if __name__ == "__main__":
    main()

"""FastAPI 工作台：clerk 的唯一 HTTP 入口。

## 职责（集成层——业务判断都在 service/bargain，这里只做映射与接线）
1. 把 docs/32 契约 §3 的 API 落成 HTTP：错误类 → 状态码/错误码
   （QuotaExceeded → **402**，向 Machine Pay 的语义致敬；NotFound → 404；其余 → 400）
2. 托管 clerk/web 前端静态文件——评委打开站点即产品
3. 演示模式 /api/demo/*：**强制 TemplateJudge + 自动采纳**（评委 60 秒路径；
   进度由服务端从台账推导，刷新页面剧本接着走）
4. 支付桩 /api/pay/*：G2 闸门前一律 501——**明确说"没接入"，不假装能用**

## 两个刻意决定
- **每请求开/关数据库连接**：不跨线程共享 sqlite 连接（clerk/db.py 的纪律）。
- **CORS 全开**：Chrome 扩展要从 goofish.com 页面跨域调用；凭证走 X-Clerk-User 头
  而不是 cookie，全开 CORS 不构成凭据泄露面。

## 跑起来
    .venv\\Scripts\\python.exe -m uvicorn clerk.server:app --port 8100
    # 打开 http://127.0.0.1:8100 ——无 API key 也能完整演示（TemplateJudge 自动兜底）
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import clerk.db as db
from clerk import config, demo, machine_pay, pay, pay_vibe, service
from clerk.bargain import (
    BargainError,
    BargainFacts,
    decide_bargain,
    default_floor_price,
    to_money,
)
from clerk.service import (
    ClerkError,
    GlobalQuotaExhausted,
    ItemNotFound,
    QuotaExceeded,
    SuggestionNotFound,
)
from clerk.templates import LANGUAGES, TemplateJudge, select_judge

__all__ = ["app", "main"]

WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动预热：单连接建表 + 完成 WAL 切换，把唯一需要排他锁的动作留在流量之前。"""
    with get_conn():
        pass
    yield


app = FastAPI(title=config.PRODUCT_NAME, description=config.PRODUCT_TAGLINE, lifespan=lifespan)

# 测试覆盖位：置为 TemplateJudge/FakeJudge 可让全部真实链路测试离线跑。
# None 时首个请求触发 select_judge()（有 key → DeepSeek+缓存；无 key → TemplateJudge）。
app.state.judge = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# 错误映射：每类异常一个稳定错误码（前端按 code 查 i18n 字典，见契约 §0）
# --------------------------------------------------------------------------- #


class UserTokenRequired(ClerkError):
    """缺 X-Clerk-User 头。前端应在 localStorage 生成 UUID 并随每个请求携带。"""


class ConversationNotFound(ClerkError):
    pass


def _error_response(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message, **extra}}
    )


def _simple_handler(status: int, code: str):
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(status, code, str(exc))

    return handle


@app.exception_handler(QuotaExceeded)
async def _quota_handler(request: Request, exc: QuotaExceeded) -> JSONResponse:
    # 402 + 定价：前端拿到就弹付费引导——额度墙本身就是收银台入口
    return _error_response(402, "QUOTA_EXCEEDED", str(exc), pricing=exc.pricing)


app.add_exception_handler(ItemNotFound, _simple_handler(404, "ITEM_NOT_FOUND"))
app.add_exception_handler(SuggestionNotFound, _simple_handler(404, "SUGGESTION_NOT_FOUND"))
app.add_exception_handler(ConversationNotFound, _simple_handler(404, "CONVERSATION_NOT_FOUND"))
app.add_exception_handler(UserTokenRequired, _simple_handler(400, "USER_TOKEN_REQUIRED"))
# 全站预算闸用 503（今天打烊了，明天再来）——与 402（你该付费了）语义刻意分开
app.add_exception_handler(GlobalQuotaExhausted, _simple_handler(503, "GLOBAL_QUOTA_EXHAUSTED"))
app.add_exception_handler(ClerkError, _simple_handler(400, "BAD_REQUEST"))
app.add_exception_handler(db.DbError, _simple_handler(400, "DB_REJECTED"))
app.add_exception_handler(demo.DemoError, _simple_handler(400, "DEMO_ERROR"))
app.add_exception_handler(BargainError, _simple_handler(400, "BARGAIN_ERROR"))
app.add_exception_handler(pay.PayError, _simple_handler(400, "PAY_REJECTED"))


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #


@contextmanager
def get_conn() -> Iterator[db.sqlite3.Connection]:
    conn = db.open_db()
    try:
        yield conn
    finally:
        conn.close()


def require_token(request: Request) -> str:
    token = (request.headers.get("x-clerk-user") or "").strip()
    if not token:
        raise UserTokenRequired(
            "缺少 X-Clerk-User 请求头（客户端生成 UUID 存 localStorage，随每个请求携带）"
        )
    return token


def resolve_judge() -> Any:
    if app.state.judge is None:
        app.state.judge = select_judge()
    return app.state.judge


def _dump(payload: BaseModel) -> dict:
    """pydantic v2/v1 双兼容的导出（环境里两代 API 都出现过，不赌版本）。"""
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_none=True)
    return payload.dict(exclude_none=True)  # pragma: no cover — pydantic v1 兜底


_JSON_FIELDS = ("citations_json", "reasons_json", "judgement_json", "classification_json", "guardrail_json")


def _expand_decision(row: dict) -> dict:
    """台账行 → API 形状：*_json 解析回结构，布尔归一。"""
    out = dict(row)
    for key in _JSON_FIELDS:
        raw = out.pop(key, None)
        out[key.replace("_json", "")] = json.loads(raw) if raw else None
    out["requires_human_review"] = bool(out.get("requires_human_review"))
    return out


# --------------------------------------------------------------------------- #
# 请求体模型（契约 §3）
# --------------------------------------------------------------------------- #


class ItemCreate(BaseModel):
    title: str
    asking_price: str
    floor_price: str | None = None


class ItemUpdate(BaseModel):
    title: str | None = None
    asking_price: str | None = None
    floor_price: str | None = None
    status: str | None = None


class InquiryRequest(BaseModel):
    item_id: str
    message: str
    conversation_id: str | None = None
    source: str = "paste"


class AdoptRequest(BaseModel):
    action: str
    final_text: str | None = None


class DemoStepRequest(BaseModel):
    persona_id: str
    conversation_id: str | None = None


class PayOrderRequest(BaseModel):
    product_code: str


class PayNotifyRequest(BaseModel):
    out_trade_no: str
    amount: str | float
    trade_no: str | None = None


class PayQueryRequest(BaseModel):
    out_trade_no: str


# --------------------------------------------------------------------------- #
# 基础与商品
# --------------------------------------------------------------------------- #


@app.get("/api/health")
def health() -> dict:
    import agent.judge  # noqa: F401 — 触发 .env 加载（密钥加载跟着用它的模块走）

    judge = resolve_judge()
    return {
        "status": "ok",
        "product": config.PRODUCT_NAME,
        "tagline": config.PRODUCT_TAGLINE,
        "version": "0.1.0",
        "languages": list(LANGUAGES),
        "judge_mode": "template" if isinstance(judge, TemplateJudge) else "llm",
        "has_api_key": bool(os.getenv("DEEPSEEK_API_KEY")),
    }


@app.post("/api/items")
def create_item(payload: ItemCreate, request: Request) -> dict:
    token = require_token(request)
    asking = str(to_money(payload.asking_price))
    floor = (
        str(to_money(payload.floor_price))
        if payload.floor_price
        else str(default_floor_price(asking))  # 智能默认：底价 = 挂牌 × 0.85，卖家可再调
    )
    with get_conn() as conn:
        db.ensure_user(conn, token)
        item = db.create_item(conn, token, payload.title, asking, floor)
    return {"item": item}


@app.get("/api/items")
def list_items(request: Request) -> dict:
    token = require_token(request)
    with get_conn() as conn:
        db.ensure_user(conn, token)
        return {"items": db.list_items(conn, token)}


@app.patch("/api/items/{item_id}")
def update_item(item_id: str, payload: ItemUpdate, request: Request) -> dict:
    token = require_token(request)
    fields = _dump(payload)
    for key in ("asking_price", "floor_price"):
        if key in fields:
            fields[key] = str(to_money(fields[key]))
    with get_conn() as conn:
        item = db.update_item(conn, token, item_id, **fields)
    return {"item": item}


# --------------------------------------------------------------------------- #
# 核心链路：询价 → 建议 → 采纳
# --------------------------------------------------------------------------- #


@app.post("/api/inquiry")
def inquiry(payload: InquiryRequest, request: Request) -> dict:
    token = require_token(request)
    with get_conn() as conn:
        return service.suggest(
            token=token,
            item_id=payload.item_id,
            message=payload.message,
            conversation_id=payload.conversation_id,
            source=payload.source,
            judge=resolve_judge(),
            conn=conn,
        )


@app.post("/api/inquiries/{suggestion_id}/adopt")
def adopt_inquiry(suggestion_id: str, payload: AdoptRequest, request: Request) -> dict:
    token = require_token(request)
    with get_conn() as conn:
        return service.adopt(
            suggestion_id=suggestion_id,
            action=payload.action,
            final_text=payload.final_text,
            token=token,
            conn=conn,
        )


@app.get("/api/conversations")
def list_conversations(request: Request) -> dict:
    token = require_token(request)
    with get_conn() as conn:
        return {"conversations": db.list_conversations(conn, token)}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request) -> dict:
    token = require_token(request)
    with get_conn() as conn:
        conv = db.get_conversation(conn, conversation_id)
        # 越权访问报"不存在"——不向探测者泄露资源存在性
        if conv is None or conv["token"] != token:
            raise ConversationNotFound(conversation_id)
        messages = db.get_conversation_messages(conn, conversation_id)
        decisions = [
            _expand_decision(row) for row in db.get_conversation_decisions(conn, conversation_id)
        ]
    return {"conversation": conv, "messages": messages, "decisions": decisions}


@app.get("/api/ledger")
def ledger(request: Request, day: str | None = None) -> dict:
    token = require_token(request)
    day = day or db.today_shanghai()
    with get_conn() as conn:
        rows = db.ledger_by_day(conn, token, day)
    return {"day": day, "entries": [_expand_decision(row) for row in rows]}


@app.get("/api/report/daily")
def report_daily(request: Request, day: str | None = None) -> dict:
    token = require_token(request)
    with get_conn() as conn:
        return service.daily_report(token=token, day=day, conn=conn)


# --------------------------------------------------------------------------- #
# 演示模式（评委 60 秒路径：无账号、无 key、无扩展）
# --------------------------------------------------------------------------- #


@app.get("/api/demo/bootstrap")
def demo_bootstrap() -> dict:
    return demo.bootstrap()


@app.post("/api/demo/step")
def demo_step(payload: DemoStepRequest) -> dict:
    """推进一步演示剧本。

    进度不存客户端：conversation_id 回传后，step_index 从台账里的买家消息数推导——
    刷新页面、换设备，剧本都从真实数据接着走。每步自动 adopt(sent)，
    让步计数（I1）随之递推，梯度才会真的走完 T1→T2→T3→firm。
    """
    with get_conn() as conn:
        seeded = demo.seed_demo(conn)
        persona = demo.get_persona(payload.persona_id)
        item = seeded[persona["item_key"]]

        step_index = (
            demo.step_index_for_conversation(conn, payload.conversation_id)
            if payload.conversation_id
            else 0
        )
        step = demo.next_step(payload.persona_id, step_index)

        # 演示强制 TemplateJudge：评委现场没有我们的 key，且每步必须逐字节可复现
        result = service.suggest(
            token=demo.DEMO_TOKEN,
            item_id=item["id"],
            message=step["message"],
            conversation_id=payload.conversation_id,
            source="demo",
            judge=TemplateJudge(),
            conn=conn,
        )
        adoption = service.adopt(
            suggestion_id=result["suggestion_id"],
            action="sent",
            token=demo.DEMO_TOKEN,
            conn=conn,
        )

    return {
        **result,
        "persona_message": step["message"],
        "note_zh": step["note_zh"],
        "note_en": step["note_en"],
        "expected": step["expected"],
        "expected_classify": step["expected_classify"],
        "step_index": step["step_index"],
        "total_steps": step["total_steps"],
        "finished": step["finished"],
        "concessions_used": adoption["concessions_used"],
        "persona": {
            key: persona[key]
            for key in (
                "id", "name_zh", "name_en", "style_zh", "style_en",
                "language", "avatar_color", "item_key",
            )
        },
    }


# --------------------------------------------------------------------------- #
# 支付：状态机已上线（clerk/pay.py）；真实渠道等 G2，适配器一换即可
# --------------------------------------------------------------------------- #


@app.get("/api/pay/products")
def pay_products() -> dict:
    """定价档位（价格取值在 clerk/config.py，★作者文件★）。前端付费弹层的数据源。"""
    return {
        "tiers": [
            {
                "code": code,
                "name_zh": product["name_zh"],
                "name_en": product["name_en"],
                "price": str(product["price"]),
            }
            for code, product in pay.PRODUCTS.items()
        ],
        "free": {
            "daily_suggestions": config.FREE_DAILY_SUGGESTIONS,
            "max_items": config.FREE_MAX_ITEMS,
        },
    }


@app.post("/api/pay/order")
def pay_order(payload: PayOrderRequest, request: Request) -> dict:
    """创建订单。payment 字段是适配器的输出——现在是 FakeAdapter：
    联调环境给模拟入口，生产环境如实说"通道接入中"。**不假装能收款。**"""
    token = require_token(request)
    with get_conn() as conn:
        order = pay.create_order(conn, token, payload.product_code)
    return {"order": order, "payment": pay.get_adapter().create_payment(order)}


@app.post("/api/pay/notify-dev")
def pay_notify_dev(payload: PayNotifyRequest) -> Any:
    """联调回调：只在 CLERK_PAY_DEV=1 时工作。

    生产环境未签名回调一律 403——这条入口永远不能成为"白嫖权益"的后门。
    G2 之后真实异步通知走 VibePayAdapter.verify_notify（验签），状态机不变。
    """
    if not pay.dev_mode():
        return _error_response(
            403,
            "DEV_NOTIFY_DISABLED",
            "未签名回调入口在生产环境关闭；真实支付回调将在 G2 签约后以验签形式接入",
        )
    with get_conn() as conn:
        return pay.handle_paid_notification(
            conn,
            out_trade_no=payload.out_trade_no,
            amount=payload.amount,
            trade_no=payload.trade_no,
            raw={"via": "notify-dev"},
        )


@app.post("/api/pay/notify", response_class=PlainTextResponse)
async def pay_notify(request: Request) -> str:
    """支付宝异步通知（生产回调入口）。

    文档纪律逐条落地：
    - 验签失败/二次校验失败/处理异常 → "failure"（支付宝按 4m/10m/10m/1h/2h/6h/15h 重发）
    - 处理成功 → "success"（纯文本，停止重发）；重发安全由状态机幂等保证
    - 只有 TRADE_SUCCESS / TRADE_FINISHED 才推进 created→paid
    - TRADE_CLOSED 且带退款特征、且订单已 paid → 走退款状态机（权益降回免费）
    - 通道未配置时一律 "failure"：没签约却收到"支付宝通知"，那不是事故就是伪造
    """
    if not pay_vibe.is_configured():
        return "failure"
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    try:
        info = pay_vibe.verify_notify(params)
    except Exception as exc:  # noqa: BLE001 — 验签环节任何异常都按失败处理
        print(f"[pay] 异步通知验签失败：{exc}")
        return "failure"

    try:
        with get_conn() as conn:
            status = info["trade_status"]
            if status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
                pay.handle_paid_notification(
                    conn,
                    out_trade_no=info["out_trade_no"],
                    amount=info["amount"],
                    trade_no=info.get("trade_no"),
                    raw={"via": "async_notify", "notify_id": info.get("notify_id")},
                )
            elif status == "TRADE_CLOSED" and info.get("has_refund"):
                order = pay.get_order(conn, out_trade_no=info["out_trade_no"])
                if order is not None and order["status"] == "paid":
                    pay.handle_refund_notification(
                        conn, out_trade_no=info["out_trade_no"], raw={"via": "async_notify"}
                    )
            # WAIT_BUYER_PAY / 未付款超时关单：只路过，不改状态
    except Exception as exc:  # noqa: BLE001 — 处理异常返回 failure 让支付宝重试，绝不吞通知
        print(f"[pay] 异步通知处理异常：{exc}")
        return "failure"
    return "success"


@app.post("/api/pay/query")
def pay_query(payload: PayQueryRequest, request: Request) -> dict:
    """主动查询兜底：文档原文"商家也可以直接调用该查询接口，不需要依赖异步通知"。

    前端从收银台回跳后轮询这里；查询到 TRADE_SUCCESS 且本地还是 created，
    就以查询结果入账（与异步通知走同一个幂等状态机，两边先到都安全）。
    通道未配置时只返回本地状态（dev 联调用）。
    """
    token = require_token(request)
    with get_conn() as conn:
        order = pay.get_order(conn, out_trade_no=payload.out_trade_no)
        # 越权与不存在给同一个错——不泄露订单号是否存在
        if order is None or order["token"] != token:
            raise pay.PayError(f"订单不存在：{payload.out_trade_no}")
        trade_status = None
        if pay_vibe.is_configured() and order["status"] == "created":
            body = pay_vibe.query_trade(payload.out_trade_no)
            trade_status = body.get("trade_status")
            if body.get("code") == "10000" and trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
                pay.handle_paid_notification(
                    conn,
                    out_trade_no=payload.out_trade_no,
                    amount=body["total_amount"],
                    trade_no=body.get("trade_no"),
                    raw={"via": "trade_query"},
                )
        order = pay.get_order(conn, out_trade_no=payload.out_trade_no)
        return {
            "trade_status": trade_status,
            "order": order,
            "entitlement": pay.entitlement(conn, token),
        }


@app.get("/api/entitlements/me")
def entitlements(request: Request) -> dict:
    token = require_token(request)
    with get_conn() as conn:
        entitlement_data = pay.entitlement(conn, token)
        used = db.get_usage(conn, token, db.today_shanghai())
    return {
        **entitlement_data,
        "quota": {"used_today": used, "free_limit": config.FREE_DAILY_SUGGESTIONS},
    }


# --------------------------------------------------------------------------- #
# Machine Pay（A2A · 402 协议）：把「可信议价决策」卖给其他 Agent
# --------------------------------------------------------------------------- #


class AgentBargainRequest(BaseModel):
    asking_price: str
    buyer_offer: str
    floor_price: str | None = None  # 缺省 = default_floor_price（挂牌 × 85%）
    concessions_used: int = 0


@app.post("/api/agent/bargain")
def agent_bargain(payload: AgentBargainRequest, request: Request):
    """402 资源端点：无凭证 → 402+账单；带 Payment-Proof → 验凭证 → 交付决策 → 履约回执。

    交付顺序纪律：**先算资源（纯函数、不花钱），再占 trade_no、后交付**——
    入参非法时买家 Agent 的钱不能白花（测试盯着这个顺序）。
    """
    if not machine_pay.is_configured():
        return _error_response(
            501,
            "MACHINE_PAY_NOT_CONFIGURED",
            "A2A 按量付费通道未配置（缺 MACHINE_PAY_* 凭证）；人类通道（/api/inquiry）不受影响",
        )

    proof_header = request.headers.get("payment-proof")
    if not proof_header:
        # 第一步：签发账单，告诉对方"这个资源要先付钱"
        out_trade_no = machine_pay.new_out_trade_no()
        invoice = machine_pay.build_invoice(out_trade_no)
        return JSONResponse(
            status_code=402,
            content={
                "error": "Payment Needed",
                "message": f"请先支付 {invoice['protocol']['amount']} CNY 以访问议价决策资源",
                "resourceId": machine_pay.RESOURCE_ID,
            },
            headers={"Payment-Needed": machine_pay.encode_payment_needed(invoice)},
        )

    # 第二步：验凭证（签名真伪、active、金额、归属、资源防串）
    try:
        proof = machine_pay.parse_payment_proof(proof_header)
        verdict = machine_pay.verify_proof(proof)
        machine_pay.check_verification(
            verdict, expected_amount=config.MACHINE_PAY_PRICE
        )
    except Exception as exc:  # noqa: BLE001 — 任何验证失败都回到 402：重新支付
        return _error_response(402, "PROOF_INVALID", f"支付凭证无效或已过期：{exc}")

    # 第三步：先算资源（纯函数），坏入参在这一步就被挡下、不消耗凭证
    try:
        asking = to_money(payload.asking_price)
        floor = (
            to_money(payload.floor_price)
            if payload.floor_price
            else default_floor_price(asking)
        )
        facts = BargainFacts(
            asking_price=asking,
            buyer_offer=to_money(payload.buyer_offer),
            floor_price=floor,
            concessions_used=payload.concessions_used,
        )
        decision = decide_bargain(facts)
    except BargainError as exc:
        return _error_response(400, "BAD_FACTS", str(exc))

    # 第四步：占 trade_no（同一笔支付只能用一次）→ 交付 → 履约回执
    trade_no = str(verdict.get("trade_no") or proof["protocol"]["trade_no"])
    with get_conn() as conn:
        fresh = db.record_machine_fulfillment(
            conn,
            trade_no,
            str(verdict.get("out_trade_no") or ""),
            machine_pay.RESOURCE_ID,
            str(to_money(verdict.get("amount") or config.MACHINE_PAY_PRICE)),
        )
    if not fresh:
        return _error_response(402, "PROOF_REUSED", "该支付凭证已履约过——同一笔支付不能重复使用")

    machine_pay.confirm_fulfillment(trade_no)
    return {
        "resource": machine_pay.RESOURCE_ID,
        "trade_no": trade_no,
        "decision": decision.to_dict(),
    }


# --------------------------------------------------------------------------- #
# 前端静态托管（最后挂载：API 路由优先匹配）
# --------------------------------------------------------------------------- #

if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


def main() -> None:  # pragma: no cover — 手动启动用
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8100)


if __name__ == "__main__":  # pragma: no cover
    main()

#!/usr/bin/env python3
"""同花顺问财 ETF 选择器（按 hithink-etf-selector 规范）。"""

import json
import os
import secrets
import urllib.error
import urllib.request

SKILL_ID = "hithink-etf-selector"
SKILL_VERSION = "1.0.0"
DEFAULT_BASE_URL = "https://openapi.iwencai.com"
DEFAULT_API_PATH = "/v1/query2data"


class IwencaiETFError(RuntimeError):
    pass


def _trace_id():
    return secrets.token_hex(32)


def _api_key(explicit_key=None):
    key = explicit_key or os.environ.get("IWENCAI_API_KEY", "")
    if not key:
        raise IwencaiETFError("缺少 IWENCAI_API_KEY 环境变量")
    return key


def normalize_symbol(code):
    """510300.SH -> 510300; 159919.SZ -> 159919"""
    if not code:
        return ""
    s = str(code).strip().upper()
    if "." in s:
        s = s.split(".", 1)[0]
    return s


def _rewrite_query(user_query):
    q = (user_query or "").strip()
    if not q:
        return "ETF有哪些"
    if "ETF" not in q.upper():
        return f"{q} ETF"
    return q


def _relaxed_query(prev_query):
    q = prev_query.replace("且", " ").replace("并且", " ").replace("同时", " ")
    q = q.replace("大于", "").replace("小于", "")
    q = " ".join(p for p in q.split() if p)
    return q if q else "ETF有哪些"


def query_etf(query, page="1", limit="10", call_type="normal", timeout=30, api_key=None, base_url=None):
    key = _api_key(api_key)
    base = (base_url or os.environ.get("IWENCAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    url = f"{base}{DEFAULT_API_PATH}"
    trace_id = _trace_id()

    payload = {
        "query": query,
        "page": str(page),
        "limit": str(limit),
        "is_cache": "1",
        "expand_index": "true",
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": call_type,
        "X-Claw-Skill-Id": SKILL_ID,
        "X-Claw-Skill-Version": SKILL_VERSION,
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": trace_id,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise IwencaiETFError("问财返回格式异常")
            data["_trace_id"] = trace_id
            data["_used_query"] = query
            return data
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore") if e.fp else ""
        raise IwencaiETFError(f"问财接口HTTP错误 {e.code}: {detail[:300]}") from e
    except urllib.error.URLError as e:
        raise IwencaiETFError(f"问财接口网络错误: {e.reason}") from e


def _score_item(item):
    """粗略排序：优先成交额/成交量/基金规模。"""
    keys = ["成交额", "成交量", "基金规模", "最新规模(亿元)", "资产规模"]
    score = 0.0
    for k in keys:
        v = item.get(k)
        try:
            if isinstance(v, str):
                v = v.replace(",", "").replace("亿元", "").replace("万", "")
            score = max(score, float(v))
        except Exception:
            pass
    return score


def select_top_etf(user_query, limit="20", timeout=30, api_key=None, base_url=None):
    """按 skill 规则: 改写 query + 最多 2 次放宽重试，返回最优 ETF。"""
    q1 = _rewrite_query(user_query)
    attempts = [(q1, "normal"), (_relaxed_query(q1), "retry"), ("ETF有哪些", "retry")]

    last = None
    for q, call_type in attempts:
        result = query_etf(q, page="1", limit=str(limit), call_type=call_type,
                           timeout=timeout, api_key=api_key, base_url=base_url)
        datas = result.get("datas", []) if isinstance(result, dict) else []
        if datas:
            best = sorted(datas, key=_score_item, reverse=True)[0]
            code = best.get("ETF代码") or best.get("证券代码") or best.get("代码")
            name = best.get("ETF简称") or best.get("简称") or best.get("名称")
            symbol = normalize_symbol(code)
            if not symbol:
                raise IwencaiETFError(f"问财返回无可用 ETF 代码: {best}")
            return {
                "symbol": symbol,
                "code": code,
                "name": name or symbol,
                "used_query": result.get("_used_query", q),
                "code_count": int(result.get("code_count", len(datas) or 0)),
                "source": "同花顺问财",
                "trace_id": result.get("_trace_id", ""),
            }
        last = result

    raise IwencaiETFError(f"未查到符合条件的ETF，最后一次响应: {str(last)[:300]}")

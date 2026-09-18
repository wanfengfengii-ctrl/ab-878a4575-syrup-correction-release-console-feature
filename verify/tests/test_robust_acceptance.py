"""稳健刻度方案 API 网络验收：通过真实 HTTP 打到运行中的判定服务。

覆盖：稳健主线与两端点终态、无稳健刻度容差缺口、容量放不下一个刻度、
非法 Q/U/E 按顺序定位，以及原判定 / 腾容契约不变。
算法正确性的穷举对拍由 api 单测覆盖，本文件聚焦真实网络契约。
"""

from decimal import Decimal, localcontext

import httpx

ALLOWED_PAYLOAD = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}


def post(api_base_url: str, payload: dict):
    return httpx.post(f"{api_base_url}/api/robust-plan", json=payload, timeout=10)


def test_robust_mainline_shows_dose_range_and_worst_deviation(api_base_url: str):
    """稳健：剂量 nQ、两端点终态糖度区间、最坏偏差齐全。"""
    resp = post(api_base_url, {**ALLOWED_PAYLOAD, "Q": "10", "U": "1", "E": "0.5"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    assert body["message"] == "稳健刻度"
    assert body["n"] == 7
    assert Decimal(body["dose"]) == Decimal(70)
    # F_- = (2500 + 70×29)/570，F_+ = (2500 + 70×31)/570（与服务同精度 50 位复算）
    with localcontext() as ctx:
        ctx.prec = 50
        e_low = (Decimal(2500) + Decimal(70) * 29) / Decimal(570)
        e_high = (Decimal(2500) + Decimal(70) * 31) / Decimal(570)
        worst = max(Decimal(8) - e_low, e_high - Decimal(8))
    assert Decimal(body["finalConcentrationLow"]) == e_low
    assert Decimal(body["finalConcentrationHigh"]) == e_high
    assert Decimal(body["worstDeviation"]) == worst
    assert worst <= Decimal("0.5")
    assert body["toleranceGap"] is None
    assert set(body["inputs"]) == {"V", "C", "T", "S", "K", "Q", "U", "E"}


def test_no_robust_mark_shows_tolerance_gap(api_base_url: str):
    """最优偏差超过 E：无稳健刻度，给出最小容差缺口且不给剂量。"""
    resp = post(api_base_url, {**ALLOWED_PAYLOAD, "Q": "10", "U": "2", "E": "0.01"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_ROBUST_MARK"
    assert body["message"] == "无稳健刻度"
    assert Decimal(body["toleranceGap"]) > 0
    assert body["dose"] is None
    assert body["n"] is None
    assert body["finalConcentrationLow"] is None
    assert body["finalConcentrationHigh"] is None
    assert body["worstDeviation"] is None


def test_capacity_cannot_fit_one_mark_is_business_result(api_base_url: str):
    """V+Q>K（判定仍允许：568.18<600，但 Q=101 使 500+101>600）：业务结果，不报字段错误。"""
    resp = post(
        api_base_url, {**ALLOWED_PAYLOAD, "Q": "101", "U": "1", "E": "0.5"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_ROBUST_MARK"
    assert body["toleranceGap"] is None
    assert body["dose"] is None


def test_invalid_params_located_in_q_u_e_order(api_base_url: str):
    """Q<=0、U<0、E<0：422 一次性返回 Q、U、E 三字段错误。"""
    resp = post(api_base_url, {**ALLOWED_PAYLOAD, "Q": "0", "U": "-1", "E": "-0.1"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "输入校验失败，已整单拒绝"
    assert [e["field"] for e in body["errors"]] == ["Q", "U", "E"]
    assert "dose" not in body and "n" not in body


def test_syrup_endpoint_relation_errors_located_at_u(api_base_url: str):
    """S-U<=T 与 S+U>100：均定位 U 字段。"""
    resp = post(
        api_base_url,
        {"V": "500", "C": "5", "T": "8", "S": "60", "K": "600", "Q": "10", "U": "55", "E": "0.5"},
    )
    assert resp.status_code == 422
    u_msgs = [e["message"] for e in resp.json()["errors"] if e["field"] == "U"]
    assert any("S-U" in m for m in u_msgs)
    assert any("S+U" in m for m in u_msgs)


def test_zero_fluctuation_accepted(api_base_url: str):
    """U=0：区间退化为单点，受理且两端点终态相同。"""
    resp = post(api_base_url, {**ALLOWED_PAYLOAD, "Q": "10", "U": "0", "E": "1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    assert Decimal(body["finalConcentrationLow"]) == Decimal(body["finalConcentrationHigh"])


def test_huge_mark_range_resolved_without_scanning(api_base_url: str):
    """可行刻度数约 1e16：服务必须常数级返回，不得逐刻度扫描。"""
    payload = {
        "V": "1", "C": "5", "T": "8", "S": "30", "K": "1000000000000",
        "Q": "0.0001", "U": "1", "E": "0.0001",
    }
    resp = post(api_base_url, payload)
    assert resp.status_code == 200
    n_max = int((Decimal(payload["K"]) - Decimal(payload["V"])) // Decimal(payload["Q"]))
    assert n_max > 10**15
    if resp.json()["n"] is not None:
        assert 1 <= resp.json()["n"] <= n_max


def test_judge_and_drain_contracts_unchanged_by_robust_feature(api_base_url: str):
    """原 /api/judge 与 /api/drain-plan 请求与响应契约不变。"""
    judge = httpx.post(f"{api_base_url}/api/judge", json=ALLOWED_PAYLOAD, timeout=10)
    assert judge.status_code == 200
    assert set(judge.json()) == {
        "verdict", "message", "dose", "finalVolume",
        "remainingCapacity", "excess", "inputs",
    }
    drain = httpx.post(
        f"{api_base_url}/api/drain-plan",
        json={**ALLOWED_PAYLOAD, "K": "550", "D": "20"},
        timeout=10,
    )
    assert drain.status_code == 200
    assert drain.json()["status"] == "EXECUTABLE"
    assert set(drain.json()["inputs"]) == {"V", "C", "T", "S", "K", "D"}

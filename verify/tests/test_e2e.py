"""端到端验收：Playwright 驱动真实浏览器，经 nginx 访问真实前端 + 真实 API。

覆盖三条主线：放行、溢罐、非法输入（含整单拒绝与旧结论清除）。
"""

import re

from playwright.sync_api import Page, expect

ALLOW_VALUES = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}


def fill_form(page: Page, values: dict[str, str]) -> None:
    for key, value in values.items():
        page.locator(f"#field-{key}").fill(value)


def submit(page: Page) -> None:
    page.get_by_role("button", name="判定补加").click()


def test_allow_mainline(page: Page, base_url: str):
    page.goto(base_url)
    fill_form(page, ALLOW_VALUES)
    submit(page)

    expect(page.get_by_test_id("verdict")).to_have_text("允许补加")
    expect(page.get_by_test_id("formula")).to_have_text(
        "x = V×(T-C)/(S-T) = 500×(8-5)/(30-8) = 68.1818"
    )
    expect(page.get_by_test_id("dose")).to_have_text("68.1818")
    expect(page.get_by_test_id("final-volume")).to_have_text("568.1818")
    expect(page.get_by_test_id("remaining")).to_have_text("31.8182")
    expect(page.get_by_test_id("excess")).to_have_count(0)


def test_overflow_mainline(page: Page, base_url: str):
    page.goto(base_url)
    fill_form(page, {**ALLOW_VALUES, "K": "550"})
    submit(page)

    expect(page.get_by_test_id("verdict")).to_have_text("禁止补加")
    expect(page.get_by_test_id("dose")).to_have_text("68.1818")
    expect(page.get_by_test_id("final-volume")).to_have_text("568.1818")
    expect(page.get_by_test_id("excess")).to_have_text("18.1818")
    expect(page.get_by_test_id("remaining")).to_have_count(0)


def test_micro_overflow_shows_trace_not_zero(page: Page, base_url: str):
    # 实际超出 0.00000400008... mL（< 0.00005）：禁止补加，
    # 超出量四位小数舍入为零，必须明确指示微量而非显示 0
    page.goto(base_url)
    fill_form(page, {"V": "10000", "C": "5", "T": "5.0001", "S": "10", "K": "10000.2"})
    submit(page)

    expect(page.get_by_test_id("verdict")).to_have_text("禁止补加")
    expect(page.get_by_test_id("excess")).to_have_text("<0.0001")
    expect(page.get_by_test_id("dose")).to_have_text("0.2")
    expect(page.get_by_test_id("final-volume")).to_have_text("10000.2")


def test_invalid_input_rejects_and_clears_previous_result(page: Page, base_url: str):
    page.goto(base_url)
    # 先得到一次有效结论
    fill_form(page, ALLOW_VALUES)
    submit(page)
    expect(page.get_by_test_id("verdict")).to_have_text("允许补加")

    # 再把目标糖度改成不大于当前糖度：整单拒绝并清除旧结论
    page.locator("#field-T").fill("3")
    submit(page)

    expect(page.get_by_test_id("error-T")).to_have_text("目标糖度 T 必须大于当前糖度 C")
    expect(page.get_by_test_id("global-error")).to_contain_text("整单拒绝")
    expect(page.get_by_test_id("result")).to_have_count(0)


def test_empty_submit_locates_all_fields(page: Page, base_url: str):
    page.goto(base_url)
    submit(page)

    for key in ("V", "C", "T", "S", "K"):
        expect(page.get_by_test_id(f"error-{key}")).to_have_text("必填项缺失")
    expect(page.get_by_test_id("result")).to_have_count(0)


def test_precision_overflow_located(page: Page, base_url: str):
    page.goto(base_url)
    fill_form(page, {**ALLOW_VALUES, "C": "1.23456"})
    submit(page)

    expect(page.get_by_test_id("error-C")).to_have_text(re.compile("四位小数"))
    expect(page.get_by_test_id("result")).to_have_count(0)


# ---------- 腾容方案主线 ----------

FORBIDDEN_VALUES = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "550"}


def submit_drain(page: Page) -> None:
    page.get_by_test_id("drain-entry").click()


def test_drain_executable_plan_at_capacity_boundary(page: Page, base_url: str):
    # d = 500-550×22/25 = 16，排出后 484，补加 66，终态恰好顶到容量 550
    page.goto(base_url)
    fill_form(page, FORBIDDEN_VALUES)
    submit(page)
    expect(page.get_by_test_id("verdict")).to_have_text("禁止补加")

    page.locator("#field-D").fill("20")
    submit_drain(page)

    expect(page.get_by_test_id("drain-status")).to_have_text("可执行")
    expect(page.get_by_test_id("drain-min")).to_have_text("16")
    expect(page.get_by_test_id("drain-volume-after")).to_have_text("484")
    expect(page.get_by_test_id("drain-dose")).to_have_text("66")
    expect(page.get_by_test_id("drain-final-volume")).to_have_text("550")
    expect(page.get_by_test_id("drain-shortfall")).to_have_count(0)
    # 方案挂在结论之下，原禁止判定保持不变
    expect(page.get_by_test_id("verdict")).to_have_text("禁止补加")


def test_drain_exceeds_limit_shows_shortfall_only(page: Page, base_url: str):
    page.goto(base_url)
    fill_form(page, FORBIDDEN_VALUES)
    submit(page)
    expect(page.get_by_test_id("verdict")).to_have_text("禁止补加")

    page.locator("#field-D").fill("10")
    submit_drain(page)

    expect(page.get_by_test_id("drain-status")).to_have_text("超出排出上限")
    expect(page.get_by_test_id("drain-shortfall")).to_have_text("6")
    # 不呈现可执行剂量
    expect(page.get_by_test_id("drain-dose")).to_have_count(0)
    expect(page.get_by_test_id("drain-min")).to_have_count(0)


def test_invalid_d_clears_old_plan_but_keeps_forbidden_verdict(page: Page, base_url: str):
    page.goto(base_url)
    fill_form(page, FORBIDDEN_VALUES)
    submit(page)
    expect(page.get_by_test_id("verdict")).to_have_text("禁止补加")

    # 先生成一个合法方案
    page.locator("#field-D").fill("20")
    submit_drain(page)
    expect(page.get_by_test_id("drain-status")).to_have_text("可执行")

    # 再填非法 D：定位字段、清除旧方案，但保留原禁止结论
    page.locator("#field-D").fill("-1")
    submit_drain(page)

    expect(page.get_by_test_id("error-D")).to_have_text("排出上限 D 不能为负数")
    expect(page.get_by_test_id("drain-result")).to_have_count(0)
    expect(page.get_by_test_id("verdict")).to_have_text("禁止补加")


def test_allowed_verdict_has_no_drain_entry(page: Page, base_url: str):
    page.goto(base_url)
    fill_form(page, ALLOW_VALUES)
    submit(page)

    expect(page.get_by_test_id("verdict")).to_have_text("允许补加")
    expect(page.get_by_test_id("drain-entry")).to_have_count(0)
    expect(page.get_by_test_id("drain-panel")).to_have_count(0)


# ---------- 稳健刻度方案主线 ----------


def submit_robust(page: Page) -> None:
    page.get_by_test_id("robust-entry").click()


def fill_robust(page: Page, q: str, u: str, e: str) -> None:
    page.locator("#field-Q").fill(q)
    page.locator("#field-U").fill(u)
    page.locator("#field-E").fill(e)


def test_forbidden_verdict_has_no_robust_entry(page: Page, base_url: str):
    page.goto(base_url)
    fill_form(page, FORBIDDEN_VALUES)
    submit(page)

    expect(page.get_by_test_id("verdict")).to_have_text("禁止补加")
    expect(page.get_by_test_id("robust-entry")).to_have_count(0)
    expect(page.get_by_test_id("robust-panel")).to_have_count(0)


def test_robust_plan_mainline_under_allowed_verdict(page: Page, base_url: str):
    # V=500,C=5,T=8,S=30,K=600,Q=10,U=0：n=7，剂量 70，终态 570，糖度单点 8.0702
    page.goto(base_url)
    fill_form(page, ALLOW_VALUES)
    submit(page)
    expect(page.get_by_test_id("verdict")).to_have_text("允许补加")

    fill_robust(page, "10", "0", "0.5")
    submit_robust(page)

    expect(page.get_by_test_id("robust-status")).to_have_text("稳健刻度")
    expect(page.get_by_test_id("robust-dose")).to_have_text("70")
    expect(page.get_by_test_id("robust-final-volume")).to_have_text("570")
    expect(page.get_by_test_id("robust-sugar-range")).to_have_text("8.0702 ~ 8.0702")
    expect(page.get_by_test_id("robust-worst")).to_have_text("0.0702")
    expect(page.get_by_test_id("robust-gap")).to_have_count(0)
    # 方案挂在允许结论之下，原判定保持不变
    expect(page.get_by_test_id("verdict")).to_have_text("允许补加")
    # 允许结论下不出现腾容入口
    expect(page.get_by_test_id("drain-panel")).to_have_count(0)


def test_robust_sugar_interval_with_uncertainty(page: Page, base_url: str):
    # U=2：终态糖度为真实区间，两端点不再相同
    page.goto(base_url)
    fill_form(page, ALLOW_VALUES)
    submit(page)

    fill_robust(page, "10", "2", "5")
    submit_robust(page)

    expect(page.get_by_test_id("robust-status")).to_have_text("稳健刻度")
    range_text = page.get_by_test_id("robust-sugar-range").inner_text()
    low, high = [part.strip() for part in range_text.split("~")]
    assert low != high
    expect(page.get_by_test_id("robust-worst")).not_to_have_text("")


def test_no_robust_shows_tolerance_gap(page: Page, base_url: str):
    # K=569 时判定仍为允许补加（终态 568.18≤569）；Q=10,U=2,E=0 时
    # n_max=6，最优 n=6 最坏偏差 0.5357…>0，无稳健刻度，缺口 0.5357
    page.goto(base_url)
    fill_form(page, {**ALLOW_VALUES, "K": "569"})
    submit(page)
    expect(page.get_by_test_id("verdict")).to_have_text("允许补加")

    fill_robust(page, "10", "2", "0")
    submit_robust(page)

    expect(page.get_by_test_id("robust-status")).to_have_text("无稳健刻度")
    expect(page.get_by_test_id("robust-gap")).to_have_text("0.5357")
    # 仍给出最优刻度剂量与最坏偏差
    expect(page.get_by_test_id("robust-dose")).to_have_text("60")
    expect(page.get_by_test_id("robust-worst")).to_have_text("0.5357")


def test_no_capacity_shows_business_message(page: Page, base_url: str):
    # K=569 时判定仍为允许补加（终态 568.18≤569），但剩余 69 mL 放不下 Q=70 一个刻度
    page.goto(base_url)
    fill_form(page, {**ALLOW_VALUES, "K": "569"})
    submit(page)
    expect(page.get_by_test_id("verdict")).to_have_text("允许补加")

    fill_robust(page, "70", "1", "0.1")
    submit_robust(page)

    expect(page.get_by_test_id("robust-status")).to_have_text("容量放不下一个刻度")
    expect(page.get_by_test_id("robust-dose")).to_have_count(0)


def test_invalid_q_clears_old_plan_but_keeps_allowed_verdict(page: Page, base_url: str):
    page.goto(base_url)
    fill_form(page, ALLOW_VALUES)
    submit(page)
    expect(page.get_by_test_id("verdict")).to_have_text("允许补加")

    fill_robust(page, "10", "0", "0.5")
    submit_robust(page)
    expect(page.get_by_test_id("robust-status")).to_have_text("稳健刻度")

    # 再填非法 Q：定位字段、清除旧方案，但保留原允许结论
    page.locator("#field-Q").fill("0")
    submit_robust(page)

    expect(page.get_by_test_id("error-Q")).to_have_text("单刻度量 Q 必须大于 0")
    expect(page.get_by_test_id("robust-result")).to_have_count(0)
    expect(page.get_by_test_id("verdict")).to_have_text("允许补加")


def test_rejudge_clears_robust_plan(page: Page, base_url: str):
    page.goto(base_url)
    fill_form(page, ALLOW_VALUES)
    submit(page)
    fill_robust(page, "10", "0", "0.5")
    submit_robust(page)
    expect(page.get_by_test_id("robust-status")).to_have_text("稳健刻度")

    # 重新判定为禁止补加：稳健刻度方案与其入口一并消失，腾容入口出现
    page.locator("#field-K").fill("550")
    submit(page)

    expect(page.get_by_test_id("verdict")).to_have_text("禁止补加")
    expect(page.get_by_test_id("robust-panel")).to_have_count(0)
    expect(page.get_by_test_id("drain-panel")).to_have_count(1)


def test_invalid_rejudge_clears_robust_plan(page: Page, base_url: str):
    page.goto(base_url)
    fill_form(page, ALLOW_VALUES)
    submit(page)
    fill_robust(page, "10", "0", "0.5")
    submit_robust(page)
    expect(page.get_by_test_id("robust-status")).to_have_text("稳健刻度")

    # 非法输入重新判定：整单拒绝并清除结论与方案
    page.locator("#field-T").fill("3")
    submit(page)

    expect(page.get_by_test_id("result")).to_have_count(0)
    expect(page.get_by_test_id("robust-panel")).to_have_count(0)
    expect(page.get_by_test_id("error-T")).to_have_text("目标糖度 T 必须大于当前糖度 C")

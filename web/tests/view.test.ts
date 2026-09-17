import { describe, expect, it } from 'vitest';
import type { DrainPlanResponse, JudgeResponse } from '../src/lib/api';
import { buildDrainPlanView, buildResultView, mapFieldErrors, splitDrainErrors } from '../src/lib/view';

// 以下响应取自真实 API 计算结果（decimal，50 位有效数字）
const allowedResponse: JudgeResponse = {
  verdict: 'ALLOWED',
  message: '允许补加',
  dose: '68.181818181818181818181818181818181818181818181818',
  finalVolume: '568.18181818181818181818181818181818181818181818182',
  remainingCapacity: '31.81818181818181818181818181818181818181818181818',
  excess: null,
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '600' },
};

const forbiddenResponse: JudgeResponse = {
  verdict: 'FORBIDDEN',
  message: '禁止补加',
  dose: '68.181818181818181818181818181818181818181818181818',
  finalVolume: '568.18181818181818181818181818181818181818181818182',
  remainingCapacity: null,
  excess: '18.18181818181818181818181818181818181818181818182',
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '550' },
};

// 真实 API 计算值：仅超出 0.00000400008... mL，四位小数舍入为零
const microOverflowResponse: JudgeResponse = {
  verdict: 'FORBIDDEN',
  message: '禁止补加',
  dose: '0.20000400008000160003200064001280025600512010240205',
  finalVolume: '10000.200004000080001600032000640012800256005120102',
  remainingCapacity: null,
  excess: '0.000004000080001600032000640012800256005120102',
  inputs: { V: '10000', C: '5', T: '5.0001', S: '10', K: '10000.2' },
};

describe('buildResultView 放行主线', () => {
  it('展示公式代入、唯一补加量、终态体积、剩余容量与允许补加', () => {
    const view = buildResultView(allowedResponse);
    expect(view.verdict).toBe('ALLOWED');
    expect(view.verdictText).toBe('允许补加');
    expect(view.formula).toBe('x = V×(T-C)/(S-T) = 500×(8-5)/(30-8) = 68.1818');
    const rows = Object.fromEntries(view.rows.map((r) => [r.testId, r.value]));
    expect(rows['dose']).toBe('68.1818');
    expect(rows['final-volume']).toBe('568.1818');
    expect(rows['remaining']).toBe('31.8182');
    expect(rows['excess']).toBeUndefined();
  });
});

describe('buildResultView 溢罐主线', () => {
  it('展示超出量与禁止补加，不展示剩余容量', () => {
    const view = buildResultView(forbiddenResponse);
    expect(view.verdict).toBe('FORBIDDEN');
    expect(view.verdictText).toBe('禁止补加');
    const rows = Object.fromEntries(view.rows.map((r) => [r.testId, r.value]));
    expect(rows['dose']).toBe('68.1818');
    expect(rows['excess']).toBe('18.1818');
    expect(rows['remaining']).toBeUndefined();
  });

  it('微量溢出舍入为零时明确显示仍有溢出（<0.0001）', () => {
    const view = buildResultView(microOverflowResponse);
    expect(view.verdict).toBe('FORBIDDEN');
    const rows = Object.fromEntries(view.rows.map((r) => [r.testId, r.value]));
    expect(rows['excess']).toBe('<0.0001');
    expect(rows['dose']).toBe('0.2');
    expect(rows['final-volume']).toBe('10000.2');
  });
});

describe('mapFieldErrors 非法输入主线', () => {
  it('字段错误定位到字段，全局错误单独收集', () => {
    const { fieldErrors, globalMessages } = mapFieldErrors([
      { field: 'T', message: '目标糖度 T 必须大于当前糖度 C' },
      { field: 'C', message: '最多允许四位小数' },
      { field: null, message: '请求体不是有效的 JSON' },
    ]);
    expect(fieldErrors.T).toBe('目标糖度 T 必须大于当前糖度 C');
    expect(fieldErrors.C).toBe('最多允许四位小数');
    expect(fieldErrors.V).toBeUndefined();
    expect(globalMessages).toEqual(['请求体不是有效的 JSON']);
  });
});

// 以下响应取自真实 API 计算结果（decimal，50 位有效数字）：
// V=500 C=5 T=8 S=30 K=550 时 d = 500-550×22/25 = 16，排出后 484，补加 66，终态恰为 550
const executablePlan: DrainPlanResponse = {
  status: 'EXECUTABLE',
  message: '可执行',
  minDrain: '16',
  volumeAfterDrain: '484',
  dose: '66',
  finalVolume: '550',
  shortfall: null,
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '550', D: '20' },
};

const exceedsLimitPlan: DrainPlanResponse = {
  status: 'EXCEEDS_LIMIT',
  message: '超出排出上限',
  minDrain: '16',
  volumeAfterDrain: null,
  dose: null,
  finalVolume: null,
  shortfall: '6',
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '550', D: '10' },
};

describe('buildDrainPlanView 腾容方案', () => {
  it('可执行：展示最小排出量、排出后体积、补加量与终态', () => {
    const view = buildDrainPlanView(executablePlan);
    expect(view.status).toBe('EXECUTABLE');
    expect(view.statusText).toBe('可执行');
    const rows = Object.fromEntries(view.rows.map((r) => [r.testId, r.value]));
    expect(rows['drain-min']).toBe('16');
    expect(rows['drain-volume-after']).toBe('484');
    expect(rows['drain-dose']).toBe('66');
    expect(rows['drain-final-volume']).toBe('550');
    expect(rows['drain-shortfall']).toBeUndefined();
  });

  it('超出排出上限：只展示仍缺少的排出量，不呈现可执行剂量', () => {
    const view = buildDrainPlanView(exceedsLimitPlan);
    expect(view.status).toBe('EXCEEDS_LIMIT');
    expect(view.statusText).toBe('超出排出上限');
    const rows = Object.fromEntries(view.rows.map((r) => [r.testId, r.value]));
    expect(rows['drain-shortfall']).toBe('6');
    expect(rows['drain-dose']).toBeUndefined();
    expect(rows['drain-min']).toBeUndefined();
    expect(rows['drain-final-volume']).toBeUndefined();
  });
});

describe('splitDrainErrors 腾容非法输入', () => {
  it('D 定位到排出上限字段，五项回到主表单，其余进全局消息', () => {
    const { fieldErrors, drainFieldError, globalMessages } = splitDrainErrors([
      { field: 'D', message: '排出上限 D 不能为负数' },
      { field: 'T', message: '目标糖度 T 必须大于当前糖度 C' },
      { field: null, message: '请求体不是有效的 JSON' },
    ]);
    expect(drainFieldError).toBe('排出上限 D 不能为负数');
    expect(fieldErrors.T).toBe('目标糖度 T 必须大于当前糖度 C');
    expect(globalMessages).toEqual(['请求体不是有效的 JSON']);
  });

  it('无 D 错误时 drainFieldError 为空', () => {
    const { drainFieldError } = splitDrainErrors([
      { field: 'V', message: '当前体积 V 必须大于 0' },
    ]);
    expect(drainFieldError).toBeNull();
  });
});

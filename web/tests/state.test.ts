import { describe, expect, it } from 'vitest';
import type { DrainPlanResponse, JudgeResponse } from '../src/lib/api';
import { consoleReducer, initialState } from '../src/lib/state';

const result: JudgeResponse = {
  verdict: 'ALLOWED',
  message: '允许补加',
  dose: '100',
  finalVolume: '500',
  remainingCapacity: '0',
  excess: null,
  inputs: { V: '400', C: '5', T: '9', S: '25', K: '500' },
};

const forbiddenResult: JudgeResponse = {
  ...result,
  verdict: 'FORBIDDEN',
  message: '禁止补加',
  remainingCapacity: null,
  excess: '18.18181818181818181818181818181818181818181818182',
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '550' },
};

const drainPlan: DrainPlanResponse = {
  status: 'EXECUTABLE',
  message: '可执行',
  minDrain: '16',
  volumeAfterDrain: '484',
  dose: '66',
  finalVolume: '550',
  shortfall: null,
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '550', D: '20' },
};

describe('consoleReducer 状态机', () => {
  it('提交成功：写入结论并清空错误', () => {
    const dirty = {
      ...initialState,
      fieldErrors: { T: '目标糖度 T 必须大于当前糖度 C' },
      globalError: '输入校验失败，已整单拒绝',
    };
    const next = consoleReducer(dirty, { type: 'submit/success', result });
    expect(next.result).toBe(result);
    expect(next.fieldErrors).toEqual({});
    expect(next.globalError).toBeNull();
    expect(next.submitting).toBe(false);
  });

  it('整单拒绝：定位字段并清除旧结论', () => {
    const withResult = { ...initialState, result };
    const next = consoleReducer(withResult, {
      type: 'submit/rejected',
      fieldErrors: { C: '当前糖度 C 必须大于 0' },
      message: '输入校验失败，已整单拒绝',
    });
    expect(next.result).toBeNull();
    expect(next.fieldErrors.C).toBe('当前糖度 C 必须大于 0');
    expect(next.globalError).toBe('输入校验失败，已整单拒绝');
  });

  it('请求失败：清除旧结论并提示', () => {
    const withResult = { ...initialState, result };
    const next = consoleReducer(withResult, {
      type: 'submit/failed',
      message: '无法连接判定服务，请稍后重试',
    });
    expect(next.result).toBeNull();
    expect(next.globalError).toBe('无法连接判定服务，请稍后重试');
  });

  it('开始提交：进入提交中并清除全局错误', () => {
    const withError = { ...initialState, globalError: '旧错误' };
    const next = consoleReducer(withError, { type: 'submit/start' });
    expect(next.submitting).toBe(true);
    expect(next.globalError).toBeNull();
  });
});

describe('consoleReducer 腾容方案', () => {
  const withForbidden = { ...initialState, result: forbiddenResult };

  it('生成成功：写入方案且不动原判定结论', () => {
    const next = consoleReducer(withForbidden, { type: 'drain/success', plan: drainPlan });
    expect(next.drainPlan).toBe(drainPlan);
    expect(next.result).toBe(forbiddenResult);
    expect(next.drainFieldError).toBeNull();
    expect(next.drainGlobalError).toBeNull();
    expect(next.drainSubmitting).toBe(false);
  });

  it('非法 D：定位 D 字段、清除旧方案、保留原禁止结论', () => {
    const withPlan = { ...withForbidden, drainPlan };
    const next = consoleReducer(withPlan, {
      type: 'drain/rejected',
      fieldErrors: {},
      drainFieldError: '排出上限 D 不能为负数',
      message: '输入校验失败，已整单拒绝',
    });
    expect(next.drainPlan).toBeNull();
    expect(next.drainFieldError).toBe('排出上限 D 不能为负数');
    expect(next.result).toBe(forbiddenResult);
  });

  it('腾容请求失败：清除旧方案、保留原判定，失败信息不进入判定结论', () => {
    const withPlan = { ...withForbidden, drainPlan };
    const next = consoleReducer(withPlan, {
      type: 'drain/failed',
      message: '无法连接判定服务，请稍后重试',
    });
    expect(next.drainPlan).toBeNull();
    expect(next.drainGlobalError).toBe('无法连接判定服务，请稍后重试');
    expect(next.result).toBe(forbiddenResult);
    expect(next.globalError).toBeNull();
  });

  it('主判定重新得出结论时旧腾容方案作废', () => {
    const withPlan = { ...withForbidden, drainPlan, drainFieldError: '旧错误' };
    const next = consoleReducer(withPlan, { type: 'submit/success', result });
    expect(next.drainPlan).toBeNull();
    expect(next.drainFieldError).toBeNull();
    expect(next.drainGlobalError).toBeNull();
  });

  it('主判定被拒绝或失败时旧腾容方案一并清除', () => {
    const withPlan = { ...withForbidden, drainPlan };
    const rejected = consoleReducer(withPlan, {
      type: 'submit/rejected',
      fieldErrors: {},
      message: '输入校验失败，已整单拒绝',
    });
    expect(rejected.drainPlan).toBeNull();
    const failed = consoleReducer(withPlan, { type: 'submit/failed', message: '网络异常' });
    expect(failed.drainPlan).toBeNull();
  });
});

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RobustPlanPanel } from '../src/components/RobustPlanPanel';
import type { RobustPlanResponse } from '../src/lib/api';

// 响应取自真实 API 计算结果：V=500 C=5 T=8 S=30 K=600，Q=10 U=1，最优 n=7（剂量 70）
const robustPlan: RobustPlanResponse = {
  status: 'ROBUST',
  message: '稳健刻度',
  n: 7,
  dose: '70',
  finalConcentrationLow: '7.9473684210526315789473684210526315789473684210526',
  finalConcentrationHigh: '8.1929824561403508771929824561403508771929824561404',
  worstDeviation: '0.1929824561403508771929824561403508771929824561404',
  toleranceGap: null,
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '600', Q: '10', U: '1', E: '0.5' },
};

const noRobustPlan: RobustPlanResponse = {
  status: 'NO_ROBUST_MARK',
  message: '无稳健刻度',
  n: null,
  dose: null,
  finalConcentrationLow: null,
  finalConcentrationHigh: null,
  worstDeviation: null,
  toleranceGap: '0.3057894736842105263157894736842105263157894736842',
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '600', Q: '10', U: '2', E: '0.01' },
};

function empty() {
  return { Q: '', U: '', E: '' };
}

function renderPanel(overrides: Partial<Parameters<typeof RobustPlanPanel>[0]> = {}) {
  const props = {
    plan: null,
    values: empty(),
    onValueChange: vi.fn(),
    fieldErrors: {},
    globalError: null,
    submitting: false,
    onSubmit: vi.fn(),
    ...overrides,
  };
  render(<RobustPlanPanel {...props} />);
  return props;
}

describe('RobustPlanPanel 入口与提交', () => {
  it('渲染 Q/U/E 输入与生成入口', () => {
    renderPanel();
    expect(screen.getByTestId('robust-entry')).toHaveTextContent('生成稳健刻度方案');
    expect(screen.getByLabelText('单刻度量 Q（mL）')).toBeInTheDocument();
    expect(screen.getByLabelText('糖度波动 U（%）')).toBeInTheDocument();
    expect(screen.getByLabelText('终态容差 E（%）')).toBeInTheDocument();
    expect(screen.queryByTestId('robust-result')).toBeNull();
  });

  it('提交表单触发生成回调', () => {
    const props = renderPanel({ values: { Q: '10', U: '1', E: '0.5' } });
    fireEvent.click(screen.getByTestId('robust-entry'));
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it('输入变更按字段回调', () => {
    const props = renderPanel();
    fireEvent.change(screen.getByLabelText('单刻度量 Q（mL）'), { target: { value: '10' } });
    expect(props.onValueChange).toHaveBeenCalledWith('Q', '10');
  });

  it('Q/U/E 的字段错误分别定位到输入框', () => {
    renderPanel({ fieldErrors: { Q: '单刻度量 Q 必须大于 0', E: '终态容差 E 不能为负数' } });
    expect(screen.getByTestId('error-Q')).toHaveTextContent('单刻度量 Q 必须大于 0');
    expect(screen.getByTestId('error-E')).toHaveTextContent('终态容差 E 不能为负数');
    expect(screen.getByLabelText('单刻度量 Q（mL）')).toHaveAttribute('aria-invalid', 'true');
  });
});

describe('RobustPlanPanel 方案展示', () => {
  it('稳健：展示剂量、终态糖度区间与最坏偏差', () => {
    renderPanel({ plan: robustPlan });
    expect(screen.getByTestId('robust-status')).toHaveTextContent('稳健刻度');
    expect(screen.getByTestId('robust-dose')).toHaveTextContent('70');
    expect(screen.getByTestId('robust-range')).toHaveTextContent('7.9474 ~ 8.193');
    expect(screen.getByTestId('robust-worst')).toHaveTextContent('0.193');
    expect(screen.queryByTestId('robust-gap')).toBeNull();
  });

  it('无稳健刻度：只展示最小容差缺口，不呈现剂量与区间', () => {
    renderPanel({ plan: noRobustPlan });
    expect(screen.getByTestId('robust-status')).toHaveTextContent('无稳健刻度');
    expect(screen.getByTestId('robust-gap')).toHaveTextContent('0.3058');
    expect(screen.queryByTestId('robust-dose')).toBeNull();
    expect(screen.queryByTestId('robust-range')).toBeNull();
    expect(screen.queryByTestId('robust-worst')).toBeNull();
  });

  it('请求级错误展示为全局错误而非方案', () => {
    renderPanel({ globalError: '无法连接判定服务，请稍后重试' });
    expect(screen.getByTestId('robust-error')).toHaveTextContent('无法连接判定服务');
    expect(screen.queryByTestId('robust-result')).toBeNull();
  });
});

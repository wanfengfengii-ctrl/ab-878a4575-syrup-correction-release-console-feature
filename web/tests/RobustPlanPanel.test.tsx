import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RobustPlanPanel } from '../src/components/RobustPlanPanel';
import type { RobustPlanResponse } from '../src/lib/api';

// 响应取自真实 API 计算结果：V=500 C=5 T=8 S=30 K=600 Q=10 U=0 E=0.5，n=7
const robustPlan: RobustPlanResponse = {
  feasible: true,
  status: 'ROBUST',
  message: '稳健刻度',
  n: 7,
  dose: '70',
  finalVolume: '570',
  finalSugarLow: '8.0701754385964912280701754385964912280701754385965',
  finalSugarHigh: '8.0701754385964912280701754385964912280701754385965',
  worstDeviation: '0.070175438596491228070175438596491228070175438596491',
  minToleranceGap: null,
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '600', Q: '10', U: '0', E: '0.5' },
};

// E=0：无稳健刻度，n=6，最坏偏差 0.5357…，缺口同值
const noRobustPlan: RobustPlanResponse = {
  feasible: false,
  status: 'NO_ROBUST',
  message: '无稳健刻度',
  n: 6,
  dose: '60',
  finalVolume: '560',
  finalSugarLow: '7.4642857142857142857142857142857142857142857142857',
  finalSugarHigh: '7.8928571428571428571428571428571428571428571428571',
  worstDeviation: '0.53571428571428571428571428571428571428571428571429',
  minToleranceGap: '0.53571428571428571428571428571428571428571428571429',
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '560', Q: '10', U: '2', E: '0' },
};

const noCapacityPlan: RobustPlanResponse = {
  feasible: false,
  status: 'NO_CAPACITY',
  message: '容量放不下一个刻度',
  n: null,
  dose: null,
  finalVolume: null,
  finalSugarLow: null,
  finalSugarHigh: null,
  worstDeviation: null,
  minToleranceGap: null,
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '505', Q: '10', U: '1', E: '0.1' },
};

function renderPanel(overrides: Partial<Parameters<typeof RobustPlanPanel>[0]> = {}) {
  const props = {
    plan: null,
    values: { Q: '', U: '', E: '' },
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
    const props = renderPanel({ values: { Q: '10', U: '0', E: '0.5' } });
    fireEvent.click(screen.getByTestId('robust-entry'));
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it('输入变更按字段回调', () => {
    const props = renderPanel();
    fireEvent.change(screen.getByLabelText('单刻度量 Q（mL）'), { target: { value: '12' } });
    expect(props.onValueChange).toHaveBeenCalledWith('Q', '12');
  });

  it('Q/U/E 的字段错误分别定位到输入框', () => {
    renderPanel({ fieldErrors: { U: '糖度区间下界 S-U 必须大于目标糖度 T' } });
    expect(screen.getByTestId('error-U')).toHaveTextContent('S-U 必须大于目标糖度 T');
    expect(screen.getByLabelText('糖度波动 U（%）')).toHaveAttribute('aria-invalid', 'true');
  });
});

describe('RobustPlanPanel 方案展示', () => {
  it('稳健刻度：展示剂量、终态体积、糖度区间与最坏偏差，不展示缺口', () => {
    renderPanel({ plan: robustPlan });
    expect(screen.getByTestId('robust-status')).toHaveTextContent('稳健刻度');
    expect(screen.getByTestId('robust-dose')).toHaveTextContent('70');
    expect(screen.getByTestId('robust-final-volume')).toHaveTextContent('570');
    expect(screen.getByTestId('robust-sugar-range')).toHaveTextContent('8.0702 ~ 8.0702');
    expect(screen.getByTestId('robust-worst')).toHaveTextContent('0.0702');
    expect(screen.queryByTestId('robust-gap')).toBeNull();
  });

  it('无稳健刻度：展示最优刻度、最坏偏差与最小容差缺口', () => {
    renderPanel({ plan: noRobustPlan });
    expect(screen.getByTestId('robust-status')).toHaveTextContent('无稳健刻度');
    expect(screen.getByTestId('robust-dose')).toHaveTextContent('60');
    expect(screen.getByTestId('robust-worst')).toHaveTextContent('0.5357');
    expect(screen.getByTestId('robust-gap')).toHaveTextContent('0.5357');
  });

  it('容量放不下一个刻度：只展示结论文案，无数据行', () => {
    renderPanel({ plan: noCapacityPlan });
    expect(screen.getByTestId('robust-status')).toHaveTextContent('容量放不下一个刻度');
    expect(screen.queryByTestId('robust-dose')).toBeNull();
    expect(screen.queryByTestId('robust-gap')).toBeNull();
  });

  it('请求级错误展示为全局错误而非方案', () => {
    renderPanel({ globalError: '无法连接判定服务，请稍后重试' });
    expect(screen.getByTestId('robust-error')).toHaveTextContent('无法连接判定服务');
    expect(screen.queryByTestId('robust-result')).toBeNull();
  });
});

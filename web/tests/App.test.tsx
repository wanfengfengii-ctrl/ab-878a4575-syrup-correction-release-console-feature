import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import App from '../src/App';
import type { JudgeResponse, RobustPlanResponse } from '../src/lib/api';

const allowedResult: JudgeResponse = {
  verdict: 'ALLOWED',
  message: '允许补加',
  dose: '68.181818181818181818181818181818181818181818181818',
  finalVolume: '568.18181818181818181818181818181818181818181818182',
  remainingCapacity: '31.81818181818181818181818181818181818181818181818',
  excess: null,
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '600' },
};

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

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function fillMainForm() {
  fireEvent.change(screen.getByLabelText(/当前体积 V/), { target: { value: '500' } });
  fireEvent.change(screen.getByLabelText(/当前糖度 C/), { target: { value: '5' } });
  fireEvent.change(screen.getByLabelText(/目标糖度 T/), { target: { value: '8' } });
  fireEvent.change(screen.getByLabelText(/糖浆糖度 S/), { target: { value: '30' } });
  fireEvent.change(screen.getByLabelText(/罐体容量 K/), { target: { value: '600' } });
}

describe('App 稳健刻度方案集成', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('允许补加结论下生成稳健刻度方案，并复用原五项输入', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(allowedResult))
      .mockResolvedValueOnce(jsonResponse(robustPlan));

    render(<App />);
    fillMainForm();
    fireEvent.click(screen.getByRole('button', { name: '判定补加' }));

    await waitFor(() => expect(screen.getByTestId('verdict')).toHaveTextContent('允许补加'));
    // 允许结论下：稳健刻度入口出现、腾容入口不出现
    expect(screen.getByTestId('robust-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('drain-panel')).toBeNull();

    fireEvent.change(screen.getByLabelText(/单刻度量 Q/), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText(/糖度波动 U/), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText(/终态容差 E/), { target: { value: '0.5' } });
    fireEvent.click(screen.getByTestId('robust-entry'));

    await waitFor(() => expect(screen.getByTestId('robust-status')).toHaveTextContent('稳健刻度'));
    expect(screen.getByTestId('robust-dose')).toHaveTextContent('70');

    // 第二个请求复用了原判定五项并带上 Q/U/E
    const robustCall = fetchMock.mock.calls[1];
    expect(robustCall[0]).toBe('/api/robust-plan');
    expect(JSON.parse(robustCall[1]!.body as string)).toEqual({
      V: '500', C: '5', T: '8', S: '30', K: '600', Q: '10', U: '0', E: '0.5',
    });
  });

  it('非法 Q：定位字段并清除旧方案，但保留允许结论', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(allowedResult))
      .mockResolvedValueOnce(jsonResponse(robustPlan))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: '输入校验失败，已整单拒绝',
            errors: [{ field: 'Q', message: '单刻度量 Q 必须大于 0' }],
          },
          422,
        ),
      );

    render(<App />);
    fillMainForm();
    fireEvent.click(screen.getByRole('button', { name: '判定补加' }));
    await waitFor(() => expect(screen.getByTestId('verdict')).toHaveTextContent('允许补加'));

    fireEvent.change(screen.getByLabelText(/单刻度量 Q/), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText(/糖度波动 U/), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText(/终态容差 E/), { target: { value: '0.5' } });
    fireEvent.click(screen.getByTestId('robust-entry'));
    await waitFor(() => expect(screen.getByTestId('robust-status')).toHaveTextContent('稳健刻度'));

    fireEvent.change(screen.getByLabelText(/单刻度量 Q/), { target: { value: '0' } });
    fireEvent.click(screen.getByTestId('robust-entry'));

    await waitFor(() => expect(screen.getByTestId('error-Q')).toBeInTheDocument());
    expect(screen.getByTestId('error-Q')).toHaveTextContent('单刻度量 Q 必须大于 0');
    expect(screen.queryByTestId('robust-result')).toBeNull();
    // 原允许结论保留
    expect(screen.getByTestId('verdict')).toHaveTextContent('允许补加');
  });

  it('重新判定（成功）时清除旧稳健刻度方案与 Q/U/E 输入', async () => {
    const forbiddenResult: JudgeResponse = {
      ...allowedResult,
      verdict: 'FORBIDDEN',
      message: '禁止补加',
      remainingCapacity: null,
      excess: '18.18181818181818181818181818181818181818181818182',
      inputs: { V: '500', C: '5', T: '8', S: '30', K: '550' },
    };
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(allowedResult))
      .mockResolvedValueOnce(jsonResponse(robustPlan))
      .mockResolvedValueOnce(jsonResponse(forbiddenResult));

    render(<App />);
    fillMainForm();
    fireEvent.click(screen.getByRole('button', { name: '判定补加' }));
    await waitFor(() => expect(screen.getByTestId('verdict')).toHaveTextContent('允许补加'));

    fireEvent.change(screen.getByLabelText(/单刻度量 Q/), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText(/糖度波动 U/), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText(/终态容差 E/), { target: { value: '0.5' } });
    fireEvent.click(screen.getByTestId('robust-entry'));
    await waitFor(() => expect(screen.getByTestId('robust-status')).toHaveTextContent('稳健刻度'));

    // 重新判定为禁止补加
    fireEvent.change(screen.getByLabelText(/罐体容量 K/), { target: { value: '550' } });
    fireEvent.click(screen.getByRole('button', { name: '判定补加' }));

    await waitFor(() => expect(screen.getByTestId('verdict')).toHaveTextContent('禁止补加'));
    expect(screen.queryByTestId('robust-panel')).toBeNull();
    expect(screen.getByTestId('drain-panel')).toBeInTheDocument();
  });

  it('重新判定仍为允许补加时 Q/U/E 输入随旧方案清空', async () => {
    const allowedAgain: JudgeResponse = {
      ...allowedResult,
      remainingCapacity: '21.81818181818181818181818181818181818181818181818',
      inputs: { V: '500', C: '5', T: '8', S: '30', K: '590' },
    };
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(allowedResult))
      .mockResolvedValueOnce(jsonResponse(robustPlan))
      .mockResolvedValueOnce(jsonResponse(allowedAgain));

    render(<App />);
    fillMainForm();
    fireEvent.click(screen.getByRole('button', { name: '判定补加' }));
    await waitFor(() => expect(screen.getByTestId('verdict')).toHaveTextContent('允许补加'));

    fireEvent.change(screen.getByLabelText(/单刻度量 Q/), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText(/糖度波动 U/), { target: { value: '0' } });
    fireEvent.change(screen.getByLabelText(/终态容差 E/), { target: { value: '0.5' } });
    fireEvent.click(screen.getByTestId('robust-entry'));
    await waitFor(() => expect(screen.getByTestId('robust-status')).toHaveTextContent('稳健刻度'));

    fireEvent.change(screen.getByLabelText(/罐体容量 K/), { target: { value: '590' } });
    fireEvent.click(screen.getByRole('button', { name: '判定补加' }));

    await waitFor(() => expect(screen.getByTestId('verdict')).toHaveTextContent('允许补加'));
    expect(screen.queryByTestId('robust-result')).toBeNull();
    expect((screen.getByLabelText(/单刻度量 Q/) as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText(/糖度波动 U/) as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText(/终态容差 E/) as HTMLInputElement).value).toBe('');
  });
});

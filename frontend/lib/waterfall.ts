/** Explicit endpoints work across zero; positive/negative stacks do not. */
export function waterfallSteps(values: number[]) {
  let running = 0;
  return values.map((value, index) => {
    const total = index === 0 || (index === values.length - 1 && Math.abs(value - running) < 1e-9);
    const start = total ? 0 : running;
    const end = total ? value : running + value;
    running = end;
    return { start, end, value, total };
  });
}

export function waterfallSeries(values: number[], colors: { up: string; down: string; total: string; ink: string }) {
  const steps = waterfallSteps(values);
  return {
    type: "custom",
    encode: { x: 0, y: [1, 2] },
    data: steps.map((step, i) => [i, step.start, step.end]),
    renderItem: (params: { dataIndex: number }, api: { coord: (value: number[]) => number[]; size: (value: number[]) => number[] }) => {
      const step = steps[params.dataIndex];
      const from = api.coord([params.dataIndex, step.start]);
      const to = api.coord([params.dataIndex, step.end]);
      const width = Math.min(54, Math.abs(api.size([1, 0])[0]) * 0.65);
      const top = Math.min(from[1], to[1]);
      return {
        type: "group",
        children: [
          { type: "rect", shape: { x: from[0] - width / 2, y: top, width, height: Math.abs(to[1] - from[1]) },
            style: { fill: step.total ? colors.total : step.value >= 0 ? colors.up : colors.down } },
          { type: "text", style: { x: from[0], y: top - 5, text: String(step.value), fill: colors.ink, align: "center", verticalAlign: "bottom", fontSize: 11 } },
        ],
      };
    },
  };
}

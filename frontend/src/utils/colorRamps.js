export const COLOR_PALETTES = {
  viridis: ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'],
  plasma: ['#0d0887', '#6a00a8', '#b12a90', '#e16462', '#fca636'],
  blues: ['#eff3ff', '#bdd7e7', '#6baed6', '#3182bd', '#08519c'],
  reds: ['#fee5d9', '#fcae91', '#fb6a4a', '#de2d26', '#a50f15'],
  emerald: ['#edf8e9', '#bae4b3', '#74c476', '#31a354', '#006d2c'],
};

/**
 * Builds a MapLibre GL expression for continuous linear interpolation
 * @param {string} property - Numeric feature property name (e.g. 'feature_count')
 * @param {number} minVal - Minimum value in dataset
 * @param {number} maxVal - Maximum value in dataset
 * @param {string[]} colors - Array of 5 hex colors
 */
export function buildInterpolateColor(property, minVal = 0, maxVal = 10, colors = COLOR_PALETTES.viridis) {
  if (minVal === maxVal) {
    return colors[Math.floor(colors.length / 2)];
  }

  const step = (maxVal - minVal) / (colors.length - 1);
  const expr = ['interpolate', ['linear'], ['coalesce', ['get', property], minVal]];

  colors.forEach((color, idx) => {
    const val = Number((minVal + idx * step).toFixed(2));
    expr.push(val, color);
  });

  return expr;
}
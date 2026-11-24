// Tree-shaken ECharts: only the pieces the system-metrics charts use.
// The full `echarts` entry weighs ~1.1 MB; this is a fraction of that.
import * as echarts from 'echarts/core';
import { LineChart, ScatterChart, BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, MarkLineComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([LineChart, ScatterChart, BarChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer]);

export default echarts;

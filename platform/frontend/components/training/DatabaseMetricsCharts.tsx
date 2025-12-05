"use client";

import React, { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Star } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

// Backend response types
interface TrainingMetric {
  id: number;
  job_id: number;
  epoch: number;
  step?: number;
  loss?: number;
  accuracy?: number;
  learning_rate?: number;
  extra_metrics?: Record<string, any>;
  checkpoint_path?: string;
  created_at: string;
}

interface MetricSchema {
  job_id: number;
  framework: string;
  task_type: string;
  primary_metric: string;
  primary_metric_mode: string;
  available_metrics: string[];
  metric_count: number;
}

// Chart data format (compatible with MLflow charts)
interface MetricDataPoint {
  step: number;
  value: number;
  timestamp: number;
}

interface DatabaseMetricsChartsProps {
  jobId: number | string;
  selectedMetrics?: string[];
  jobStatus?: string;
  refreshKey?: number; // Incremented by parent when WebSocket receives metrics updates
}

export default function DatabaseMetricsCharts({
  jobId,
  selectedMetrics = [],
  jobStatus,
  refreshKey,
}: DatabaseMetricsChartsProps) {
  const [metricsData, setMetricsData] = useState<{
    [key: string]: MetricDataPoint[];
  } | null>(null);
  const [metricSchema, setMetricSchema] = useState<MetricSchema | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Don't fetch if job is pending
    if (jobStatus === 'pending') {
      setIsLoading(false);
      return;
    }

    const fetchMetrics = async () => {
      try {
        // Fetch both metrics data and schema in parallel
        const [metricsResponse, schemaResponse] = await Promise.all([
          fetch(`${API_URL}/training/jobs/${jobId}/metrics?limit=1000`),
          fetch(`${API_URL}/training/jobs/${jobId}/metric-schema`)
        ]);

        if (metricsResponse.ok && schemaResponse.ok) {
          const metrics: TrainingMetric[] = await metricsResponse.json();
          const schema: MetricSchema = await schemaResponse.json();

          // Transform backend data to chart format
          const transformedData = transformMetricsToChartFormat(metrics);

          setMetricsData(transformedData);
          setMetricSchema(schema);
        }
      } catch (error) {
        console.error("[DatabaseMetricsCharts] Error fetching metrics:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchMetrics();
  }, [jobId, jobStatus, refreshKey]); // WebSocket-triggered refresh

  // Transform backend metrics to chart format
  const transformMetricsToChartFormat = (
    metrics: TrainingMetric[]
  ): { [key: string]: MetricDataPoint[] } => {
    const chartData: { [key: string]: MetricDataPoint[] } = {};

    metrics.forEach((metric) => {
      const step = metric.epoch;
      const timestamp = new Date(metric.created_at).getTime();

      // Add standard fields if they exist
      if (metric.loss !== undefined && metric.loss !== null) {
        if (!chartData['loss']) chartData['loss'] = [];
        chartData['loss'].push({ step, value: metric.loss, timestamp });
      }

      if (metric.accuracy !== undefined && metric.accuracy !== null) {
        if (!chartData['accuracy']) chartData['accuracy'] = [];
        chartData['accuracy'].push({ step, value: metric.accuracy, timestamp });
      }

      if (metric.learning_rate !== undefined && metric.learning_rate !== null) {
        if (!chartData['learning_rate']) chartData['learning_rate'] = [];
        chartData['learning_rate'].push({ step, value: metric.learning_rate, timestamp });
      }

      // Flatten extra_metrics into separate metric series
      if (metric.extra_metrics) {
        Object.entries(metric.extra_metrics).forEach(([key, value]) => {
          // Skip metadata fields
          if (['batch', 'total_batches', 'epoch_time'].includes(key)) {
            return;
          }

          if (typeof value === 'number' && !isNaN(value)) {
            if (!chartData[key]) chartData[key] = [];
            chartData[key].push({ step, value, timestamp });
          }
        });
      }
    });

    return chartData;
  };

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="animate-pulse">
          <div className="h-48 bg-gray-200 rounded-lg"></div>
        </div>
        <div className="animate-pulse">
          <div className="h-48 bg-gray-200 rounded-lg"></div>
        </div>
      </div>
    );
  }

  // Show message for pending status (no spinner)
  if (jobStatus === 'pending') {
    return (
      <div className="p-6 bg-white rounded-lg border border-gray-200 flex flex-col items-center justify-center">
        <p className="text-sm text-gray-500">
          학습을 시작하면 메트릭이 표시됩니다
        </p>
      </div>
    );
  }

  if (!metricsData || Object.keys(metricsData).length === 0) {
    return (
      <div className="p-6 bg-white rounded-lg border border-gray-200 flex flex-col items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-400 mb-3"></div>
        <p className="text-xs text-gray-400">
          1에폭 완료 후 표시됩니다.
        </p>
      </div>
    );
  }

  const primary_metric = metricSchema?.primary_metric || 'accuracy';
  const primary_metric_mode = metricSchema?.primary_metric_mode || 'max';

  // Extract all available metric keys dynamically
  const availableMetricKeys = Object.keys(metricsData).filter(
    key => metricsData[key] && metricsData[key].length > 0
  );

  console.log('[DatabaseMetricsCharts] Available metrics:', availableMetricKeys);
  console.log('[DatabaseMetricsCharts] Primary metric:', primary_metric);

  // Group metrics by category (loss, accuracy, etc.)
  const lossMetrics = availableMetricKeys.filter(key => key.toLowerCase().includes('loss'));
  const primaryMetricKey = primary_metric;

  // Find metrics that match the primary metric name
  const primaryMetrics = availableMetricKeys.filter(key =>
    key.toLowerCase().includes(primaryMetricKey.toLowerCase())
  );

  console.log('[DatabaseMetricsCharts] Loss metrics:', lossMetrics);
  console.log('[DatabaseMetricsCharts] Primary metrics:', primaryMetrics);

  // Check if we have data
  const hasLoss = lossMetrics.length > 0;
  const hasPrimaryMetric = primaryMetrics.length > 0;

  // Format metric name for display
  const formatMetricName = (key: string) => {
    return key
      .replace(/_/g, ' ')
      .replace(/^./, (str) => str.toUpperCase())
      .trim();
  };

  // Check if metric should show percentage
  const isPercentageMetric = (key: string) => {
    return (
      key.toLowerCase().includes('accuracy') ||
      key.toLowerCase().includes('precision') ||
      key.toLowerCase().includes('recall') ||
      key.toLowerCase().includes('map') ||
      key.toLowerCase().includes('iou')
    );
  };

  // Build list of metrics to display
  const metricsToDisplay: Array<{
    key: string; // Display name
    actualKey: string; // Actual key in metrics object
    isPrimary: boolean;
  }> = [];

  // Always show primary metrics first (if available)
  if (hasPrimaryMetric) {
    primaryMetrics.forEach(metricKey => {
      metricsToDisplay.push({
        key: formatMetricName(metricKey),
        actualKey: metricKey,
        isPrimary: true,
      });
    });
  }

  // Add selected metrics if they exist in available metrics
  if (selectedMetrics && selectedMetrics.length > 0) {
    selectedMetrics.forEach((selectedKey) => {
      // Find matching metric keys (flexible matching by substring)
      const matchingKeys = availableMetricKeys.filter(key =>
        key.toLowerCase().includes(selectedKey.toLowerCase()) &&
        !primaryMetrics.includes(key) // Skip if already added as primary
      );

      matchingKeys.forEach(metricKey => {
        metricsToDisplay.push({
          key: formatMetricName(metricKey),
          actualKey: metricKey,
          isPrimary: false,
        });
      });
    });
  }

  // Color palette for multi-metric chart
  const multiMetricColors = [
    'rgb(16, 185, 129)',   // emerald
    'rgb(245, 158, 11)',   // amber
    'rgb(139, 92, 246)',   // violet
    'rgb(236, 72, 153)',   // pink
    'rgb(14, 165, 233)',   // sky
    'rgb(6, 182, 212)',    // cyan
    'rgb(251, 191, 36)',   // yellow
    'rgb(167, 139, 250)',  // purple
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Loss Chart (if available) */}
        {hasLoss && lossMetrics.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-semibold text-gray-900">Loss</h4>
              <div className="flex gap-4 text-xs">
                {lossMetrics.slice(0, 2).map((key, idx) => (
                  <div key={key} className="flex items-center gap-1">
                    <div className={`w-3 h-3 rounded-sm ${idx === 0 ? 'bg-blue-500' : 'bg-purple-500'}`}></div>
                    <span className="text-gray-600">{formatMetricName(key)}</span>
                  </div>
                ))}
              </div>
            </div>
            <SimpleLineChart
              trainData={metricsData[lossMetrics[0]] || []}
              valData={lossMetrics[1] ? metricsData[lossMetrics[1]] : []}
              color1="rgb(59, 130, 246)"
              color2="rgb(168, 85, 247)"
            />
            {lossMetrics[1] && metricsData[lossMetrics[1]] && metricsData[lossMetrics[1]].length > 0 && (
              <MetricSummary
                label={`Latest ${formatMetricName(lossMetrics[1])}`}
                value={metricsData[lossMetrics[1]][metricsData[lossMetrics[1]].length - 1].value}
                trend={
                  metricsData[lossMetrics[1]].length > 1
                    ? metricsData[lossMetrics[1]][metricsData[lossMetrics[1]].length - 1].value <
                      metricsData[lossMetrics[1]][metricsData[lossMetrics[1]].length - 2].value
                    : null
                }
              />
            )}
          </div>
        )}

        {/* Multi-Metric Chart (Primary + Selected Metrics) */}
        {metricsToDisplay.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                <Star className="w-4 h-4 text-blue-600" fill="currentColor" />
                메트릭
              </h4>
              <div className="flex flex-wrap gap-3 text-xs">
                {metricsToDisplay.map((metricInfo, index) => (
                  <div key={metricInfo.key} className="flex items-center gap-1">
                    <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: multiMetricColors[index % multiMetricColors.length] }}></div>
                    <span className="text-gray-600">{formatMetricName(metricInfo.key)}</span>
                  </div>
                ))}
              </div>
            </div>
            <MultiMetricChart
              metrics={metricsData}
              metricsToDisplay={metricsToDisplay}
              colors={multiMetricColors}
            />
            {/* Show latest value for primary metric */}
            {metricsToDisplay.length > 0 && (() => {
              const primaryInfo = metricsToDisplay[0];
              const dataToUse = metricsData[primaryInfo.actualKey];

              if (dataToUse && dataToUse.length > 0) {
                return (
                  <MetricSummary
                    label={`Latest ${formatMetricName(primaryInfo.key)}`}
                    value={dataToUse[dataToUse.length - 1].value}
                    trend={
                      dataToUse.length > 1
                        ? primary_metric_mode === 'max'
                          ? dataToUse[dataToUse.length - 1].value > dataToUse[dataToUse.length - 2].value
                          : dataToUse[dataToUse.length - 1].value < dataToUse[dataToUse.length - 2].value
                        : null
                    }
                    isAccuracy={isPercentageMetric(primaryInfo.key)}
                  />
                );
              }
              return null;
            })()}
          </div>
        )}
      </div>
    </div>
  );
}

// Multi-metric chart component with hover tooltip (reused from MLflow version)
function MultiMetricChart({
  metrics,
  metricsToDisplay,
  colors,
}: {
  metrics: { [key: string]: MetricDataPoint[] };
  metricsToDisplay: Array<{
    key: string;
    actualKey: string;
    isPrimary: boolean;
  }>;
  colors: string[];
}) {
  const [hoveredPoint, setHoveredPoint] = useState<{
    epoch: number;
    x: number;
    y: number;
    values: { name: string; value: number; color: string }[];
  } | null>(null);

  const width = 600;
  const height = 200;
  const padding = { top: 10, right: 10, bottom: 30, left: 50 };

  // Collect all data points
  const allDataPoints: { metricIndex: number; data: MetricDataPoint[] }[] = [];
  metricsToDisplay.forEach((metricInfo, index) => {
    const dataToUse = metrics[metricInfo.actualKey];

    if (dataToUse && dataToUse.length > 0) {
      allDataPoints.push({ metricIndex: index, data: dataToUse });
    }
  });

  if (allDataPoints.length === 0) {
    return <div className="text-center text-gray-500 py-8">데이터 없음</div>;
  }

  // Find min/max for scaling
  const allValues = allDataPoints.flatMap(({ data }) => data.map((d) => d.value));
  const minValue = Math.min(...allValues);
  const maxValue = Math.max(...allValues);
  const maxStep = Math.max(
    ...allDataPoints.flatMap(({ data }) => data.map((d) => d.step))
  );

  // Scaling functions
  const xScale = (step: number) =>
    padding.left + ((step - 1) / maxStep) * (width - padding.left - padding.right);
  const yScale = (value: number) =>
    height -
    padding.bottom -
    ((value - minValue) / (maxValue - minValue)) *
      (height - padding.top - padding.bottom);

  // Create path string
  const createPath = (data: MetricDataPoint[]) => {
    if (data.length === 0) return "";
    return data
      .map((d, i) => `${i === 0 ? "M" : "L"} ${xScale(d.step)} ${yScale(d.value)}`)
      .join(" ");
  };

  // Format metric name
  const formatMetricName = (key: string) => {
    return key
      .replace(/_/g, ' ')
      .replace(/^./, (str) => str.toUpperCase())
      .trim();
  };

  // Handle mouse move to show tooltip
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;

    // Find closest epoch
    const xPos = mouseX - padding.left;
    const xRatio = xPos / (width - padding.left - padding.right);
    const closestStep = Math.round(1 + xRatio * maxStep);

    if (closestStep < 1 || closestStep > maxStep) {
      setHoveredPoint(null);
      return;
    }

    // Get values for all metrics at this epoch
    const values: { name: string; value: number; color: string }[] = [];
    allDataPoints.forEach(({ metricIndex, data }) => {
      const point = data.find((d) => d.step === closestStep);
      if (point) {
        values.push({
          name: formatMetricName(metricsToDisplay[metricIndex].key),
          value: point.value,
          color: colors[metricIndex % colors.length],
        });
      }
    });

    if (values.length > 0) {
      setHoveredPoint({
        epoch: closestStep,
        x: xScale(closestStep),
        y: e.clientY - rect.top,
        values,
      });
    }
  };

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ maxHeight: "200px" }}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredPoint(null)}
      >
        {/* Grid lines */}
        <g className="grid" stroke="#e5e7eb" strokeWidth="1">
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
            <line
              key={ratio}
              x1={padding.left}
              y1={
                height -
                padding.bottom -
                ratio * (height - padding.top - padding.bottom)
              }
              x2={width - padding.right}
              y2={
                height -
                padding.bottom -
                ratio * (height - padding.top - padding.bottom)
              }
            />
          ))}
        </g>

        {/* Y-axis labels */}
        <g className="y-axis" fontSize="10" fill="#6b7280">
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
            const value = minValue + ratio * (maxValue - minValue);
            return (
              <text
                key={ratio}
                x={padding.left - 5}
                y={
                  height -
                  padding.bottom -
                  ratio * (height - padding.top - padding.bottom)
                }
                textAnchor="end"
                dominantBaseline="middle"
              >
                {value.toFixed(3)}
              </text>
            );
          })}
        </g>

        {/* X-axis labels */}
        <g className="x-axis" fontSize="10" fill="#6b7280">
          {allDataPoints[0].data
            .filter((_, i) => i % Math.ceil(allDataPoints[0].data.length / 5) === 0)
            .map((d) => (
              <text
                key={d.step}
                x={xScale(d.step)}
                y={height - padding.bottom + 15}
                textAnchor="middle"
              >
                Epoch {d.step}
              </text>
            ))}
        </g>

        {/* Lines and points for each metric */}
        {allDataPoints.map(({ metricIndex, data }) => {
          const color = colors[metricIndex % colors.length];
          return (
            <g key={metricIndex}>
              {/* Line */}
              <path
                d={createPath(data)}
                fill="none"
                stroke={color}
                strokeWidth="2"
              />
              {/* Points */}
              {data.map((d) => (
                <circle
                  key={`${metricIndex}-${d.step}`}
                  cx={xScale(d.step)}
                  cy={yScale(d.value)}
                  r="3"
                  fill={color}
                />
              ))}
            </g>
          );
        })}

        {/* Hover indicator line */}
        {hoveredPoint && (
          <line
            x1={hoveredPoint.x}
            y1={padding.top}
            x2={hoveredPoint.x}
            y2={height - padding.bottom}
            stroke="#9ca3af"
            strokeWidth="1"
            strokeDasharray="4 2"
          />
        )}
      </svg>

      {/* Tooltip */}
      {hoveredPoint && (
        <div
          className="absolute z-50 bg-white border border-gray-300 rounded-lg shadow-lg p-3 pointer-events-none"
          style={{
            left: `${(hoveredPoint.x / width) * 100}%`,
            top: "50%",
            transform: "translate(-50%, -50%)",
            minWidth: "150px",
          }}
        >
          <div className="text-xs font-semibold text-gray-700 mb-2">
            Epoch {hoveredPoint.epoch}
          </div>
          {hoveredPoint.values.map((v, i) => (
            <div key={i} className="flex items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-1.5">
                <div
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: v.color }}
                />
                <span className="text-gray-600">{v.name}:</span>
              </div>
              <span className="font-mono font-medium text-gray-900">
                {v.value.toFixed(4)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Simple SVG line chart component with hover (reused from MLflow version)
function SimpleLineChart({
  trainData,
  valData,
  color1,
  color2,
}: {
  trainData: MetricDataPoint[];
  valData: MetricDataPoint[];
  color1: string;
  color2: string;
}) {
  const [hoveredPoint, setHoveredPoint] = useState<{
    epoch: number;
    x: number;
    trainValue?: number;
    valValue?: number;
  } | null>(null);

  const width = 600;
  const height = 200;
  const padding = { top: 10, right: 10, bottom: 30, left: 50 };

  // Find min/max for scaling
  const allValues = [
    ...trainData.map((d) => d.value),
    ...valData.map((d) => d.value),
  ];
  const minValue = Math.min(...allValues);
  const maxValue = Math.max(...allValues);
  const maxStep = Math.max(
    ...trainData.map((d) => d.step),
    ...valData.map((d) => d.step)
  );

  // Scaling functions
  const xScale = (step: number) =>
    padding.left + ((step - 1) / maxStep) * (width - padding.left - padding.right);
  const yScale = (value: number) =>
    height -
    padding.bottom -
    ((value - minValue) / (maxValue - minValue)) *
      (height - padding.top - padding.bottom);

  // Create path string
  const createPath = (data: MetricDataPoint[]) => {
    if (data.length === 0) return "";
    return data
      .map((d, i) => `${i === 0 ? "M" : "L"} ${xScale(d.step)} ${yScale(d.value)}`)
      .join(" ");
  };

  // Handle mouse move
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;

    const xPos = mouseX - padding.left;
    const xRatio = xPos / (width - padding.left - padding.right);
    const closestStep = Math.round(1 + xRatio * maxStep);

    if (closestStep < 1 || closestStep > maxStep) {
      setHoveredPoint(null);
      return;
    }

    const trainPoint = trainData.find((d) => d.step === closestStep);
    const valPoint = valData.find((d) => d.step === closestStep);

    if (trainPoint || valPoint) {
      setHoveredPoint({
        epoch: closestStep,
        x: xScale(closestStep),
        trainValue: trainPoint?.value,
        valValue: valPoint?.value,
      });
    }
  };

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ maxHeight: "200px" }}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredPoint(null)}
      >
        {/* Grid lines */}
        <g className="grid" stroke="#e5e7eb" strokeWidth="1">
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
            <line
              key={ratio}
              x1={padding.left}
              y1={
                height -
                padding.bottom -
                ratio * (height - padding.top - padding.bottom)
              }
              x2={width - padding.right}
              y2={
                height -
                padding.bottom -
                ratio * (height - padding.top - padding.bottom)
              }
            />
          ))}
        </g>

        {/* Y-axis labels */}
        <g className="y-axis" fontSize="10" fill="#6b7280">
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
            const value = minValue + ratio * (maxValue - minValue);
            return (
              <text
                key={ratio}
                x={padding.left - 5}
                y={
                  height -
                  padding.bottom -
                  ratio * (height - padding.top - padding.bottom)
                }
                textAnchor="end"
                dominantBaseline="middle"
              >
                {value.toFixed(3)}
              </text>
            );
          })}
        </g>

        {/* X-axis labels */}
        <g className="x-axis" fontSize="10" fill="#6b7280">
          {trainData
            .filter((_, i) => i % Math.ceil(trainData.length / 5) === 0)
            .map((d) => (
              <text
                key={d.step}
                x={xScale(d.step)}
                y={height - padding.bottom + 15}
                textAnchor="middle"
              >
                Epoch {d.step}
              </text>
            ))}
        </g>

        {/* Lines */}
        {trainData.length > 0 && (
          <path
            d={createPath(trainData)}
            fill="none"
            stroke={color1}
            strokeWidth="2"
          />
        )}
        {valData.length > 0 && (
          <path
            d={createPath(valData)}
            fill="none"
            stroke={color2}
            strokeWidth="2"
          />
        )}

        {/* Points */}
        {trainData.map((d) => (
          <circle
            key={`train-${d.step}`}
            cx={xScale(d.step)}
            cy={yScale(d.value)}
            r="3"
            fill={color1}
          />
        ))}
        {valData.map((d) => (
          <circle
            key={`val-${d.step}`}
            cx={xScale(d.step)}
            cy={yScale(d.value)}
            r="3"
            fill={color2}
          />
        ))}

        {/* Hover indicator */}
        {hoveredPoint && (
          <line
            x1={hoveredPoint.x}
            y1={padding.top}
            x2={hoveredPoint.x}
            y2={height - padding.bottom}
            stroke="#9ca3af"
            strokeWidth="1"
            strokeDasharray="4 2"
          />
        )}
      </svg>

      {/* Tooltip */}
      {hoveredPoint && (
        <div
          className="absolute z-50 bg-white border border-gray-300 rounded-lg shadow-lg p-3 pointer-events-none"
          style={{
            left: `${(hoveredPoint.x / width) * 100}%`,
            top: "50%",
            transform: "translate(-50%, -50%)",
            minWidth: "120px",
          }}
        >
          <div className="text-xs font-semibold text-gray-700 mb-2">
            Epoch {hoveredPoint.epoch}
          </div>
          {hoveredPoint.trainValue !== undefined && (
            <div className="flex items-center justify-between gap-3 text-xs mb-1">
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full" style={{ backgroundColor: color1 }} />
                <span className="text-gray-600">Train:</span>
              </div>
              <span className="font-mono font-medium text-gray-900">
                {hoveredPoint.trainValue.toFixed(4)}
              </span>
            </div>
          )}
          {hoveredPoint.valValue !== undefined && (
            <div className="flex items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full" style={{ backgroundColor: color2 }} />
                <span className="text-gray-600">Val:</span>
              </div>
              <span className="font-mono font-medium text-gray-900">
                {hoveredPoint.valValue.toFixed(4)}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MetricSummary({
  label,
  value,
  trend,
  isAccuracy = false,
}: {
  label: string;
  value: number;
  trend: boolean | null;
  isAccuracy?: boolean;
}) {
  const displayValue = isAccuracy
    ? `${(value * 100).toFixed(2)}%`
    : value.toFixed(4);

  // For accuracy, up is good. For loss, down is good.
  const isGoodTrend = isAccuracy ? trend === true : trend === false;

  return (
    <div className="mt-4 flex items-center justify-between text-sm border-t border-gray-200 pt-3">
      <span className="text-gray-600">{label}:</span>
      <div className="flex items-center gap-2">
        <span className="font-semibold text-gray-900">{displayValue}</span>
        {trend !== null && (
          <span
            className={
              isGoodTrend ? "text-emerald-600" : "text-red-600"
            }
          >
            {trend ? (
              <TrendingUp className="w-4 h-4" />
            ) : (
              <TrendingDown className="w-4 h-4" />
            )}
          </span>
        )}
      </div>
    </div>
  );
}

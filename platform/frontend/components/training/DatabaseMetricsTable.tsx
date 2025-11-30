"use client";

import React, { useMemo } from "react";
import { CheckCircle2, XCircle, Star } from "lucide-react";
import useSWR from "swr";

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
const fetcher = (url: string) => fetch(`${API_URL}${url}`).then((res) => res.json());

interface TrainingMetric {
  id: number;
  job_id: number;
  epoch: number;
  step?: number;
  loss?: number;
  accuracy?: number;
  learning_rate?: number;
  checkpoint_path?: string;
  extra_metrics?: Record<string, any>;
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

interface DatabaseMetricsTableProps {
  jobId: number;
  metrics: TrainingMetric[];
  selectedMetrics?: string[];
  onMetricToggle?: (metricKey: string) => void;
  onCheckpointSelect?: (checkpointPath: string, epoch: number) => void;
  jobStatus?: string;
}

export default function DatabaseMetricsTable({
  jobId,
  metrics,
  selectedMetrics = [],
  onMetricToggle,
  onCheckpointSelect,
  jobStatus,
}: DatabaseMetricsTableProps) {

  // Fetch metric schema for dynamic columns (don't fetch if pending)
  const { data: metricSchema, isLoading: schemaLoading } = useSWR<MetricSchema>(
    jobId && jobStatus !== 'pending' ? `/training/jobs/${jobId}/metric-schema` : null,
    fetcher,
    {
      refreshInterval: 0, // Only fetch once
      revalidateOnFocus: false, // Don't refetch on window focus
      dedupingInterval: 60000 // Cache for 1 minute
    }
  );

  // Get metric columns from schema, or extract from actual metrics data
  // IMPORTANT: useMemo must be called before any conditional returns (React hooks rule)
  const metricColumns = useMemo(() => {
    if (metricSchema?.available_metrics && metricSchema.available_metrics.length > 0) {
      // Use schema if available
      return metricSchema.available_metrics;
    }

    // Extract unique metric keys from all metrics' extra_metrics
    if (!metrics || metrics.length === 0) {
      return [];
    }

    const allKeys = new Set<string>();
    metrics.forEach(metric => {
      if (metric.extra_metrics) {
        Object.keys(metric.extra_metrics).forEach(key => {
          // Exclude metadata keys
          if (!['batch', 'total_batches', 'epoch_time'].includes(key)) {
            allKeys.add(key);
          }
        });
      }
      // Also include standard fields
      if (metric.loss !== undefined && metric.loss !== null) allKeys.add('loss');
      if (metric.accuracy !== undefined && metric.accuracy !== null) allKeys.add('accuracy');
      if (metric.learning_rate !== undefined && metric.learning_rate !== null) allKeys.add('learning_rate');
    });

    const extractedColumns = Array.from(allKeys).sort();
    return extractedColumns;
  }, [metrics, metricSchema]);

  const primaryMetric = metricSchema?.primary_metric || 'loss';
  const primaryMetricMode = metricSchema?.primary_metric_mode || 'min';

  // Early return AFTER all hooks
  if (!metrics || metrics.length === 0) {

    // Show message without spinner for pending status
    if (jobStatus === 'pending') {
      return (
        <div className="p-6 bg-white rounded-lg border border-gray-200 flex flex-col items-center justify-center">
          <p className="text-sm text-gray-500">
            학습을 시작하면 메트릭이 표시됩니다
          </p>
        </div>
      );
    }

    // Show spinner for running status
    return (
      <div className="p-6 bg-white rounded-lg border border-gray-200 flex flex-col items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-400 mb-3"></div>
        <p className="text-xs text-gray-400">
          1에폭 완료 후 표시됩니다.
        </p>
      </div>
    );
  }

  // Show last 10 epochs
  const recentMetrics = metrics.slice(-10).reverse();

  // Helper function to format metric display name
  const formatMetricName = (key: string): string => {
    // Convert snake_case or camelCase to Title Case
    return key
      .replace(/_/g, ' ')
      .replace(/([A-Z])/g, ' $1')
      .replace(/^./, (str) => str.toUpperCase())
      .trim();
  };

  // Helper function to format metric value
  const formatMetricValue = (key: string, value: any): string => {
    if (value === undefined || value === null) return '-';

    // Percentage metrics (accuracy, recall, precision, mAP, etc.)
    if (
      key.toLowerCase().includes('accuracy') ||
      key.toLowerCase().includes('acc') ||
      key.toLowerCase().includes('precision') ||
      key.toLowerCase().includes('recall') ||
      key.toLowerCase().includes('map') ||
      key.toLowerCase().includes('iou')
    ) {
      // If value is already > 1, assume it's already in percentage
      if (value > 1) {
        return `${value.toFixed(2)}%`;
      }
      // Otherwise convert to percentage
      return `${(value * 100).toFixed(2)}%`;
    }

    // Loss metrics - 4 decimal places
    if (key.toLowerCase().includes('loss')) {
      return value.toFixed(4);
    }

    // Learning rate - 6 decimal places
    if (key.toLowerCase().includes('lr') || key.toLowerCase().includes('learning')) {
      return value.toFixed(6);
    }

    // Default - 4 decimal places
    if (typeof value === 'number') {
      return value.toFixed(4);
    }

    return String(value);
  };

  // Helper function to get metric value from metric object
  const getMetricValue = (metric: TrainingMetric, key: string): any => {
    // Check standard fields first
    if (key === 'loss' && metric.loss !== undefined) return metric.loss;
    if (key === 'accuracy' && metric.accuracy !== undefined) return metric.accuracy;
    if (
      (key === 'learning_rate' || key === 'lr') &&
      metric.learning_rate !== undefined
    )
      return metric.learning_rate;

    // Check extra_metrics
    if (metric.extra_metrics && metric.extra_metrics[key] !== undefined) {
      return metric.extra_metrics[key];
    }

    return undefined;
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <h4 className="text-xs font-semibold text-gray-900">
          학습 메트릭 (최근 {recentMetrics.length} Epochs)
        </h4>
        {metricSchema && (
          <div className="flex items-center gap-2 text-[10px]">
            <span className="text-gray-500">Primary Metric:</span>
            <div className="flex items-center gap-1 px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded-full font-medium">
              <Star className="w-2.5 h-2.5" fill="currentColor" />
              {formatMetricName(primaryMetric)}
              <span className="text-[9px] opacity-75">
                ({primaryMetricMode === 'max' ? '↑' : '↓'})
              </span>
            </div>
          </div>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[10px]">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-2 py-1 text-left font-semibold text-gray-700 sticky left-0 bg-gray-50 z-10">
                Epoch
              </th>
              {metricColumns.map((col) => {
                const isPrimary = col === primaryMetric;
                const isSelected = selectedMetrics.includes(col);
                const isClickable = onMetricToggle !== undefined;

                return (
                  <th
                    key={col}
                    onClick={() => isClickable && onMetricToggle(col)}
                    className={`px-2 py-1 text-right font-semibold transition-colors ${
                      isPrimary
                        ? 'bg-blue-50 text-blue-900'
                        : isSelected
                        ? 'bg-emerald-50 text-emerald-900'
                        : 'text-gray-700'
                    } ${
                      isClickable ? 'cursor-pointer hover:bg-gray-100' : ''
                    }`}
                    title={isClickable ? 'Click to toggle chart visibility' : ''}
                  >
                    <div className="flex items-center justify-end gap-0.5">
                      {isPrimary && (
                        <Star className="w-2.5 h-2.5 text-blue-600" fill="currentColor" />
                      )}
                      {!isPrimary && isSelected && (
                        <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
                      )}
                      {formatMetricName(col)}
                    </div>
                  </th>
                );
              })}
              <th className="px-2 py-1 text-center font-semibold text-gray-700">
                Checkpoint
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {recentMetrics.map((metric, index) => {
              return (
                <tr
                  key={metric.id}
                  className={index === 0 ? "bg-violet-50" : "hover:bg-gray-50"}
                >
                  <td className="px-2 py-1 font-medium text-gray-900 sticky left-0 bg-inherit z-10">
                    {metric.epoch}
                    {index === 0 && (
                      <span className="ml-1 text-[9px] text-violet-600 font-semibold">
                        Latest
                      </span>
                    )}
                  </td>
                  {metricColumns.map((col) => {
                    const value = getMetricValue(metric, col);
                    const isPrimary = col === primaryMetric;
                    return (
                      <td
                        key={col}
                        className={`px-2 py-1 text-right font-mono ${
                          isPrimary
                            ? 'bg-blue-50/50 text-blue-900 font-semibold'
                            : 'text-gray-700'
                        }`}
                      >
                        {formatMetricValue(col, value)}
                      </td>
                    );
                  })}
                  <td className="px-2 py-1 text-center">
                    {metric.checkpoint_path && metric.checkpoint_path.trim() !== '' ? (
                      <div className="flex items-center justify-center gap-1">
                        <CheckCircle2 className="w-3 h-3 text-green-600" />
                        {onCheckpointSelect && (
                          <button
                            onClick={() =>
                              onCheckpointSelect(
                                metric.checkpoint_path!,
                                metric.epoch
                              )
                            }
                            className="text-[9px] text-violet-600 hover:text-violet-700 font-medium hover:underline"
                          >
                            Load
                          </button>
                        )}
                      </div>
                    ) : (
                      <XCircle className="w-3 h-3 text-gray-300 mx-auto" />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {metrics.length > 10 && (
        <div className="px-3 py-1.5 bg-gray-50 border-t border-gray-200 text-center">
          <p className="text-[10px] text-gray-500">
            총 {metrics.length} epochs (최근 10개만 표시)
          </p>
        </div>
      )}
    </div>
  );
}

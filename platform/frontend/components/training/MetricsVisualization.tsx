"use client";

import React from "react";

interface MetricsVisualizationProps {
  jobId: number | string;
  height?: string;
}

export default function MetricsVisualization({
  jobId,
  height = "600px",
}: MetricsVisualizationProps) {
  // Grafana dashboard URL with kiosk mode
  // - vision-ai-training: dashboard UID
  // - kiosk: hide Grafana UI elements
  // - var-job_id: set the job_id variable
  // - refresh=10s: auto-refresh every 10 seconds
  const grafanaBaseUrl = process.env.NEXT_PUBLIC_GRAFANA_URL || "http://localhost:3200";
  const grafanaUrl = `${grafanaBaseUrl}/d/vision-ai-training/vision-ai-training-metrics?orgId=1&kiosk&var-job_id=${jobId}&refresh=10s&from=now-30m&to=now`;

  return (
    <div className="w-full rounded-lg overflow-hidden border border-gray-200 shadow-sm">
      <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
        <h3 className="text-sm font-medium text-gray-700">
          Training Metrics (Job {jobId})
        </h3>
      </div>
      <div className="relative" style={{ height }}>
        <iframe
          src={grafanaUrl}
          className="w-full h-full"
          frameBorder="0"
          title={`Training Metrics for Job ${jobId}`}
        />
      </div>
    </div>
  );
}

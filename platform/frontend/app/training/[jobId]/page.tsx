/**
 * Training Job Detail Page
 *
 * Complete example of monitoring integration
 */

'use client';

import { useParams } from 'next/navigation';
import { TrainingMonitorPanel } from '@/components/TrainingMonitorPanel';
import { useTrainingJob } from '@/hooks/useTrainingJob';

export default function TrainingJobPage() {
  const params = useParams();
  const jobId = parseInt(params.jobId as string);

  // Fetch job details from REST API
  const { job, isLoading, error } = useTrainingJob(jobId);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4" />
          <p className="text-gray-600">Loading training job...</p>
        </div>
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="text-red-500 text-4xl mb-4">⚠️</div>
          <p className="text-gray-600">Failed to load training job</p>
          <p className="text-sm text-gray-500 mt-2">{error?.message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold mb-2">Training Job #{jobId}</h1>
        <div className="flex items-center space-x-4 text-sm text-gray-600">
          <span>Model: {job.model_name}</span>
          <span>•</span>
          <span>Framework: {job.framework}</span>
          <span>•</span>
          <span>Task: {job.task_type}</span>
        </div>
      </div>

      {/* Job Configuration */}
      <div className="mb-6 p-4 bg-white border rounded-lg shadow-sm">
        <h2 className="text-xl font-semibold mb-3">Configuration</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-gray-600">Dataset:</span>
            <p className="font-medium">{job.dataset_path}</p>
          </div>
          <div>
            <span className="text-gray-600">Epochs:</span>
            <p className="font-medium">{job.num_epochs}</p>
          </div>
          <div>
            <span className="text-gray-600">Batch Size:</span>
            <p className="font-medium">{job.batch_size}</p>
          </div>
          <div>
            <span className="text-gray-600">Learning Rate:</span>
            <p className="font-medium">{job.learning_rate}</p>
          </div>
          {job.image_size && (
            <div>
              <span className="text-gray-600">Image Size:</span>
              <p className="font-medium">{job.image_size}</p>
            </div>
          )}
          {job.num_classes && (
            <div>
              <span className="text-gray-600">Classes:</span>
              <p className="font-medium">{job.num_classes}</p>
            </div>
          )}
          <div>
            <span className="text-gray-600">Executor:</span>
            <p className="font-medium">{job.executor_type}</p>
          </div>
        </div>
      </div>

      {/* Real-time Monitoring Panel */}
      <TrainingMonitorPanel
        jobId={jobId}
        sessionId={job.session_id}
      />

      {/* External Links */}
      {job.mlflow_run_id && (
        <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <h3 className="text-lg font-semibold mb-2">External Tracking</h3>
          <div className="space-y-2">
            <a
              href={`${process.env.NEXT_PUBLIC_MLFLOW_URL || 'http://localhost:5000'}/#/experiments/${job.mlflow_run_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center text-blue-600 hover:text-blue-800"
            >
              View in MLflow →
            </a>
            <br />
            <a
              href={`${process.env.NEXT_PUBLIC_GRAFANA_URL || 'http://localhost:3200'}/d/training-dashboard`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center text-blue-600 hover:text-blue-800"
            >
              View in Grafana →
            </a>
          </div>
        </div>
      )}
    </div>
  );
}

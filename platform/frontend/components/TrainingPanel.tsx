'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { Play, Square, AlertCircle, ExternalLink, ArrowLeft, ChevronRight, ChevronDown, ChevronUp, HelpCircle } from 'lucide-react'
import { cn } from '@/lib/utils/cn'
import { getModelDisplayNameSync, getTaskDisplayName, formatTrainingJobTitle } from '@/lib/utils/modelUtils'
// import MLflowMetricsCharts from './training/MLflowMetricsCharts' // Removed: Migrated to ClearML
import DatabaseMetricsTable from './training/DatabaseMetricsTable'
import ResumeDialog from './training/ResumeDialog'
import { ValidationDashboard } from './training/validation/ValidationDashboard'
import TestInferencePanel from './training/TestInferencePanel'
import ExportJobList from './export/ExportJobList'
import CreateExportModal from './export/CreateExportModal'
import DeploymentList from './export/DeploymentList'
import CreateDeploymentModal from './export/CreateDeploymentModal'
import InferenceTestPanel from './export/InferenceTestPanel'
import { useTrainingMonitor } from '@/hooks/useTrainingMonitor'

interface TrainingJob {
  id: number
  project_id: number | null
  project_name: string | null
  framework: string
  model_name: string
  task_type: string
  num_classes: number | null
  dataset_format: string
  dataset_path?: string
  dataset_id?: string
  output_dir?: string
  epochs: number
  batch_size: number
  learning_rate: number
  advanced_config: any | null
  status: string
  final_accuracy: number | null
  primary_metric: string | null
  primary_metric_mode: string | null
  // Phase 12: Temporal Workflow & Dataset Snapshot metadata
  workflow_id?: string | null
  dataset_snapshot_id?: string | null
}

interface TrainingMetric {
  id: number
  job_id: number
  epoch: number
  step?: number
  loss?: number
  accuracy?: number
  learning_rate?: number
  checkpoint_path?: string
  extra_metrics?: {
    train_loss?: number
    train_accuracy?: number
    val_loss?: number
    val_accuracy?: number
    [key: string]: any
  }
  created_at: string
}

interface TrainingLog {
  id: number
  log_type: string
  content: string
  created_at: string
}

interface TrainingPanelProps {
  trainingJobId: number | null
  onNavigateToExperiments?: () => void
}

export default function TrainingPanel({ trainingJobId, onNavigateToExperiments }: TrainingPanelProps) {
  const [job, setJob] = useState<TrainingJob | null>(null)
  const [metrics, setMetrics] = useState<TrainingMetric[]>([])
  const [logs, setLogs] = useState<TrainingLog[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [resumeDialogMode, setResumeDialogMode] = useState<'start' | 'restart' | null>(null)
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>([])
  const [showMetricTip, setShowMetricTip] = useState(false)
  const [activeTab, setActiveTab] = useState<'metrics' | 'validation' | 'test_inference' | 'export_deploy' | 'config' | 'logs'>('metrics')
  const logsContainerRef = useRef<HTMLDivElement>(null)

  // Helper: Get auth headers (Phase 12: JWT required for all API calls)
  const getAuthHeaders = () => {
    const token = localStorage.getItem('access_token')
    return {
      'Content-Type': 'application/json',
      ...(token && { 'Authorization': `Bearer ${token}` })
    }
  }

  // Export & Deploy modals
  const [showCreateExportModal, setShowCreateExportModal] = useState(false)
  const [showCreateDeploymentModal, setShowCreateDeploymentModal] = useState(false)
  const [selectedExportJobId, setSelectedExportJobId] = useState<number | undefined>(undefined)
  const [testingDeployment, setTestingDeployment] = useState<{ id: number; apiKey: string; endpointUrl: string } | null>(null)
  const [exportRefreshKey, setExportRefreshKey] = useState(0) // Incremented to trigger ExportJobList refresh
  const [metricsRefreshKey, setMetricsRefreshKey] = useState(0) // Incremented to trigger MLflowMetricsCharts refresh

  // Fetch functions as callbacks for reuse
  const fetchJob = useCallback(async () => {
    if (!trainingJobId) return
    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${trainingJobId}`,
        { headers: getAuthHeaders() }
      )
      if (response.ok) {
        const data = await response.json()
        setJob(data)
      }
    } catch (error) {
      console.error('Error fetching training job:', error)
    }
  }, [trainingJobId])

  const fetchMetrics = useCallback(async () => {
    if (!trainingJobId) return
    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${trainingJobId}/metrics`
      )
      if (response.ok) {
        const data = await response.json()
        setMetrics(data)
      }
    } catch (error) {
      console.error('Error fetching metrics:', error)
    }
  }, [trainingJobId])

  const fetchLogs = useCallback(async () => {
    if (!trainingJobId) return
    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${trainingJobId}/logs?limit=1000`
      )
      if (response.ok) {
        const data = await response.json()
        setLogs(data)
      }
    } catch (error) {
      console.error('Error fetching logs:', error)
    }
  }, [trainingJobId])

  // WebSocket for real-time updates (replaces polling)
  useTrainingMonitor({
    jobId: trainingJobId,
    autoConnect: !!trainingJobId,
    onStatusChange: (jobId, oldStatus, newStatus) => {
      console.log(`[WebSocket] Job ${jobId} status changed: ${oldStatus} -> ${newStatus}`)
      fetchJob() // Refetch job details on status change
    },
    onMetrics: (jobId, metrics) => {
      console.log(`[WebSocket] Job ${jobId} new metrics received`)
      fetchMetrics() // Refetch all metrics
      setMetricsRefreshKey(prev => prev + 1) // Trigger MLflowMetricsCharts refresh
    },
    onLog: (jobId, log) => {
      console.log(`[WebSocket] Job ${jobId} new log received:`, log)
      // Refetch all logs (similar to metrics pattern)
      fetchLogs()
    },
    onExportStatusChange: (jobId, exportJobId, oldStatus, newStatus) => {
      console.log(`[WebSocket] Export job ${exportJobId} status changed: ${oldStatus} -> ${newStatus}`)
      setExportRefreshKey(prev => prev + 1) // Trigger ExportJobList refresh
    },
    onConnect: () => {
      console.log('[WebSocket] Connected to training updates')
    },
    onDisconnect: () => {
      console.log('[WebSocket] Disconnected from training updates')
    }
  })

  // Initial data fetch (no polling - WebSocket handles updates)
  useEffect(() => {
    if (!trainingJobId) return
    fetchJob()
  }, [trainingJobId, fetchJob])

  // Initial metrics fetch (WebSocket handles updates)
  useEffect(() => {
    if (!trainingJobId) return
    fetchMetrics()
  }, [trainingJobId, fetchMetrics])

  // Refetch metrics when switching to metrics tab
  useEffect(() => {
    if (activeTab === 'metrics' && trainingJobId) {
      fetchMetrics()
    }
  }, [activeTab, trainingJobId, fetchMetrics])

  // Initial logs fetch (WebSocket handles updates)
  useEffect(() => {
    if (!trainingJobId) return
    fetchLogs()
  }, [trainingJobId, fetchLogs])

  // Auto-scroll logs to bottom when updated
  useEffect(() => {
    if (logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight
    }
  }, [logs])

  const startTraining = async () => {
    if (!trainingJobId) return

    // Check if there are any checkpoints
    const latestCheckpoint = metrics
      .slice()
      .reverse()
      .find((m) => m.checkpoint_path)

    if (latestCheckpoint) {
      // Show resume dialog if checkpoints exist
      setResumeDialogMode('start')
    } else {
      // Start from scratch if no checkpoints
      await startTrainingFromScratch()
    }
  }

  const startTrainingFromScratch = async () => {
    if (!trainingJobId) return

    setIsLoading(true)
    setResumeDialogMode(null)
    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${trainingJobId}/start`,
        {
          method: 'POST',
          headers: getAuthHeaders()
        }
      )

      if (response.ok) {
        const data = await response.json()
        setJob(data)
      } else {
        alert('학습 시작 실패')
      }
    } catch (error) {
      console.error('Error starting training:', error)
      alert('학습 시작 실패')
    } finally {
      setIsLoading(false)
    }
  }

  const startTrainingWithResume = async () => {
    if (!trainingJobId) return

    // Find the latest checkpoint
    const latestCheckpoint = metrics
      .slice()
      .reverse()
      .find((m) => m.checkpoint_path)

    if (!latestCheckpoint?.checkpoint_path) {
      alert('체크포인트를 찾을 수 없습니다')
      return
    }

    setIsLoading(true)
    setResumeDialogMode(null)
    try {
      const url = new URL(
        `${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${trainingJobId}/start`
      )
      url.searchParams.append('checkpoint_path', latestCheckpoint.checkpoint_path)
      url.searchParams.append('resume', 'true')

      const response = await fetch(url.toString(), { method: 'POST', headers: getAuthHeaders() })

      if (response.ok) {
        const data = await response.json()
        setJob(data)
      } else {
        alert('학습 재개 실패')
      }
    } catch (error) {
      console.error('Error resuming training:', error)
      alert('학습 재개 실패')
    } finally {
      setIsLoading(false)
    }
  }

  const cancelTraining = async () => {
    if (!trainingJobId) return

    setIsLoading(true)
    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${trainingJobId}/cancel`,
        {
          method: 'POST',
          headers: getAuthHeaders()
        }
      )

      if (response.ok) {
        const data = await response.json()
        setJob(data)
      } else {
        alert('학습 중단 실패')
      }
    } catch (error) {
      console.error('Error canceling training:', error)
      alert('학습 중단 실패')
    } finally {
      setIsLoading(false)
    }
  }

  const restartTraining = async () => {
    if (!trainingJobId) return

    // Check if there are any checkpoints
    const latestCheckpoint = metrics
      .slice()
      .reverse()
      .find((m) => m.checkpoint_path)

    if (latestCheckpoint) {
      // Show resume dialog if checkpoints exist
      setResumeDialogMode('restart')
    } else {
      // No checkpoints - just restart from scratch
      await restartTrainingFromScratch()
    }
  }

  const restartTrainingFromScratch = async () => {
    if (!trainingJobId) return

    setIsLoading(true)
    setResumeDialogMode(null)
    try {
      // First reset the job
      const restartResponse = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${trainingJobId}/restart`,
        { method: 'POST', headers: getAuthHeaders() }
      )

      if (!restartResponse.ok) {
        alert('학습 재시작 실패')
        return
      }

      const restartData = await restartResponse.json()
      setJob(restartData)
      setMetrics([])
      setLogs([])

      // Then start training
      const startResponse = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${trainingJobId}/start`,
        { method: 'POST', headers: getAuthHeaders() }
      )

      if (startResponse.ok) {
        const startData = await startResponse.json()
        setJob(startData)
      } else {
        alert('학습 시작 실패')
      }
    } catch (error) {
      console.error('Error restarting training:', error)
      alert('학습 재시작 실패')
    } finally {
      setIsLoading(false)
    }
  }

  const restartTrainingWithResume = async () => {
    if (!trainingJobId) return

    // Find the latest checkpoint
    const latestCheckpoint = metrics
      .slice()
      .reverse()
      .find((m) => m.checkpoint_path)

    if (!latestCheckpoint?.checkpoint_path) {
      alert('체크포인트를 찾을 수 없습니다')
      return
    }

    setIsLoading(true)
    setResumeDialogMode(null)
    try {
      // First reset the job to pending state
      const restartResponse = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${trainingJobId}/restart`,
        { method: 'POST', headers: getAuthHeaders() }
      )

      if (!restartResponse.ok) {
        alert('학습 재시작 실패')
        return
      }

      const restartData = await restartResponse.json()
      setJob(restartData)

      // Don't clear metrics/logs when resuming - we need them!
      // setMetrics([])
      // setLogs([])

      // Then start training with checkpoint
      const url = new URL(
        `${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${trainingJobId}/start`
      )
      url.searchParams.append('checkpoint_path', latestCheckpoint.checkpoint_path)
      url.searchParams.append('resume', 'true')

      const startResponse = await fetch(url.toString(), { method: 'POST', headers: getAuthHeaders() })

      if (startResponse.ok) {
        const startData = await startResponse.json()
        setJob(startData)
      } else {
        alert('학습 재개 실패')
      }
    } catch (error) {
      console.error('Error resuming training:', error)
      alert('학습 재개 실패')
    } finally {
      setIsLoading(false)
    }
  }

  // Calculate current epoch and iteration progress
  const getCurrentProgress = () => {
    if (!job || metrics.length === 0) {
      return { currentEpoch: 0, totalEpochs: job?.epochs || 0, currentIteration: 0, totalIterations: 0 }
    }

    // Get latest metric
    const latestMetric = metrics[metrics.length - 1]
    const currentEpoch = latestMetric?.epoch || 0
    const totalEpochs = job?.epochs || 0

    // Get iteration info from extra_metrics if available
    const currentIteration = latestMetric?.extra_metrics?.batch || 0
    const totalIterations = latestMetric?.extra_metrics?.total_batches || 0

    return { currentEpoch, totalEpochs, currentIteration, totalIterations }
  }

  const progress = getCurrentProgress()

  // Calculate progress percentage safely
  const epochProgressPercent = progress.totalEpochs > 0
    ? Math.round((progress.currentEpoch / progress.totalEpochs) * 100)
    : 0

  const getStatusBadge = (status: string) => {
    const styles = {
      pending: 'bg-gray-100 text-gray-800',
      running: 'bg-emerald-100 text-emerald-800',
      completed: 'bg-violet-100 text-violet-800',
      failed: 'bg-red-100 text-red-800',
      cancelled: 'bg-amber-100 text-amber-800',
    }

    return (
      <span
        className={cn(
          'px-2.5 py-1 rounded-md text-xs font-semibold',
          styles[status as keyof typeof styles] || styles.pending
        )}
      >
        {status.toUpperCase()}
      </span>
    )
  }

  if (!job) {
    return (
      <div className="h-full flex items-center justify-center bg-gray-50">
        <div className="text-center text-gray-500">
          <AlertCircle className="w-12 h-12 mx-auto mb-4 text-gray-400" />
          <p className="text-sm">학습 작업이 없습니다</p>
          <p className="text-xs mt-2">채팅에서 학습 설정을 완료하세요</p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-gray-50">
      {/* Header */}
      <div className="p-6 bg-white border-b border-gray-200">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-gray-600 mb-3">
          <button
            onClick={onNavigateToExperiments}
            className="hover:text-violet-600 transition-colors"
          >
            {job.project_name || '프로젝트'}
          </button>
          <ChevronRight className="w-4 h-4" />
          <button
            onClick={onNavigateToExperiments}
            className="hover:text-violet-600 transition-colors"
          >
            실험
          </button>
          <ChevronRight className="w-4 h-4" />
          <span className="text-gray-900 font-medium">학습 #{job.id}</span>
        </div>

        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <button
              onClick={onNavigateToExperiments}
              className={cn(
                'p-2 rounded-lg',
                'text-gray-600 hover:text-violet-600',
                'hover:bg-gray-100',
                'transition-colors'
              )}
              title="실험 목록으로 돌아가기"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">
                {formatTrainingJobTitle(job.framework, job.model_name, job.task_type)}
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">학습 진행 상황</p>
            </div>
          </div>
          {getStatusBadge(job.status)}
        </div>

        {/* Action Buttons and Progress */}
        <div className="space-y-3">
          {/* Buttons and Epoch Progress in one row */}
          <div className="flex items-center gap-4">
            {/* Action Buttons */}
            <div className="flex gap-2">
              {job.status === 'pending' && (
                <button
                  onClick={startTraining}
                  disabled={isLoading}
                  className={cn(
                    'px-4 py-2.5',
                    'bg-violet-600 hover:bg-violet-700',
                    'text-white font-semibold',
                    'rounded-lg shadow-md',
                    'transition-all duration-200',
                    'disabled:opacity-40',
                    'flex items-center gap-2'
                  )}
                >
                  <Play className="w-4 h-4" />
                  학습 시작
                </button>
              )}

              {job.status === 'running' && (
                <button
                  onClick={cancelTraining}
                  disabled={isLoading}
                  className={cn(
                    'px-4 py-2.5',
                    'bg-red-600 hover:bg-red-700',
                    'text-white font-semibold',
                    'rounded-lg',
                    'transition-all duration-200',
                    'disabled:opacity-40',
                    'flex items-center gap-2'
                  )}
                >
                  <Square className="w-4 h-4 animate-pulse" />
                  중단
                </button>
              )}

              {(job.status === 'completed' || job.status === 'cancelled' || job.status === 'failed') && (
                <button
                  onClick={restartTraining}
                  disabled={isLoading}
                  className={cn(
                    'px-4 py-2.5',
                    'bg-violet-600 hover:bg-violet-700',
                    'text-white font-semibold',
                    'rounded-lg shadow-md',
                    'transition-all duration-200',
                    'disabled:opacity-40',
                    'flex items-center gap-2'
                  )}
                >
                  <Play className="w-4 h-4" />
                  재학습
                </button>
              )}
            </div>

            {/* Epoch Progress - Show from epoch 0 */}
            {job.status !== 'pending' && (
              <div className="flex-1">
                <div className="flex justify-between text-xs text-gray-600 mb-1">
                  <span className="font-medium">Epoch {progress.currentEpoch} / {progress.totalEpochs}</span>
                  <span className="text-gray-500">
                    {epochProgressPercent}%
                  </span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2.5 overflow-hidden">
                  <div
                    className="h-2.5 rounded-full transition-all duration-300 bg-gradient-to-r from-violet-600 via-fuchsia-500 to-purple-600 animate-gradient-x"
                    style={{ width: `${Math.max(epochProgressPercent, job.status === 'running' ? 2 : 0)}%` }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Iteration Progress - Show only when training is running */}
          {job.status === 'running' && progress.totalIterations > 0 && (
            <div>
              <div className="flex justify-between text-xs text-gray-600 mb-1">
                <span>Iteration Progress (Current Epoch)</span>
                <span>{progress.currentIteration} / {progress.totalIterations}</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2.5">
                <div
                  className="bg-emerald-500 h-2.5 rounded-full transition-all duration-300"
                  style={{ width: `${(progress.currentIteration / progress.totalIterations) * 100}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </div>


      {/* Content Area */}
      <div className="flex-1 overflow-y-auto">
        {/* Tabs - Always show */}
        <>
          {/* Tab Navigation - Sticky */}
          <div className="sticky top-0 z-20 border-b border-gray-200 bg-white px-6 shadow-sm">
            <div className="flex space-x-8">
                <button
                  onClick={() => setActiveTab('metrics')}
                  className={cn(
                    'px-1 py-4 text-sm font-medium border-b-2 transition-colors',
                    activeTab === 'metrics'
                      ? 'border-violet-600 text-violet-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  )}
                >
                  학습 메트릭
                </button>
                <button
                  onClick={() => setActiveTab('validation')}
                  className={cn(
                    'px-1 py-4 text-sm font-medium border-b-2 transition-colors',
                    activeTab === 'validation'
                      ? 'border-violet-600 text-violet-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  )}
                >
                  검증 메트릭
                </button>
                <button
                  onClick={() => setActiveTab('test_inference')}
                  className={cn(
                    'px-1 py-4 text-sm font-medium border-b-2 transition-colors',
                    activeTab === 'test_inference'
                      ? 'border-violet-600 text-violet-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  )}
                >
                  테스트/추론
                </button>
                <button
                  onClick={() => setActiveTab('export_deploy')}
                  className={cn(
                    'px-1 py-4 text-sm font-medium border-b-2 transition-colors',
                    activeTab === 'export_deploy'
                      ? 'border-violet-600 text-violet-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  )}
                >
                  📦 Export & Deploy
                </button>
                <button
                  onClick={() => setActiveTab('config')}
                  className={cn(
                    'px-1 py-4 text-sm font-medium border-b-2 transition-colors',
                    activeTab === 'config'
                      ? 'border-violet-600 text-violet-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  )}
                >
                  학습 설정
                </button>
                <button
                  onClick={() => setActiveTab('logs')}
                  className={cn(
                    'px-1 py-4 text-sm font-medium border-b-2 transition-colors relative',
                    activeTab === 'logs'
                      ? 'border-violet-600 text-violet-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  )}
                >
                  로그
                  {logs.length > 0 && (
                    <span className="ml-2 px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full">
                      {logs.length}
                    </span>
                  )}
                </button>
              </div>
            </div>

            {/* Tab Content */}
            <div className="p-6 space-y-6">
              {/* Metrics Tab */}
              {activeTab === 'metrics' && (
                <>
            {/* Metrics Charts */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-gray-900">
                    학습 메트릭 차트
                  </h3>
                  <div className="relative">
                    <button
                      onClick={() => setShowMetricTip(!showMetricTip)}
                      className="p-1 rounded-full hover:bg-gray-100 transition-colors"
                      title="도움말"
                    >
                      <HelpCircle className="w-4 h-4 text-gray-500" />
                    </button>
                    {showMetricTip && (
                      <>
                        {/* Backdrop */}
                        <div
                          className="fixed inset-0 z-40"
                          onClick={() => setShowMetricTip(false)}
                        />
                        {/* Tooltip */}
                        <div className="absolute left-0 top-full mt-2 w-80 p-3 bg-white border border-gray-200 rounded-lg shadow-lg z-50 animate-scale-in">
                          <div className="flex items-start gap-2">
                            <div className="flex-shrink-0 mt-0.5">
                              <div className="w-6 h-6 bg-blue-50 rounded-full flex items-center justify-center">
                                <span className="text-sm">💡</span>
                              </div>
                            </div>
                            <div className="flex-1">
                              <h4 className="text-sm font-semibold text-gray-900 mb-1">메트릭 차트 사용법</h4>
                              <p className="text-xs text-gray-600">
                                아래 메트릭 테이블의 컬럼 헤더를 클릭하면 해당 메트릭 차트가 추가됩니다.
                                Primary Metric은 자동으로 표시되며, 필요한 메트릭을 추가로 선택할 수 있습니다.
                              </p>
                            </div>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <a
                    href="http://localhost:3001"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-orange-600 hover:text-orange-700 hover:underline flex items-center gap-1"
                  >
                    <ExternalLink className="w-3 h-3" />
                    Grafana
                  </a>
                  <a
                    href={`${process.env.NEXT_PUBLIC_CLEARML_WEB_URL || 'http://localhost:8080'}/projects/*/experiments/${job.clearml_task_id || ''}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-purple-600 hover:text-purple-700 hover:underline flex items-center gap-1"
                    title={job.clearml_task_id ? `Open ClearML Task: ${job.clearml_task_id}` : 'ClearML task not yet created'}
                  >
                    <ExternalLink className="w-3 h-3" />
                    ClearML
                  </a>
                </div>
              </div>
              {/* MLflowMetricsCharts removed - migrated to ClearML */}
            </div>

            {/* Metrics Table - Hide when pending */}
            {job.status !== 'pending' && (
              <div>
                <DatabaseMetricsTable
                  jobId={job.id}
                  metrics={metrics}
                  selectedMetrics={selectedMetrics}
                  jobStatus={job.status}
                  onMetricToggle={(metricKey) => {
                    setSelectedMetrics(prev =>
                      prev.includes(metricKey)
                        ? prev.filter(m => m !== metricKey)
                        : [...prev, metricKey]
                    )
                  }}
                  onCheckpointSelect={(checkpointPath, epoch) => {
                    console.log('Selected checkpoint:', checkpointPath, 'epoch:', epoch)
                    // Will implement resume dialog in next step
                  }}
                />
              </div>
            )}

            {/* Final Metric */}
            {job.final_accuracy !== null && (
              <div className="p-4 bg-violet-50 rounded-lg border border-violet-200">
                <p className="text-sm font-semibold text-violet-900">
                  최종 {job.primary_metric || 'accuracy'}: {(job.final_accuracy * 100).toFixed(2)}%
                </p>
              </div>
            )}
                </>
              )}

              {/* Validation Tab */}
              {activeTab === 'validation' && (
                <>
                  {job.status === 'pending' || metrics.length > 0 ? (
                    <ValidationDashboard
                      jobId={job.id}
                      currentEpoch={metrics[metrics.length - 1]?.epoch}
                      jobStatus={job.status}
                    />
                  ) : (
                    <div className="p-6 bg-white rounded-lg border border-gray-200 flex flex-col items-center justify-center">
                      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-400 mb-3"></div>
                      <p className="text-xs text-gray-400">
                        1에폭 완료 후 표시됩니다.
                      </p>
                    </div>
                  )}
                </>
              )}

              {/* Test/Inference Tab */}
              {activeTab === 'test_inference' && (
                <TestInferencePanel jobId={job.id} />
              )}

              {/* Config Tab */}
              {activeTab === 'config' && (
                <div className="bg-white rounded-lg border border-gray-200 p-6 space-y-6">
                  <h3 className="text-lg font-semibold text-gray-900">학습 설정</h3>

                  {/* Basic Config */}
                  <div>
                    <h4 className="text-sm font-semibold text-gray-700 mb-3">기본 설정</h4>
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <span className="text-gray-600">프레임워크:</span>
                        <span className="ml-2 font-medium text-gray-900">{job.framework}</span>
                      </div>
                      <div>
                        <span className="text-gray-600">모델:</span>
                        <span className="ml-2 font-medium text-gray-900">
                          {getModelDisplayNameSync(job.framework, job.model_name)}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-600">작업 유형:</span>
                        <span className="ml-2 font-medium text-gray-900">
                          {getTaskDisplayName(job.task_type)}
                        </span>
                      </div>
                      {job.num_classes && (
                        <div>
                          <span className="text-gray-600">클래스 수:</span>
                          <span className="ml-2 font-medium text-gray-900">{job.num_classes}개</span>
                        </div>
                      )}
                      <div>
                        <span className="text-gray-600">데이터셋 형식:</span>
                        <span className="ml-2 font-medium text-gray-900">{job.dataset_format}</span>
                      </div>
                      <div>
                        <span className="text-gray-600">에포크:</span>
                        <span className="ml-2 font-medium text-gray-900">{job.epochs}</span>
                      </div>
                      <div>
                        <span className="text-gray-600">배치 크기:</span>
                        <span className="ml-2 font-medium text-gray-900">{job.batch_size}</span>
                      </div>
                      <div>
                        <span className="text-gray-600">학습률:</span>
                        <span className="ml-2 font-medium text-gray-900">{job.learning_rate}</span>
                      </div>
                      {job.primary_metric && (
                        <div>
                          <span className="text-gray-600">Primary Metric:</span>
                          <span className="ml-2 font-medium text-gray-900">{job.primary_metric}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Advanced Config */}
                  {job.advanced_config && Object.keys(job.advanced_config).length > 0 && (
                    <div>
                      <h4 className="text-sm font-semibold text-gray-700 mb-3">고급 설정</h4>
                      <div className="space-y-3">
                        {/* Optimizer */}
                        {job.advanced_config.optimizer?.type && (
                          <div className="bg-gray-50 rounded-lg p-3">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-xs font-semibold text-gray-700">Optimizer</span>
                              <span className="px-2 py-0.5 bg-violet-100 text-violet-700 rounded text-xs font-medium">
                                {job.advanced_config.optimizer?.type.toUpperCase()}
                              </span>
                            </div>
                            <div className="grid grid-cols-2 gap-2 text-xs text-gray-600">
                              {job.advanced_config.optimizer.weight_decay !== undefined && (
                                <div>Weight Decay: <span className="font-medium">{job.advanced_config.optimizer.weight_decay}</span></div>
                              )}
                              {job.advanced_config.optimizer.momentum !== undefined && (
                                <div>Momentum: <span className="font-medium">{job.advanced_config.optimizer.momentum}</span></div>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Scheduler */}
                        {job.advanced_config.scheduler?.type && job.advanced_config.scheduler?.type !== 'none' && (
                          <div className="bg-gray-50 rounded-lg p-3">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-xs font-semibold text-gray-700">LR Scheduler</span>
                              <span className="px-2 py-0.5 bg-emerald-100 text-emerald-700 rounded text-xs font-medium">
                                {job.advanced_config.scheduler?.type.toUpperCase()}
                              </span>
                            </div>
                            <div className="text-xs text-gray-600">
                              {job.advanced_config.scheduler.warmup_epochs !== undefined && (
                                <div>Warmup: {job.advanced_config.scheduler.warmup_epochs} epochs</div>
                              )}
                            </div>
                          </div>
                        )}
                        {job.advanced_config.cos_lr !== undefined && (
                          <div className="bg-gray-50 rounded-lg p-3">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-xs font-semibold text-gray-700">LR Scheduler</span>
                              <span className="px-2 py-0.5 bg-emerald-100 text-emerald-700 rounded text-xs font-medium">
                                {job.advanced_config.cos_lr ? 'COSINE' : 'CONSTANT'}
                              </span>
                            </div>
                            {job.advanced_config.scheduler?.warmup_epochs !== undefined && (
                              <div className="text-xs text-gray-600">
                                Warmup: {job.advanced_config.scheduler.warmup_epochs} epochs
                              </div>
                            )}
                          </div>
                        )}

                        {/* Augmentation - Classification (timm) */}
                        {(job.advanced_config.augmentation?.enabled || job.advanced_config.augmentation?.random_flip || job.advanced_config.augmentation?.mixup || job.advanced_config.augmentation?.cutmix) && (
                          <div className="bg-gray-50 rounded-lg p-3">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-xs font-semibold text-gray-700">Data Augmentation</span>
                              <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs font-medium">
                                {job.advanced_config.augmentation?.enabled ? '활성화' : '부분 활성화'}
                              </span>
                            </div>
                            <div className="flex gap-1 flex-wrap">
                              {job.advanced_config.augmentation?.random_flip && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">Flip</span>
                              )}
                              {job.advanced_config.augmentation?.random_rotation && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">Rotation</span>
                              )}
                              {job.advanced_config.augmentation?.color_jitter && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">Color Jitter</span>
                              )}
                              {job.advanced_config.augmentation?.mixup && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">Mixup</span>
                              )}
                              {job.advanced_config.augmentation?.cutmix && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">CutMix</span>
                              )}
                              {job.advanced_config.augmentation?.random_erasing && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">Random Erasing</span>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Augmentation - Detection (YOLO) */}
                        {(job.advanced_config.mosaic !== undefined || job.advanced_config.fliplr !== undefined) && (
                          <div className="bg-gray-50 rounded-lg p-3">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-xs font-semibold text-gray-700">Data Augmentation (YOLO)</span>
                              <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs font-medium">
                                활성화
                              </span>
                            </div>
                            <div className="flex gap-1 flex-wrap">
                              {job.advanced_config.mosaic > 0 && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">
                                  Mosaic ({(job.advanced_config.mosaic * 100).toFixed(0)}%)
                                </span>
                              )}
                              {job.advanced_config.augmentation?.mixup > 0 && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">
                                  Mixup ({(job.advanced_config.augmentation?.mixup * 100).toFixed(0)}%)
                                </span>
                              )}
                              {job.advanced_config.copy_paste > 0 && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">
                                  Copy-Paste ({(job.advanced_config.copy_paste * 100).toFixed(0)}%)
                                </span>
                              )}
                              {job.advanced_config.fliplr > 0 && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">
                                  Flip ({(job.advanced_config.fliplr * 100).toFixed(0)}%)
                                </span>
                              )}
                              {job.advanced_config.degrees > 0 && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">
                                  Rotation (±{job.advanced_config.degrees}°)
                                </span>
                              )}
                              {(job.advanced_config.hsv_h > 0 || job.advanced_config.hsv_s > 0 || job.advanced_config.hsv_v > 0) && (
                                <span className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">HSV Aug</span>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Other Settings */}
                        {(job.advanced_config.mixed_precision || job.advanced_config.gradient_clip_value || job.advanced_config.amp !== undefined) && (
                          <div className="bg-gray-50 rounded-lg p-3">
                            <span className="text-xs font-semibold text-gray-700 block mb-2">기타</span>
                            <div className="flex gap-2 flex-wrap text-xs">
                              {(job.advanced_config.mixed_precision || job.advanced_config.amp) && (
                                <span className="px-2 py-0.5 bg-amber-100 text-amber-700 rounded">Mixed Precision</span>
                              )}
                              {job.advanced_config.gradient_clip_value && (
                                <span className="px-2 py-0.5 bg-amber-100 text-amber-700 rounded">
                                  Gradient Clipping ({job.advanced_config.gradient_clip_value})
                                </span>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Dataset Path */}
                  <div>
                    <h4 className="text-sm font-semibold text-gray-700 mb-3">데이터셋</h4>
                    <div className="space-y-3 text-sm">
                      {job.dataset_id && (
                        <div>
                          <span className="text-gray-600">데이터셋 ID:</span>
                          <p className="mt-1 font-mono text-xs text-gray-900 bg-gray-50 p-2 rounded border border-gray-200 break-all">
                            {job.dataset_id}
                          </p>
                        </div>
                      )}
                      {job.dataset_path && (
                        <div>
                          <span className="text-gray-600">경로:</span>
                          <p className="mt-1 font-mono text-xs text-gray-900 bg-gray-50 p-2 rounded border border-gray-200 break-all">
                            {job.dataset_path}
                          </p>
                        </div>
                      )}
                      {job.dataset_snapshot_id && (
                        <div>
                          <span className="text-gray-600 flex items-center gap-1">
                            Snapshot ID:
                            <span className="text-xs text-green-600 bg-green-50 px-1.5 py-0.5 rounded">Phase 12</span>
                          </span>
                          <p className="mt-1 font-mono text-xs text-gray-900 bg-green-50 p-2 rounded border border-green-200 break-all">
                            {job.dataset_snapshot_id}
                          </p>
                          <p className="mt-1 text-xs text-gray-500">
                            재현 가능한 메타데이터 전용 스냅샷 (~500 bytes)
                          </p>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Workflow Orchestration */}
                  {job.workflow_id && (
                    <div>
                      <h4 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                        워크플로우 오케스트레이션
                        <span className="text-xs text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">Phase 12</span>
                      </h4>
                      <div className="text-sm">
                        <span className="text-gray-600">Temporal Workflow ID:</span>
                        <p className="mt-1 font-mono text-xs text-gray-900 bg-blue-50 p-2 rounded border border-blue-200 break-all">
                          {job.workflow_id}
                        </p>
                        <p className="mt-2 text-xs text-gray-500">
                          이 작업은 Temporal Workflow로 오케스트레이션되어 장기 실행 작업의 안정성과 재시작 기능을 제공합니다.
                        </p>
                      </div>
                    </div>
                  )}

                  {/* Output Directory */}
                  <div>
                    <h4 className="text-sm font-semibold text-gray-700 mb-3">출력</h4>
                    <div className="text-sm">
                      <span className="text-gray-600">출력 디렉토리:</span>
                      <p className="mt-1 font-mono text-xs text-gray-900 bg-gray-50 p-2 rounded border border-gray-200 break-all">
                        {job.output_dir || 'N/A'}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Logs Tab */}
              {activeTab === 'logs' && (
                <div className="bg-white rounded-lg border border-gray-200 p-4">
                  {logs.length === 0 ? (
                    <p className="text-sm text-gray-500">학습을 시작하면 로그가 표시됩니다</p>
                  ) : (
                    <div
                      ref={logsContainerRef}
                      className="bg-gray-900 rounded-lg p-4 font-mono text-xs overflow-auto"
                      style={{ maxHeight: '600px' }}
                    >
                      {logs.map((log) => {
                        // Extract log level from content (e.g., "[INFO]", "[ERROR]")
                        const levelMatch = log.content.match(/^\[(\w+)\]/)
                        const level = levelMatch ? levelMatch[1] : null

                        return (
                          <div
                            key={log.id}
                            className={cn(
                              'mb-1 whitespace-pre-wrap break-words',
                              level === 'ERROR' ? 'text-red-400' :
                              level === 'WARNING' ? 'text-yellow-400' :
                              level === 'INFO' ? 'text-blue-400' :
                              level === 'DEBUG' ? 'text-gray-400' :
                              log.log_type === 'stderr' ? 'text-red-400' : 'text-green-400'
                            )}
                          >
                            <span className="text-gray-500 mr-2">
                              {new Date(log.created_at).toLocaleTimeString()}
                            </span>
                            {log.content}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Export & Deploy Tab */}
              {activeTab === 'export_deploy' && (
                <div className="space-y-6">
                  {/* Export Jobs Section */}
                  <div>
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-lg font-semibold text-gray-900">Export Jobs</h3>
                      <button
                        className="px-4 py-2 bg-violet-600 text-white rounded-lg hover:bg-violet-700 transition-colors text-sm font-medium"
                        onClick={() => setShowCreateExportModal(true)}
                      >
                        + New Export
                      </button>
                    </div>

                    <ExportJobList
                      trainingJobId={trainingJobId!}
                      onCreateExport={() => setShowCreateExportModal(true)}
                      onDeploy={(exportJobId) => {
                        setSelectedExportJobId(exportJobId)
                        setShowCreateDeploymentModal(true)
                      }}
                      refreshKey={exportRefreshKey}
                    />
                  </div>

                  {/* Deployments Section */}
                  <div>
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-lg font-semibold text-gray-900">Deployments</h3>
                      <button
                        className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors text-sm font-medium"
                        onClick={() => {
                          setSelectedExportJobId(undefined)
                          setShowCreateDeploymentModal(true)
                        }}
                      >
                        + New Deployment
                      </button>
                    </div>

                    <DeploymentList
                      trainingJobId={trainingJobId!}
                      onCreateDeployment={() => {
                        setSelectedExportJobId(undefined)
                        setShowCreateDeploymentModal(true)
                      }}
                      onTestInference={(deploymentId) => {
                        // Fetch deployment details to get API key and endpoint
                        fetch(`${process.env.NEXT_PUBLIC_API_URL}/deployments/${deploymentId}`, {
                          headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` }
                        })
                          .then(res => res.json())
                          .then(deployment => {
                            setTestingDeployment({
                              id: deploymentId,
                              apiKey: deployment.deployment_config.api_key || '',
                              endpointUrl: deployment.deployment_config.endpoint_url || ''
                            })
                          })
                          .catch(err => console.error('Failed to fetch deployment:', err))
                      }}
                    />
                  </div>

                  {/* Inference Test Panel */}
                  {testingDeployment && (
                    <div>
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-semibold text-gray-900">Test Inference</h3>
                        <button
                          className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
                          onClick={() => setTestingDeployment(null)}
                        >
                          Close
                        </button>
                      </div>

                      <InferenceTestPanel
                        deploymentId={testingDeployment.id}
                        apiKey={testingDeployment.apiKey}
                        endpointUrl={testingDeployment.endpointUrl}
                        taskType={job?.task_type}
                      />
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
      </div>

      {/* Resume Dialog */}
      <ResumeDialog
        isOpen={resumeDialogMode !== null}
        onClose={() => setResumeDialogMode(null)}
        onStartFromScratch={
          resumeDialogMode === 'restart'
            ? restartTrainingFromScratch
            : startTrainingFromScratch
        }
        onResume={
          resumeDialogMode === 'restart'
            ? restartTrainingWithResume
            : startTrainingWithResume
        }
        latestCheckpointEpoch={
          metrics
            .slice()
            .reverse()
            .find((m) => m.checkpoint_path)?.epoch
        }
      />

      {/* Export & Deploy Modals */}
      {trainingJobId && (
        <>
          <CreateExportModal
            isOpen={showCreateExportModal}
            onClose={() => setShowCreateExportModal(false)}
            trainingJobId={trainingJobId}
            onSuccess={() => {
              setShowCreateExportModal(false)
              // Trigger refresh by re-rendering the tab
              setActiveTab('export_deploy')
            }}
          />

          <CreateDeploymentModal
            isOpen={showCreateDeploymentModal}
            onClose={() => {
              setShowCreateDeploymentModal(false)
              setSelectedExportJobId(undefined)
            }}
            trainingJobId={trainingJobId}
            onSuccess={() => {
              setShowCreateDeploymentModal(false)
              setSelectedExportJobId(undefined)
              // Trigger refresh by re-rendering the tab
              setActiveTab('export_deploy')
            }}
            selectedExportJobId={selectedExportJobId}
          />
        </>
      )}
    </div>
  )
}

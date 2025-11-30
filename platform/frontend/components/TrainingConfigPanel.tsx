'use client'

import { useState, useEffect } from 'react'
import { ArrowLeftIcon, ArrowRightIcon, CheckIcon, Settings } from 'lucide-react'
import { cn } from '@/lib/utils/cn'
import AdvancedConfigPanel from './training/AdvancedConfigPanel'
import ModelSelector from './training/ModelSelector'
import CustomPromptsModal from './training/CustomPromptsModal'
import { ModelInfo } from './training/ModelCard'

// Helper: Infer task type from dataset format
const getTaskTypeFromFormat = (format: string): string => {
  const taskTypeMap: Record<string, string> = {
    'imagefolder': '이미지 분류',
    'yolo': '객체 탐지',
    'coco': '객체 탐지',
  }
  return taskTypeMap[format?.toLowerCase()] || '알 수 없음'
}


interface TrainingConfig {
  framework?: string
  model_name?: string
  task_type?: string
  dataset_id?: string  // Phase 12: Labeler integration
  dataset_path?: string
  dataset_format?: string
  epochs?: number
  batch_size?: number
  learning_rate?: number
}

interface TrainingConfigPanelProps {
  projectId?: number | null
  initialConfig?: TrainingConfig | null
  onCancel: () => void
  onTrainingStarted: (jobId: number) => void
}

export default function TrainingConfigPanel({
  projectId,
  initialConfig,
  onCancel,
  onTrainingStarted,
}: TrainingConfigPanelProps) {
  const [step, setStep] = useState(1)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Step 1: Model & Task
  const [framework, setFramework] = useState(initialConfig?.framework || 'timm')
  const [modelName, setModelName] = useState(initialConfig?.model_name || '')
  const [taskType, setTaskType] = useState(initialConfig?.task_type || 'image_classification')
  const [selectedModel, setSelectedModel] = useState<ModelInfo | null>(null)
  const [customPrompts, setCustomPrompts] = useState<string[]>([])
  const [showPromptsModal, setShowPromptsModal] = useState(false)

  // Step 2: Dataset
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  const [selectedDataset, setSelectedDataset] = useState<any | null>(null)
  const [datasetPath, setDatasetPath] = useState(initialConfig?.dataset_path || '')
  const [datasetFormat, setDatasetFormat] = useState(initialConfig?.dataset_format || 'imagefolder')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [datasetInfo, setDatasetInfo] = useState<any | null>(null)
  const [analysisError, setAnalysisError] = useState<string | null>(null)

  // R2 Datasets (loaded from Backend API with authentication)
  const [availableDatasets, setAvailableDatasets] = useState<any[]>([])
  const [isLoadingDatasets, setIsLoadingDatasets] = useState(true)

  // Load available datasets from Backend API
  useEffect(() => {
    console.log('[TrainingConfigPanel] Component mounted, fetching datasets...')
    fetchAvailableDatasets()
  }, [])

  // Reload datasets when task_type changes (Phase 16.6: task-type-specific statistics)
  useEffect(() => {
    if (taskType) {
      console.log('[DATASETS] Task type changed to:', taskType, '- Reloading datasets...')
      fetchAvailableDatasets()
    }
  }, [taskType])

  // Load primary fields when framework changes
  useEffect(() => {
    if (framework) {
      fetchPrimaryFields(framework)
    }
  }, [framework])

  const fetchAvailableDatasets = async () => {
    console.log('[DATASETS] fetchAvailableDatasets() called')
    try {
      setIsLoadingDatasets(true)
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'
      const token = localStorage.getItem('access_token')

      console.log('[DATASETS] baseUrl:', baseUrl)
      console.log('[DATASETS] token exists:', !!token)
      console.log('[DATASETS] task_type:', taskType || 'not specified')

      if (!token) {
        console.error('[DATASETS] No access token found')
        alert('로그인 토큰이 없습니다. 다시 로그인해주세요.')
        setAvailableDatasets([])
        setIsLoadingDatasets(false)
        return
      }

      // Phase 16.6: Include task_type for task-specific statistics
      const params = new URLSearchParams({ labeled: 'true' })
      if (taskType) {
        params.append('task_type', taskType)
      }

      const apiUrl = `${baseUrl}/datasets/available?${params.toString()}`
      console.log('[DATASETS] Calling API:', apiUrl)

      const response = await fetch(apiUrl, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      })

      if (response.ok) {
        const datasets = await response.json()
        console.log('[DATASETS] Fetched datasets:', datasets)
        console.log('[DATASETS] Dataset count:', datasets.length)
        setAvailableDatasets(datasets)
      } else {
        console.error('[DATASETS] Failed to fetch datasets:', response.status, response.statusText)
        alert(`데이터셋 로드 실패: ${response.status} ${response.statusText}`)
        setAvailableDatasets([])
      }
    } catch (error) {
      console.error('[DATASETS] Error fetching datasets:', error)
      alert(`데이터셋 로드 에러: ${error instanceof Error ? error.message : 'Unknown error'}`)
      setAvailableDatasets([])
    } finally {
      setIsLoadingDatasets(false)
    }
  }

  const fetchPrimaryFields = async (fw: string) => {
    try {
      setLoadingPrimaryFields(true)
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'
      const response = await fetch(`${baseUrl}/training/config-schema?framework=${fw}`)

      if (response.ok) {
        const schema = await response.json()
        const primary = schema.fields.filter((f: any) => f.primary === true)
        setPrimaryFields(primary)

        // Initialize values with defaults
        const initialValues: Record<string, any> = {}
        primary.forEach((field: any) => {
          initialValues[field.name] = field.default
        })
        setPrimaryFieldsValues(initialValues)
      } else {
        console.error('Failed to fetch config schema:', response.statusText)
        setPrimaryFields([])
      }
    } catch (error) {
      console.error('Error fetching primary fields:', error)
      setPrimaryFields([])
    } finally {
      setLoadingPrimaryFields(false)
    }
  }

  // Step 3: Hyperparameters
  const [epochs, setEpochs] = useState(Number(initialConfig?.epochs) || 50)
  const [batchSize, setBatchSize] = useState(Number(initialConfig?.batch_size) || 32)

  // Debug batchSize changes
  useEffect(() => {
    console.log('[DEBUG] batchSize changed:', batchSize, typeof batchSize)
  }, [batchSize])

  // Primary fields from config schema (dynamic)
  const [primaryFields, setPrimaryFields] = useState<any[]>([])
  const [primaryFieldsValues, setPrimaryFieldsValues] = useState<Record<string, any>>({})
  const [loadingPrimaryFields, setLoadingPrimaryFields] = useState(false)

  // Primary Metric Selection
  const [primaryMetric, setPrimaryMetric] = useState<string>('')
  const [primaryMetricMode, setPrimaryMetricMode] = useState<'max' | 'min'>('max')

  // Advanced Configuration
  const [advancedConfig, setAdvancedConfig] = useState<any>(null)
  const [showAdvancedConfig, setShowAdvancedConfig] = useState(false)

  // All available frameworks with their supported tasks
  const allFrameworks = [
    { value: 'timm', label: 'timm (PyTorch Image Models)', supportedTasks: ['image_classification'] },
    { value: 'ultralytics', label: 'Ultralytics YOLO', supportedTasks: ['object_detection', 'instance_segmentation', 'pose_estimation', 'image_classification'] },
  ]

  // All available models with their framework and supported tasks
  const allModels = [
    // timm models
    { value: 'resnet18', label: 'ResNet-18', framework: 'timm', supportedTasks: ['image_classification'] },
    { value: 'resnet50', label: 'ResNet-50', framework: 'timm', supportedTasks: ['image_classification'] },
    { value: 'efficientnet_b0', label: 'EfficientNet-B0', framework: 'timm', supportedTasks: ['image_classification'] },
    // Ultralytics models
    {
      value: 'yolov8n',
      label: 'YOLOv8n (Nano)',
      framework: 'ultralytics',
      supportedTasks: ['object_detection', 'instance_segmentation', 'pose_estimation', 'image_classification']
    },
    {
      value: 'yolov8s',
      label: 'YOLOv8s (Small)',
      framework: 'ultralytics',
      supportedTasks: ['object_detection', 'instance_segmentation', 'pose_estimation', 'image_classification']
    },
    {
      value: 'yolov8m',
      label: 'YOLOv8m (Medium)',
      framework: 'ultralytics',
      supportedTasks: ['object_detection', 'instance_segmentation', 'pose_estimation', 'image_classification']
    },
  ]

  // Get frameworks that support the selected task type
  const getFrameworkOptions = () => {
    if (!taskType) return allFrameworks

    return allFrameworks.filter(fw =>
      fw.supportedTasks.includes(taskType)
    )
  }

  // Get models that support both the selected task type and framework
  const getModelOptions = () => {
    if (!taskType) return []

    let models = allModels.filter(model =>
      model.supportedTasks.includes(taskType)
    )

    if (framework) {
      models = models.filter(model => model.framework === framework)
    }

    return models
  }

  // All task types
  const allTaskTypes = [
    { value: 'image_classification', label: '이미지 분류 (Image Classification)' },
    { value: 'object_detection', label: '객체 탐지 (Object Detection)' },
    { value: 'pose_estimation', label: '포즈 추정 (Pose Estimation)' },
  ]

  // Dataset format options
  const datasetFormats = [
    { value: 'imagefolder', label: 'ImageFolder (PyTorch)' },
    { value: 'yolo', label: 'YOLO Format' },
    { value: 'coco', label: 'COCO Format' },
  ]

  // Primary metric options based on task type
  const getMetricOptions = () => {
    const metricsByTask: Record<string, Array<{ value: string; label: string; mode: 'max' | 'min'; description: string }>> = {
      'image_classification': [
        { value: 'accuracy', label: 'Accuracy (정확도)', mode: 'max', description: '전체 예측의 정확도' },
        { value: 'loss', label: 'Loss (손실)', mode: 'min', description: '학습 손실 값' },
        { value: 'val_accuracy', label: 'Validation Accuracy', mode: 'max', description: '검증 데이터 정확도' },
        { value: 'val_loss', label: 'Validation Loss', mode: 'min', description: '검증 손실 값' },
      ],
      // Support both 'detection' (from DB) and 'object_detection' (full name)
      'detection': [
        { value: 'mAP50', label: 'mAP@0.5 (평균 정밀도)', mode: 'max', description: 'IoU 0.5 기준 평균 정밀도' },
        { value: 'mAP50-95', label: 'mAP@0.5:0.95', mode: 'max', description: 'COCO 표준 mAP' },
        { value: 'precision', label: 'Precision (정밀도)', mode: 'max', description: '탐지 정밀도' },
        { value: 'recall', label: 'Recall (재현율)', mode: 'max', description: '탐지 재현율' },
        { value: 'loss', label: 'Loss (손실)', mode: 'min', description: '학습 손실 값' },
      ],
      'object_detection': [
        { value: 'mAP50', label: 'mAP@0.5 (평균 정밀도)', mode: 'max', description: 'IoU 0.5 기준 평균 정밀도' },
        { value: 'mAP50-95', label: 'mAP@0.5:0.95', mode: 'max', description: 'COCO 표준 mAP' },
        { value: 'precision', label: 'Precision (정밀도)', mode: 'max', description: '탐지 정밀도' },
        { value: 'recall', label: 'Recall (재현율)', mode: 'max', description: '탐지 재현율' },
        { value: 'loss', label: 'Loss (손실)', mode: 'min', description: '학습 손실 값' },
      ],
      'instance_segmentation': [
        { value: 'mAP50', label: 'mAP@0.5 (평균 정밀도)', mode: 'max', description: 'IoU 0.5 기준 평균 정밀도' },
        { value: 'mAP50-95', label: 'mAP@0.5:0.95', mode: 'max', description: 'COCO 표준 mAP' },
        { value: 'precision', label: 'Precision (정밀도)', mode: 'max', description: '분할 정밀도' },
        { value: 'recall', label: 'Recall (재현율)', mode: 'max', description: '분할 재현율' },
        { value: 'loss', label: 'Loss (손실)', mode: 'min', description: '학습 손실 값' },
      ],
      'pose_estimation': [
        { value: 'mAP50', label: 'mAP@0.5 (평균 정밀도)', mode: 'max', description: 'IoU 0.5 기준 평균 정밀도' },
        { value: 'mAP50-95', label: 'mAP@0.5:0.95', mode: 'max', description: 'COCO 표준 mAP' },
        { value: 'precision', label: 'Precision (정밀도)', mode: 'max', description: '키포인트 정밀도' },
        { value: 'recall', label: 'Recall (재현율)', mode: 'max', description: '키포인트 재현율' },
        { value: 'loss', label: 'Loss (손실)', mode: 'min', description: '학습 손실 값' },
      ],
    }

    return metricsByTask[taskType] || metricsByTask['image_classification']
  }

  // REMOVED: These useEffect hooks were resetting modelName based on hardcoded allModels array
  // which didn't include newer models like yolo11n. Since we now use ModelSelector with API data,
  // we don't need these validation hooks. The ModelSelector ensures valid model selection.

  // Update primary metric when task type changes
  useEffect(() => {
    const metricOptions = getMetricOptions()
    // Auto-select first metric as default if not set
    if (!primaryMetric && metricOptions.length > 0) {
      setPrimaryMetric(metricOptions[0].value)
      setPrimaryMetricMode(metricOptions[0].mode)
    }
    // If current metric is not available for new task, reset to first option
    else if (primaryMetric && !metricOptions.find(m => m.value === primaryMetric)) {
      setPrimaryMetric(metricOptions[0].value)
      setPrimaryMetricMode(metricOptions[0].mode)
    }
  }, [taskType])

  // Dataset analysis function
  const handleAnalyzeDataset = async () => {
    if (!datasetPath.trim()) {
      setAnalysisError('데이터셋 경로를 입력하세요')
      return
    }

    setIsAnalyzing(true)
    setAnalysisError(null)
    setDatasetInfo(null)

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/datasets/analyze`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          path: datasetPath.trim(),
          format_hint: null  // Auto-detect
        }),
      })

      const data = await response.json()

      if (data.status === 'success' && data.dataset_info) {
        setDatasetInfo(data.dataset_info)
        // Auto-fill format if detected
        if (data.dataset_info.format) {
          setDatasetFormat(data.dataset_info.format)
        }
      } else {
        setAnalysisError(data.message || '데이터셋 분석에 실패했습니다')
      }
    } catch (err) {
      console.error('Dataset analysis error:', err)
      setAnalysisError('데이터셋 분석 중 오류가 발생했습니다')
    } finally {
      setIsAnalyzing(false)
    }
  }

  // Validation
  const canProceedStep1 = framework && modelName && taskType && (
    // YOLO-World requires custom prompts
    taskType !== 'zero_shot_detection' || customPrompts.length > 0
  )
  const canProceedStep2 = selectedDatasetId !== null  // Dataset selected from R2

  // Check primary fields are all set (lr0, imgsz, etc.)
  // If no primary fields exist for this framework, skip validation (backward compatible)
  const primaryFieldsValid = primaryFields.length === 0 || (
    !loadingPrimaryFields && primaryFields.every(
      field => primaryFieldsValues[field.name] !== undefined && primaryFieldsValues[field.name] !== null
    )
  )

  const canSubmit = canProceedStep1 && canProceedStep2 && epochs > 0 && batchSize > 0 && primaryFieldsValid

  // Debug validation state
  useEffect(() => {
    console.log('[DEBUG] Validation state:', {
      canProceedStep1,
      canProceedStep2,
      epochs,
      batchSize,
      loadingPrimaryFields,
      primaryFields: primaryFields.length,
      primaryFieldsValues,
      primaryFieldsValid,
      canSubmit
    })
  }, [canProceedStep1, canProceedStep2, epochs, batchSize, loadingPrimaryFields, primaryFields, primaryFieldsValues, primaryFieldsValid, canSubmit])

  const handleNext = () => {
    setError(null)
    if (step < 3) {
      setStep(step + 1)
    }
  }

  const handlePrev = () => {
    setError(null)
    if (step > 1) {
      setStep(step - 1)
    }
  }

  const handleModelSelect = (model: ModelInfo) => {
    console.log('[DEBUG] handleModelSelect called with model:', model)
    console.log('[DEBUG]   model.framework:', model.framework)
    console.log('[DEBUG]   model.model_name:', model.model_name)
    console.log('[DEBUG]   model.task_types:', model.task_types)

    setSelectedModel(model)
    setFramework(model.framework)
    setModelName(model.model_name)
    setTaskType(model.task_types[0])  // Use first task type

    console.log('[DEBUG] After setState calls - new values:')
    console.log('[DEBUG]   framework:', model.framework)
    console.log('[DEBUG]   modelName:', model.model_name)

    // Apply recommended settings (only if provided)
    if (model.recommended_batch_size !== undefined) {
      setBatchSize(model.recommended_batch_size)
    }
    if (model.recommended_lr !== undefined) {
      setPrimaryFieldsValues(prev => ({
        ...prev,
        lr0: model.recommended_lr
      }))
    }

    // Show prompts modal for YOLO-World
    if (model.task_types.includes('zero_shot_detection')) {
      setShowPromptsModal(true)
    } else {
      setCustomPrompts([])
    }
  }

  const handlePromptsConfirm = (prompts: string[]) => {
    setCustomPrompts(prompts)
    setShowPromptsModal(false)
  }

  const handleSubmit = async () => {
    if (!canSubmit) return

    setIsSubmitting(true)
    setError(null)

    try {
      const config = {
        framework,
        model_name: modelName,
        task_type: taskType,
        dataset_id: selectedDatasetId,  // Use dataset_id instead of dataset_path
        dataset_format: selectedDataset?.format || datasetFormat,
        // num_classes will be determined by Backend from Labeler metadata
        epochs,
        batch_size: batchSize,
        primary_metric: primaryMetric || undefined,
        primary_metric_mode: primaryMetricMode,
        advanced_config: {
          ...primaryFieldsValues,  // Include primary fields (lr0, imgsz, etc.)
          ...(advancedConfig || {})  // Merge with user's advanced settings
        },
        custom_prompts: customPrompts.length > 0 ? customPrompts : undefined,
      }

      // DEBUG: Log what we're sending
      console.log('[DEBUG] Training config before submit:')
      console.log('[DEBUG]   framework:', framework)
      console.log('[DEBUG]   modelName state:', modelName)
      console.log('[DEBUG]   selectedModel:', selectedModel)
      console.log('[DEBUG]   config.model_name:', config.model_name)

      const requestBody: any = { config }
      if (projectId) {
        requestBody.project_id = projectId
      }

      console.log('[DEBUG] Request body:', JSON.stringify(requestBody, null, 2))

      // Get JWT token for authentication (Phase 12: Required for all training job creation)
      const token = localStorage.getItem('access_token')
      if (!token) {
        throw new Error('인증이 필요합니다. 다시 로그인해주세요.')
      }

      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/training/jobs`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,  // Phase 12: JWT authentication
        },
        body: JSON.stringify(requestBody),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        // Handle FastAPI validation errors (array of error objects)
        if (Array.isArray(errorData.detail)) {
          const messages = errorData.detail.map((err: any) => err.msg || err.type).join(', ')
          throw new Error(`Validation error: ${messages}`)
        }
        throw new Error(errorData.detail || errorData.message || '학습 작업 생성에 실패했습니다')
      }

      const job = await response.json()
      console.log('Training job created:', job)

      // Notify parent
      onTrainingStarted(job.id)
    } catch (err) {
      console.error('Error creating training job:', err)
      // Better error message extraction
      let errorMessage = '학습 작업 생성 중 오류가 발생했습니다'
      if (err instanceof Error) {
        errorMessage = err.message
      } else if (typeof err === 'string') {
        errorMessage = err
      } else if (err && typeof err === 'object') {
        errorMessage = JSON.stringify(err)
      }
      setError(errorMessage)
    } finally {
      setIsSubmitting(false)
    }
  }

  const renderStepIndicator = () => (
    <div className="flex items-center justify-center mb-6">
      {[1, 2, 3].map((stepNum) => (
        <div key={stepNum} className="flex items-center">
          <div
            className={cn(
              'w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium',
              step >= stepNum
                ? 'bg-violet-600 text-white'
                : 'bg-gray-200 text-gray-600'
            )}
          >
            {step > stepNum ? <CheckIcon className="w-5 h-5" /> : stepNum}
          </div>
          {stepNum < 3 && (
            <div
              className={cn(
                'w-16 h-1 mx-2',
                step > stepNum ? 'bg-violet-600' : 'bg-gray-200'
              )}
            />
          )}
        </div>
      ))}
    </div>
  )

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="p-6 border-b border-gray-200">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-4">
            <button
              onClick={onCancel}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <ArrowLeftIcon className="w-5 h-5 text-gray-600" />
            </button>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">
                {initialConfig ? '설정 복사하여 새 학습' : '새 학습 시작'}
              </h2>
              <p className="text-sm text-gray-600 mt-1">
                {step === 1 && '작업 유형과 모델을 선택하세요'}
                {step === 2 && '데이터셋 경로를 지정하세요'}
                {step === 3 && '학습 하이퍼파라미터를 설정하세요'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl mx-auto">
          {renderStepIndicator()}

          {/* Error Message */}
          {error && (
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          {/* Step 1: Model & Task */}
          {step === 1 && (
            <div className="space-y-6">
              {initialConfig && (
                <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <p className="text-sm text-blue-800">
                    📋 기존 설정을 복사했습니다. 원하는 부분만 수정하세요.
                  </p>
                </div>
              )}

              <div>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-base font-semibold text-gray-900">
                    모델 선택
                  </h3>
                  {selectedModel && (
                    <span className="text-sm text-gray-600">
                      선택됨: <span className="font-semibold text-blue-600">{selectedModel.display_name}</span>
                    </span>
                  )}
                </div>

                <ModelSelector
                  onModelSelect={handleModelSelect}
                  selectedModel={selectedModel}
                />
              </div>

              {/* YOLO-World Custom Prompts */}
              {selectedModel && selectedModel.task_types.includes('zero_shot_detection') && (
                <div className="p-4 bg-purple-50 border border-purple-200 rounded-lg">
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <h4 className="text-sm font-semibold text-purple-900 mb-1">
                        텍스트 프롬프트 설정 필요
                      </h4>
                      <p className="text-xs text-purple-700">
                        YOLO-World는 탐지할 객체를 자연어로 정의해야 합니다
                      </p>
                    </div>
                  </div>

                  {customPrompts.length > 0 ? (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-purple-900">
                          설정된 클래스: {customPrompts.length}개
                        </span>
                        <button
                          onClick={() => setShowPromptsModal(true)}
                          className="text-sm text-purple-700 hover:text-purple-900 font-medium"
                        >
                          수정
                        </button>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {customPrompts.slice(0, 5).map((prompt, idx) => (
                          <span
                            key={idx}
                            className="px-2 py-1 rounded-md text-xs bg-purple-100 text-purple-800"
                          >
                            {prompt}
                          </span>
                        ))}
                        {customPrompts.length > 5 && (
                          <span className="px-2 py-1 rounded-md text-xs bg-purple-100 text-purple-800">
                            +{customPrompts.length - 5}개 더
                          </span>
                        )}
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => setShowPromptsModal(true)}
                      className="w-full px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 transition-colors text-sm font-medium"
                    >
                      프롬프트 설정하기
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Step 2: Dataset */}
          {step === 2 && (
            <div className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-3">
                  데이터셋 선택 <span className="text-red-500">*</span>
                </label>
                <p className="text-xs text-gray-500 mb-4">
                  R2 Storage에 저장된 레이블링된 데이터셋 중 하나를 선택하세요
                </p>

                {isLoadingDatasets ? (
                  <div className="p-8 bg-gray-50 rounded-lg text-center">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-violet-600 mx-auto mb-3"></div>
                    <p className="text-sm text-gray-500">데이터셋 목록을 불러오는 중...</p>
                  </div>
                ) : availableDatasets.length === 0 ? (
                  <div className="p-8 bg-gray-50 rounded-lg text-center">
                    <div className="text-4xl mb-3">📦</div>
                    <p className="text-sm text-gray-700 font-medium mb-1">사용 가능한 데이터셋이 없습니다</p>
                    <p className="text-xs text-gray-500">데이터셋 관리 페이지에서 먼저 데이터셋을 생성하고 이미지를 업로드하세요</p>
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-4">
                    {availableDatasets.map((dataset) => (
                      <button
                        key={dataset.id}
                        onClick={() => {
                          setSelectedDatasetId(dataset.id)
                          setSelectedDataset(dataset)
                        }}
                        className={cn(
                          'p-4 border-2 rounded-lg text-left transition-all',
                          'hover:shadow-md',
                          selectedDatasetId === dataset.id
                            ? 'border-violet-500 bg-violet-50'
                            : 'border-gray-200 hover:border-violet-300'
                        )}
                      >
                        <div className="flex items-start justify-between mb-2">
                          <div className="flex-1">
                            <h3 className="text-sm font-semibold text-gray-900 mb-1">
                              {dataset.name}
                            </h3>
                            <p className="text-xs text-gray-500 line-clamp-2">
                              {dataset.description}
                            </p>
                          </div>
                          {selectedDatasetId === dataset.id && (
                            <div className="ml-2 flex-shrink-0">
                              <div className="w-5 h-5 bg-violet-600 rounded-full flex items-center justify-center">
                                <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                              </div>
                            </div>
                          )}
                        </div>

                        <div className="flex flex-wrap gap-2 mb-3">
                          <span className={cn(
                            'px-2 py-0.5 rounded text-xs font-medium',
                            dataset.labeled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'
                          )}>
                            {dataset.labeled ? '레이블링됨' : '미레이블'}
                          </span>
                          <span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
                            {dataset.format.toUpperCase()}
                          </span>
                          {dataset.source === 'r2' && (
                            <span className="px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
                              R2 Storage
                            </span>
                          )}
                        </div>

                        <div className="flex items-center justify-between text-xs text-gray-600">
                          <span>{dataset.num_images?.toLocaleString() || 0} images</span>
                          {dataset.size_mb && (
                            <span>{dataset.size_mb.toFixed(1)} MB</span>
                          )}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Selected Dataset Info */}
              {selectedDataset && (
                <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-emerald-600 font-semibold">✓ 선택된 데이터셋</span>
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <span className="text-gray-600">이름:</span>
                      <span className="ml-2 font-medium text-gray-900">{selectedDataset.name}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">형식:</span>
                      <span className="ml-2 font-medium text-gray-900">{selectedDataset.format.toUpperCase()}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">이미지 수:</span>
                      <span className="ml-2 font-medium text-gray-900">
                        {selectedDataset.num_images?.toLocaleString() || 0}장
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-600">상태:</span>
                      <span className={cn(
                        "ml-2 font-medium",
                        selectedDataset.labeled ? "text-green-600" : "text-gray-600"
                      )}>
                        {selectedDataset.labeled ? '레이블링됨' : '미레이블'}
                      </span>
                    </div>
                  </div>

                  {selectedDataset.description && (
                    <div className="pt-2 border-t border-emerald-200">
                      <span className="text-xs text-gray-600">설명:</span>
                      <p className="text-sm text-gray-700 mt-1">{selectedDataset.description}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Step 3: Hyperparameters */}
          {step === 3 && (
            <div className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Epochs <span className="text-red-500">*</span>
                </label>
                <input
                  type="number"
                  value={epochs}
                  onChange={(e) => setEpochs(parseInt(e.target.value) || 0)}
                  min="1"
                  max="1000"
                  className={cn(
                    'w-full px-4 py-2.5 border border-gray-300 rounded-lg',
                    'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
                    'text-sm'
                  )}
                />
                <p className="text-xs text-gray-500 mt-1">
                  학습 반복 횟수 (1-1000)
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Batch Size <span className="text-red-500">*</span>
                </label>
                <select
                  value={batchSize}
                  onChange={(e) => setBatchSize(parseInt(e.target.value))}
                  className={cn(
                    'w-full px-4 py-2.5 border border-gray-300 rounded-lg',
                    'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
                    'text-sm bg-white'
                  )}
                >
                  <option value="8">8</option>
                  <option value="16">16</option>
                  <option value="32">32</option>
                  <option value="64">64</option>
                  <option value="128">128</option>
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  한 번에 처리할 데이터 개수 (GPU 메모리에 따라 조정)
                </p>
              </div>

              {/* Dynamic Primary Fields */}
              {primaryFields.map((field: any) => (
                <div key={field.name}>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {field.description} <span className="text-red-500">*</span>
                  </label>
                  {field.type === 'int' || field.type === 'float' ? (
                    <input
                      type="number"
                      value={primaryFieldsValues[field.name] ?? field.default}
                      onChange={(e) => {
                        const value = field.type === 'int'
                          ? parseInt(e.target.value) || 0
                          : parseFloat(e.target.value) || 0
                        setPrimaryFieldsValues({
                          ...primaryFieldsValues,
                          [field.name]: value
                        })
                      }}
                      min={field.min}
                      max={field.max}
                      step={field.step}
                      className={cn(
                        'w-full px-4 py-2.5 border border-gray-300 rounded-lg',
                        'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
                        'text-sm'
                      )}
                    />
                  ) : field.type === 'bool' ? (
                    <input
                      type="checkbox"
                      checked={primaryFieldsValues[field.name] ?? field.default}
                      onChange={(e) => setPrimaryFieldsValues({
                        ...primaryFieldsValues,
                        [field.name]: e.target.checked
                      })}
                      className="w-4 h-4 text-violet-600"
                    />
                  ) : null}
                  <p className="text-xs text-gray-500 mt-1">
                    {field.min !== undefined && field.max !== undefined
                      ? `${field.min}-${field.max}`
                      : `기본값: ${field.default}`}
                  </p>
                </div>
              ))}

              {/* Primary Metric Selection */}
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <label className="block text-sm font-semibold text-blue-900 mb-2">
                  Primary Metric (주요 평가 지표)
                </label>
                <select
                  value={primaryMetric}
                  onChange={(e) => {
                    const selected = getMetricOptions().find(m => m.value === e.target.value)
                    if (selected) {
                      setPrimaryMetric(selected.value)
                      setPrimaryMetricMode(selected.mode)
                    }
                  }}
                  className={cn(
                    'w-full px-4 py-2.5 border border-blue-300 rounded-lg',
                    'focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent',
                    'text-sm bg-white'
                  )}
                >
                  {getMetricOptions().map((metric) => (
                    <option key={metric.value} value={metric.value}>
                      {metric.label} {metric.mode === 'max' ? '↑' : '↓'}
                    </option>
                  ))}
                </select>
                <div className="mt-2 text-xs text-blue-700">
                  <p className="font-medium">
                    선택된 메트릭: <span className="font-mono">{primaryMetric}</span>
                    <span className="ml-2 px-1.5 py-0.5 bg-blue-200 rounded">
                      {primaryMetricMode === 'max' ? '최대화 ↑' : '최소화 ↓'}
                    </span>
                  </p>
                  <p className="mt-1 text-blue-600">
                    {getMetricOptions().find(m => m.value === primaryMetric)?.description || ''}
                  </p>
                </div>
              </div>

              {/* Advanced Configuration Button */}
              <div className="border-t border-gray-200 pt-6">
                <button
                  type="button"
                  onClick={() => setShowAdvancedConfig(true)}
                  className={cn(
                    'w-full flex items-center justify-center gap-2 px-4 py-3',
                    'border-2 border-dashed rounded-lg transition-colors',
                    advancedConfig
                      ? 'border-violet-300 bg-violet-50 text-violet-700 hover:bg-violet-100'
                      : 'border-gray-300 text-gray-600 hover:border-gray-400 hover:bg-gray-50'
                  )}
                >
                  <Settings className="w-5 h-5" />
                  <span className="font-medium">
                    {advancedConfig ? 'Advanced 설정 수정하기' : 'Advanced 설정 (선택사항)'}
                  </span>
                  {advancedConfig && (
                    <span className="ml-auto px-2 py-1 bg-violet-200 text-violet-800 rounded text-xs font-semibold">
                      설정됨
                    </span>
                  )}
                </button>
                {advancedConfig && (
                  <p className="text-xs text-gray-500 mt-2 text-center">
                    Optimizer, Scheduler, Augmentation 등이 설정되었습니다
                  </p>
                )}
              </div>

              {/* Summary */}
              <div className="p-4 bg-gray-50 rounded-lg">
                <h3 className="text-sm font-semibold text-gray-900 mb-3">설정 요약</h3>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-600">모델:</span>
                    <span className="font-medium">{modelName}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">작업:</span>
                    <span className="font-medium">{taskType}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">데이터셋:</span>
                    <span className="font-medium text-xs truncate max-w-[200px]">
                      {selectedDataset?.name || '선택되지 않음'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Epochs:</span>
                    <span className="font-medium">{epochs}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Batch Size:</span>
                    <span className="font-medium">{batchSize}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Learning Rate:</span>
                    <span className="font-medium">{primaryFieldsValues.lr0 || 'N/A'}</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Footer - Navigation Buttons */}
      <div className="p-6 border-t border-gray-200">
        <div className="max-w-2xl mx-auto flex gap-3">
          {step > 1 && (
            <button
              onClick={handlePrev}
              disabled={isSubmitting}
              className={cn(
                'flex-1 px-4 py-2.5 border border-gray-300 rounded-lg',
                'text-gray-700 font-medium hover:bg-gray-50',
                'transition-colors flex items-center justify-center gap-2',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              <ArrowLeftIcon className="w-4 h-4" />
              이전
            </button>
          )}

          {step < 3 ? (
            <button
              onClick={handleNext}
              disabled={
                (step === 1 && !canProceedStep1) ||
                (step === 2 && !canProceedStep2)
              }
              className={cn(
                'flex-1 px-4 py-2.5 bg-violet-600 text-white rounded-lg',
                'font-medium hover:bg-violet-700',
                'transition-colors flex items-center justify-center gap-2',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              다음
              <ArrowRightIcon className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={!canSubmit || isSubmitting}
              className={cn(
                'flex-1 px-4 py-2.5 bg-violet-600 text-white rounded-lg',
                'font-medium hover:bg-violet-700',
                'transition-colors flex items-center justify-center gap-2',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              {isSubmitting ? '학습 시작 중...' : '학습 시작 🚀'}
            </button>
          )}
        </div>
      </div>

      {/* Advanced Configuration Modal */}
      {showAdvancedConfig && (
        <AdvancedConfigPanel
          framework={framework}
          taskType={taskType}
          config={advancedConfig}
          onChange={(newConfig) => {
            setAdvancedConfig(newConfig)
            setShowAdvancedConfig(false)
          }}
          onClose={() => setShowAdvancedConfig(false)}
        />
      )}

      {/* Custom Prompts Modal (YOLO-World) */}
      <CustomPromptsModal
        isOpen={showPromptsModal}
        onClose={() => setShowPromptsModal(false)}
        onConfirm={handlePromptsConfirm}
        initialPrompts={customPrompts}
        modelName={selectedModel?.display_name}
      />
    </div>
  )
}

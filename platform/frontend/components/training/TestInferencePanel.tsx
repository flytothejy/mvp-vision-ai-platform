'use client'

/**
 * TestInferencePanel Component
 *
 * Interactive inference panel for running predictions on uploaded images.
 * Features image upload, checkpoint selection, task-specific settings, and real-time results.
 */

import { useState, useEffect, useRef } from 'react'
import { Upload, Settings, Play, AlertCircle, Terminal, Info, CheckCircle, XCircle, Trash2, X } from 'lucide-react'
import { cn } from '@/lib/utils/cn'
import { SlidePanel } from '../SlidePanel'
import ImageUploadList from './ImageUploadList'

interface TrainingJob {
  id: number
  task_type: string
  framework: string
  model_name: string
  output_dir: string
}

interface TestInferencePanelProps {
  jobId: number
}

interface UploadedImage {
  id: string
  file: File
  preview: string
  serverPath?: string  // Server path after upload
  status: 'pending' | 'processing' | 'completed' | 'failed'
  result?: any
  error?: string
}

interface EpochMetric {
  epoch: number
  primary_metric: number
  loss: number
  checkpoint_path?: string | null
  [key: string]: any  // Allow additional task-specific metrics
}

export default function TestInferencePanel({ jobId }: TestInferencePanelProps) {
  const [job, setJob] = useState<TrainingJob | null>(null)
  const [images, setImages] = useState<UploadedImage[]>([])
  const [selectedImageId, setSelectedImageId] = useState<string | null>(null)
  const [epochMetrics, setEpochMetrics] = useState<EpochMetric[]>([])
  const [selectedEpoch, setSelectedEpoch] = useState<EpochMetric | null>(null)
  const [bestEpoch, setBestEpoch] = useState<number | null>(null)
  const [bestMetricName, setBestMetricName] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [loading, setLoading] = useState(true)
  const [showSlidePanel, setShowSlidePanel] = useState(false)

  // Session ID for image uploads (generated once per component mount)
  const [sessionId] = useState<string>(() => {
    // Generate UUID v4
    return crypto.randomUUID()
  })

  // Inference settings
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.25)
  const [iouThreshold, setIouThreshold] = useState(0.45)
  const [maxDetections, setMaxDetections] = useState(100)
  const [topK, setTopK] = useState(5)

  // Visualization settings
  const [showMasks, setShowMasks] = useState(true)
  const [showBoxes, setShowBoxes] = useState(true)

  // Canvas ref for bbox visualization
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imageRef = useRef<HTMLImageElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Logs state
  interface LogEntry {
    timestamp: Date
    level: 'info' | 'success' | 'warning' | 'error'
    message: string
  }
  const [logs, setLogs] = useState<LogEntry[]>([])
  const logsEndRef = useRef<HTMLDivElement>(null)

  // Helper to add log entry
  const addLog = (level: LogEntry['level'], message: string) => {
    setLogs(prev => [...prev, { timestamp: new Date(), level, message }])
  }

  // Fetch job details
  useEffect(() => {
    const fetchJob = async () => {
      try {
        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${jobId}`
        )
        if (response.ok) {
          const data = await response.json()
          setJob(data)
        }
      } catch (error) {
        console.error('Error fetching job:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchJob()
  }, [jobId])

  // Fetch validation summary (includes checkpoint paths)
  useEffect(() => {
    const fetchValidationSummary = async () => {
      try {
        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/validation/jobs/${jobId}/summary`
        )
        if (response.ok) {
          const data = await response.json()
          setEpochMetrics(data.epoch_metrics || [])
          setBestEpoch(data.best_epoch)
          setBestMetricName(data.best_metric_name)

          // Auto-select best epoch
          const bestEpochMetric = data.epoch_metrics?.find(
            (m: EpochMetric) => m.epoch === data.best_epoch
          )
          if (bestEpochMetric) setSelectedEpoch(bestEpochMetric)
        }
      } catch (error) {
        console.error('Error fetching validation summary:', error)
      }
    }
    if (job) fetchValidationSummary()
  }, [job, jobId])

  // Cleanup session on component unmount
  useEffect(() => {
    return () => {
      // Clean up session when leaving the inference panel
      fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/test_inference/inference/session/${sessionId}`,
        { method: 'DELETE' }
      ).catch((error) => {
        // Ignore errors - background cleanup will handle it
        console.log('Session cleanup failed (will be handled by background task):', error)
      })
    }
  }, [sessionId])

  // Draw bboxes when image, results, or visibility changes
  useEffect(() => {
    const selectedImage = images.find(img => img.id === selectedImageId)
    if (selectedImage?.result && imageRef.current?.complete) {
      drawBoundingBoxes()
    }
  }, [images, selectedImageId, showMasks, showBoxes])

  const drawBoundingBoxes = () => {
    const canvas = canvasRef.current
    const image = imageRef.current
    if (!canvas || !image || !image.complete) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Get selected image
    const selectedImage = images.find(img => img.id === selectedImageId)
    if (!selectedImage) return

    // Set canvas size to match displayed image size
    const rect = image.getBoundingClientRect()
    canvas.width = image.naturalWidth
    canvas.height = image.naturalHeight
    canvas.style.width = `${rect.width}px`
    canvas.style.height = `${rect.height}px`

    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    // Only draw for detection/segmentation tasks
    if (!selectedImage?.result ||
        (selectedImage.result.task_type !== 'object_detection' &&
         selectedImage.result.task_type !== 'instance_segmentation')) {
      return
    }

    const boxes = selectedImage.result.predicted_boxes || []
    const masks = selectedImage.result.predicted_masks || []

    console.log('[CANVAS] task_type:', selectedImage.result.task_type)
    console.log('[CANVAS] masks array:', masks)
    console.log('[CANVAS] masks.length:', masks.length)
    console.log('[CANVAS] showMasks:', showMasks)
    console.log('[CANVAS] showBoxes:', showBoxes)
    console.log('[CANVAS] canvas size:', canvas.width, 'x', canvas.height)

    // Draw masks first (if segmentation task and showMasks is enabled)
    if (showMasks && selectedImage.result.task_type === 'instance_segmentation' && masks.length > 0) {
      console.log('[CANVAS] Drawing masks...')
      masks.forEach((mask: any, idx: number) => {
        console.log(`[CANVAS] Mask ${idx}:`, mask)
        console.log(`[CANVAS] Mask ${idx} polygon length:`, mask.polygon?.length)
        if (mask.polygon && mask.polygon.length > 0) {
          console.log(`[CANVAS] Drawing polygon for mask ${idx} with ${mask.polygon.length} points`)

          // Use different colors for each instance (cycle through palette)
          const colors = [
            { fill: 'rgba(168, 85, 247, 0.4)', stroke: '#A855F7' },  // Purple
            { fill: 'rgba(34, 197, 94, 0.4)', stroke: '#22C55E' },   // Green
            { fill: 'rgba(59, 130, 246, 0.4)', stroke: '#3B82F6' },  // Blue
            { fill: 'rgba(251, 146, 60, 0.4)', stroke: '#FB923C' },  // Orange
            { fill: 'rgba(236, 72, 153, 0.4)', stroke: '#EC4899' },  // Pink
          ]
          const color = colors[idx % colors.length]

          // Draw filled polygon with transparency
          ctx.fillStyle = color.fill
          ctx.strokeStyle = color.stroke
          ctx.lineWidth = 3

          ctx.beginPath()
          const firstPoint = mask.polygon[0]
          console.log('[CANVAS] First point:', firstPoint)
          ctx.moveTo(firstPoint[0], firstPoint[1])

          mask.polygon.forEach((point: number[]) => {
            ctx.lineTo(point[0], point[1])
          })

          ctx.closePath()
          ctx.fill()
          ctx.stroke()
          console.log(`[CANVAS] Mask ${idx} drawn successfully with color:`, color.stroke)
        } else {
          console.log(`[CANVAS] Mask ${idx} has no polygon data`)
        }
      })
    } else {
      console.log('[CANVAS] NOT drawing masks. Reason:',
        selectedImage.result.task_type !== 'instance_segmentation' ? 'not segmentation task' : 'no masks')
    }

    // Draw bboxes (if showBoxes is enabled)
    if (showBoxes) {
      ctx.lineWidth = 3
      boxes.forEach((box: any) => {
      // Use x1, y1, x2, y2 from backend
      if (box.x1 !== undefined && box.x2 !== undefined) {
        const x = box.x1
        const y = box.y1
        const w = box.x2 - box.x1
        const h = box.y2 - box.y1

        // Draw bbox
        ctx.strokeStyle = '#EF4444'  // red
        ctx.strokeRect(x, y, w, h)

        // Draw label with confidence
        if (box.label && box.confidence) {
          const label = `${box.label} ${(box.confidence * 100).toFixed(1)}%`
          ctx.font = 'bold 14px sans-serif'
          const metrics = ctx.measureText(label)
          const padding = 4

          // Background
          ctx.fillStyle = '#EF4444'
          ctx.fillRect(x, y - 20, metrics.width + padding * 2, 20)

          // Text
          ctx.fillStyle = '#FFFFFF'
          ctx.fillText(label, x + padding, y - 6)
        }
      }
      })
    }
  }

  const handleImageLoad = () => {
    drawBoundingBoxes()
  }

  const addImages = (files: File[]) => {
    const newImages: UploadedImage[] = files.map(file => ({
      id: `${Date.now()}-${Math.random()}`,
      file,
      preview: URL.createObjectURL(file),
      status: 'pending'
    }))
    setImages(prev => [...prev, ...newImages])
    if (!selectedImageId && newImages.length > 0) {
      setSelectedImageId(newImages[0].id)
    }
    addLog('info', `${newImages.length}개의 이미지를 추가했습니다: ${files.map(f => f.name).join(', ')}`)
  }

  // Add state for InferenceJob tracking
  const [inferenceJobId, setInferenceJobId] = useState<number | null>(null)
  const [inferenceStatus, setInferenceStatus] = useState<string>('idle')

  const runInference = async () => {
    // Allow inference if either pretrained (selectedEpoch is null) or checkpoint exists
    if (images.length === 0) return
    if (selectedEpoch && !selectedEpoch.checkpoint_path) return

    setIsRunning(true)
    setInferenceStatus('uploading')

    const weightType = selectedEpoch ? `Epoch ${selectedEpoch.epoch}` : 'Pretrained Weight'
    addLog('info', `추론을 시작합니다 (가중치: ${weightType}, 이미지: ${images.length}개)`)

    try {
      // Step 1: Upload all images to S3 Internal Storage
      addLog('info', `${images.length}개의 이미지를 S3에 업로드 중...`)

      const formData = new FormData()
      images.forEach(image => {
        formData.append('files', image.file)
      })

      const uploadResponse = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/test_inference/inference/upload-images?training_job_id=${jobId}`,
        {
          method: 'POST',
          body: formData
        }
      )

      if (!uploadResponse.ok) {
        throw new Error('Failed to upload images to S3')
      }

      const uploadData = await uploadResponse.json()
      const s3Prefix = uploadData.s3_prefix

      // Build mapping from unique filename (S3) to original filename (local)
      const uniqueToOriginalMap = new Map<string, string>()
      if (uploadData.uploaded_files) {
        uploadData.uploaded_files.forEach((f: { original_filename: string; unique_filename: string }) => {
          uniqueToOriginalMap.set(f.unique_filename, f.original_filename)
        })
      }

      addLog('success', `✓ ${uploadData.total_files}개의 이미지를 S3에 업로드 완료`)
      addLog('info', `S3 경로: ${s3Prefix}`)

      // Step 2: Create InferenceJob
      addLog('info', '추론 작업을 생성 중...')
      setInferenceStatus('creating')

      const checkpointPath = selectedEpoch?.checkpoint_path || 'pretrained'

      const createJobResponse = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/test_inference/inference/jobs`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            training_job_id: jobId,
            checkpoint_path: checkpointPath,
            inference_type: 'batch',
            input_data: {
              image_paths_s3: s3Prefix,
              confidence_threshold: confidenceThreshold,
              iou_threshold: iouThreshold,
              max_detections: maxDetections,
              image_size: 640,
              device: 'cpu',
              save_txt: true,
              save_conf: true,
              save_crop: false
            }
          })
        }
      )

      if (!createJobResponse.ok) {
        throw new Error('Failed to create inference job')
      }

      const jobData = await createJobResponse.json()
      const createdInferenceJobId = jobData.id
      setInferenceJobId(createdInferenceJobId)

      addLog('success', `✓ 추론 작업 생성 완료 (Job ID: ${createdInferenceJobId})`)
      addLog('info', '추론을 실행 중입니다...')
      setInferenceStatus('running')

      // Step 3: Poll for job completion
      let pollCount = 0
      const maxPolls = 60 // 60 * 2s = 2 minutes max

      const pollInterval = setInterval(async () => {
        pollCount++

        try {
          const statusResponse = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/test_inference/inference/jobs/detail/${createdInferenceJobId}`
          )

          if (!statusResponse.ok) {
            clearInterval(pollInterval)
            throw new Error('Failed to fetch job status')
          }

          const statusData = await statusResponse.json()

          if (statusData.status === 'completed') {
            clearInterval(pollInterval)

            addLog('success', `✓ 추론 완료 (총 ${statusData.total_images}개, 평균 ${statusData.avg_inference_time_ms?.toFixed(1)}ms)`)

            // Step 4: Fetch results
            addLog('info', '추론 결과를 불러오는 중...')

            const resultsResponse = await fetch(
              `${process.env.NEXT_PUBLIC_API_URL}/test_inference/inference/jobs/${createdInferenceJobId}/results`
            )

            if (!resultsResponse.ok) {
              throw new Error('Failed to fetch inference results')
            }

            const resultsData = await resultsResponse.json()

            // Update images with results
            // Map unique filenames (from S3) back to original filenames (from upload)
            const resultsByOriginalName = new Map(
              resultsData.results.map((r: any) => {
                const originalName = uniqueToOriginalMap.get(r.image_name) || r.image_name
                return [originalName, r]
              })
            )

            setImages(prev => prev.map(img => {
              const result = resultsByOriginalName.get(img.file.name) as any
              if (result) {
                // Map task_type: "detection" → "object_detection", etc.
                const taskTypeMap: Record<string, string> = {
                  'detection': 'object_detection',
                  'classification': 'image_classification',
                  'segmentation': 'instance_segmentation',
                  'pose': 'pose_estimation'
                }
                const mappedTaskType = job?.task_type
                  ? (taskTypeMap[job.task_type] || job.task_type)
                  : 'object_detection'

                // Transform result to match expected format
                const transformedResult = {
                  success: true,
                  task_type: mappedTaskType,
                  inference_time_ms: result.inference_time_ms,
                  predicted_boxes: result.predicted_boxes || [],
                  predictions: result.predictions || [],
                  top5_predictions: result.top5_predictions || []
                }

                return {
                  ...img,
                  status: 'completed' as const,
                  result: transformedResult
                }
              }
              return img
            }))

            addLog('success', `✓ 모든 결과를 불러왔습니다`)

            setInferenceStatus('completed')
            setIsRunning(false)

          } else if (statusData.status === 'failed') {
            clearInterval(pollInterval)
            addLog('error', `추론 실패: ${statusData.error_message || 'Unknown error'}`)
            setInferenceStatus('failed')
            setIsRunning(false)

          } else if (statusData.status === 'running') {
            if (pollCount % 5 === 0) { // Log every 10 seconds
              addLog('info', '추론이 진행 중입니다...')
            }
          }

          if (pollCount >= maxPolls) {
            clearInterval(pollInterval)
            addLog('error', '추론 타임아웃 (2분 경과)')
            setInferenceStatus('failed')
            setIsRunning(false)
          }

        } catch (error) {
          clearInterval(pollInterval)
          addLog('error', `상태 조회 실패: ${error}`)
          setInferenceStatus('failed')
          setIsRunning(false)
        }
      }, 2000) // Poll every 2 seconds

    } catch (error: any) {
      addLog('error', `추론 실패: ${error.message || 'Unknown error'}`)
      setInferenceStatus('failed')
      setIsRunning(false)

      // Mark all images as failed
      setImages(prev => prev.map(img => ({
        ...img,
        status: 'failed' as const,
        error: error.message
      })))
    }
  }

  // Legacy code for reference (to be removed after migration is complete)
  const runInferenceLegacy_DEPRECATED = async () => {
    // OLD IMPLEMENTATION - DO NOT USE
    // This code is kept for reference only and will be removed
    // See docs/INFERENCE_JOB_PATTERN.md for the new implementation

    if (images.length === 0) return
    if (selectedEpoch && !selectedEpoch.checkpoint_path) return

    setIsRunning(true)

    const weightType = selectedEpoch ? `Epoch ${selectedEpoch.epoch}` : 'Pretrained Weight'
    addLog('info', `추론을 시작합니다 (가중치: ${weightType}, 이미지: ${images.length}개)`)

    try {
      for (const image of images) {
        setImages(prev => prev.map(img =>
          img.id === image.id ? { ...img, status: 'processing' } : img
        ))

        try {
          let serverPath = image.serverPath
          if (!serverPath) {
            addLog('info', `이미지 업로드 중: ${image.file.name}`)
            const formData = new FormData()
            formData.append('file', image.file)

            const uploadResponse = await fetch(
              `${process.env.NEXT_PUBLIC_API_URL}/test_inference/inference/upload-image?session_id=${sessionId}`,
              {
                method: 'POST',
                body: formData
              }
            )

            if (!uploadResponse.ok) {
              throw new Error('Failed to upload image')
            }

            const uploadData = await uploadResponse.json()
            serverPath = uploadData.server_path

            setImages(prev => prev.map(img =>
              img.id === image.id ? { ...img, serverPath } : img
            ))
            addLog('success', `이미지 업로드 완료: ${image.file.name}`)
          }

          if (!serverPath) {
            addLog('error', `이미지 경로를 찾을 수 없습니다: ${image.file.name}`)
            continue
          }

          addLog('info', `추론 실행 중: ${image.file.name}`)

          const params = new URLSearchParams({
            training_job_id: jobId.toString(),
            image_path: serverPath,
            confidence_threshold: confidenceThreshold.toString(),
            iou_threshold: iouThreshold.toString(),
            max_detections: maxDetections.toString(),
            top_k: topK.toString()
          })

          if (selectedEpoch && selectedEpoch.checkpoint_path) {
            params.append('checkpoint_path', selectedEpoch.checkpoint_path)
          }

          const response = await fetch(
            `${process.env.NEXT_PUBLIC_API_URL}/test_inference/inference/quick?` + params.toString(),
            { method: 'POST' }
          )

          if (response.ok) {
            const result = await response.json()

            setImages(prev => prev.map(img =>
              img.id === image.id ? { ...img, status: 'completed', result } : img
            ))

            let resultSummary = `추론 완료: ${image.file.name} (${result.inference_time_ms?.toFixed(1)}ms)`
            if (result.task_type === 'image_classification') {
              const topPred = result.top5_predictions?.[0]
              if (topPred) {
                resultSummary += ` - Top-1: ${topPred.label} (${(topPred.confidence * 100).toFixed(1)}%)`
              }
            } else if (result.task_type === 'object_detection') {
              resultSummary += ` - ${result.num_detections}개 탐지`
            } else if (result.task_type === 'instance_segmentation' || result.task_type === 'semantic_segmentation') {
              resultSummary += ` - ${result.num_instances}개 인스턴스`
            } else if (result.task_type === 'pose_estimation') {
              resultSummary += ` - ${result.num_persons}명 탐지`
            }
            addLog('success', resultSummary)
          } else {
            const errorData = await response.json().catch(() => ({}))
            throw new Error(errorData.detail || 'Inference failed')
          }
        } catch (error) {
          console.error('Inference error:', error)
          const errorMessage = error instanceof Error ? error.message : 'Unknown error'
          setImages(prev => prev.map(img =>
            img.id === image.id ? { ...img, status: 'failed', error: errorMessage } : img
          ))
          addLog('error', `추론 실패: ${image.file.name} - ${errorMessage}`)
        }
      }

      const successCount = images.filter(img => img.status === 'completed').length
      const failedCount = images.filter(img => img.status === 'failed').length
      addLog('info', `추론 완료 - 성공: ${successCount}개, 실패: ${failedCount}개`)
    } finally {
      setIsRunning(false)
    }
  }

  const selectedImage = images.find(img => img.id === selectedImageId)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400">Loading...</div>
      </div>
    )
  }

  if (!job) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center text-gray-500">
          <AlertCircle className="w-12 h-12 mx-auto mb-4 text-gray-400" />
          <p className="text-sm">학습 작업을 찾을 수 없습니다</p>
        </div>
      </div>
    )
  }

  const handleImageRemove = (imageId: string) => {
    setImages(prev => prev.filter(img => img.id !== imageId))
    // If removed image was selected, select another or none
    if (selectedImageId === imageId) {
      const remainingImages = images.filter(img => img.id !== imageId)
      setSelectedImageId(remainingImages.length > 0 ? remainingImages[0].id : null)
    }
    addLog('info', '이미지를 삭제했습니다')
  }

  const handleClearAll = () => {
    setImages([])
    setSelectedImageId(null)
    addLog('info', '모든 이미지를 삭제했습니다')
  }

  const handleImageSelect = (imageId: string) => {
    console.log('[DEBUG] handleImageSelect called with imageId:', imageId)
    const image = images.find(img => img.id === imageId)
    console.log('[DEBUG] Found image:', image)
    if (!image) {
      console.log('[DEBUG] Image not found, returning')
      return
    }

    console.log('[DEBUG] Setting selectedImageId to:', imageId)
    console.log('[DEBUG] Image result:', image.result)
    console.log('[DEBUG] Image task_type:', image.result?.task_type)
    console.log('[DEBUG] Image top5_predictions:', image.result?.top5_predictions)
    setSelectedImageId(imageId)

    // Show slide panel for super-resolution results
    if (image.result && image.status === 'completed' && image.result.upscaled_image_url) {
      setShowSlidePanel(true)
    }
  }

  return (
    <div className="space-y-3">
      {/* Task Type Header */}
      <div className="bg-gradient-to-r from-violet-50 to-purple-50 rounded-lg border border-violet-200 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={cn(
              "px-3 py-1 rounded-full text-xs font-semibold",
              job.task_type === 'instance_segmentation' || job.task_type === 'segmentation'
                ? "bg-purple-500 text-white"
                : job.task_type === 'object_detection' || job.task_type === 'detection'
                ? "bg-blue-500 text-white"
                : "bg-green-500 text-white"
            )}>
              {job.task_type === 'instance_segmentation' || job.task_type === 'segmentation' ? '🎭 Instance Segmentation' :
               job.task_type === 'object_detection' || job.task_type === 'detection' ? '📦 Object Detection' :
               '🖼️ Image Classification'}
            </div>
            <span className="text-sm text-gray-700">
              {job.task_type === 'instance_segmentation' || job.task_type === 'segmentation'
                ? 'Mask와 Bounding Box를 함께 예측합니다'
                : job.task_type === 'object_detection' || job.task_type === 'detection'
                ? 'Bounding Box를 예측합니다'
                : 'Class와 Confidence를 예측합니다'}
            </span>
          </div>
          <div className="text-xs text-gray-500">
            Model: <span className="font-mono text-violet-600">{job.model_name}</span>
          </div>
        </div>
      </div>

      {/* Top Row - Image Uploader (2) + Inference Settings (8) */}
      <div className="grid grid-cols-10 gap-3">
        {/* Image Uploader - No thumbnails */}
        <div className="col-span-2 bg-white rounded-lg border border-gray-200 p-6">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">이미지 업로드</h3>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*"
            onChange={(e) => {
              const files = Array.from(e.target.files || [])
              if (files.length > 0) {
                addImages(files)
              }
              e.target.value = ''
            }}
            className="hidden"
          />

          {/* Drop Zone */}
          <div
            onClick={() => fileInputRef.current?.click()}
            onDrop={(e) => {
              e.preventDefault()
              const files = Array.from(e.dataTransfer.files).filter(file =>
                file.type.startsWith('image/')
              )
              if (files.length > 0) {
                addImages(files)
              }
            }}
            onDragOver={(e) => e.preventDefault()}
            className={cn(
              'border-2 border-dashed border-gray-300 rounded-lg py-8',
              'flex items-center justify-center cursor-pointer',
              'hover:border-violet-400 hover:bg-violet-50/50',
              'transition-colors'
            )}
          >
            <Upload className="w-12 h-12 text-gray-300" />
          </div>
        </div>

        {/* Inference Settings - 8 columns */}
        <div className="col-span-8 bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center gap-2 mb-6">
            <Settings className="w-5 h-5 text-violet-600" />
            <h3 className="text-sm font-semibold text-gray-900">추론 설정</h3>
          </div>

          <div className="grid grid-cols-12 gap-4 items-end">
            {/* Epoch Selection */}
            <div className="col-span-3">
              <label className="block text-xs font-medium text-gray-700 mb-2">
                모델 가중치 선택
              </label>
              <select
                value={selectedEpoch?.epoch || 'pretrained'}
                onChange={(e) => {
                  if (e.target.value === 'pretrained') {
                    setSelectedEpoch(null)
                  } else {
                    const epoch = epochMetrics.find(m => m.epoch === Number(e.target.value))
                    setSelectedEpoch(epoch || null)
                  }
                }}
                className={cn(
                  'w-full px-3 py-2 text-sm',
                  'border border-gray-300 rounded-lg',
                  'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
                  'bg-white'
                )}
              >
                <option value="pretrained">
                  🔷 Pretrained Weight (사전학습 모델)
                </option>
                {epochMetrics.length > 0 && (
                  <optgroup label="학습된 체크포인트">
                    {epochMetrics.map(metric => (
                      <option
                        key={metric.epoch}
                        value={metric.epoch}
                        disabled={!metric.checkpoint_path}
                      >
                        Epoch {metric.epoch}
                        {metric.epoch === bestEpoch ? ' ⭐' : ''}
                        {bestMetricName && typeof metric.primary_metric === 'number' ? ` - ${bestMetricName}: ${metric.primary_metric.toFixed(4)}` : ''}
                        {!metric.checkpoint_path ? ' (체크포인트 없음)' : ''}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
              {!selectedEpoch && (
                <p className="text-xs text-gray-500 mt-1.5">
                  💡 ImageNet, COCO 등으로 사전학습된 가중치를 사용합니다
                </p>
              )}
            </div>

            {/* Task-specific settings */}
            {job.task_type === 'image_classification' && (
              <div className="col-span-2">
                <label className="block text-xs font-medium text-gray-700 mb-2">
                  Top-K Predictions
                </label>
                <input
                  type="number"
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                  min={1}
                  max={10}
                  className={cn(
                    'w-full px-3 py-2 text-sm',
                    'border border-gray-300 rounded-lg',
                    'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent'
                  )}
                />
              </div>
            )}

            {(job.task_type === 'object_detection' || job.task_type === 'instance_segmentation') && (
              <>
                <div className="col-span-2">
                  <label className="block text-xs font-medium text-gray-700 mb-2">
                    Confidence: {confidenceThreshold.toFixed(2)}
                  </label>
                  <input
                    type="range"
                    value={confidenceThreshold}
                    onChange={(e) => setConfidenceThreshold(Number(e.target.value))}
                    min={0}
                    max={1}
                    step={0.05}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-violet-600"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-xs font-medium text-gray-700 mb-2">
                    IoU: {iouThreshold.toFixed(2)}
                  </label>
                  <input
                    type="range"
                    value={iouThreshold}
                    onChange={(e) => setIouThreshold(Number(e.target.value))}
                    min={0}
                    max={1}
                    step={0.05}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-violet-600"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-xs font-medium text-gray-700 mb-2">
                    Max Detections
                  </label>
                  <input
                    type="number"
                    value={maxDetections}
                    onChange={(e) => setMaxDetections(Number(e.target.value))}
                    min={1}
                    max={300}
                    className={cn(
                      'w-full px-3 py-2 text-sm',
                      'border border-gray-300 rounded-lg',
                      'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent'
                    )}
                  />
                </div>
              </>
            )}

            {/* Spacer */}
            {job.task_type !== 'image_classification' &&
             job.task_type !== 'object_detection' &&
             job.task_type !== 'instance_segmentation' && (
              <div className="col-span-6"></div>
            )}

            {/* Run Button */}
            <div className={cn(
              "col-span-3",
              job.task_type === 'image_classification' ? 'col-start-10' : ''
            )}>
              <button
                onClick={runInference}
                disabled={images.length === 0 || isRunning || Boolean(selectedEpoch && !selectedEpoch.checkpoint_path)}
                className={cn(
                  'w-full px-6 py-2.5',
                  'bg-violet-600 hover:bg-violet-700',
                  'text-white font-semibold text-sm',
                  'rounded-lg shadow-md',
                  'transition-all duration-200',
                  'disabled:opacity-40 disabled:cursor-not-allowed',
                  'flex items-center justify-center gap-2'
                )}
              >
                <Play className="w-4 h-4" />
                {isRunning ? '추론 실행 중...' : '추론 시작'}
              </button>
              {images.length === 0 && (
                <p className="text-xs text-gray-500 text-center mt-2">
                  이미지를 업로드하세요
                </p>
              )}
              {!selectedEpoch && images.length > 0 && (
                <p className="text-xs text-green-600 text-center mt-2">
                  ✓ Pretrained weight로 추론 가능
                </p>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Row - Image List (2) + Image Viewer (5) + Results (3) */}
      <div className="grid grid-cols-10 gap-3 h-[600px]">
        {/* Image List - 1 column thumbnails */}
        <div className="col-span-2 bg-white rounded-lg border border-gray-200 p-6 overflow-y-auto">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-xs font-semibold text-gray-900">
              이미지 목록 {images.length > 0 && `(${images.length})`}
            </h4>
            {images.length > 0 && (
              <button
                onClick={handleClearAll}
                className="p-1 text-gray-400 hover:text-red-600 transition-colors"
                title="전체 삭제"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
          {images.length === 0 ? (
            <div className="text-center text-gray-400 py-8">
              <p className="text-xs">업로드된 이미지가 없습니다</p>
            </div>
          ) : (
            <div className="space-y-3">
              {images.map((image) => (
                <div
                  key={image.id}
                  onClick={() => handleImageSelect(image.id)}
                  className={cn(
                    'relative group cursor-pointer rounded-lg border-2 p-2 transition-all',
                    selectedImageId === image.id
                      ? 'border-violet-600 bg-violet-50 shadow-md'
                      : 'border-gray-200 hover:border-gray-300 hover:shadow-sm'
                  )}
                >
                  {/* Image */}
                  <div className="relative">
                    <img
                      src={image.preview}
                      alt={image.file.name}
                      className="w-full h-32 object-cover rounded mb-2"
                    />

                    {/* Status Badge */}
                    <div className="absolute top-1 right-1">
                      <span className={cn(
                        'text-xs px-1.5 py-0.5 rounded font-medium',
                        image.status === 'completed' && 'bg-green-500 text-white',
                        image.status === 'pending' && 'bg-gray-500 text-white',
                        image.status === 'processing' && 'bg-blue-500 text-white',
                        image.status === 'failed' && 'bg-red-500 text-white'
                      )}>
                        {image.status === 'completed' && '✓'}
                        {image.status === 'pending' && '⏳'}
                        {image.status === 'processing' && '⚙️'}
                        {image.status === 'failed' && '✗'}
                      </span>
                    </div>

                    {/* Remove Button */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleImageRemove(image.id)
                      }}
                      className={cn(
                        'absolute top-1 left-1 p-1 rounded-full',
                        'bg-red-500 text-white',
                        'opacity-0 group-hover:opacity-100',
                        'transition-opacity hover:bg-red-600'
                      )}
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>

                  {/* Filename */}
                  <p className="text-xs text-gray-600 truncate" title={image.file.name}>
                    {image.file.name}
                  </p>

                  {/* Error */}
                  {image.error && image.status === 'failed' && (
                    <p className="text-xs text-red-600 mt-1 truncate" title={image.error}>
                      {image.error}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Image Viewer - 5 columns */}
        <div className="col-span-5 bg-white rounded-lg border border-gray-200 p-6">
          <h4 className="text-xs font-semibold text-gray-900 mb-3">이미지 뷰어</h4>
          {selectedImage ? (
            <div className="flex items-center justify-center h-[calc(100%-2rem)] relative">
              <div className="relative">
                <img
                  ref={imageRef}
                  src={selectedImage.preview}
                  alt={selectedImage.file.name}
                  className="max-w-full max-h-full object-contain rounded"
                  onLoad={handleImageLoad}
                />
                <canvas
                  ref={canvasRef}
                  className="absolute top-0 left-0 pointer-events-none"
                  style={{ maxWidth: '100%', maxHeight: '100%' }}
                />
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-[calc(100%-2rem)] text-gray-400">
              <div className="text-center">
                <Upload className="w-12 h-12 mx-auto mb-3 text-gray-300" />
                <p className="text-sm">이미지를 선택하세요</p>
              </div>
            </div>
          )}
        </div>

        {/* Inference Results - 3 columns */}
        <div className="col-span-3 bg-white rounded-lg border border-gray-200 p-6 overflow-y-auto">
          <h4 className="text-xs font-semibold text-gray-900 mb-3">추론 결과</h4>
          {selectedImage?.result ? (
              <div className="space-y-4">
                {/* Performance Metrics */}
                <div className="pb-3 border-b border-gray-200">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-500">추론 시간</span>
                    <span className="font-medium text-gray-900">
                      {selectedImage.result.inference_time_ms?.toFixed(1)}ms
                    </span>
                  </div>
                  {selectedImage.result.preprocessing_time_ms > 0 && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-gray-500">전처리</span>
                      <span className="font-medium text-gray-700">
                        {selectedImage.result.preprocessing_time_ms?.toFixed(1)}ms
                      </span>
                    </div>
                  )}
                </div>

                {/* Classification Results */}
                {selectedImage.result.task_type === 'image_classification' && (
                  <div>
                    <h5 className="text-xs font-semibold text-gray-900 mb-3">예측 결과</h5>
                    <div className="space-y-2">
                      {selectedImage.result.top5_predictions?.map((pred: any, idx: number) => (
                        <div key={idx} className="space-y-1">
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-medium text-gray-900">
                              {idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `${idx + 1}.`} {pred.label}
                            </span>
                            <span className="text-gray-600">{(pred.confidence * 100).toFixed(1)}%</span>
                          </div>
                          <div className="w-full bg-gray-200 rounded-full h-1.5">
                            <div
                              className={cn(
                                'h-1.5 rounded-full',
                                idx === 0 ? 'bg-violet-600' : 'bg-gray-400'
                              )}
                              style={{ width: `${pred.confidence * 100}%` }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Detection Results */}
                {selectedImage.result.task_type === 'object_detection' && (
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <h5 className="text-xs font-semibold text-gray-900">
                        탐지된 객체 ({selectedImage.result.num_detections || 0}개)
                      </h5>
                      {selectedImage.result.task_type === 'instance_segmentation' && (
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={showMasks}
                            onChange={(e) => setShowMasks(e.target.checked)}
                            className="w-4 h-4 text-purple-600 border-gray-300 rounded focus:ring-purple-500"
                          />
                          <span className="text-xs text-gray-600">Mask 표시</span>
                        </label>
                      )}
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={showBoxes}
                          onChange={(e) => setShowBoxes(e.target.checked)}
                          className="w-4 h-4 text-red-600 border-gray-300 rounded focus:ring-red-500"
                        />
                        <span className="text-xs text-gray-600">BBox 표시</span>
                      </label>
                    </div>
                    {selectedImage.result.num_detections === 0 ? (
                      <div className="p-4 bg-gray-50 rounded-lg text-center">
                        <p className="text-xs text-gray-500">검출된 객체가 없습니다</p>
                        <p className="text-xs text-gray-400 mt-1">Confidence threshold를 낮춰보세요</p>
                      </div>
                    ) : (
                    <div className="space-y-3">
                      {selectedImage.result.predicted_boxes?.slice(0, 10).map((box: any, idx: number) => (
                        <div key={idx} className="p-3 bg-gray-50 rounded-lg">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-medium text-gray-900">
                              📦 Object #{idx + 1}
                            </span>
                            <span className="text-xs px-2 py-0.5 bg-violet-100 text-violet-700 rounded">
                              {(box.confidence * 100).toFixed(1)}%
                            </span>
                          </div>
                          <div className="text-xs text-gray-600 space-y-1">
                            <div>Class: <span className="font-medium">{box.label}</span></div>
                            <div className="text-xs text-gray-500">
                              BBox: [{box.x1}, {box.y1}, {box.x2}, {box.y2}]
                            </div>
                          </div>
                        </div>
                      ))}
                      {selectedImage.result.num_detections > 10 && (
                        <p className="text-xs text-gray-500 text-center">
                          ...and {selectedImage.result.num_detections - 10} more
                        </p>
                      )}
                    </div>
                    )}
                  </div>
                )}

                {/* Segmentation Results */}
                {(selectedImage.result.task_type === 'instance_segmentation' ||
                  selectedImage.result.task_type === 'semantic_segmentation') && (
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <h5 className="text-xs font-semibold text-gray-900">
                        분할된 인스턴스 ({selectedImage.result.num_instances || 0}개)
                      </h5>
                      {selectedImage.result.task_type === 'instance_segmentation' && (
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={showMasks}
                            onChange={(e) => setShowMasks(e.target.checked)}
                            className="w-4 h-4 text-purple-600 border-gray-300 rounded focus:ring-purple-500"
                          />
                          <span className="text-xs text-gray-600">Mask 표시</span>
                        </label>
                      )}
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={showBoxes}
                          onChange={(e) => setShowBoxes(e.target.checked)}
                          className="w-4 h-4 text-red-600 border-gray-300 rounded focus:ring-red-500"
                        />
                        <span className="text-xs text-gray-600">BBox 표시</span>
                      </label>
                    </div>
                    {selectedImage.result.num_instances === 0 ? (
                      <div className="p-4 bg-gray-50 rounded-lg text-center">
                        <p className="text-xs text-gray-500">분할된 인스턴스가 없습니다</p>
                        <p className="text-xs text-gray-400 mt-1">Confidence threshold를 낮춰보세요</p>
                      </div>
                    ) : (
                    <div className="space-y-3">
                      {selectedImage.result.predicted_boxes?.slice(0, 10).map((box: any, idx: number) => (
                        <div key={idx} className="p-3 bg-gray-50 rounded-lg">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-medium text-gray-900">
                              🎨 Instance #{idx + 1}
                            </span>
                            <span className="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded">
                              {(box.confidence * 100).toFixed(1)}%
                            </span>
                          </div>
                          <div className="text-xs text-gray-600">
                            Class: <span className="font-medium">{box.label}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                    )}
                  </div>
                )}

                {/* Pose Estimation Results */}
                {selectedImage.result.task_type === 'pose_estimation' && (
                  <div>
                    <h5 className="text-xs font-semibold text-gray-900 mb-3">
                      탐지된 사람 ({selectedImage.result.num_persons}명)
                    </h5>
                    <div className="space-y-3">
                      {selectedImage.result.predicted_keypoints?.slice(0, 5).map((person: any, idx: number) => (
                        <div key={idx} className="p-3 bg-gray-50 rounded-lg">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-medium text-gray-900">
                              🧍 Person #{idx + 1}
                            </span>
                            <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded">
                              {person.keypoints?.length || 0} keypoints
                            </span>
                          </div>
                          <div className="text-xs text-gray-600">
                            Detected: {person.num_detected || 0}/17
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Super-Resolution Results */}
                {selectedImage.result.task_type === 'super_resolution' && (
                  <div>
                    <h5 className="text-xs font-semibold text-gray-900 mb-3">업스케일 결과</h5>
                    <div className="space-y-3">
                      <div className="p-3 bg-gradient-to-br from-violet-50 to-purple-50 rounded-lg border border-violet-200">
                        <div className="text-xs text-gray-700">
                          <span className="font-medium">변환:</span> {selectedImage.result.predicted_label}
                        </div>
                      </div>
                      <div className="text-xs text-gray-500 text-center">
                        💡 이미지를 클릭하여 결과를 비교하세요
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center text-gray-400 py-12">
                <AlertCircle className="w-8 h-8 mx-auto mb-2" />
                <p className="text-xs">추론을 실행하세요</p>
              </div>
            )}
          </div>
        </div>

      {logs.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="flex items-center gap-2 px-6 py-3 border-b border-gray-200">
            <Terminal className="w-4 h-4 text-gray-500" />
            <h3 className="text-sm font-semibold text-gray-900">추론 로그</h3>
            <span className="ml-auto text-xs text-gray-500">{logs.length}개 이벤트</span>
          </div>
          <div className="p-4 overflow-y-auto max-h-60 font-mono text-xs">
            {logs.map((log, index) => (
              <div
                key={index}
                className={cn(
                  'flex items-start gap-3 py-1.5 px-2 rounded mb-1',
                  log.level === 'success' && 'bg-green-50',
                  log.level === 'error' && 'bg-red-50',
                  log.level === 'warning' && 'bg-yellow-50',
                  log.level === 'info' && 'bg-blue-50'
                )}
              >
                {log.level === 'info' && <Info className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />}
                {log.level === 'success' && <CheckCircle className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />}
                {log.level === 'error' && <XCircle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />}
                {log.level === 'warning' && <AlertCircle className="w-4 h-4 text-yellow-600 shrink-0 mt-0.5" />}

                <span
                  className={cn(
                    'px-1.5 py-0.5 rounded text-xs font-medium shrink-0',
                    log.level === 'info' && 'bg-blue-100 text-blue-700',
                    log.level === 'success' && 'bg-green-100 text-green-700',
                    log.level === 'warning' && 'bg-yellow-100 text-yellow-700',
                    log.level === 'error' && 'bg-red-100 text-red-700'
                  )}
                >
                  {log.level === 'info' && 'INFO'}
                  {log.level === 'success' && 'SUCCESS'}
                  {log.level === 'warning' && 'WARN'}
                  {log.level === 'error' && 'ERROR'}
                </span>

                <span
                  className={cn(
                    'flex-1',
                    log.level === 'error' && 'text-red-700',
                    log.level === 'success' && 'text-green-700',
                    log.level === 'warning' && 'text-yellow-700',
                    log.level === 'info' && 'text-gray-700'
                  )}
                >
                  {log.message}
                </span>
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </div>
      )}

      {/* Slide Panel for Super-Resolution Comparison */}
      <SlidePanel
        isOpen={showSlidePanel && !!selectedImage?.result?.upscaled_image_url}
        onClose={() => {
          console.log('[DEBUG] Closing slide panel')
          setShowSlidePanel(false)
        }}
        title="Super-Resolution 결과 비교"
        width="xl"
      >
        {selectedImage?.result && (
          <div className="p-6 space-y-6">
            {/* Metadata */}
            <div className="bg-gradient-to-br from-violet-50 to-purple-50 rounded-lg p-4 border border-violet-200">
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-gray-600">파일명</span>
                  <span className="font-medium text-gray-900">{selectedImage.file.name}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-600">변환</span>
                  <span className="font-medium text-violet-700">{selectedImage.result.predicted_label}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-600">추론 시간</span>
                  <span className="font-medium text-gray-900">{selectedImage.result.inference_time_ms?.toFixed(1)}ms</span>
                </div>
              </div>
            </div>

            {/* Before Image */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-semibold text-gray-900">원본 이미지</h4>
                <span className="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded">Before</span>
              </div>
              <div className="border border-gray-200 rounded-lg overflow-hidden bg-gray-50">
                <img
                  src={selectedImage.preview}
                  alt="Original"
                  className="w-full h-auto"
                />
              </div>
            </div>

            {/* After Image */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-semibold text-gray-900">업스케일된 이미지</h4>
                <span className="text-xs px-2 py-1 bg-green-100 text-green-700 rounded">After</span>
              </div>
              <div className="border border-gray-200 rounded-lg overflow-hidden bg-gray-50">
                <img
                  src={`${process.env.NEXT_PUBLIC_API_URL}${selectedImage.result.upscaled_image_url}`}
                  alt="Upscaled"
                  className="w-full h-auto"
                />
              </div>
            </div>

            {/* Info */}
            <div className="text-xs text-gray-500 bg-gray-50 rounded-lg p-3">
              💡 스크롤하여 두 이미지를 비교하고, 디테일의 차이를 확인하세요.
            </div>
          </div>
        )}
      </SlidePanel>
    </div>
  )
}

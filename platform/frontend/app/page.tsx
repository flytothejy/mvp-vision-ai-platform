'use client'

import { useState, useRef, useEffect } from 'react'
import Sidebar from '@/components/Sidebar'
import ChatPanel from '@/components/ChatPanel'
import TrainingPanel from '@/components/TrainingPanel'
import ProjectDetail from '@/components/ProjectDetail'
import CreateProjectForm from '@/components/CreateProjectForm'
import TrainingConfigPanel from '@/components/TrainingConfigPanel'
import ImageToolsPanel from '@/components/ImageToolsPanel'
import LoginModal from '@/components/LoginModal'
import RegisterModal from '@/components/RegisterModal'
import ProfileModal from '@/components/ProfileModal'
import AdminProjectsPanel from '@/components/AdminProjectsPanel'
import AdminUsersPanel from '@/components/AdminUsersPanel'
import AdminDatasetsPanel from '@/components/AdminDatasetsPanel'
import DatasetPanel from '@/components/DatasetPanel'

interface TrainingConfig {
  framework?: string
  model_name?: string
  task_type?: string
  dataset_path?: string
  dataset_format?: string
  epochs?: number
  batch_size?: number
  learning_rate?: number
}

export default function Home() {
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [trainingJobId, setTrainingJobId] = useState<number | null>(null)
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [previousProjectId, setPreviousProjectId] = useState<number | null>(null) // For back button
  const [isCreatingProject, setIsCreatingProject] = useState(false)
  const [isCreatingTraining, setIsCreatingTraining] = useState(false)
  const [trainingConfig, setTrainingConfig] = useState<TrainingConfig | null>(null)
  const [trainingProjectId, setTrainingProjectId] = useState<number | null>(null)
  const [sidebarKey, setSidebarKey] = useState(0) // For forcing Sidebar refresh
  const [centerWidth, setCenterWidth] = useState(25) // Chat panel width (25%)
  const [isDragging, setIsDragging] = useState(false)
  const [chatCollapsed, setChatCollapsed] = useState(true) // Chat panel collapse state (collapsed by default)
  const containerRef = useRef<HTMLDivElement>(null)

  // Modal states
  const [showLoginModal, setShowLoginModal] = useState(false)
  const [showRegisterModal, setShowRegisterModal] = useState(false)
  const [showProfileModal, setShowProfileModal] = useState(false)

  // Admin panel states
  const [showAdminProjects, setShowAdminProjects] = useState(false)
  const [showAdminUsers, setShowAdminUsers] = useState(false)
  const [showAdminDatasets, setShowAdminDatasets] = useState(false)

  // Image tools state
  const [showImageTools, setShowImageTools] = useState(false)

  // Dataset panel state
  const [showDatasets, setShowDatasets] = useState(false)

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging || !containerRef.current) return

      const containerRect = containerRef.current.getBoundingClientRect()
      const newCenterWidth = ((e.clientX - containerRect.left) / containerRect.width) * 100

      // Clamp between 25% (min) and 50% (max) for chat panel
      const clampedWidth = Math.max(25, Math.min(50, newCenterWidth))
      setCenterWidth(clampedWidth)
    }

    const handleMouseUp = () => {
      setIsDragging(false)
    }

    if (isDragging) {
      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', handleMouseUp)
    }

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging])

  const handleProjectSelect = (projectId: number) => {
    setSelectedProjectId(projectId)
    setIsCreatingProject(false)  // Close create form if open
    setIsCreatingTraining(false) // Close training config if open
    setTrainingJobId(null)       // Close training panel if open
    setShowAdminProjects(false)  // Close admin panels if open
    setShowAdminUsers(false)
    setShowAdminDatasets(false)
    setShowDatasets(false)       // Close dataset panel if open
    setShowImageTools(false)     // Close image tools if open
  }

  const handleCreateProject = () => {
    console.log('handleCreateProject called')
    setPreviousProjectId(selectedProjectId) // Save current project for back button
    setIsCreatingProject(true)
    console.log('isCreatingProject set to true')
    setSelectedProjectId(null)   // Close project detail if open
    setIsCreatingTraining(false) // Close training config if open
    setTrainingJobId(null)       // Close training panel if open
    setShowAdminProjects(false)  // Close admin panels if open
    setShowAdminUsers(false)
    setShowAdminDatasets(false)
    setShowDatasets(false)       // Close dataset panel if open
    setShowImageTools(false)     // Close image tools if open
  }

  const handleProjectCreated = (projectId: number) => {
    setIsCreatingProject(false)
    setPreviousProjectId(null)   // Clear previous project
    setSelectedProjectId(projectId)  // Show the newly created project
    setSidebarKey(prev => prev + 1)  // Force Sidebar to refresh by changing key
  }

  const handleCancelCreateProject = () => {
    setIsCreatingProject(false)
    // Restore previous project if there was one
    if (previousProjectId !== null) {
      setSelectedProjectId(previousProjectId)
      setPreviousProjectId(null)
    }
  }

  const handleStartNewTraining = (projectId?: number) => {
    setTrainingConfig(null) // Clear config for fresh start
    setTrainingProjectId(projectId || null)
    setIsCreatingTraining(true)
    setIsCreatingProject(false)  // Close project creation if open
    setSelectedProjectId(null)   // Close project detail if open
    setTrainingJobId(null)       // Close training panel if open
  }

  const handleCloneExperiment = async (experimentId: number, projectId?: number) => {
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/training/jobs/${experimentId}`)
      if (!response.ok) {
        console.error('Failed to fetch experiment config')
        return
      }

      const experiment = await response.json()

      // Extract config from experiment
      const config: TrainingConfig = {
        framework: experiment.framework,
        model_name: experiment.model_name,
        task_type: experiment.task_type,
        dataset_path: experiment.dataset_path,
        dataset_format: experiment.dataset_format,
        epochs: experiment.config?.epochs,
        batch_size: experiment.config?.batch_size,
        learning_rate: experiment.config?.learning_rate,
      }

      setTrainingConfig(config)
      setTrainingProjectId(projectId || null)
      setIsCreatingTraining(true)
      setIsCreatingProject(false)
      setSelectedProjectId(null)
      setTrainingJobId(null)
    } catch (error) {
      console.error('Error cloning experiment:', error)
    }
  }

  const handleTrainingStarted = (jobId: number) => {
    setIsCreatingTraining(false)
    setTrainingConfig(null)
    setTrainingJobId(jobId)
  }

  const handleCancelTraining = () => {
    setIsCreatingTraining(false)
    setTrainingConfig(null)
  }

  const handleViewExperiment = (experimentId: number) => {
    // Store the current project ID so we can go back
    setPreviousProjectId(selectedProjectId)
    setTrainingJobId(experimentId)
    setSelectedProjectId(null)   // Close project detail
    setIsCreatingTraining(false) // Close training config if open
    setIsCreatingProject(false)  // Close create project if open
  }

  const handleNavigateToExperiments = () => {
    // Go back to project detail from training panel
    setTrainingJobId(null)
    if (previousProjectId !== null) {
      setSelectedProjectId(previousProjectId)
      setPreviousProjectId(null)
    }
  }

  const handleOpenAdminProjects = () => {
    setShowAdminProjects(true)
    setShowAdminUsers(false)
    setShowAdminDatasets(false)
    setShowDatasets(false)
    setShowImageTools(false)
    setSelectedProjectId(null)
    setIsCreatingProject(false)
    setIsCreatingTraining(false)
    setTrainingJobId(null)
  }

  const handleOpenAdminUsers = () => {
    setShowAdminUsers(true)
    setShowAdminProjects(false)
    setShowAdminDatasets(false)
    setShowDatasets(false)
    setShowImageTools(false)
    setSelectedProjectId(null)
    setIsCreatingProject(false)
    setIsCreatingTraining(false)
    setTrainingJobId(null)
  }

  const handleOpenAdminDatasets = () => {
    setShowAdminDatasets(true)
    setShowAdminUsers(false)
    setShowAdminProjects(false)
    setShowDatasets(false)
    setShowImageTools(false)
    setSelectedProjectId(null)
    setIsCreatingProject(false)
    setIsCreatingTraining(false)
    setTrainingJobId(null)
  }

  const handleOpenImageTools = () => {
    setShowImageTools(true)
    setShowAdminProjects(false)
    setShowAdminUsers(false)
    setShowAdminDatasets(false)
    setShowDatasets(false)
    setSelectedProjectId(null)
    setIsCreatingProject(false)
    setIsCreatingTraining(false)
    setTrainingJobId(null)
  }

  const handleOpenDatasets = async () => {
    // Platform → Labeler SSO flow (Phase 11.5.6)
    try {
      const token = localStorage.getItem('access_token')
      if (!token) {
        console.error('No access token found')
        return
      }

      // Get service token for SSO
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/auth/labeler-token`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      })

      if (!response.ok) {
        console.error('Failed to get labeler token:', response.status)
        return
      }

      const data = await response.json()
      const labelerUrl = process.env.NEXT_PUBLIC_LABELER_URL || 'http://localhost:8011'

      // Redirect to Labeler with service token (full API path)
      window.location.href = `${labelerUrl}/api/v1/auth/sso?token=${data.service_token}`
    } catch (error) {
      console.error('Failed to redirect to Labeler:', error)
    }
  }

  const handleLogout = () => {
    // Reset all workspace states when logging out
    setShowImageTools(false)
    setShowAdminUsers(false)
    setShowAdminProjects(false)
    setShowAdminDatasets(false)
    setShowDatasets(false)
    setSelectedProjectId(null)
    setIsCreatingProject(false)
    setIsCreatingTraining(false)
    setTrainingJobId(null)
  }

  return (
    <div className="h-screen flex">
      {/* Sidebar - Fixed Left */}
      <Sidebar
        key={sidebarKey}
        onProjectSelect={handleProjectSelect}
        selectedProjectId={selectedProjectId}
        onCreateProject={handleCreateProject}
        onOpenImageTools={handleOpenImageTools}
        onOpenDatasets={handleOpenDatasets}
        onOpenLogin={() => setShowLoginModal(true)}
        onOpenRegister={() => setShowRegisterModal(true)}
        onOpenProfile={() => setShowProfileModal(true)}
        onOpenAdminProjects={handleOpenAdminProjects}
        onOpenAdminUsers={handleOpenAdminUsers}
        onOpenAdminDatasets={handleOpenAdminDatasets}
        onLogout={handleLogout}
      />

      {/* Main Content Area - 3 Column Layout */}
      <main ref={containerRef} className="flex-1 flex overflow-hidden relative">
        {/* Chat Panel - Center (Resizable) - Conditionally rendered */}
        {!chatCollapsed && (
          <>
            <div
              style={{ width: `${centerWidth}%` }}
              className="border-r border-gray-200"
            >
              <ChatPanel
                sessionId={sessionId}
                onSessionCreated={setSessionId}
                onTrainingRequested={setTrainingJobId}
                onProjectSelected={handleProjectSelect}
                onCollapse={() => setChatCollapsed(true)}
              />
            </div>

            {/* Resizer */}
            <div
              onMouseDown={handleMouseDown}
              className={`w-1 bg-gray-200 hover:bg-violet-400 cursor-col-resize transition-colors relative group ${
                isDragging ? 'bg-violet-500' : ''
              }`}
            >
              <div className="absolute inset-y-0 -left-1 -right-1" />
            </div>
          </>
        )}

        {/* Workspace Panel - Right (Dynamic Content) */}
        <div style={{ width: chatCollapsed ? '100%' : `${100 - centerWidth}%` }} className="flex-1 relative">
          {/* Circular expand button when chat is collapsed */}
          {chatCollapsed && (
            <button
              onClick={() => setChatCollapsed(false)}
              className="absolute bottom-6 left-6 w-14 h-14 bg-violet-600 text-white rounded-full shadow-lg hover:bg-violet-700 hover:shadow-xl transition-all duration-200 z-50 flex items-center justify-center group"
              title="채팅 패널 열기"
            >
              <svg
                className="w-6 h-6 transform group-hover:scale-110 transition-transform"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                />
              </svg>
            </button>
          )}

          {showDatasets ? (
            // Show dataset panel
            <DatasetPanel />
          ) : showImageTools ? (
            // Show image tools panel
            <ImageToolsPanel />
          ) : showAdminProjects ? (
            // Show admin projects panel
            <AdminProjectsPanel />
          ) : showAdminUsers ? (
            // Show admin users panel
            <AdminUsersPanel />
          ) : showAdminDatasets ? (
            // Show admin datasets panel
            <AdminDatasetsPanel />
          ) : isCreatingProject ? (
            // Show create project form
            <CreateProjectForm
              onCancel={handleCancelCreateProject}
              onProjectCreated={handleProjectCreated}
            />
          ) : isCreatingTraining ? (
            // Show training config panel
            <TrainingConfigPanel
              projectId={trainingProjectId}
              initialConfig={trainingConfig}
              onCancel={handleCancelTraining}
              onTrainingStarted={handleTrainingStarted}
            />
          ) : selectedProjectId ? (
            // Show project detail when project is selected
            <ProjectDetail
              projectId={selectedProjectId}
              onBack={() => setSelectedProjectId(null)}
              onStartNewTraining={handleStartNewTraining}
              onCloneExperiment={handleCloneExperiment}
              onViewExperiment={handleViewExperiment}
            />
          ) : trainingJobId ? (
            // Show training panel when training job exists
            <TrainingPanel trainingJobId={trainingJobId} onNavigateToExperiments={handleNavigateToExperiments} />
          ) : (
            // Default empty state
            <div className="h-full flex items-center justify-center bg-gray-50">
              <div className="text-center text-gray-500">
                <p className="text-sm">작업 공간</p>
                <p className="text-xs mt-1 text-gray-400">
                  프로젝트를 선택하거나 학습을 시작하세요
                </p>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Modals */}
      <LoginModal
        isOpen={showLoginModal}
        onClose={() => setShowLoginModal(false)}
        onSwitchToRegister={() => {
          setShowLoginModal(false)
          setShowRegisterModal(true)
        }}
      />

      <RegisterModal
        isOpen={showRegisterModal}
        onClose={() => setShowRegisterModal(false)}
        onSwitchToLogin={() => {
          setShowRegisterModal(false)
          setShowLoginModal(true)
        }}
      />

      <ProfileModal
        isOpen={showProfileModal}
        onClose={() => setShowProfileModal(false)}
      />
    </div>
  )
}

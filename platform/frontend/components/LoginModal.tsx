'use client'

import { useState } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/utils/cn'
import Modal from './Modal'

interface LoginModalProps {
  isOpen: boolean
  onClose: () => void
  onSwitchToRegister?: () => void
}

export default function LoginModal({
  isOpen,
  onClose,
  onSwitchToRegister,
}: LoginModalProps) {
  const { login } = useAuth()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      await login(email, password)
      // Reset form
      setEmail('')
      setPassword('')
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSwitchToRegister = () => {
    setEmail('')
    setPassword('')
    setError('')
    onSwitchToRegister?.()
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="로그인" size="sm">
      {/* Error Message */}
      {error && (
        <div className="mb-6 p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
          <div className="text-sm text-red-400 whitespace-pre-line">
            {error}
          </div>
        </div>
      )}

      {/* Login Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label htmlFor="email" className="block text-sm font-medium text-gray-300 mb-2">
            이메일
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className={cn(
              'w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg',
              'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
              'text-white placeholder-gray-500'
            )}
            placeholder="your@email.com"
          />
        </div>

        <div>
          <label htmlFor="password" className="block text-sm font-medium text-gray-300 mb-2">
            비밀번호
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className={cn(
              'w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg',
              'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
              'text-white placeholder-gray-500'
            )}
            placeholder="••••••••"
          />
        </div>

        <button
          type="submit"
          disabled={isLoading}
          className={cn(
            'w-full py-3 px-4 rounded-lg font-semibold',
            'bg-violet-600 hover:bg-violet-700 text-white',
            'transition-all duration-200',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            'shadow-lg hover:shadow-xl'
          )}
        >
          {isLoading ? '로그인 중...' : '로그인'}
        </button>
      </form>

      {/* Divider */}
      <div className="mt-6 pt-6 border-t border-gray-800">
        <p className="text-center text-sm text-gray-400">
          계정이 없으신가요?{' '}
          <button
            onClick={handleSwitchToRegister}
            className="font-semibold text-violet-400 hover:text-violet-300"
          >
            회원가입
          </button>
        </p>
      </div>

      {/* Demo Credentials */}
      <div className="mt-4 p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg">
        <p className="text-xs text-blue-400 font-medium mb-2">데모 계정:</p>
        <p className="text-xs text-blue-300">
          이메일: admin@example.com<br />
          비밀번호: admin123
        </p>
      </div>
    </Modal>
  )
}

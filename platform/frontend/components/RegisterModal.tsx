'use client'

import { useState } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { cn } from '@/lib/utils/cn'
import Modal from './Modal'

interface RegisterModalProps {
  isOpen: boolean
  onClose: () => void
  onSwitchToLogin?: () => void
}

const COMPANIES = ['삼성전자', '협력사', '직접 입력']
const DIVISIONS = ['생산기술연구소', 'MX', 'VD', 'DA', 'SR', '직접 입력']

export default function RegisterModal({
  isOpen,
  onClose,
  onSwitchToLogin,
}: RegisterModalProps) {
  const { register } = useAuth()

  // Basic fields
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [fullName, setFullName] = useState('')

  // Organization fields
  const [company, setCompany] = useState('')
  const [companyCustom, setCompanyCustom] = useState('')
  const [division, setDivision] = useState('')
  const [divisionCustom, setDivisionCustom] = useState('')
  const [department, setDepartment] = useState('')

  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    // Validation
    if (password.length < 8) {
      setError('비밀번호는 최소 8자 이상이어야 합니다')
      return
    }

    if (password !== confirmPassword) {
      setError('비밀번호가 일치하지 않습니다')
      return
    }

    if (company === '직접 입력' && !companyCustom) {
      setError('회사명을 입력해주세요')
      return
    }

    if (division === '직접 입력' && !divisionCustom) {
      setError('사업부명을 입력해주세요')
      return
    }

    setIsLoading(true)

    try {
      await register({
        email,
        password,
        full_name: fullName || undefined,
        company: company || undefined,
        company_custom: company === '직접 입력' ? companyCustom : undefined,
        division: division || undefined,
        division_custom: division === '직접 입력' ? divisionCustom : undefined,
        department: department || undefined,
      })
      // Reset form
      setEmail('')
      setPassword('')
      setConfirmPassword('')
      setFullName('')
      setCompany('')
      setCompanyCustom('')
      setDivision('')
      setDivisionCustom('')
      setDepartment('')
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSwitchToLogin = () => {
    setEmail('')
    setPassword('')
    setConfirmPassword('')
    setFullName('')
    setCompany('')
    setCompanyCustom('')
    setDivision('')
    setDivisionCustom('')
    setDepartment('')
    setError('')
    onSwitchToLogin?.()
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="회원가입" size="md">
      <div className="max-h-[70vh] overflow-y-auto pr-2">
        {/* Error Message */}
        {error && (
          <div className="mb-6 p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
            <div className="text-sm text-red-400 whitespace-pre-line">
              {error}
            </div>
          </div>
        )}

        {/* Register Form */}
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Basic Information */}
          <div className="space-y-4">
            <h3 className="text-sm font-semibold text-gray-300">기본 정보</h3>

            <div>
              <label htmlFor="fullName" className="block text-sm font-medium text-gray-300 mb-2">
                이름
              </label>
              <input
                id="fullName"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className={cn(
                  'w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg',
                  'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
                  'text-white placeholder-gray-500'
                )}
                placeholder="홍길동"
              />
            </div>

            <div>
              <label htmlFor="reg-email" className="block text-sm font-medium text-gray-300 mb-2">
                이메일 *
              </label>
              <input
                id="reg-email"
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
              <label htmlFor="reg-password" className="block text-sm font-medium text-gray-300 mb-2">
                비밀번호 * (최소 8자)
              </label>
              <input
                id="reg-password"
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

            <div>
              <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-300 mb-2">
                비밀번호 확인 *
              </label>
              <input
                id="confirmPassword"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                className={cn(
                  'w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg',
                  'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
                  'text-white placeholder-gray-500'
                )}
                placeholder="••••••••"
              />
            </div>
          </div>

          {/* Organization Information */}
          <div className="space-y-4 pt-4 border-t border-gray-800">
            <h3 className="text-sm font-semibold text-gray-300">조직 정보</h3>

            <div>
              <label htmlFor="company" className="block text-sm font-medium text-gray-300 mb-2">
                회사
              </label>
              <select
                id="company"
                value={company}
                onChange={(e) => setCompany(e.target.value)}
                className={cn(
                  'w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg',
                  'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
                  'text-white'
                )}
              >
                <option value="">선택하세요</option>
                {COMPANIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>

            {company === '직접 입력' && (
              <div>
                <label htmlFor="companyCustom" className="block text-sm font-medium text-gray-300 mb-2">
                  회사명 입력
                </label>
                <input
                  id="companyCustom"
                  type="text"
                  value={companyCustom}
                  onChange={(e) => setCompanyCustom(e.target.value)}
                  className={cn(
                    'w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg',
                    'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
                    'text-white placeholder-gray-500'
                  )}
                  placeholder="회사명을 입력하세요"
                />
              </div>
            )}

            <div>
              <label htmlFor="division" className="block text-sm font-medium text-gray-300 mb-2">
                사업부
              </label>
              <select
                id="division"
                value={division}
                onChange={(e) => setDivision(e.target.value)}
                className={cn(
                  'w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg',
                  'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
                  'text-white'
                )}
              >
                <option value="">선택하세요</option>
                {DIVISIONS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>

            {division === '직접 입력' && (
              <div>
                <label htmlFor="divisionCustom" className="block text-sm font-medium text-gray-300 mb-2">
                  사업부명 입력
                </label>
                <input
                  id="divisionCustom"
                  type="text"
                  value={divisionCustom}
                  onChange={(e) => setDivisionCustom(e.target.value)}
                  className={cn(
                    'w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg',
                    'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
                    'text-white placeholder-gray-500'
                  )}
                  placeholder="사업부명을 입력하세요"
                />
              </div>
            )}

            <div>
              <label htmlFor="department" className="block text-sm font-medium text-gray-300 mb-2">
                부서
              </label>
              <input
                id="department"
                type="text"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                className={cn(
                  'w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-lg',
                  'focus:outline-none focus:ring-2 focus:ring-violet-600 focus:border-transparent',
                  'text-white placeholder-gray-500'
                )}
                placeholder="개발팀"
              />
            </div>
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
            {isLoading ? '회원가입 중...' : '회원가입'}
          </button>
        </form>

        {/* Divider */}
        <div className="mt-6 pt-6 border-t border-gray-800">
          <p className="text-center text-sm text-gray-400">
            이미 계정이 있으신가요?{' '}
            <button
              onClick={handleSwitchToLogin}
              className="font-semibold text-violet-400 hover:text-violet-300"
            >
              로그인
            </button>
          </p>
        </div>
      </div>
    </Modal>
  )
}

'use client'

import React, { createContext, useContext, useState, useEffect } from 'react'

interface User {
  id: number
  email: string
  full_name: string | null
  is_active: boolean
  system_role: string  // '''guest''' | '''standard_engineer''' | '''advanced_engineer''' | '''manager''' | '''admin'''
  badge_color?: string | null
  company?: string | null
  division?: string | null
  department?: string | null
  phone_number?: string | null
  bio?: string | null
}

interface RegisterData {
  email: string
  password: string
  full_name?: string
  company?: string
  company_custom?: string
  division?: string
  division_custom?: string
  department?: string
  phone_number?: string
  bio?: string
}

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (data: RegisterData) => Promise<void>
  logout: () => void
  refreshToken: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Check for existing token on mount
  useEffect(() => {
    const checkAuth = async () => {
      const token = localStorage.getItem('access_token')
      if (token) {
        try {
          // Fetch current user info
          const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/auth/me`, {
            headers: {
              'Authorization': `Bearer ${token}`
            }
          })

          if (response.ok) {
            const userData = await response.json()
            setUser(userData)
          } else {
            // Token invalid, clear it
            localStorage.removeItem('access_token')
            localStorage.removeItem('refresh_token')
          }
        } catch (error) {
          console.error('Error checking auth:', error)
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
        }
      }
      setIsLoading(false)
    }

    checkAuth()
  }, [])

  const login = async (email: string, password: string) => {
    // OAuth2 format requires FormData with 'username' and 'password' fields
    const formData = new FormData()
    formData.append('username', email)  // OAuth2 uses 'username' field for email
    formData.append('password', password)

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/auth/login`, {
        method: 'POST',
        body: formData
      })

      if (!response.ok) {
        let errorMessage = 'Login failed'

        try {
          const error = await response.json()

          // Customize error messages based on status code
          if (response.status === 503) {
            errorMessage = '🔌 데이터베이스 서버에 연결할 수 없습니다.\n\nPostgreSQL이 실행 중인지 확인해주세요 (포트 5433).'
          } else if (response.status === 500) {
            errorMessage = '⚠️ 서버 내부 오류가 발생했습니다.\n\n' + (error.detail || 'Backend 로그를 확인해주세요.')
          } else if (response.status === 401) {
            errorMessage = '🔒 이메일 또는 비밀번호가 올바르지 않습니다.'
          } else if (response.status === 400) {
            errorMessage = error.detail || 'Invalid request'
          } else {
            errorMessage = error.detail || `Server error (${response.status})`
          }
        } catch (e) {
          // If response body is not JSON
          errorMessage = `서버 오류 (${response.status}): ${response.statusText}`
        }

        throw new Error(errorMessage)
      }

      const data = await response.json()

      // Store tokens
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)

      // Fetch user info
      const userResponse = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/auth/me`, {
        headers: {
          'Authorization': `Bearer ${data.access_token}`
        }
      })

      if (userResponse.ok) {
        const userData = await userResponse.json()
        setUser(userData)
      }
    } catch (error) {
      // Network error (server not running, CORS, etc.)
      if (error instanceof TypeError && error.message.includes('fetch')) {
        throw new Error('🌐 Backend 서버에 연결할 수 없습니다.\n\nBackend가 실행 중인지 확인해주세요 (http://localhost:8000).')
      }

      // Re-throw if it's already our custom error
      throw error
    }
  }

  const register = async (data: RegisterData) => {
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/auth/register`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
      })

      if (!response.ok) {
        let errorMessage = 'Registration failed'

        try {
          const error = await response.json()

          // Customize error messages based on status code
          if (response.status === 503) {
            errorMessage = '🔌 데이터베이스 서버에 연결할 수 없습니다.\n\nPostgreSQL이 실행 중인지 확인해주세요 (포트 5433).'
          } else if (response.status === 500) {
            errorMessage = '⚠️ 서버 내부 오류가 발생했습니다.\n\n' + (error.detail || 'Backend 로그를 확인해주세요.')
          } else if (response.status === 400) {
            errorMessage = error.detail || 'Invalid registration data'
          } else if (response.status === 409) {
            errorMessage = '이미 등록된 이메일입니다.'
          } else {
            errorMessage = error.detail || `Server error (${response.status})`
          }
        } catch (e) {
          // If response body is not JSON
          errorMessage = `서버 오류 (${response.status}): ${response.statusText}`
        }

        throw new Error(errorMessage)
      }

      // Auto-login after registration
      await login(data.email, data.password)
    } catch (error) {
      // Network error (server not running, CORS, etc.)
      if (error instanceof TypeError && error.message.includes('fetch')) {
        throw new Error('🌐 Backend 서버에 연결할 수 없습니다.\n\nBackend가 실행 중인지 확인해주세요 (http://localhost:8000).')
      }

      // Re-throw if it's already our custom error
      throw error
    }
  }

  const logout = () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    setUser(null)
  }

  const refreshToken = async () => {
    const refresh = localStorage.getItem('refresh_token')
    if (!refresh) {
      logout()
      return
    }

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/auth/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ refresh_token: refresh })
      })

      if (response.ok) {
        const data = await response.json()
        localStorage.setItem('access_token', data.access_token)
        localStorage.setItem('refresh_token', data.refresh_token)
      } else {
        logout()
      }
    } catch (error) {
      console.error('Error refreshing token:', error)
      logout()
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        register,
        logout,
        refreshToken
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

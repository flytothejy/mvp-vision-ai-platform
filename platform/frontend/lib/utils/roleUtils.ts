/**
 * Global role utility functions for consistent role display across the application
 */

export type SystemRole = 'guest' | 'standard_engineer' | 'advanced_engineer' | 'manager' | 'admin'

/**
 * Get the Korean label for a system role
 */
export function getRoleLabel(role: string): string {
  switch (role) {
    case 'guest':
      return '게스트'
    case 'standard_engineer':
      return '엔지니어(기본)'
    case 'advanced_engineer':
      return '엔지니어(고급)'
    case 'manager':
      return '매니저'
    case 'admin':
      return '관리자'
    default:
      return role
  }
}

/**
 * Get the Tailwind CSS classes for role badge colors
 */
export function getRoleBadgeColor(role: string): string {
  switch (role) {
    case 'guest':
      return 'bg-gray-100 text-gray-700'
    case 'standard_engineer':
      return 'bg-blue-100 text-blue-700'
    case 'advanced_engineer':
      return 'bg-green-100 text-green-700'
    case 'manager':
      return 'bg-orange-100 text-orange-700'
    case 'admin':
      return 'bg-violet-100 text-violet-700'
    default:
      return 'bg-gray-100 text-gray-700'
  }
}

/**
 * Get the shorter role label for sidebar display (without parentheses)
 */
export function getRoleLabelShort(role?: string): string {
  return getRoleLabel(role || 'guest')
}

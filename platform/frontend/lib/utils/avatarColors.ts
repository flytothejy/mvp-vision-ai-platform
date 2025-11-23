/**
 * Avatar badge color utilities
 *
 * Provides consistent solid colors for user avatar badges based on the badge_color field.
 * Colors are assigned randomly during user registration and remain consistent for each user.
 */

export type AvatarColor =
  | 'red' | 'orange' | 'green' | 'emerald'
  | 'teal' | 'cyan' | 'sky' | 'blue'
  | 'indigo' | 'violet' | 'purple' | 'fuchsia' | 'pink'

/**
 * Get inline style object for avatar badge background
 * Supports both hex colors (#0EA5E9) and legacy Tailwind color names (sky)
 */
export function getAvatarColorStyle(color: string | null | undefined): { backgroundColor: string } {
  // If color is already a hex value, use it directly
  if (color && color.startsWith('#')) {
    return { backgroundColor: color }
  }

  // Legacy Tailwind color name mapping (for backwards compatibility)
  const colors: Record<string, string> = {
    red: '#EF4444',       // red-500
    orange: '#F97316',    // orange-500
    green: '#22C55E',     // green-500
    emerald: '#10B981',   // emerald-500
    teal: '#14B8A6',      // teal-500
    cyan: '#06B6D4',      // cyan-500
    sky: '#0EA5E9',       // sky-500
    blue: '#3B82F6',      // blue-500
    indigo: '#6366F1',    // indigo-500
    violet: '#8B5CF6',    // violet-500
    purple: '#A855F7',    // purple-500
    fuchsia: '#D946EF',   // fuchsia-500
    pink: '#EC4899',      // pink-500
  }

  const bgColor = colors[color || ''] || colors.violet
  return { backgroundColor: bgColor }
}

/**
 * @deprecated Use getAvatarColorStyle instead
 */
export function getAvatarColor(color: string | null | undefined): string {
  // This function is kept for compatibility but won't work with Tailwind JIT
  return 'bg-violet-600'
}

/**
 * @deprecated Use getAvatarColorStyle instead
 */
export function getAvatarGradient(color: string | null | undefined): string {
  return getAvatarColor(color)
}

/**
 * Get Tailwind ring color classes for avatar badge hover effect
 * Note: Returns a neutral ring color since hex colors cannot be dynamically mapped to Tailwind classes
 */
export function getAvatarRingColor(color: string | null | undefined): string {
  // Use a neutral semi-transparent white ring that works with any background color
  return 'hover:ring-white/20'
}

/**
 * Get complete avatar badge classes including background color and ring
 */
export function getAvatarBadgeClasses(color: string | null | undefined): string {
  const bgColor = getAvatarColor(color)
  const ring = getAvatarRingColor(color)

  return `${bgColor} ${ring}`
}

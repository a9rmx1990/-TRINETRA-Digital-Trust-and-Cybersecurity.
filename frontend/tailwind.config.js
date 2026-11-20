/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['IBM Plex Sans', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['IBM Plex Mono', 'ui-monospace', 'monospace'],
      },
      colors: {
        // Brand
        brand: {
          DEFAULT: '#6366f1',
          dim: '#4f52c8',
          glow: 'rgba(99,102,241,0.25)',
        },
        // Surfaces (OLED dark)
        surface: {
          0: '#000000',
          1: '#0a0a0f',
          2: '#111118',
          3: '#18181f',
          4: '#1e1e28',
          border: 'rgba(255,255,255,0.07)',
          'border-hover': 'rgba(255,255,255,0.14)',
        },
        // Status
        allow:  { DEFAULT: '#10b981', dim: '#064e3b', glow: 'rgba(16,185,129,0.2)' },
        hold:   { DEFAULT: '#f43f5e', dim: '#4c0519', glow: 'rgba(244,63,94,0.25)' },
        stepup: { DEFAULT: '#f59e0b', dim: '#451a03', glow: 'rgba(245,158,11,0.2)' },
        // Legacy alias for existing components
        border: 'rgba(255,255,255,0.07)',
      },
      backgroundImage: {
        'gradient-brand': 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
        'gradient-surface': 'linear-gradient(180deg, #0a0a0f 0%, #000000 100%)',
        'noise': "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E\")",
      },
      boxShadow: {
        'brand': '0 0 0 1px rgba(99,102,241,0.3), 0 0 20px rgba(99,102,241,0.15)',
        'brand-sm': '0 0 0 1px rgba(99,102,241,0.2), 0 0 8px rgba(99,102,241,0.1)',
        'glow-allow': '0 0 20px rgba(16,185,129,0.15)',
        'glow-hold': '0 0 20px rgba(244,63,94,0.2)',
        'glow-stepup': '0 0 20px rgba(245,158,11,0.15)',
        'glass': '0 1px 0 0 rgba(255,255,255,0.05) inset, 0 -1px 0 0 rgba(0,0,0,0.3) inset',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'slide-in-right': {
          '0%': { opacity: '0', transform: 'translateX(16px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        'hold-pulse': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(244,63,94,0.5)' },
          '50%': { boxShadow: '0 0 0 6px rgba(244,63,94,0)' },
        },
        'shimmer': {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        'blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.3' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.35s cubic-bezier(0.16, 1, 0.3, 1) both',
        'fade-in': 'fade-in 0.25s ease both',
        'slide-in-right': 'slide-in-right 0.3s cubic-bezier(0.16, 1, 0.3, 1) both',
        'hold-pulse': 'hold-pulse 1.6s ease-in-out infinite',
        'shimmer': 'shimmer 2s linear infinite',
        'blink': 'blink 1.4s ease-in-out infinite',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
}

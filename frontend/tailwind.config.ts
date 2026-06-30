import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ae: {
          bg: '#0a0a1a',
          card: '#12122a',
          border: '#1e1e3a',
          accent: '#6C5CE7',
          'accent-bright': '#A29BFE',
          cyan: '#00D2FF',
          green: '#00E676',
          gray: '#9CA3AF',
          'gray-dark': '#4B5563',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'fade-in-up': 'fadeInUp 0.6s ease-out both',
        'fade-in-down': 'fadeInDown 0.6s ease-out both',
        float: 'float 6s ease-in-out infinite',
        'pulse-glow': 'pulseGlow 3s ease-in-out infinite',
        'pulse-slow': 'pulse 4s ease-in-out infinite',
      },
      keyframes: {
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        fadeInDown: {
          '0%': { opacity: '0', transform: 'translateY(-10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-12px)' },
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 15px rgba(108,92,231,0.3)' },
          '50%': { boxShadow: '0 0 30px rgba(108,92,231,0.6)' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config

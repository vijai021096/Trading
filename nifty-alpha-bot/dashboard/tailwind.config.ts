import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:       '#080b14',
        panel:    '#0f1221',
        card:     '#151929',
        cardHigh: '#1c2035',
        line:     '#252d45',
        lineHi:   '#2f3856',
        accent:   '#5b7bf7',
        accentDim:'#1a2354',
        green:    '#00d97e',
        greenDim: '#00230f',
        red:      '#ff4d6a',
        redDim:   '#2a0812',
        amber:    '#fbbf24',
        amberDim: '#2a1800',
        sky:      '#38bdf8',
        text1:    '#e8eaf2',
        text2:    '#9ba3bf',
        text3:    '#4b5473',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s ease-in-out infinite',
        'fade-in': 'fadeIn 0.2s ease-out',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config

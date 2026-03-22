import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  safelist: [
    { pattern: /bg-(green|red|amber|cyan|accent)\/(5|8|10|12|15|20)/ },
    { pattern: /border-(green|red|amber|cyan|accent)\/(15|20|25|30)/ },
    { pattern: /border-l-(green|red|amber|cyan|accent)/ },
    { pattern: /text-(green|red|amber|cyan|accent|green-l|red-l|accent-l)/ },
  ],
  theme: {
    extend: {
      colors: {
        bg:       '#0a0f1e',
        surface:  '#111827',
        panel:    '#151c32',
        card:     '#1a2140',
        'card-hi':'#212b52',
        line:     '#2a3460',
        'line-hi':'#364078',
        accent:   '#6366f1',
        'accent-d':'#312e81',
        'accent-l':'#a5b4fc',
        cyan:     '#22d3ee',
        'cyan-d': '#0e4a5a',
        green:    '#22c55e',
        'green-l':'#86efac',
        'green-d':'#052e16',
        red:      '#ef4444',
        'red-l':  '#fca5a5',
        'red-d':  '#450a0a',
        amber:    '#f59e0b',
        'amber-d':'#451a03',
        text1:    '#f1f5f9',
        text2:    '#a0aec0',
        text3:    '#5a6a8a',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        'xs':   ['13px', '18px'],
        'sm':   ['14px', '20px'],
        'base': ['15px', '22px'],
        'lg':   ['17px', '24px'],
        'xl':   ['20px', '28px'],
        '2xl':  ['24px', '32px'],
        '3xl':  ['30px', '38px'],
        '4xl':  ['36px', '44px'],
      },
      animation: {
        'fade-up':    'fadeUp 0.5s cubic-bezier(0.16,1,0.3,1) both',
        'fade-in':    'fadeIn 0.4s ease-out both',
        'pulse-slow': 'pulse 3s ease-in-out infinite',
        'glow-pulse': 'glowPulse 2.5s ease-in-out infinite',
      },
      keyframes: {
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        glowPulse: {
          '0%,100%': { opacity: '0.5' },
          '50%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config

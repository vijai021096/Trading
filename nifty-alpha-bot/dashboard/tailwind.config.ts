import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  safelist: [
    { pattern: /bg-(green|red|amber|cyan|accent|gold)\/(5|8|10|12|15|20|25)/ },
    { pattern: /border-(green|red|amber|cyan|accent|gold)\/(10|15|20|25|30|40)/ },
    { pattern: /border-l-(green|red|amber|cyan|accent|gold)/ },
    { pattern: /text-(green|red|amber|cyan|accent|gold|green-l|red-l|accent-l|cyan-l)/ },
  ],
  theme: {
    extend: {
      colors: {
        // ── Backgrounds ──────────────────────────────────────────
        bg:       '#050810',  // near-black with cool tint
        surface:  '#0a1020',  // dark navy base
        panel:    '#0e1629',  // mid-level panels
        card:     '#121e34',  // cards
        'card-hi':'#172540',  // highlighted / hover cards
        line:     '#1b2d4a',  // subtle borders
        'line-hi':'#243d62',  // hover borders

        // ── Accent = AMBER (Bloomberg-style gold) ────────────────
        accent:   '#f59e0b',  // amber primary ★
        'accent-d':'#6f3b04', // dark amber
        'accent-l':'#fde68a', // light amber
        gold:     '#d97706',  // slightly darker gold

        // ── Status colors ────────────────────────────────────────
        cyan:     '#22d3ee',
        'cyan-l': '#a5f3fc',
        'cyan-d': '#0b3f4e',
        green:    '#22c55e',
        'green-l':'#86efac',
        'green-d':'#052e16',
        red:      '#ef4444',
        'red-l':  '#fca5a5',
        'red-d':  '#450a0a',
        amber:    '#f97316',  // orange-amber (warning/paper badges)
        'amber-d':'#431407',

        // ── Typography ───────────────────────────────────────────
        text1:    '#eef2ff',  // near white with blue cast
        text2:    '#8fa8c8',  // muted blue-gray
        text3:    '#3d5478',  // very muted
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', '"Cascadia Code"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        'xs':  ['12px', '16px'],
        'sm':  ['13px', '18px'],
        'base':['15px', '22px'],
        'lg':  ['17px', '24px'],
        'xl':  ['20px', '28px'],
        '2xl': ['24px', '32px'],
        '3xl': ['30px', '38px'],
        '4xl': ['36px', '44px'],
      },
      animation: {
        'fade-up':    'fadeUp 0.4s cubic-bezier(0.16,1,0.3,1) both',
        'fade-in':    'fadeIn 0.3s ease-out both',
        'pulse-slow': 'pulse 3s ease-in-out infinite',
        'glow-pulse': 'glowPulse 2s ease-in-out infinite',
        'scan':       'scan 2s ease-in-out infinite',
      },
      keyframes: {
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        glowPulse: {
          '0%,100%': { opacity: '0.6' },
          '50%': { opacity: '1' },
        },
        scan: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(400%)' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config
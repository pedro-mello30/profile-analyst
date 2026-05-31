import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        base:    '#090A0F',
        surface: '#10111A',
        elevated:'#181921',
        overlay: '#1E1F2A',
        amber:   '#E8B84B',
        teal:    '#2DD4BF',
        red:     '#F87171',
        blue:    '#60A5FA',
      },
      fontFamily: {
        display: ['Syne', 'sans-serif'],
        mono:    ['JetBrains Mono', 'monospace'],
        body:    ['Manrope', 'sans-serif'],
      },
      borderColor: {
        DEFAULT: 'rgba(255,255,255,0.06)',
      },
    },
  },
  plugins: [],
} satisfies Config

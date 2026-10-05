/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Deep clinical navy — the base canvas
        canvas: {
          DEFAULT: '#0a0e17',
          soft: '#0f1420',
          raised: '#141b2b',
          hover: '#1a2233',
        },
        // Primary accent: medical cyan-teal
        brand: {
          50: '#e6fbfb',
          100: '#c0f4f6',
          200: '#8ae9ee',
          300: '#4dd8e2',
          400: '#22c1d0',
          500: '#0ea5b7',
          600: '#0b8494',
          700: '#0c6875',
          800: '#10545f',
          900: '#12464f',
        },
        // Clinical risk semantics.
        // NOTE: deliberately icon+label backed, never colour-only.
        risk: {
          high: '#f2545b',      // malignant / positive
          highSoft: '#3a1a20',
          low: '#3ecf8e',       // benign / negative
          lowSoft: '#123027',
          warn: '#f5a524',
          warnSoft: '#3a2c12',
        },
        ink: {
          DEFAULT: '#e8edf5',
          muted: '#94a3b8',
          faint: '#64748b',
          ghost: '#475569',
        },
        line: {
          DEFAULT: '#1f2937',
          soft: '#182033',
          strong: '#2c3a52',
        },
      },
      fontFamily: {
        sans: ['Inter', 'Noto Sans SC', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'SF Mono', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      boxShadow: {
        panel: '0 1px 2px rgba(0,0,0,.3), 0 8px 24px -8px rgba(0,0,0,.5)',
        lift: '0 2px 4px rgba(0,0,0,.3), 0 16px 40px -12px rgba(0,0,0,.6)',
        glow: '0 0 0 1px rgba(34,193,208,.25), 0 0 28px -6px rgba(34,193,208,.35)',
        'glow-risk': '0 0 0 1px rgba(242,84,91,.3), 0 0 32px -6px rgba(242,84,91,.4)',
        'glow-safe': '0 0 0 1px rgba(62,207,142,.3), 0 0 32px -6px rgba(62,207,142,.4)',
      },
      backgroundImage: {
        'grid-faint':
          'linear-gradient(to right, rgba(148,163,184,.045) 1px, transparent 1px), linear-gradient(to bottom, rgba(148,163,184,.045) 1px, transparent 1px)',
        'brand-sheen':
          'linear-gradient(135deg, rgba(34,193,208,.14) 0%, rgba(34,193,208,0) 60%)',
        'risk-sheen':
          'linear-gradient(135deg, rgba(242,84,91,.16) 0%, rgba(242,84,91,0) 65%)',
      },
      backgroundSize: {
        grid: '32px 32px',
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
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(.96)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-500px 0' },
          '100%': { backgroundPosition: '500px 0' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(.9)', opacity: '.7' },
          '70%': { transform: 'scale(1.15)', opacity: '0' },
          '100%': { transform: 'scale(1.15)', opacity: '0' },
        },
        'draw-bar': {
          '0%': { transform: 'scaleX(0)' },
          '100%': { transform: 'scaleX(1)' },
        },
      },
      animation: {
        'fade-up': 'fade-up .35s cubic-bezier(.16,1,.3,1) both',
        'fade-in': 'fade-in .25s ease both',
        'scale-in': 'scale-in .22s cubic-bezier(.16,1,.3,1) both',
        shimmer: 'shimmer 1.6s linear infinite',
        'pulse-ring': 'pulse-ring 2s cubic-bezier(.4,0,.6,1) infinite',
        'draw-bar': 'draw-bar .6s cubic-bezier(.16,1,.3,1) both',
      },
      transitionTimingFunction: {
        snap: 'cubic-bezier(.16,1,.3,1)',
      },
      // The default scale skips 4/6/8/12/85/95/97, but the design leans on
      // very low alpha washes for tinted surfaces. Extend rather than
      // replace so every default step stays available.
      opacity: {
        4: '0.04',
        6: '0.06',
        8: '0.08',
        12: '0.12',
        85: '0.85',
        95: '0.95',
        97: '0.97',
      },
    },
  },
  plugins: [],
}

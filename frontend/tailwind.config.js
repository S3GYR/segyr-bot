/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#0f1729',
          alt: '#111827',
          card: '#151f33',
          border: '#1f2937',
        },
        accent: '#22d3ee',
        warning: '#fb923c',
        danger: '#f87171',
        success: '#34d399',
      },
    },
  },
  plugins: [],
}

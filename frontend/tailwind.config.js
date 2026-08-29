import frappeUIPreset from 'frappe-ui/tailwind'

export default {
  presets: [frappeUIPreset],
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
    './node_modules/frappe-ui/src/**/*.{vue,js,ts,jsx,tsx}',
    '../node_modules/frappe-ui/src/**/*.{vue,js,ts,jsx,tsx}',
    './node_modules/frappe-ui/frappe/**/*.{vue,js,ts,jsx,tsx}',
    '../node_modules/frappe-ui/frappe/**/*.{vue,js,ts,jsx,tsx}',
  ],
  safelist: [{ pattern: /!(text|bg)-/, variants: ['hover', 'active'] }],
  theme: {
    extend: {
      colors: {
        // FPT brand ramp. Separate from frappe-ui `blue` (kept for informational
        // semantics) and `orange` (kept for warnings). See src/theme-brand.css for
        // the matching semantic CSS variables and dark-mode values.
        brand: {
          50: '#FFF4ED',
          100: '#FFE6D5',
          200: '#FECDAA',
          300: '#FDAC74',
          400: '#FB8B3C',
          500: '#F37024',
          600: '#EC5F16',
          700: '#C9490F',
          800: '#A23D14',
          900: '#833318',
          DEFAULT: '#F37024',
        },
      },
    },
  },
  plugins: [],
}

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "./static/**/*.html",
    "./static/**/*.js",
    "./src/**/*.py"
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#ecfdf5',
          100: '#d1fae5',
          400: '#34d399',
          500: '#10b981',
          600: '#059669',
          700: '#047857'
        },
        darkbg: '#0B0F17',
        darkcard: '#151D2A',
        darkborder: '#1F2A3C'
      }
    }
  },
  plugins: [],
}

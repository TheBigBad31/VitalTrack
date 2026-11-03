/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './static/index.html',
    './static/modules/**/*.js',
    './static/**/*.html'
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#F5F3FF',
          100: '#EDE9FE',
          400: '#A78BFA',
          500: '#7C3AED',
          600: '#6D28D9',
          700: '#5B21B6'
        },
        electric: {
          blue: '#2563FF',
          cyan: '#22D3EE',
          magenta: '#C026D3'
        },
        darkbg: '#0B0B1A',
        darkcard: '#14142B',
        darkborder: '#25254A'
      }
    }
  },
  plugins: []
};

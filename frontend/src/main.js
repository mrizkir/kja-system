import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import { definePreset } from '@primevue/themes'
import Aura from '@primevue/themes/aura'
import 'primeicons/primeicons.css'

import App from './App.vue'
import './styles.css'

const KjaPreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: '#e6faf5',
      100: '#b3f0e4',
      200: '#80e6d3',
      300: '#4ddcc2',
      400: '#26d4b5',
      500: '#00C9A7',
      600: '#00a88c',
      700: '#008771',
      800: '#006656',
      900: '#00453b',
      950: '#002e27'
    }
  },
  colorScheme: {
    dark: {
      surface: {
        0: '#06101E',
        50: '#0D1B2E',
        100: '#112240',
        200: '#1E3A5F',
        300: '#2a4a73',
        400: '#3d5f8f',
        500: '#7B93B0',
        600: '#9aafc9',
        700: '#b8c9de',
        800: '#d6e2f0',
        900: '#E8F0FE',
        950: '#f5f8fd'
      }
    }
  }
})

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(PrimeVue, {
  theme: {
    preset: KjaPreset,
    options: {
      darkModeSelector: '.dark',
      cssLayer: false
    }
  }
})
app.use(ToastService)

app.mount('#app')

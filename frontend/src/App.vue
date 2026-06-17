<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useToast } from 'primevue/usetoast'
import Toast from 'primevue/toast'
import Message from 'primevue/message'
import Badge from 'primevue/badge'

import SensorCard from '@/components/SensorCard.vue'
import KjaMap from '@/components/KjaMap.vue'
import TrendChart from '@/components/TrendChart.vue'
import AlertPanel from '@/components/AlertPanel.vue'
import DoPrediction from '@/components/DoPrediction.vue'
import { useSensorStore } from '@/stores/sensor'
import { useSensorData } from '@/composables/useSensorData'

const store = useSensorStore()
const { error, refreshForSelectedKja, markAlertRead, startPolling, stopPolling } = useSensorData()
const toast = useToast()

const clock = ref('')
let clockTimer = null

function updateClock() {
  clock.value = new Date().toLocaleString('id-ID', {
    timeZone: 'Asia/Jakarta',
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }) + ' WIB'
}

function onNewDanger(alert) {
  toast.add({
    severity: 'error',
    summary: 'Peringatan Kritis',
    detail: alert.message,
    life: 8000
  })
}

function onSelectKja(id) {
  store.selectKja(id)
}

async function onMarkRead(id) {
  await markAlertRead(id)
}

const reading = computed(() => store.selectedReading)
const criticalAlert = computed(() => store.criticalAlert)

const messageSeverity = computed(() => {
  if (!criticalAlert.value) return 'info'
  if (criticalAlert.value.severity === 'danger') return 'error'
  if (criticalAlert.value.severity === 'warn') return 'warn'
  return 'info'
})

watch(
  () => store.selectedKjaId,
  async () => {
    await refreshForSelectedKja()
  }
)

onMounted(() => {
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
  startPolling(onNewDanger)
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
  stopPolling()
})
</script>

<template>
  <div class="dashboard">
    <Toast position="top-right" />

    <header class="dashboard-header">
      <div>
        <h1 class="dashboard-title">KJA Digital Twin</h1>
        <p class="dashboard-subtitle">
          Sistem Pemantauan Budidaya Kerapu — Tanjungpinang, Kepulauan Riau
        </p>
      </div>
      <div class="header-meta">
        <span class="clock">{{ clock }}</span>
        <Badge value="LIVE" severity="success" />
      </div>
    </header>

    <Message
      v-if="criticalAlert"
      :severity="messageSeverity"
      :closable="false"
    >
      {{ criticalAlert.message }}
    </Message>
    <Message v-else severity="success" :closable="false">
      Semua parameter dalam batas normal untuk unit terpilih.
    </Message>

    <Message v-if="error" severity="error" :closable="false">
      Gagal memuat data: {{ error }}
    </Message>

    <section class="sensor-grid">
      <SensorCard
        title="pH"
        icon="pi pi-sliders-h"
        :value="reading?.ph?.toFixed(2)"
        :status="reading?.status?.ph"
        :loading="store.loading"
      />
      <SensorCard
        title="Suhu"
        icon="pi pi-sun"
        :value="reading?.temperature?.toFixed(1)"
        unit="°C"
        :status="reading?.status?.temperature"
        :loading="store.loading"
      />
      <SensorCard
        title="Salinitas"
        icon="pi pi-database"
        :value="reading?.salinity?.toFixed(1)"
        unit="ppt"
        :status="reading?.status?.salinity"
        :loading="store.loading"
      />
      <SensorCard
        title="Turbiditas"
        icon="pi pi-eye"
        :value="reading?.turbidity?.toFixed(1)"
        unit="NTU"
        :status="reading?.status?.turbidity"
        :loading="store.loading"
      />
      <SensorCard
        title="DO (Prediksi)"
        icon="pi pi-bolt"
        :value="reading?.do_predicted?.toFixed(2)"
        unit="mg/L"
        :status="reading?.status?.do_predicted"
        :loading="store.loading"
        show-tft-badge
      />
      <SensorCard
        title="Cahaya"
        icon="pi pi-lightbulb"
        :value="reading ? Math.round(reading.light_intensity).toLocaleString('id-ID') : '—'"
        unit="lux"
        status="normal"
        :loading="store.loading"
      />
    </section>

    <section class="bottom-grid">
      <div class="left-column">
        <KjaMap
          :units="store.kjaUnits"
          :selected-kja-id="store.selectedKjaId"
          @select="onSelectKja"
        />
        <TrendChart
          :history="store.history"
          :kja-name="store.selectedUnit?.name || 'KJA-01'"
        />
      </div>
      <div class="right-column">
        <AlertPanel :alerts="store.alerts" @read="onMarkRead" />
        <DoPrediction :prediction="store.doPrediction" :loading="store.loading" />
      </div>
    </section>
  </div>
</template>

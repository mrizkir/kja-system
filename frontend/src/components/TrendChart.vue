<script setup>
import { computed } from 'vue'
import Card from 'primevue/card'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler)

const props = defineProps({
  history: { type: Array, default: () => [] },
  kjaName: { type: String, default: 'KJA-01' }
})

const chartData = computed(() => {
  const labels = props.history.map((r) => {
    const d = new Date(r.timestamp)
    return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })
  })

  return {
    labels,
    datasets: [
      {
        label: 'DO (mg/L)',
        data: props.history.map((r) => r.do_predicted),
        borderColor: '#00C9A7',
        backgroundColor: 'rgba(0, 201, 167, 0.12)',
        fill: true,
        tension: 0.35,
        pointRadius: 0
      },
      {
        label: 'Suhu (°C)',
        data: props.history.map((r) => r.temperature),
        borderColor: '#4FC3F7',
        backgroundColor: 'transparent',
        tension: 0.35,
        pointRadius: 0,
        yAxisID: 'y1'
      }
    ]
  }
})

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: {
      labels: { color: '#7B93B0', font: { family: 'Inter' } }
    }
  },
  scales: {
    x: {
      ticks: { color: '#7B93B0', maxTicksLimit: 8 },
      grid: { color: 'rgba(30, 58, 95, 0.4)' }
    },
    y: {
      ticks: { color: '#7B93B0' },
      grid: { color: 'rgba(30, 58, 95, 0.4)' },
      title: { display: true, text: 'DO', color: '#7B93B0' }
    },
    y1: {
      position: 'right',
      ticks: { color: '#7B93B0' },
      grid: { drawOnChartArea: false },
      title: { display: true, text: 'Suhu', color: '#7B93B0' }
    }
  }
}
</script>

<template>
  <Card>
    <template #title>Tren 24 Jam — {{ kjaName }}</template>
    <template #content>
      <div class="chart-box">
        <Line v-if="history.length" :data="chartData" :options="chartOptions" />
        <p v-else class="empty">Belum ada data historis.</p>
      </div>
    </template>
  </Card>
</template>

<style scoped>
.chart-box {
  height: 260px;
}

.empty {
  color: var(--slate);
  font-size: 0.9rem;
}
</style>

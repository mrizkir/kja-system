<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Badge from 'primevue/badge'
import Button from 'primevue/button'
import InputNumber from 'primevue/inputnumber'
import Message from 'primevue/message'
import Toast from 'primevue/toast'
import { useToast } from 'primevue/usetoast'

const POLL_MS = 5_000
const FRESH_MS = 2 * 60 * 1000
const STALE_MS = 15 * 60 * 1000

const toast = useToast()
const readings = ref([])
const loading = ref(true)
const error = ref(null)
const lastPollAt = ref(null)
const sending = ref(false)
const lastIngest = ref(null)
const rainfallFetchedAt = ref(null)
const rainfallRowCount = ref(0)

const form = reactive({
  kja_id: 1,
  ph: 8.0,
  suhu: 27.0,
  salinitas: 30.0,
  kekeruhan: 10.0,
  status: 'Data Masuk'
})

// Same default as receiver.ino BEARER_TOKEN / Config.INGEST_BEARER_TOKEN
const INGEST_BEARER =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6ImE3ZDJkMWY2LTliNTgtNDYyZC05MGZkLTA1YmViOTRlNWVjMSIsInJvbGUiOiJhZG1pbiIsImlhdCI6MTc1Njg5OTIxOH0.siu-ITBJxhl5Jhap0ohHRdmd70kFY6oI0CevIgGgLnI'

let pollTimer = null

function ageMs(iso) {
  if (!iso) return Number.POSITIVE_INFINITY
  return Date.now() - new Date(iso).getTime()
}

function freshness(iso) {
  const age = ageMs(iso)
  if (age <= FRESH_MS) return { label: 'Segar', severity: 'success', hint: '< 2 menit' }
  if (age <= STALE_MS) return { label: 'Lama', severity: 'warn', hint: '< 15 menit' }
  return { label: 'Stale', severity: 'danger', hint: '> 15 menit / seed' }
}

function formatTime(iso) {
  if (!iso) return '—'
  return (
    new Date(iso).toLocaleString('id-ID', {
      timeZone: 'Asia/Jakarta',
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    }) + ' WIB'
  )
}

function formatAge(iso) {
  const age = ageMs(iso)
  if (!Number.isFinite(age)) return '—'
  const sec = Math.floor(age / 1000)
  if (sec < 60) return `${sec}s lalu`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m lalu`
  const hr = Math.floor(min / 60)
  return `${hr}j ${min % 60}m lalu`
}

const rows = computed(() =>
  [...readings.value]
    .sort((a, b) => a.kja_id - b.kja_id)
    .map((r) => ({
      ...r,
      freshness: freshness(r.timestamp),
      ageLabel: formatAge(r.timestamp),
      timeLabel: formatTime(r.timestamp)
    }))
)

const freshCount = computed(() => rows.value.filter((r) => r.freshness.label === 'Segar').length)

const rainfallFreshness = computed(() => freshness(rainfallFetchedAt.value))

async function poll() {
  try {
    const [sensorRes, rainRes] = await Promise.all([
      fetch('/api/sensor/latest'),
      fetch('/api/weather/rainfall/status')
    ])
    if (!sensorRes.ok) throw new Error(`HTTP ${sensorRes.status}`)
    readings.value = await sensorRes.json()
    if (rainRes.ok) {
      const rain = await rainRes.json()
      rainfallFetchedAt.value = rain.fetched_at || null
      rainfallRowCount.value = rain.row_count ?? 0
    }
    error.value = null
    lastPollAt.value = new Date()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function sendTestIngest() {
  sending.value = true
  try {
    const body = {
      kja_id: form.kja_id,
      ph: form.ph,
      temperature: form.suhu,
      salinity: form.salinitas,
      turbidity: form.kekeruhan,
      status: form.status
    }
    const response = await fetch('/api/sensor/ingest', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${INGEST_BEARER}`
      },
      body: JSON.stringify(body)
    })
    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.error || `HTTP ${response.status}`)
    }
    lastIngest.value = data
    toast.add({
      severity: 'success',
      summary: 'Ingest OK',
      detail: `${data.kja_name || 'KJA'} tersimpan (format receiver.ino)`,
      life: 4000
    })
    await poll()
  } catch (err) {
    toast.add({
      severity: 'error',
      summary: 'Ingest gagal',
      detail: err.message,
      life: 6000
    })
  } finally {
    sending.value = false
  }
}

onMounted(() => {
  poll()
  pollTimer = setInterval(poll, POLL_MS)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="dashboard iot-page">
    <Toast position="top-right" />

    <header class="dashboard-header">
      <div>
        <h1 class="dashboard-title">Monitor IoT</h1>
        <p class="dashboard-subtitle">
          Pantau reading terakhir dari receiver — terpisah dari dashboard operasional
        </p>
      </div>
      <div class="header-meta">
        <nav class="app-nav">
          <RouterLink class="nav-link" to="/">Dashboard</RouterLink>
          <RouterLink class="nav-link" to="/iot">Monitor IoT</RouterLink>
        </nav>
        <Badge :value="`${freshCount}/${rows.length || 1} segar`" severity="info" />
        <Badge value="POLL 5s" severity="success" />
      </div>
    </header>

    <Message v-if="error" severity="error" :closable="false">
      Gagal memuat latest: {{ error }}
    </Message>
    <Message v-else severity="info" :closable="false">
      Status Segar = timestamp &lt; 2 menit (kemungkinan ingest IoT baru).
      Stale biasanya data seed atau receiver belum kirim.
      <span v-if="lastPollAt" class="mono poll-hint">
        · last poll {{ lastPollAt.toLocaleTimeString('id-ID') }}
      </span>
    </Message>
    <p class="dashboard-subtitle rainfall-status">
      Curah hujan (cache VPS):
      <template v-if="rainfallFetchedAt">
        <Badge
          :value="rainfallFreshness.label"
          :severity="rainfallFreshness.severity"
        />
        <span class="mono">
          · {{ formatAge(rainfallFetchedAt) }}
          · {{ formatTime(rainfallFetchedAt) }}
          · {{ rainfallRowCount }} jam
        </span>
      </template>
      <span v-else>belum ada data (sync cron belum berhasil)</span>
    </p>

    <section class="iot-table-wrap">
      <table class="iot-table">
        <thead>
          <tr>
            <th>KJA</th>
            <th>Status</th>
            <th>Usia data</th>
            <th>Timestamp</th>
            <th>pH</th>
            <th>Suhu</th>
            <th>Salinitas</th>
            <th>Turbiditas</th>
            <th>DO</th>
            <th>Sumber DO</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="10" class="iot-empty">Memuat…</td>
          </tr>
          <tr v-else-if="!rows.length">
            <td colspan="10" class="iot-empty">Belum ada reading.</td>
          </tr>
          <tr v-for="row in rows" :key="row.kja_id">
            <td class="mono">{{ row.kja_name || `KJA-${row.kja_id}` }}</td>
            <td>
              <Badge :value="row.freshness.label" :severity="row.freshness.severity" />
            </td>
            <td class="mono">{{ row.ageLabel }}</td>
            <td class="mono">{{ row.timeLabel }}</td>
            <td class="mono">{{ row.ph?.toFixed(2) }}</td>
            <td class="mono">{{ row.temperature?.toFixed(1) }} °C</td>
            <td class="mono">{{ row.salinity?.toFixed(1) }} ppt</td>
            <td class="mono">{{ row.turbidity?.toFixed(1) }} NTU</td>
            <td class="mono">{{ row.do_predicted?.toFixed(2) }}</td>
            <td class="mono">{{ row.do_source }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="iot-test-panel">
      <h2 class="iot-section-title">Uji kirim (format receiver.ino)</h2>
      <p class="dashboard-subtitle">
        Payload sama seperti ESP32:
        <span class="mono">kja_id, ph, temperature, salinity, turbidity, status</span>
        + Bearer token. Setelah sukses, baris KJA harus
        <strong>Segar</strong>.
      </p>

      <div class="iot-form">
        <label>
          <span>KJA</span>
          <span class="mono iot-kja-fixed">NODE1 → KJA-01</span>
        </label>
        <label>
          <span>pH</span>
          <InputNumber v-model="form.ph" :min-fraction-digits="1" :max-fraction-digits="2" />
        </label>
        <label>
          <span>Suhu (°C)</span>
          <InputNumber v-model="form.suhu" :min-fraction-digits="1" :max-fraction-digits="2" />
        </label>
        <label>
          <span>Salinitas (ppt)</span>
          <InputNumber v-model="form.salinitas" :min-fraction-digits="1" :max-fraction-digits="2" />
        </label>
        <label>
          <span>Kekeruhan (NTU)</span>
          <InputNumber v-model="form.kekeruhan" :min-fraction-digits="1" :max-fraction-digits="2" />
        </label>
        <div class="iot-form-actions">
          <Button label="Kirim uji" icon="pi pi-send" :loading="sending" @click="sendTestIngest" />
        </div>
      </div>

      <pre v-if="lastIngest" class="iot-response mono">{{ JSON.stringify(lastIngest, null, 2) }}</pre>
    </section>
  </div>
</template>

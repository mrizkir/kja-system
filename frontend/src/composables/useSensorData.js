import { onMounted, onUnmounted, ref } from 'vue'
import { useSensorStore } from '@/stores/sensor'

const POLL_INTERVAL_MS = 30_000

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options)
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${url}`)
  }
  return response.json()
}

export function useSensorData() {
  const store = useSensorStore()
  const error = ref(null)
  const previousDangerIds = ref(new Set())
  let timer = null

  async function refresh(selectedKjaId = store.selectedKjaId) {
    try {
      const [latest, units, alertList, historyData, prediction] = await Promise.all([
        fetchJson('/api/sensor/latest'),
        fetchJson('/api/kja/units'),
        fetchJson('/api/alert/list'),
        fetchJson(`/api/sensor/history/${selectedKjaId}?hours=24`),
        fetchJson(`/api/inference/do/${selectedKjaId}`)
      ])

      store.setData({ latest, units, alertList, historyData: historyData.readings, prediction })
      error.value = null

      return { alertList }
    } catch (err) {
      error.value = err.message
      store.loading = false
      throw err
    }
  }

  async function refreshForSelectedKja() {
    const [historyData, prediction] = await Promise.all([
      fetchJson(`/api/sensor/history/${store.selectedKjaId}?hours=24`),
      fetchJson(`/api/inference/do/${store.selectedKjaId}`)
    ])
    store.setData({ historyData: historyData.readings, prediction })
  }

  async function markAlertRead(alertId) {
    await fetchJson(`/api/alert/read/${alertId}`, { method: 'POST' })
    store.markAlertRead(alertId)
  }

  function startPolling(onNewDanger) {
    const poll = async () => {
      try {
        const { alertList } = await refresh(store.selectedKjaId)
        const currentDanger = alertList.filter((a) => a.severity === 'danger' && !a.is_read)
        for (const alert of currentDanger) {
          if (!previousDangerIds.value.has(alert.id)) {
            onNewDanger?.(alert)
          }
        }
        previousDangerIds.value = new Set(currentDanger.map((a) => a.id))
      } catch {
        // error already captured in refresh
      }
    }

    poll()
    timer = setInterval(poll, POLL_INTERVAL_MS)
  }

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  onMounted(() => {})
  onUnmounted(stopPolling)

  return {
    error,
    refresh,
    refreshForSelectedKja,
    markAlertRead,
    startPolling,
    stopPolling
  }
}

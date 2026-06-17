import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useSensorStore = defineStore('sensor', () => {
  const readings = ref([])
  const kjaUnits = ref([])
  const alerts = ref([])
  const selectedKjaId = ref(1)
  const history = ref([])
  const doPrediction = ref(null)
  const loading = ref(true)
  const lastFetchedAt = ref(null)

  const selectedReading = computed(() => {
    return readings.value.find((r) => r.kja_id === selectedKjaId.value) || readings.value[0] || null
  })

  const selectedUnit = computed(() => {
    return kjaUnits.value.find((u) => u.id === selectedKjaId.value) || kjaUnits.value[0] || null
  })

  const criticalAlert = computed(() => {
    const unread = alerts.value.filter((a) => !a.is_read)
    const danger = unread.find((a) => a.severity === 'danger')
    if (danger) return danger
    const warn = unread.find((a) => a.severity === 'warn')
    return warn || unread[0] || null
  })

  function setData({ latest, units, alertList, historyData, prediction }) {
    if (latest) readings.value = latest
    if (units) kjaUnits.value = units
    if (alertList) alerts.value = alertList
    if (historyData) history.value = historyData
    if (prediction) doPrediction.value = prediction
    lastFetchedAt.value = new Date()
    loading.value = false
  }

  function selectKja(id) {
    selectedKjaId.value = id
  }

  function markAlertRead(id) {
    const alert = alerts.value.find((a) => a.id === id)
    if (alert) alert.is_read = true
  }

  return {
    readings,
    kjaUnits,
    alerts,
    selectedKjaId,
    history,
    doPrediction,
    loading,
    lastFetchedAt,
    selectedReading,
    selectedUnit,
    criticalAlert,
    setData,
    selectKja,
    markAlertRead
  }
})

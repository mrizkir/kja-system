<script setup>
import { computed } from 'vue'
import Card from 'primevue/card'
import ProgressBar from 'primevue/progressbar'
import Badge from 'primevue/badge'
import Skeleton from 'primevue/skeleton'

const props = defineProps({
  prediction: { type: Object, default: null },
  loading: { type: Boolean, default: false }
})

const doNowPercent = computed(() => {
  if (!props.prediction) return 0
  return Math.min(100, Math.max(0, (props.prediction.do_now / 8) * 100))
})

const thresholdColor = computed(() => {
  const doVal = props.prediction?.do_now ?? 0
  if (doVal < 4) return 'var(--coral)'
  if (doVal < 5) return 'var(--amber)'
  return 'var(--teal)'
})

function q50(value) {
  if (value == null) return '—'
  if (typeof value === 'number') return value
  return value.q50 ?? '—'
}

function interval(value) {
  if (value == null || typeof value === 'number') return ''
  if (value.q10 == null || value.q90 == null) return ''
  return `${value.q10}–${value.q90}`
}
</script>

<template>
  <Card>
    <template #title>
      <div class="title-row">
        <span>Prediksi DO (TFT)</span>
        <Badge
          v-if="prediction && prediction.confidence != null"
          :value="`${Math.round(prediction.confidence * 100)}%`"
          severity="info"
        />
      </div>
    </template>
    <template #content>
      <Skeleton v-if="loading" height="8rem" />
      <div v-else-if="prediction && !prediction.error" class="prediction-body">
        <div class="do-now mono">
          {{ prediction.do_now }} <span class="unit">mg/L</span>
        </div>
        <ProgressBar
          :value="doNowPercent"
          :show-value="false"
          class="do-bar"
          :style="{ '--p-progressbar-value-background': thresholdColor }"
        />
        <div class="threshold-labels">
          <span class="danger">&lt;4 Kritis</span>
          <span class="warn">4–5 Perhatian</span>
          <span class="normal">≥5 Normal</span>
        </div>
        <div class="forecast-grid mono">
          <div>
            <span class="lbl">+6j</span>
            {{ q50(prediction.do_6h) }}
            <span v-if="interval(prediction.do_6h)" class="interval">{{ interval(prediction.do_6h) }}</span>
          </div>
          <div>
            <span class="lbl">+24j</span>
            {{ q50(prediction.do_24h) }}
            <span v-if="interval(prediction.do_24h)" class="interval">{{ interval(prediction.do_24h) }}</span>
          </div>
          <div>
            <span class="lbl">+7hari</span>
            {{ q50(prediction.do_7d) }}
            <span v-if="interval(prediction.do_7d)" class="interval">{{ interval(prediction.do_7d) }}</span>
          </div>
          <div><span class="lbl">Latensi</span> {{ prediction.latency_ms }} ms</div>
        </div>
      </div>
      <p v-else-if="prediction && prediction.error" class="empty">{{ prediction.error }}</p>
      <p v-else class="empty">Prediksi tidak tersedia.</p>
    </template>
  </Card>
</template>

<style scoped>
.title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.prediction-body {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.do-now {
  font-size: 2rem;
  font-weight: 600;
}

.unit {
  font-size: 0.95rem;
  color: var(--slate);
}

.do-bar {
  height: 0.65rem;
}

.threshold-labels {
  display: flex;
  justify-content: space-between;
  font-size: 0.72rem;
  color: var(--slate);
}

.threshold-labels .danger {
  color: var(--coral);
}

.threshold-labels .warn {
  color: var(--amber);
}

.threshold-labels .normal {
  color: var(--teal);
}

.forecast-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.5rem;
  margin-top: 0.25rem;
  font-size: 0.85rem;
}

.lbl {
  display: block;
  font-size: 0.68rem;
  color: var(--slate);
  margin-bottom: 0.15rem;
}

.interval {
  display: block;
  font-size: 0.68rem;
  color: var(--slate);
  margin-top: 0.15rem;
}

.empty {
  color: var(--slate);
  font-size: 0.9rem;
}
</style>

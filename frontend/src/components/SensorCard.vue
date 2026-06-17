<script setup>
import { computed } from 'vue'
import Card from 'primevue/card'
import Tag from 'primevue/tag'
import Badge from 'primevue/badge'
import Skeleton from 'primevue/skeleton'

const props = defineProps({
  title: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  unit: { type: String, default: '' },
  status: { type: String, default: 'normal' },
  icon: { type: String, default: 'pi pi-chart-line' },
  loading: { type: Boolean, default: false },
  showTftBadge: { type: Boolean, default: false }
})

const severityMap = {
  normal: { label: 'Normal', severity: 'success' },
  perhatian: { label: 'Perhatian', severity: 'warn' },
  kritis: { label: 'Kritis', severity: 'danger' }
}

const tag = computed(() => severityMap[props.status] || severityMap.normal)
</script>

<template>
  <Card class="sensor-card">
    <template #title>
      <div class="card-head">
        <span class="card-title">
          <i :class="icon" />
          {{ title }}
        </span>
        <Badge v-if="showTftBadge" value="TFT" severity="info" />
      </div>
    </template>
    <template #content>
      <Skeleton v-if="loading" height="2.5rem" />
      <div v-else class="card-value mono">
        {{ value }}<span v-if="unit" class="unit">{{ unit }}</span>
      </div>
      <Tag
        v-if="!loading"
        :value="tag.label"
        :severity="tag.severity"
        class="status-tag"
      />
    </template>
  </Card>
</template>

<style scoped>
.sensor-card {
  min-height: 130px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.82rem;
  color: var(--slate);
  font-weight: 500;
}

.card-value {
  font-size: 1.65rem;
  font-weight: 600;
  color: var(--white);
  margin-bottom: 0.5rem;
}

.unit {
  font-size: 0.9rem;
  color: var(--slate);
  margin-left: 0.2rem;
}

.status-tag {
  font-size: 0.72rem;
}
</style>

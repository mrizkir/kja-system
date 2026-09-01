<script setup>
import { computed } from 'vue'
import Card from 'primevue/card'

const props = defineProps({
  units: { type: Array, default: () => [] }
})

const unit = computed(() => props.units[0] || null)

const statusColor = computed(() => {
  if (!unit.value) return 'var(--teal)'
  if (unit.value.status === 'warning') return 'var(--amber)'
  if (unit.value.latest_reading?.status?.do_predicted === 'kritis') return 'var(--coral)'
  return 'var(--teal)'
})
</script>

<template>
  <Card>
    <template #title>Lokasi — Teluk Bintan</template>
    <template #content>
      <div class="map-wrap">
        <svg viewBox="0 0 100 60" class="map-svg" aria-label="Lokasi KJA petani">
          <defs>
            <linearGradient id="water" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#0a1f3d" />
              <stop offset="100%" stop-color="#06101E" />
            </linearGradient>
          </defs>
          <rect width="100" height="60" fill="url(#water)" rx="2" />
          <path
            d="M0 45 Q25 38 50 42 T100 40 L100 60 L0 60 Z"
            fill="#112240"
            opacity="0.6"
          />
          <circle
            v-if="unit"
            cx="50"
            cy="32"
            r="3.2"
            :fill="statusColor"
            stroke="var(--white)"
            stroke-width="1.2"
          />
        </svg>
        <p v-if="unit" class="unit-caption">
          {{ unit.name }} · {{ unit.farmer_name }}
        </p>
      </div>
    </template>
  </Card>
</template>

<style scoped>
.map-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.map-svg {
  width: 100%;
  height: 220px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg3);
}

.unit-caption {
  margin: 0;
  font-size: 0.85rem;
  color: var(--slate);
}
</style>

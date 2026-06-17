<script setup>
import { computed } from 'vue'
import Card from 'primevue/card'
import Chip from 'primevue/chip'

const props = defineProps({
  units: { type: Array, default: () => [] },
  selectedKjaId: { type: Number, default: 1 }
})

const emit = defineEmits(['select'])

const positions = {
  'KJA-01': { x: 18, y: 28 },
  'KJA-02': { x: 42, y: 22 },
  'KJA-03': { x: 62, y: 48 },
  'KJA-04': { x: 78, y: 32 }
}

const markers = computed(() =>
  props.units.map((unit) => ({
    ...unit,
    pos: positions[unit.name] || { x: 50, y: 50 },
    statusColor:
      unit.status === 'warning' ? 'var(--amber)' : unit.latest_reading?.status?.do_predicted === 'kritis' ? 'var(--coral)' : 'var(--teal)'
  }))
)

function onSelect(id) {
  emit('select', id)
}
</script>

<template>
  <Card>
    <template #title>Peta KJA — Teluk Bintan</template>
    <template #content>
      <div class="map-wrap">
        <svg viewBox="0 0 100 60" class="map-svg" aria-label="Peta lokasi KJA">
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
            v-for="marker in markers"
            :key="marker.id"
            :cx="marker.pos.x"
            :cy="marker.pos.y"
            r="3.2"
            :fill="marker.statusColor"
            :stroke="selectedKjaId === marker.id ? 'var(--white)' : 'transparent'"
            stroke-width="1.2"
            class="marker-dot"
            @click="onSelect(marker.id)"
          />
        </svg>
        <div class="chip-row">
          <Chip
            v-for="marker in markers"
            :key="marker.id"
            :label="marker.name"
            :class="{ active: selectedKjaId === marker.id }"
            @click="onSelect(marker.id)"
          />
        </div>
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

.marker-dot {
  cursor: pointer;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.chip-row :deep(.p-chip) {
  cursor: pointer;
  background: var(--bg3);
  border: 1px solid var(--border);
}

.chip-row :deep(.p-chip.active) {
  border-color: var(--teal);
  color: var(--teal);
}
</style>

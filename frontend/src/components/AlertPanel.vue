<script setup>
import Card from 'primevue/card'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import Button from 'primevue/button'

defineProps({
  alerts: { type: Array, default: () => [] }
})

const emit = defineEmits(['read'])

const severityMap = {
  info: { label: 'Info', severity: 'info' },
  warn: { label: 'Perhatian', severity: 'warn' },
  danger: { label: 'Kritis', severity: 'danger' }
}

function formatTime(ts) {
  return new Date(ts).toLocaleString('id-ID', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function onRead(id) {
  emit('read', id)
}
</script>

<template>
  <Card>
    <template #title>Panel Peringatan</template>
    <template #content>
      <DataTable
        :value="alerts"
        :rows="8"
        paginator
        size="small"
        striped-rows
        data-key="id"
      >
        <Column field="kja_name" header="KJA" style="width: 5rem" />
        <Column field="parameter" header="Parameter" style="width: 6rem" />
        <Column header="Tingkat" style="width: 6rem">
          <template #body="{ data }">
            <Tag
              :value="severityMap[data.severity]?.label || data.severity"
              :severity="severityMap[data.severity]?.severity || 'info'"
            />
          </template>
        </Column>
        <Column field="message" header="Pesan" />
        <Column header="Waktu" style="width: 8rem">
          <template #body="{ data }">
            <span class="mono time">{{ formatTime(data.timestamp) }}</span>
          </template>
        </Column>
        <Column header="" style="width: 4rem">
          <template #body="{ data }">
            <Button
              v-if="!data.is_read"
              icon="pi pi-check"
              size="small"
              text
              rounded
              severity="success"
              aria-label="Tandai dibaca"
              @click="onRead(data.id)"
            />
          </template>
        </Column>
      </DataTable>
    </template>
  </Card>
</template>

<style scoped>
.time {
  font-size: 0.75rem;
  color: var(--slate);
}
</style>

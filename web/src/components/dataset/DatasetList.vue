<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DatasetSummary } from '../../types/dataset'

const props = defineProps<{
  items: DatasetSummary[]
  selectedId: string
  loading?: boolean
}>()
const emit = defineEmits<{
  select: [id: string]
  create: []
  copy: [item: DatasetSummary]
  archive: [item: DatasetSummary]
  import: []
}>()

const query = ref('')
const filtered = computed(() => {
  const value = query.value.trim().toLowerCase()
  if (!value) return props.items
  return props.items.filter(item =>
    item.name.toLowerCase().includes(value) || item.description.toLowerCase().includes(value)
  )
})
</script>

<template>
  <section class="dataset-catalog" aria-labelledby="dataset-catalog-title">
    <div class="dataset-catalog-toolbar">
      <div>
        <span class="step">DATASETS</span>
        <h2 id="dataset-catalog-title">测评集</h2>
        <p>选择一个测评集查看用例和版本，或创建新的测评集。</p>
      </div>
      <div class="dataset-catalog-actions">
        <el-button @click="emit('import')">导入 JSON</el-button>
        <el-button type="primary" data-testid="create-dataset" @click="emit('create')">新建测评集</el-button>
      </div>
    </div>
    <div class="dataset-catalog-filter">
      <el-input v-model="query" clearable placeholder="按名称或描述搜索" aria-label="搜索测评集" />
      <span>{{ filtered.length }} 个测评集</span>
    </div>
    <div v-loading="loading" class="dataset-list-table">
      <div v-if="filtered.length" class="dataset-table-head" aria-hidden="true">
        <span>名称</span><span>当前版本</span><span>用例</span><span>状态</span><span>操作</span>
      </div>
      <div v-for="item in filtered" :key="item.id" class="dataset-table-row">
        <button
          class="dataset-list-item"
          :class="{ selected: item.id === selectedId }"
          :data-testid="`dataset-item-${item.id}`"
          @click="emit('select', item.id)"
        >
          <span><b>{{ item.name }}</b><small>{{ item.description || '暂无描述' }}</small></span>
          <span>v{{ item.version ?? '—' }}</span>
          <span>{{ item.case_count }}</span>
          <span><el-tag v-if="item.has_draft" size="small" type="warning">有草稿</el-tag><el-tag v-else size="small" type="info" effect="plain">已发布</el-tag></span>
          <span class="open-dataset">打开</span>
        </button>
        <el-dropdown trigger="click" class="dataset-row-menu">
          <el-button link aria-label="测评集操作">•••</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="emit('copy', item)">复制测评集</el-dropdown-item>
              <el-dropdown-item divided @click="emit('archive', item)">归档测评集</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <el-empty v-if="!filtered.length" description="暂无测评集" :image-size="72" />
    </div>
  </section>
</template>

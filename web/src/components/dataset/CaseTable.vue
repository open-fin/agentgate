<script setup lang="ts">
import { computed, ref } from 'vue'
import type { EvaluationCase } from '../../types/dataset'

const props = defineProps<{
  items: EvaluationCase[]
  selectedId: string
  editable: boolean
}>()
const emit = defineEmits<{
  select: [item: EvaluationCase]
  add: []
  copy: [item: EvaluationCase]
  remove: [item: EvaluationCase]
  reorder: [ids: string[]]
  run: [item: EvaluationCase]
}>()

const labels = {
  positive: '正例',
  negative: '负例',
  boundary: '边界',
  easy: '简单',
  medium: '中等',
  hard: '困难',
}

function move(index: number, offset: number) {
  const ids = props.items.map(item => item.id)
  const next = index + offset
  if (next < 0 || next >= ids.length) return
  ;[ids[index], ids[next]] = [ids[next], ids[index]]
  emit('reorder', ids)
}

const query = ref('')
const category = ref('all')
const difficulty = ref('all')
const filtered = computed(() => {
  const value = query.value.trim().toLowerCase()
  return props.items.filter(item =>
    (!value || item.name.toLowerCase().includes(value) || item.tags.some(tag => tag.toLowerCase().includes(value)))
    && (category.value === 'all' || item.category === category.value)
    && (difficulty.value === 'all' || item.difficulty === difficulty.value)
  )
})
</script>

<template>
  <section class="case-table-panel" aria-labelledby="case-table-title">
    <div class="case-table-toolbar">
      <div>
        <h2 id="case-table-title">用例</h2>
        <p>{{ items.length }} 个用例，点击名称查看详情。</p>
      </div>
      <el-button type="primary" :disabled="!editable" data-testid="add-case" @click="emit('add')">新增用例</el-button>
    </div>
    <div class="case-table-filters">
      <el-input v-model="query" clearable placeholder="搜索名称或标签" aria-label="搜索用例" />
      <el-select v-model="category" aria-label="按分类筛选">
        <el-option label="全部分类" value="all" />
        <el-option label="正例" value="positive" />
        <el-option label="负例" value="negative" />
        <el-option label="边界" value="boundary" />
      </el-select>
      <el-select v-model="difficulty" aria-label="按难度筛选">
        <el-option label="全部难度" value="all" />
        <el-option label="简单" value="easy" />
        <el-option label="中等" value="medium" />
        <el-option label="困难" value="hard" />
      </el-select>
      <span>{{ filtered.length }} 条</span>
    </div>
    <div class="case-table-wrap">
      <table v-if="filtered.length" class="case-table">
        <thead><tr><th>用例名称</th><th>分类</th><th>难度</th><th>对话</th><th>标签 / 备注</th><th>操作</th></tr></thead>
        <tbody>
          <tr
            v-for="item in filtered"
            :key="item.id"
            class="case-list-item"
            :class="{ selected: item.id === selectedId }"
            :data-testid="`case-item-${item.id}`"
          >
            <td><button class="case-name-button" @click="emit('select', item)">{{ item.name }}</button></td>
            <td><el-tag size="small" effect="plain">{{ labels[item.category] }}</el-tag></td>
            <td><el-tag size="small" effect="plain" type="info">{{ labels[item.difficulty] }}</el-tag></td>
            <td>{{ item.turns.length }} 轮</td>
            <td class="case-note-cell">{{ item.notes || item.tags.join(' · ') || '—' }}</td>
            <td>
              <div class="case-row-actions">
                <el-button link size="small" @click="emit('select', item)">{{ editable ? '编辑' : '查看' }}</el-button>
                <el-button v-if="!editable" link size="small" @click="emit('run', item)">运行</el-button>
                <el-dropdown v-if="editable" trigger="click">
                  <el-button link size="small">更多</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item :disabled="props.items.indexOf(item) === 0" @click="move(props.items.indexOf(item), -1)">上移</el-dropdown-item>
                      <el-dropdown-item :disabled="props.items.indexOf(item) === props.items.length - 1" @click="move(props.items.indexOf(item), 1)">下移</el-dropdown-item>
                      <el-dropdown-item @click="emit('copy', item)">复制</el-dropdown-item>
                      <el-dropdown-item divided @click="emit('remove', item)">删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <el-empty v-else description="没有符合条件的用例" :image-size="80" />
    </div>
  </section>
</template>

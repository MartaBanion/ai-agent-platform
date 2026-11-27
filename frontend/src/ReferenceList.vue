<script setup lang="ts">
import type { Reference } from './resources'
defineProps<{ items: Reference[] }>()
</script>

<template>
  <div v-if="items.length" class="references">
    <h2>引用来源</h2>
    <article v-for="item in items" :key="item.reference" class="surface reference-card">
      <div class="inline-actions"><el-tag effect="plain">{{ item.reference }}</el-tag>
        <a :href="item.download_url">{{ item.document }}</a>
        <span class="muted">{{ item.knowledge }} · {{ item.page == null ? '' : '第 ' + item.page + ' 页 · ' }}片段 {{ item.chunk }}</span>
        <span class="reference-score">相似度 {{ item.score.toFixed(3) }}</span>
      </div>
      <p>{{ item.text }}</p>
    </article>
  </div>
</template>

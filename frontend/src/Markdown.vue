<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import { ElMessage } from 'element-plus'

const props = defineProps<{ text: string }>()
const markdown = new MarkdownIt({ html: false, breaks: true })
markdown.disable('image')
const fence = markdown.renderer.rules.fence!
markdown.renderer.rules.fence = (tokens, index, options, env, renderer) =>
  '<div class="code-box"><button class="copy-code" type="button">复制代码</button>' +
  fence(tokens, index, options, env, renderer) + '</div>'
const html = computed(() => markdown.render(props.text))

async function copyCode(event: MouseEvent) {
  if (!(event.target instanceof HTMLButtonElement) || !event.target.classList.contains('copy-code')) return
  const text = event.target.parentElement?.querySelector('code')?.textContent ?? ''
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('代码已复制')
  } catch {
    ElMessage.error('剪贴板不可用')
  }
}
</script>

<template><div class="markdown" v-html="html" @click="copyCode"></div></template>

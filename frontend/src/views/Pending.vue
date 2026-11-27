<script setup lang="ts">
import { useRoute } from 'vue-router'
const route = useRoute()
</script>
<template>
  <section>
    <div class="page-heading"><h1>{{ route.meta.title }}</h1></div>
    <div class="surface">
      <el-empty :description="route.meta.missing ? '请从导航选择功能' : '该模块待建设'">
        <RouterLink to="/workbench"><el-button>返回工作台</el-button></RouterLink>
      </el-empty>
    </div>
  </section>
</template>

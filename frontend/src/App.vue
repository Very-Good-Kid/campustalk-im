<script setup>
/**
 * 根组件：只承载路由出口与全局 Toast 容器。
 * 布局骨架（顶栏 + 左侧列表 + 右侧内容）在 layouts/AppLayout.vue，
 * 登录 / 注册页不使用布局骨架，故不能把布局写在根组件里。
 */
import ToastHost from '@/components/ToastHost.vue'
</script>

<template>
  <router-view />
  <ToastHost />
</template>

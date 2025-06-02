<template>
  <div>
    <h1>{{ title }}</h1>
    <p>{{ description }}</p>
    <ul>
      <li v-for="item in items" :key="item">{{ item }}</li>
    </ul>
    <div v-if="metadata">
      Metadata: <span>{{ metadata.key }}</span>
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent, ref } from "vue";

export default defineComponent({
  setup() {
    const title = ref("%%title%%");
    const description = ref("%%description%%");
    const items = ref<string[]>([]);
    const metadata = ref({ key: "%%metadata_key%%" });

    return {
      title,
      description,
      items,
      metadata,
    };
  },
});
</script>

<style scoped>
h1 {
  color: blue;
}
</style>

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
    const title = ref("Sample Title");
    const description = ref("Sample Description");
    const items = ref(["item1", "item2"]);
    const metadata = ref({ key: "value" });

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

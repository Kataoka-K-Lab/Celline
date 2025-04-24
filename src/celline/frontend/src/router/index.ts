import { createRouter, createWebHashHistory } from "vue-router";
import App from "../../src/App.vue";

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: "/",
      component: App,
      // 他のルート定義が必要な場合はこちらに追加
    },
  ],
});

export default router;

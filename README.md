# GitHub Trending AI & Agent

每日自动追踪 GitHub 上 AI、Agent、LLM、MCP 等前沿方向开源项目的增量数据。

**网站：** [https://lukexluo.github.io/github-trending-ai](https://lukexluo.github.io/github-trending-ai)

---

## 数据维度

- **增量追踪**：对比昨日数据，只关注新增变化
- **分类标签**：AI / Agent / MCP / Codex / Coding 等
- **语言分布**：Python / TypeScript / Rust / Go 等
- **历史归档**：按日保存，支持回溯对比
- **实时筛选**：按标签、语言、关键词搜索项目

## 自动更新

每天 **23:58 CST**（北京时间），GitHub Actions 自动运行：
1. 读取历史数据
2. 调用 GitHub API 获取最新项目数据
3. 计算增量（今日 - 昨日）
4. 生成 HTML 报告并更新网站

---

Powered by [Kimi Work](https://www.moonshot.cn/)

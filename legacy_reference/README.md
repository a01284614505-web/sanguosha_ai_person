# legacy_reference 索引

本目录只保存后续阶段需要参考的历史设计与审计材料，不被运行代码导入。

| 文件 | 来源 | 价值 | 适用阶段 |
|---|---|---|---|
| `ui_v2_layout.css` | `frontend/css/game.css` | 面向图片头像的对手卡片、装备槽、身份徽章和响应式布局参考；当前样式尚未直接接线 | R8 / 主线 Stage 7 |
| `chat_bubbles.css` | `frontend/chat_test.html:85-128` | user/AI/system 三类聊天气泡样式参考 | 主线 Stage 8 |
| `chat_panel_prototype.js` | `frontend/js/chat.js` | 聊天面板、气泡折叠和新消息提示结构蓝本；依赖未定义的 `wsClient`，不能直接作为运行代码 | 主线 Stage 8 |
| `skin_system_design.md` | `P1_PLANNING.md:310-443` | SkinConfigManager 与皮肤清单设计 | 主线 Stage 7 |
| `PROJECT_AUDIT_20260804_194452.md` | `archive/status_logs/` | 仍被现行重构方案引用的审计结论，包含托管系统未落地事实 | Stage 11 |
| `deprecated_docs_notes.md` | 本次 R2 整理 | 记录过期完成文档的校正口径，避免历史文档误导后续施工 | R3 |

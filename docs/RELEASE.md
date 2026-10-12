# GitHub 發布指南

本專案以 Git 推送可追蹤檔案到公開 GitHub repository. 不要使用 GitHub 網頁直接拖曳整個工作目錄, 因為那樣不會套用 `.gitignore`.

## v0.2.1 — Runtime Safety & Data Consistency

- Knowledge 驗證、快照與索引共用完整文字來源格式。
- 未變更的 Knowledge chunk 會復用相同模型的 embedding。
- Provider 觀測記錄失敗不會丟棄已完成回覆，並採用 provider usage metadata。
- Fabric Bridge 事件使用有界傳送佇列，玩家狀態回呼切回 Server Main Thread。
- Bridge 加入 connect/read timeout、pending request TTL 與 Fabric API 依賴宣告。
- Backup schedule health 可跨重啟恢復，相同錯誤告警有冷卻。
- Runtime ZIP 排除 CI、tests、dev requirements 與 Gradle 原始碼；完整原始碼仍保留在 GitHub。

## v0.2.0 — Reliability & Release Safety

- 修正 DMCC 連線所有權與 Relay handler 錯誤隔離。
- 排程備份失敗會寫入日誌、累計健康狀態並顯示於 Owner status。
- Agent 保留最後一個無工具模型回合，用來整合工具結果。
- AI data preview 不再影響套用狀態，同步期間來源變更會拒絕寫入過期 manifest。
- Music 播放失敗改以迴圈跳過，不再遞迴耗盡 stack。
- 發布 ZIP 採頂層白名單並拒絕 symbolic link，CI 會實際封裝驗證。
- 公開 Fabric Bridge 的完整 Gradle 原始碼、測試與可重現建置流程。

## 首次發布

```bash
git init
git add .
git status
```

確認暫存清單後, 建立首次提交並推送到 `https://github.com/oMiki0826o/Discord-bot`.

## 後續更新

```bash
git add .
git status
```

每次提交前都應檢查暫存清單. 只提交程式碼, 文件, 依賴宣告與安全範本.

## 不應進入 GitHub repository 的內容

- `.env`, `.env.local`.
- `.venv/`, `venv/`, Python cache 與測試 cache.
- `data/`, SQLite, Log, AI 使用者記憶與 Prompt override.
- `settings/*.json` 部署端設定.
- `dist/`, `.git/`, `.DS_Store`, `__MACOSX/` 與其他工作目錄附加檔.
- `tools/` 會保留在公開原始碼倉庫供 CI 與維護使用，但會由正式使用者 ZIP 排除.
- 其他內部協作暫存資料.

這些路徑已由 `.gitignore` 排除. `.env.example` 與 `settings/README.md` 會保留, 讓部署者知道必要環境變數與設定位置.

## 推送前檢查

1. `.env.example` 不包含真實 Token 或 API Key.
2. README 的啟動入口為 `python main.py`.
3. `requirements.txt` 與 `requirements-lock.txt` 符合驗證版本.
4. `git status` 未列出本文件的不應發布內容.
5. 必要 Module 可以正常載入, 且 `modules.required` 沒有被停用.
6. Slash Command, Owner Prefix Command, Module reload 與安全關閉至少完成一次實機測試.

## 可重現發布 ZIP

```bash
python tools/build_release.py
python -m zipfile --test "dist/Discord-Bot-v$(cat VERSION).zip"
```

封裝器使用明確的頂層白名單、拒絕 symbolic link，並排除 Secret、部署設定與 Runtime data。CI 會在 Python 測試通過後實際建立並驗證 ZIP。

## Fabric Bridge

Bridge 原始碼位於 `bridge/minecraft-bridge/`。CI 使用 Java 21 執行 Gradle tests 與 `remapJar`，並確認建出的 JAR 與 `bridge/java_bridge.jar` 完全相同。

## 原始碼可見性

此 repository 是 Public. 已追蹤的 `bot/` 與 `main.py` 會公開可見. `.gitignore` 只能排除本機檔案, 無法隱藏已提交的原始碼.

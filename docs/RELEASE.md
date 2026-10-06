# GitHub 發布指南

本專案以 Git 推送可追蹤檔案到公開 GitHub repository. 不要使用 GitHub 網頁直接拖曳整個工作目錄, 因為那樣不會套用 `.gitignore`.

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
- `tools/` 與其他只屬於維護者本機的內容.
- 其他內部協作暫存資料.

這些路徑已由 `.gitignore` 排除. `.env.example` 與 `settings/README.md` 會保留, 讓部署者知道必要環境變數與設定位置.

## 推送前檢查

1. `.env.example` 不包含真實 Token 或 API Key.
2. README 的啟動入口為 `python main.py`.
3. `requirements.txt` 與 `requirements-lock.txt` 符合驗證版本.
4. `git status` 未列出本文件的不應發布內容.
5. 必要 Module 可以正常載入, 且 `modules.required` 沒有被停用.
6. Slash Command, Owner Prefix Command, Module reload 與安全關閉至少完成一次實機測試.

## 原始碼可見性

此 repository 是 Public. 已追蹤的 `bot/` 與 `main.py` 會公開可見. `.gitignore` 只能排除本機檔案, 無法隱藏已提交的原始碼.

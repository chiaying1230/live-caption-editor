# 聽打工作台 · Live Caption Editor

給聽打員使用的本機 AI 輔助即時字幕 MVP。瀏覽器收音，由電腦上的 **faster-whisper** 辨識中文並以 **OpenCC s2twp** 轉為繁體字與臺灣用語。你可以在收音持續進行時，修改已確認的段落；修改會寫入 SQLite 並永久鎖定，晚到的 ASR 結果也無法覆寫。

第一版不接 Google Docs，不含說話者辨識、AI 摘要或雲端語音 API，不需要 API key。

## Windows 快速開始

1. 安裝 **64 位元 Python 3.11–3.13**（本機驗證版本：3.13.2），安裝時勾選 **Add Python to PATH**。建議先用 3.13。
2. 下載此 repository 的 ZIP 並**完整解壓縮**，或使用 Git：

   ```powershell
   git clone https://github.com/chiaying1230/live-caption-editor.git
   cd live-caption-editor
   ```

3. 在專案資料夾雙擊 **`start.cmd`**。它會建立 `.venv`、安裝依賴並啟動服務。不需要 Node.js、Docker、CUDA 或另裝 FFmpeg。
4. 保持服務視窗開啟，用最新版 **Chrome / Edge** 開啟 **http://127.0.0.1:8000**。
5. 按「開始收音」。首次會下載 Whisper `base` 模型（約 150 MB），完成後瀏覽器會要求麥克風權限。允許後開始說話。

初次安裝需網路；模型完整下載後優先直接使用本機快取，可離線辨識。預設使用 **CPU / int8**，不要求獨立顯示卡。建議至少 8 GB RAM；實際延遲取決於電腦與模型。

`start.cmd` 只對當次啟動的 PowerShell 使用執行原則參數，不修改電腦的永久設定。若公司電腦不允許執行，可使用下方的手動指令。程式不會自動安裝 Python 或修改系統設定。

### 手動啟動 / macOS / Linux

在專案根目錄執行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m caption
```

macOS / Linux 將 `.\.venv\Scripts\python.exe` 換成 `.venv/bin/python`，必要時建立環境使用 `python3`。預設只監聽 `127.0.0.1:8000`。

## 使用方式

- **新增聽打**：建立獨立逐字稿；左側可重新開啟最近 100 場紀錄。
- **開始收音**：準備模型後才開啟麥克風。黃色「暫定」會反覆更新，尚不可編輯。
- **確認字幕**：說話停頓約 0.8 秒，或單段收音達 12 秒，會排入最終辨識，完成後變成藍色「AI 確認」。AI 確認表示此段不再自動更新，並非內容保證正確。
- **人工校正**：點「編輯文字」，輸入後按「儲存並鎖定」或 `Ctrl+Enter`；`Esc` 取消。綠色「人工校正 · 已鎖定」仍可再次由人修改，但 ASR 永遠不能覆寫。刪成空白也會保留鎖定。
- **同時收音與校正**：編輯框不會被新字幕重建或搶走焦點。中文輸入法組字期間不觸發快捷鍵。
- **停止收音**：先送出尾端不足 100 ms 的音訊，再等候待處理片段完成。請等「開始收音」按鈕恢復可用後再匯出。
- **匯出**：TXT 包含所有段落、狀態與時間戳（UTF-8 BOM，方便 Windows 開啟）；JSON 完整保留所有欄位；SRT 只包含有文字的 AI 確認／人工校正段落。暫定字幕不會混入 SRT。

**文字會自動儲存；編輯框中的草稿要按儲存才會保存。** 有草稿時會阻止切換聽打並暫停匯出。離開頁面時，瀏覽器會在收音中／有草稿時提醒。不要在辨識未完成時關閉服務視窗。

## 設定模型與效能

在同一個 PowerShell 視窗設定後啟動（每次啟動有效）：

```powershell
$env:ASR_MODEL = 'small'  # tiny / base / small / medium / large-v3 / large-v3-turbo
.\start.ps1
```

| 變數 | 預設 | 說明 |
| --- | --- | --- |
| `ASR_MODEL` | `base` | 多語模型名稱，或已下載的 CTranslate2 Whisper 模型資料夾。中文不要選 `.en` 模型 |
| `ASR_DEVICE` | `cpu` | `cpu` 或 `cuda` |
| `ASR_COMPUTE_TYPE` | CPU: `int8` / CUDA: `float16` | 必須與硬體相容 |
| `ASR_CPU_THREADS` | `4` | CPU 推論執行緒數 |
| `VOICE_THRESHOLD` | `0.008` | RMS 收音門檻（0–1）。收不到小聲說話可降低；環境太吵可提高 |
| `MODEL_DIR` | `.cache/models` | 模型快取位置 |
| `DATA_DIR` | `data` | SQLite 資料夾 |

`base` 是易啟動的預設，專有名詞與臺灣口音仍需要人工校正。可改 `small` 提升品質；如果出現「辨識速度跟不上收音」，先改 `tiny` 或使用更快的電腦。不要使用英文專用模型。

GPU 為進階選項，需自行安裝符合 CTranslate2 的 NVIDIA CUDA / cuDNN；第一版已驗證的是 CPU 路徑。請參考 [faster-whisper 官方安裝說明](https://github.com/SYSTRAN/faster-whisper#requirements)。

## 資料與字幕狀態

音訊僅在記憶體中暫存，不寫入音檔。辨識不會上傳到第三方；首次依賴安裝、模型下載仍會連網。所有前端資源均由本機提供，沒有外部字型或追蹤碼。

文字存於 `data/captions.sqlite3`，模型存於 `.cache/models/`，均已列入 `.gitignore`。備份請先停止服務，再複製整個 `data/` 資料夾。不要把自己的逐字稿提交到 GitHub。

每個 segment 有 `id`、`session_id`、`start`、`end`（秒）、`text`、`status`、`locked`、`revision` 與 `updated_at`。

```text
provisional (暫定) ── 最終辨識成功 ──> committed (AI 確認)
                                           │ 人工儲存
                                           v
                                human_corrected + locked=true
```

ASR 寫入使用 SQL 的 `WHERE locked=0 AND status='provisional'` 條件。已確認與人工校正的段落皆不可由 ASR 改寫。人工儲存附帶 revision，若其他頁面已修改，回傳 409 並保留編輯框草稿，避免互相覆蓋；請重新載入後再修改。

時間戳是本機收音的相對時間，以 100 ms 音訊幀計算，包含前後緩衝／停頓；不是逐字對齊。續錄接在上一段末尾，停止期間的真實經過時間不計入。

## 串流架構與 API

```text
Browser microphone
  -> AudioWorklet: resample to 16 kHz mono PCM16, 100 ms/frame
  -> WebSocket receiver: RMS gate + 200 ms pre-roll + utterance buffer
  -> coalesced provisional job (~1.2 s) / bounded final job queue
  -> faster-whisper CPU worker + Silero VAD + OpenCC s2twp
  -> SQLite atomic status/lock guard -> WebSocket UI updates

Confirmed segment editor -> HTTP PATCH + revision check -> SQLite
```

採用 **faster-whisper + 自建分段／滾動預覽**，借鑑即時語音工作台的接收／推論分離方式。**這不是 WhisperLiveKit 或 LocalAgreement／AlignAtt 的完整實作**，也不宣稱 Whisper 原生逐 token 串流。選擇此方案是為了降低 Windows 安裝負擔，先驗證「持續辨識與人工校正互不覆蓋」的核心流程。後續可用 WhisperLiveKit 替換 ASR 緩衝策略，保留資料庫鎖定規則；參考 [WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit)。

接收音訊與模型推論獨立執行；推論放入執行緒，不阻塞 HTTP 編輯。暫定工作只保留最新快照；最終工作佇列超過 3 段時，停止接收並明確提示，仍完成已接受的最後一段，不默默丟棄積壓音訊。

| API | 用途 |
| --- | --- |
| `GET /api/health` | 模型設定／載入狀態與收音忙碌狀態 |
| `GET/POST /api/sessions` | 列出／建立聽打 |
| `GET /api/sessions/{sid}` | 讀取場次與全部字幕 |
| `PATCH /api/sessions/{sid}/segments/{id}` | `{text, revision}`，人工校正並鎖定 |
| `GET /api/sessions/{sid}/export/{txt\|json\|srt}` | 匯出逐字稿 |
| `WS /api/sessions/{sid}/audio` | 100 ms PCM16 binary frame；文字 `{ "type": "stop" }` 結束 |

WebSocket 回覆 `loading` → `ready` → 多個 `segment` → `stopped`；問題以 `error` 回傳。服務也提供 `/docs` API 文件。

## 測試

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m pytest -q
# 以下需要 Node.js 22+；一般使用不需要 Node.js
node --test tests/audio-worklet.test.cjs
```

自動測試不用下載模型，涵蓋人工鎖定、晚到 ASR、版本衝突、持久化、三種匯出、WebSocket 收音中編輯、Stop 尾段、過載、靜音、錯誤保留及來源限制。GitHub Actions 設定在 Windows / Ubuntu 執行。

實際模型、瀏覽器驗證步驟與已測版本見 [TESTING.md](TESTING.md)。

## 目前限制與排錯

- **延遲與分段**：預覽每約 1.2 秒排程一次，加上實際推論時間；確認需停頓／12 秒切段後再次推論。不是零延遲字幕，慢電腦可能無法長時間跟上。
- **音量門檻**：RMS 分段較簡單，背景音或小聲語音可能誤判；Silero VAD 只在模型辨識階段再過濾。連續說話遇 12 秒切段可能截斷字詞，沒有重疊拼接或跨段上下文。
- **辨識品質**：無法保證逐字正確；可能漏字、幻覺或不理想的標點，短句／尾段尤其如此。OpenCC 會轉換臺灣詞彙，可能影響專有名詞。
- **中斷與保存**：斷線後已接受的工作會嘗試完成，已辨識文字保存在 SQLite；音訊未持久化，強制終止服務／尚未辨識的音訊不能復原。未確認文字維持暫定，TXT / JSON 明確標示；可用作人工重建參考。
- **單一收音者**：整台服務同時只允許一條收音連線。可在其他頁面讀取／校正，但不是完整多人協作系統。
- **本機範圍**：沒有登入或加密資料庫。預設只服務本機，有限制 Host／Origin；請勿把此 MVP 直接暴露到網際網路。
- **麥克風不能使用**：確認使用 `http://127.0.0.1:8000` 或 `http://localhost:8000`，不要用區網 IP；確認瀏覽器允許麥克風、裝置未被拔除。
- **下載或 DLL 錯誤**：查看服務視窗的錯誤。確認網路可連 Hugging Face，Python 為 64 位元 3.11–3.13。若 CTranslate2 缺少 `VCRUNTIME`，安裝 Microsoft 官方 Visual C++ Redistributable x64，再重啟。
- **8000 已被占用**：先關閉之前的服務；或以 `.\.venv\Scripts\python.exe -m uvicorn caption.server:create_app --factory --host 127.0.0.1 --port 8001 --ws-max-size 65536` 啟動，改開 8001。
- **PyAV 相容性**：已限制 `av>=15,<17`，避免測試發現的 PyAV 19 與 faster-whisper 解碼參數不相容。請使用專案依賴安裝方式，不要單獨升級 PyAV。

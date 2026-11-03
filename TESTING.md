# MVP 驗證紀錄

## 改字自動記憶與修正紀錄

2026-11-03：45 項 Python、4 項 AudioWorklet 測試通過。新增一兩字修正的詞典斷詞與上下文擷取、後續 ASR 套用、持久化、連續自動儲存更新／撤回、衝突停用、手動優先、設定停用、過期 revision 無副作用、撤銷自動替換時停用規則，以及標點／數字／代名詞／整句改寫保留紀錄。驗證「色及 → 設計」不會混入後面的無關字串、「髮展 → 發展」「知持 → 支持」可記為詞語，語法改寫不形成替換規則。

`tests/correction-memory-ui.cjs` 在獨立測試資料庫使用真實 API／SQLite 驗證原地修改後出現詞彙、停用、重新整理保存、修正紀錄下載、手動詞彙尚未儲存的草稿保留，以及 390 px 窄畫面。原有字幕 UI 回歸通過，沒有瀏覽器錯誤。一般使用不需 Node.js；此測試需先以 `tests/memory-ui-server.py` 的方式建立兩段測試字幕並啟動獨立服務。

## 同步錄音與回放下載

2026-11-03：新增本機 WAV 錄音，保存與 ASR 相同的 16 kHz mono PCM16 音訊，包含靜音與未辨識出的部分。每次收音另存一檔，SQLite 記錄其時間範圍與完成／中斷狀態；再次收音的時間接在完整錄音末尾。

- 38 項 Python、4 項 AudioWorklet 測試通過。新增逐位元音訊內容與標頭、靜音與續錄時間、下載範圍／場次隔離、錄音中禁止下載、無效音訊、斷線保留、重啟復原、磁碟及中繼資料寫入失敗的清理。
- 在獨立測試資料庫與 SenseVoice 真實模型上執行 Edge 整合，使用公開 WAV 代替麥克風：暫定／確認字幕、收音中原地修改、自動儲存鎖定、停止、JSON 及 WAV 下載、瀏覽器實際播放錄音、重新整理後保留錄音清單皆通過，沒有瀏覽器錯誤。
- 原有大字字幕、焦點保留、閱讀跟隨、全螢幕與窄畫面回歸通過。沒有新增懸浮校正視窗。
- 未驗證使用者實體麥克風及數小時連續錄音。強制中斷時只嘗試保留已寫入的音訊；尚未收到或磁碟未成功寫入的內容無法保證復原。

## 移除校正時的懸浮區塊

2026-11-03：移除編輯期間額外出現的浮動字幕列與其預留高度，保留原句內容編輯和自動儲存。Edge UI 回歸通過：新字幕持續加入主畫面、編輯焦點保留、人工鎖定、自動儲存、取消、閱讀跟隨、全螢幕與窄畫面；確認不存在懸浮校正視窗或浮動字幕列。檢視編輯畫面截圖，沒有瀏覽器錯誤。

## 最新：候選模型與連續校正

已下載並實際比較 SenseVoice、Breeze ASR 25、Whisper small、Qwen3-ASR 0.6B。相同公開測試集、CPU LoRA 小規模試驗與速度限制見 [MODEL_COMPARISON.md](MODEL_COMPARISON.md)，不以公開朗讀樣本宣稱實際課堂已改善。

- 31 項 Python、4 項 AudioWorklet 測試通過。新增整句重新辨識、SenseVoice 片段隔離、暫定／確認標點與晚到 ASR 不得覆蓋人工鎖定。
- Windows 啟動檔實際安裝並啟動 SenseVoice 8002、Paraformer 連續校正 8001；兩個環境 `pip check` 通過。
- 兩個真實服務都通過公開 5 秒中文 WAV → 每 100 ms WebSocket → 暫定／確認 → SQLite 的檢查，輸出非空中文並保留標點。
- SenseVoice 通過 Edge 無頭整合：測試 WAV 代替實體麥克風，正式 AudioWorklet／真實模型、收音中原地編輯、自動儲存與鎖定、Stop、JSON 匯出、重新整理後保留修改、窄畫面無水平溢出，沒有瀏覽器錯誤。
- `tests/caption-ui.cjs` 原地編輯、焦點／草稿、歷史捲動、最新字幕、全螢幕、字級與窄畫面回歸通過。
- 發現並修正初始 HTML 的「開始收音／新增聽打」在資料尚未載入時過早可點。整合測試改以 segment ID 追蹤句子，避免自動儲存改變狀態後，測試選到下一句。

SenseVoice 使用 `sherpa-onnx==2.0.1`，Small INT8 模型約 240 MB，完整來源與 revision 見比較紀錄。以 OpenCC `s2tw` 轉換臺灣繁體字形；不做 s2twp 的臺灣詞彙替換。測試錄音代替麥克風，不代表使用者實體收音或數小時課堂已驗證。以下各節保留先前版本的測試紀錄，歷史測試數與預設參數以本節及最新 README 為準。

## 大字字幕與浮動校正介面

2026-11-02：Edge 無頭瀏覽器測試 `tests/caption-ui.cjs` 通過。以模擬 API／WebSocket 與合成麥克風音訊驗證：黑底黃字、自動跟隨、往上閱讀時保留位置、回到最新、收音中開啟浮動校正、草稿與焦點保留、新字幕位於校正視窗下方、儲存鎖定與過期更新保護、空白結果隱藏、拖曳、字級調整、全螢幕，以及縮小畫面後校正視窗仍在可視範圍。檢視桌面與窄螢幕截圖；沒有瀏覽器錯誤。此項測試不代表真實 ASR 品質改善。

回歸：24 項 Python、4 項 AudioWorklet 測試通過。可在專案安裝 Playwright 至 `work`，另啟服務於 8010，再執行 `node tests/caption-ui.cjs`；可用 `UI_BASE_URL` 指定其他本機測試網址。真實模型的 `tests/browser-smoke.cjs` 也已配合新介面更新選取方式，這次未重跑模型測試。

日期：2026-11-02（Asia/Taipei）。下列為本機實際執行結果，未將硬體麥克風測試或 GitHub CI 結果混入。

## 環境

- Windows x64、Python 3.13.2、Node.js 24.21.0、Microsoft Edge（Playwright 驅動）
- faster-whisper 1.2.1、CTranslate2 4.8.4、PyAV 16.1.0
- FastAPI 0.162.0、Uvicorn 0.54.0、SQLite（Python 內建）
- NumPy 2.5.4、OpenCC Python 0.1.7、pytest 9.2.0
- Whisper **base / CPU / int8 / 4 threads**

## 結果

- **10 / 10 Python 測試通過**：狀態轉換、20 次晚到 ASR 不得覆蓋人工校正、revision 衝突、空白人工校正、SQLite 重開、TXT／JSON／SRT、WebSocket 收音中 HTTP 編輯、尾段確認、過載排空、靜音、錯誤保留、跨來源與多重收音拒絕。
- **4 / 4 音訊測試通過**：8、16、44.1、48 kHz 輸入轉 16 kHz，驗證輸出長度、PCM 數值與最後不足 100 ms 的補零送出。
- **真實模型推論通過**：下載 Whisper base，使用 PaddleSpeech 公開的約 5 秒中文範例；輸出非空繁體中文：「我認為跑步最重要的就是給我帶來了身體健康。」單次完整錄音測試含快取模型載入約 5.4 秒，不是長時延遲或準確率基準。
- **真實瀏覽器與模型整合通過**：以 WAV 測試檔代替瀏覽器麥克風，使用正式 AudioWorklet、WebSocket、faster-whisper、SQLite，看到暫定與已確認字幕；收音繼續時開啟編輯框，等待新音訊後草稿仍在，儲存變人工校正；Stop 完成後不留暫定段落；下載 JSON 確認鎖定欄位；重新整理後修改仍存在。
- **版面與錯誤檢查通過**：1440 px 桌面與 390 px 手機截圖檢視；手機無水平溢出；上述流程無 JavaScript page error。
- `pip check` 通過。
- 已直接執行 Windows `start.cmd`；在 `PIP_NO_INDEX=1` 與 `HF_HUB_OFFLINE=1` 的離線設定下，使用既有安裝成功啟動預設 8000 服務。啟動雜湊計算使用 Python，避免依賴 Windows PowerShell 的額外 cmdlet。

發現並修正：PyAV 19 的 `av.open` 不接受 faster-whisper 使用的 `metadata_errors` 參數，已限制 PyAV 15–16，並以 16.1.0 重新執行成功。

也以快速「新增聽打 → 開始收音」重現場次切換與收音競爭，已在建立／切換期間立即停用收音按鈕，並檢查字幕的 session_id，避免字幕寫入錯誤場次；瀏覽器測試包含此回歸檢查。

## 重現瀏覽器整合測試（選用）

這是另外的人工啟動整合測試，不隨一般單元測試下載模型。需要 Edge、Node.js 與可下載模型的網路；完全不使用實體麥克風。

先依 README 安裝並啟動服務，另開 PowerShell 在專案目錄執行：

```powershell
New-Item -ItemType Directory -Force work
npm install --prefix work --no-package-lock --no-audit --no-fund playwright
Invoke-WebRequest 'https://paddlespeech.cdn.bcebos.com/PaddleAudio/zh.wav' -OutFile 'work/zh.wav'
$env:SMOKE_BASE_URL = 'http://127.0.0.1:8000'
node tests/browser-smoke.cjs
```

測試會新增一場聽打、使用測試 WAV 循環收音、修改第一段，並下載 JSON 到瀏覽器測試的暫存區；會保留此場測試文字在本機 SQLite。截圖寫入 `work/smoke-desktop.png`、`work/smoke-mobile.png`。

音訊來源：[PaddleSpeech 官方語音辨識範例](https://github.com/PaddlePaddle/PaddleSpeech/blob/develop/demos/speech_recognition/README.md)。不將音訊或模型收進 repository。

## 尚未驗證

- 使用者實體麥克風、不同房間噪音、臺灣口音與課堂專有名詞。
- 長達數小時的連續收音、不同 CPU 的即時處理能力。
- GPU 路徑、macOS / Linux 實機、Python 3.11 / 3.12 實機。
- GitHub Actions 結果需以 repository 的 Actions 頁面為準。

第一次使用請錄一小段實際課堂語音，確認麥克風權限、音量門檻、文字品質與延遲，再決定模型大小。

## 麥克風無字幕回報後的回歸測試

修正原先音量未達門檻時沒有任何回饋的情況：加入裝置選擇、瀏覽器音量表、服務端接收音訊秒數、推論狀態、收音看門狗及可即時調整的靈敏度。預設門檻從 0.008 降為 0.003；前端不再要求瀏覽器降噪，以免小聲輸入被過濾。偵測聲音即顯示暫定段落佔位，文字仍以實際模型結果為準。

- **16 項 Python 測試通過**：新增低音量原本被忽略的案例、首幀即回報暫定、靜音接收統計、收音中降低門檻後辨識，以及 4 種無效門檻的拒絕。
- **4 項 AudioWorklet 測試通過**。
- 可用 `.\.venv\Scripts\python.exe tests/real-asr-smoke.py` 對獨立的 8001 測試服務執行公開 WAV → 真實模型的傳輸測試；不開啟實體麥克風，不修改既有場次。
- 使用者實體麥克風的選取與音量，仍需在更新後的畫面確認，不能以公開 WAV 測試代替。

## FunASR CPU 初步實測

硬體：同一台 i7-1260P／16 GB Windows 筆電，使用獨立短路徑環境，Python 3.13.2、FunASR 1.4.19、PyTorch／torchaudio 2.10.0+cpu。未使用 GPU。套件 `pip check` 通過。

選用模型與固定版本：

- `funasr/paraformer-zh-streaming`：`apache-2.0-20260804`，模型權重 Apache 2.0。
- `funasr/paraformer-zh`：`d7811ee3ac581fbcfdeb37c98c6ba674028433dc`；發布者模型卡標示 Apache 2.0。
- `funasr/ct-punc`：`d0e55e2b8722a78b63705ff443d09c4f86e5d750`；發布者模型卡標示 Apache 2.0。
- FunASR 工具套件本身為 MIT。模型不打包入 repository 或 ZIP。

以 PaddleSpeech 約 5 秒中文音訊，以及 Paraformer 官方約 5.55 秒中文範例執行 FP32／4 執行緒／600 ms chunk：

| 音訊長度 | 串流推論總時間 | 最慢單塊推論 | 句尾推論 |
| --- | --- | --- | --- |
| 5.00 秒 | 5.355 秒 | 0.771 秒 | 2.021 秒 |
| 5.55 秒 | 4.930 秒 | 0.747 秒 | 1.816 秒 |

兩例皆有完整中文輸出，先轉繁體後與可辨讀內容相符。時間不含模型下載與載入，不是端到端字幕延遲。樣本太少，不能據此推定臺灣口音或課堂品質。

另外實測對所有 Linear 層做 PyTorch 動態 int8 量化：串流結果出現重複字，速度也未改善，**未採用此量化方式**。保留原精度推論。

FP32 參數調整（同一份 5.00 秒公開錄音）：

| 執行緒 | 音訊塊 | 串流推論總時間 | 最慢單塊 |
| --- | --- | --- | --- |
| 2 | 600 ms | 5.614 秒 | 0.808 秒 |
| 4 | 1200 ms | 3.455 秒 | 0.907 秒 |
| 8 | 1200 ms | 3.441 秒 | 0.795 秒 |
| 4 | 1800 ms | 2.503 秒 | 0.911 秒 |

四組文字相同，因此試用版預設 4 執行緒、1800 ms。它降低計算負擔，也會增加收集音訊所需的等待；不是低於一秒的字幕保證。模型首次載入與環境匯入約數十秒，不含於上表。

目前 24 項 Python 測試、4 項 AudioWorklet 測試通過；包含 FunASR 600 ms 原生串流快照合併不漏音、場次快取隔離、句尾完整重新辨識、標點、WebSocket 中人工校正與鎖定。

正式服務整合實測：使用 1800 ms 塊、三個真實模型，以及同一公開中文 WAV，走完整 WebSocket／AudioStream／SQLite 流程，通過即時接收統計、暫定文字、句尾校正、標點、Stop 與持久化檢查；最後輸出「我認為跑步最重要的就是給我帶來了身體健康。」測試沒有使用實體麥克風。

可在 FunASR 環境重現模型計算測試：

```powershell
python tests/benchmark-funasr.py work/zh.wav --chunk-ms 1800 --output work/funasr-benchmark.json
```

這個腳本使用你明確指定的本機 16 kHz mono WAV，並將結果文字寫入指定 JSON。數字只代表模型計算時間，並非端到端字幕延遲。不要只憑兩份短樣本就取代課堂情境的實際評估。


## 即時更新、原地編輯與字彙表

2026-11-02 後續更新：預設音訊塊改為 1200 ms。合併快照逐塊發布暫定文字；預覽與最終工作交替，保留停頓前尚未執行的預覽。暫定字幕先補內部標點，不把每塊音訊末尾當作句尾；確認時再次辨識並補完整標點。

公開 4.997 秒中文 WAV、同一 CPU、1200 ms 與暫定標點的實測：串流模型計算合計 2.020 秒，最慢單塊 0.827 秒，句尾計算 0.653 秒，載入 43.796 秒。這些是模型計算時間，並非端到端延遲；單樣本不能證明臺灣課堂正確率改善。

28 項 Python 與 4 項 AudioWorklet 測試通過；新增逐塊更新、預覽先於慢速句尾、內部標點，以及字彙表持久化、長詞優先、不連鎖替換、特殊字元、無效輸入與人工文字保護。Edge UI 回歸更新為原地內容編輯、自動儲存、Esc 取消、校正中最新字幕、游標保護、閱讀跟隨、字級／全螢幕與窄畫面。先前浮動視窗介面已由原地編輯取代。

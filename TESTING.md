# MVP 驗證紀錄

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

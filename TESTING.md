# MVP 驗證紀錄

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

發現並修正：PyAV 19 的 `av.open` 不接受 faster-whisper 使用的 `metadata_errors` 參數，已限制 PyAV 15–16，並以 16.1.0 重新執行成功。

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

# 即時字幕 · Live Caption Editor

給聽打員使用的本機 AI 輔助即時字幕 MVP。瀏覽器收音，由電腦上的 **faster-whisper** 辨識中文並以 **OpenCC s2twp** 轉為繁體字與臺灣用語。你可以在收音持續進行時，修改已確認的段落；修改會寫入 SQLite 並永久鎖定，晚到的 ASR 結果也無法覆寫。

第一版不接 Google Docs，不含說話者辨識、AI 摘要或雲端語音 API，不需要 API key。

## FunASR／Paraformer CPU 試用版

除了原本 Whisper，另提供 **Paraformer 連續校正 → 標點恢復 → 繁體轉換** 的本機試用路線。每次重新評估當前一句的完整音訊，後來的語音可修正前面的暫定文字。這是滾動式離線辨識，不是原生逐字串流；仍需用實際口音與課堂術語比較品質。

1. 使用同樣的 64 位元 Python 3.11–3.13，在專案目錄雙擊 **`start-funasr.cmd`**。
2. 開啟 **http://127.0.0.1:8001**，在「設定與紀錄」可確認 `FunASR Paraformer 連續校正 · CPU`。
3. 按開始收音，等候模型準備完成。首次需下載辨識與標點兩個模型，合計約 2 GB，之後使用本機快取。

FunASR 使用獨立 Python 環境，預設位於 `%USERPROFILE%/Documents/Codex/work/live-caption-funasr`，以避免 PyTorch 安裝遇到 Windows 長路徑限制，也避免將套件裝進 OneDrive 重新導向的「文件」資料夾；不修改系統設定。可透過 `CAPTION_FUNASR_ENV` 指定其他短路徑。

**8001 試用版使用 `data-funasr/` 獨立資料庫；原本的 Whisper 逐字稿仍在 8000 的 `data/`。** 先比較兩者效果，再決定是否切換；同一場測試請只用一個頁面收音。兩個啟動視窗關閉即可停止對應服務。

模型快取在 `.cache/funasr/`，可用 `FUNASR_MODEL_DIR` 指定位置。Windows 啟動檔預設 `FUNASR_PREVIEW_MODE=context`：每 1.5 秒排程暫定辨識，單段最多 12 秒，句尾再確認一次。排程間隔不等於端到端延遲，還需加上推論時間。人工鎖定規則不變。

如要比較先前的原生串流模式，可在 PowerShell 設定 `$env:FUNASR_PREVIEW_MODE='streaming'` 再執行 `./start-funasr.ps1`；它另外載入串流模型，總快取約 3 GB。原生模式預設 1.2 秒音訊塊，可用 `FUNASR_CHUNK_MS=600`／`1200`／`1800` 調整，單段上限 20 秒。直接用 Python 建立引擎時仍預設原生模式。兩種模式都保留暫定字幕與句尾確認。

技術來源：[FunASR](https://github.com/modelscope/FunASR)、[Paraformer 串流模型](https://huggingface.co/funasr/paraformer-zh-streaming)。程式碼 MIT，選用模型的授權與固定版本見 [TESTING.md](TESTING.md)。

## SenseVoice CPU 比較版

雙擊 **`start-sensevoice.cmd`**，開啟 **http://127.0.0.1:8002**。使用相同的黑底黃字字幕、原地編輯、字彙表與人工鎖定；不需 API key 或 GPU。首次安裝選用套件，開始收音時下載約 240 MB 的 SenseVoice Small INT8 模型，之後使用本機快取。

每 2.4 秒排程當前一句的完整音訊，最長 8 秒切段，模型同時產生文字與標點，再做繁體字轉換。這也是滾動式離線辨識，可能改動暫定文字，不能保證逐字即時顯示。**8002 使用獨立的 `data-sensevoice/` 資料庫；舊逐字稿與字彙表仍留在原本的服務。** 同一時間只在一個頁面收音，切換模型前先停止。

此模型是公開測試中值得比較的候選，沒有證明能全面改善課堂辨識。可在同一房間、同一麥克風說相同內容，比較 8001 與 8002。模型路徑可用 `SENSEVOICE_MODEL_DIR` 指定，預設 `.cache/asr-candidates/sensevoice/`。採用 [sherpa-onnx 官方支援的 SenseVoice 匯出](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)，權重使用 [SenseVoice 上游模型授權](https://huggingface.co/FunAudioLLM/SenseVoiceSmall/blob/main/LICENSE)，不可把工具套件的授權視為模型權重的授權。

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

初次安裝需網路；模型完整下載後優先直接使用本機快取，可離線辨識。啟動檔僅在首次安裝或 `pyproject.toml` 變更時安裝依賴，避免每次啟動都要連網。預設使用 **CPU / int8**，不要求獨立顯示卡。建議至少 8 GB RAM；實際延遲取決於電腦與模型。

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

- **字幕畫面**：黑底黃字，預設 64 px，可調整 36–112 px。按「全螢幕」或 F11 放大。字幕依序出現，會自動跟到最新一句，不需一直手動往下捲。
- **查看前文**：往上捲動會暫停跟隨，避免新字幕打斷閱讀；按「回到最新字幕」恢復。直接編輯句子時也會保留閱讀位置。
- **新增聽打**：在「設定與紀錄」建立獨立逐字稿，或重新開啟最近 100 場紀錄。匯出、麥克風及辨識模型資訊也收在這裡。
- **開始收音**：準備模型後才開啟麥克風。虛線底線的暫定字幕會反覆更新，尚不可編輯。空白或只有標點的辨識結果不顯示在字幕畫面，但仍保留在資料庫與完整匯出中。
- **確認收音來源**：在設定中選擇實際麥克風；說話時底部「輸入音量」條應有變化。設定面板會回報服務收到幾秒音訊與模型處理狀態。
- **小聲說話**：若音量條會動但一直沒有文字，可將「收音靈敏度」改成「高」，不需停止收音。若音量條完全不動，先停止，再改選正確麥克風。
- **確認字幕**：說話停頓約 0.8 秒，或單段收音達上限（Whisper／Paraformer 連續校正 12 秒、Paraformer 原生串流 20 秒、SenseVoice 8 秒），會排入最終辨識，完成後移除虛線底線。AI 確認表示此段不再自動更新，並非內容保證正確。游標停在句子上可查看狀態與時間戳。
- **人工校正**：像 Word 一樣直接點選已確認文字，放置游標、選字、打字或貼上文字；不開啟浮動視窗。停筆約 1.2 秒自動儲存，也可按原句下方「儲存」或 `Ctrl+Enter`。`Esc`／「取消」只取消尚未儲存的修改；已自動儲存的文字可直接再改。✓ 表示人工鎖定，ASR 不會覆寫。
- **同時收音與校正**：直接在原句編輯，沒有懸浮校正視窗或額外的浮動字幕區塊。編輯時保留閱讀位置，新字幕持續加入主畫面，不改動草稿或搶走游標。結束編輯後按「回到最新字幕」即可恢復跟隨。中文輸入法組字期間不觸發儲存，組字結束後才排程。
- **停止收音**：先送出尾端不足 100 ms 的音訊，再等候待處理片段完成。請等「開始收音」按鈕恢復可用後再匯出。
- **同步錄音**：開始收音時會自動保存同一份麥克風音訊，底部顯示「同步錄音」。停止後在「設定與紀錄 → 同步錄音」回放或下載 WAV，包含停頓與未辨識出文字的部分。每次開始／停止各自保存一份，重開頁面仍可取得；更新前的字幕無法補回錄音。
- **匯出**：TXT 包含所有段落、狀態與時間戳（UTF-8 BOM，方便 Windows 開啟）；JSON 完整保留所有欄位；SRT 只包含有文字的 AI 確認／人工校正段落。暫定字幕不會混入 SRT。

**校正文字停筆後自動儲存；顯示儲存完成才代表已保存。** 有草稿時會阻止切換聽打並暫停匯出。離開頁面時，瀏覽器會在收音中／有草稿時提醒。不要在辨識未完成時關閉服務視窗。

## 糾正字彙表與訓練資料

### 改字自動記住

「設定與紀錄 → 我的修正詞彙表」預設開啟自動記憶。直接改字並儲存後，程式比較原始辨識與最新修改，只改一兩個字也會以本機中文詞典斷詞並帶入上下文，擷取成詞語或較長短句。例如「神性障礙者 → 身心障礙者」、「小額麻痺 → 小兒麻痺」、「知持 → 支持」。使用 [jieba](https://github.com/fxsjy/jieba) 的詞語位置，停用未登錄詞的猜測；為斷詞暫時轉換字形，保存的仍是原本繁體字。**詞典斷詞不能保證詞界或語意正確。** 詞彙表會顯示實際記住的範圍，可逐筆停用。字典不認識或無法明確對齊的修改留在紀錄，可用手動詞彙補充。

新學到的詞只作用於之後的 AI 字幕；人工已修改的內容仍鎖定。標點、數字、代名詞、單純補字／刪字，以及大幅整句改寫會留在修正紀錄，不直接形成替換規則。連續自動儲存會依原始辨識重算，更新或撤回尚未完成的詞語；若同一錯詞有不同改法，先暫停自動套用，手動詞彙表可指定優先答案。人工改回被自動替換的原詞時，該自動規則會停用。

取消「自動記住」會停止新增詞語規則，既有詞語可各自停用；修正紀錄仍會保存。修正詞彙、歷史與開關保存在該服務的本機 SQLite，重啟後保留。可匯出修正紀錄 JSON。這不會訓練語音模型，局部改字也不代表整個音訊片段已逐字校對，不會自動把它當成正確訓練標註。

已實測候選模型與公開語料訓練，結果及限制見 [MODEL_COMPARISON.md](MODEL_COMPARISON.md)。

已增加可在本機執行的 CPU LoRA 小規模試驗工具，資料格式、獨立測試集與選模規則見 [TRAINING.md](TRAINING.md)。它不會自動替換正式服務，也不代表已證明跨課程泛化。

在「設定與紀錄 → 糾正字彙表」貼上 `錯詞 → 正確詞`，每行一組；也可從 Excel 複製兩欄，使用 Tab 分隔。按「儲存字彙表」後，之後的 AI 暫定／確認字幕會套用。最多 500 組，每個詞最多 100 字。它儲存在該服務的 SQLite，三種模型服務各自獨立。

只做明確字串替換，長詞優先、單次比對，不連鎖替換；不是模糊猜字、模型熱詞偏置或模型訓練。避免加入「是 → 某專有名詞」等過度寬泛規則。既有確認段落與人工校正不會被批次改寫，字彙表也不影響人工輸入的文字。清空並儲存即可停用之後的替換。

只有文字聽打稿，可用來整理詞彙與典型用語，不能單獨作為語音／文字配對的聲學微調資料。有對應錄音的稿子可另行對齊、清理、切成配對片段，並保留不同場次作測試集；先比較字錯率和字幕延遲，再決定是否微調。此版本沒有上傳語料或自動訓練功能，人工校正也不會暗中訓練模型。參考 [FunASR 官方訓練說明](https://github.com/modelscope/FunASR/blob/main/docs/training.md)。

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
| `VOICE_THRESHOLD` | `0.003` | RMS 收音門檻（0–1）；畫面的靈敏度選擇可覆蓋此值。收不到小聲說話可降低；環境太吵可提高 |
| `MODEL_DIR` | `.cache/models` | 模型快取位置 |
| `DATA_DIR` | `data` | SQLite 資料夾 |
| `ASR_BACKEND` | `whisper` | `whisper`、`funasr` 或 `sensevoice`；對應啟動檔會自動設定 |
| `CAPTION_PORT` | `8000` | 本機服務連接埠；FunASR 8001、SenseVoice 8002 |
| `FUNASR_MODEL_DIR` | `.cache/funasr` | Paraformer 與標點模型資料夾 |
| `FUNASR_PREVIEW_MODE` | Python: `streaming` / Windows FunASR 啟動檔: `context` | 原生串流／整句連續校正 |
| `SENSEVOICE_MODEL_DIR` | `.cache/asr-candidates/sensevoice` | SenseVoice ONNX 模型與 tokens.txt |

`base` 是易啟動的預設，專有名詞與臺灣口音仍需要人工校正。`small` 可作比較，但更大模型未必在你的內容更準，且可能變慢；如果出現「辨識速度跟不上收音」，先改 `tiny` 或使用更快的電腦。不要使用英文專用模型。

GPU 為進階選項，需自行安裝符合 CTranslate2 的 NVIDIA CUDA / cuDNN；第一版已驗證的是 CPU 路徑。請參考 [faster-whisper 官方安裝說明](https://github.com/SYSTRAN/faster-whisper#requirements)。

## 資料與字幕狀態

音訊會以 **16 kHz、單聲道、16-bit PCM WAV** 寫入本機資料夾，約每小時 115 MB；它與 ASR 使用相同的音訊，並非麥克風原始取樣率的高音質備份。辨識與同步錄音不會上傳到第三方；首次依賴安裝、模型下載仍會連網。所有前端資源均由本機提供，沒有外部字型或追蹤碼。

Whisper 文字與錄音分別存於 `data/captions.sqlite3`、`data/recordings/`；FunASR 使用 `data-funasr/`，SenseVoice 使用 `data-sensevoice/`。模型與上述資料均已列入 `.gitignore`。備份請先停止服務，再複製該服務的整個資料夾，包含資料庫與錄音。不要把自己的逐字稿或音檔提交到 GitHub。此版不自動刪除錄音，請保留足夠磁碟空間。

錄音清單保留相對逐字稿的開始／結束時間、時長與完成／中斷狀態，JSON 逐字稿匯出也帶有這些中繼資料；音檔另行下載。續錄的字幕時間會接在先前完整收音末尾，包含先前的靜音，方便對照錄音；停止期間的現實時間不計入。早期沒有錄音的逐字稿仍以舊字幕末尾作續錄起點。

每個 segment 有 `id`、`session_id`、`start`、`end`（秒）、`text`、`status`、`locked`、`revision` 與 `updated_at`。

```text
provisional (暫定) ── 最終辨識成功 ──> committed (AI 確認)
                                           │ 人工儲存
                                           v
                                human_corrected + locked=true
```

ASR 寫入使用 SQL 的 `WHERE locked=0 AND status='provisional'` 條件。已確認與人工校正的段落皆不可由 ASR 改寫。人工儲存附帶 revision，若其他頁面已修改，回傳 409 並保留編輯框草稿，避免互相覆蓋；請先複製草稿，再取消、重新載入後修改。

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
| `GET/PUT /api/correction-memory` | 自動記住的詞彙／修正紀錄；設定是否新增詞彙 |
| `PATCH /api/correction-memory/terms` | `{source, enabled}`，啟用／停用一筆自動詞彙 |
| `GET /api/correction-memory/export` | 下載修正詞彙與紀錄 JSON |
| `GET /api/sessions/{sid}/recordings` | 該場次的錄音清單與時間戳 |
| `GET /api/sessions/{sid}/recordings/{rid}/audio` | 停止後回放 WAV；加 `?download=true` 下載 |
| `PATCH /api/sessions/{sid}/segments/{id}` | `{text, revision}`，人工校正並鎖定 |
| `GET /api/sessions/{sid}/export/{txt\|json\|srt}` | 匯出逐字稿 |
| `WS /api/sessions/{sid}/audio` | 100 ms PCM16 binary frame；文字 `{ "type": "stop" }` 結束 |

WebSocket 回覆 `loading` → `ready` → 多個 `segment` → `stopped`；另以 `audio` 回報收音秒數／音量，以 `recognizing` 回報推論中。`{"type":"configure","threshold":0.001}` 可調整當次收音門檻（0.0005–0.1）。問題以 `error` 回傳。`/api/health` 的 `capture` 欄位可查看音訊接收狀態，不含音訊或文字內容。服務也提供 `/docs` API 文件。

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

- **延遲與分段**：Whisper／Paraformer 原生串流每約 1.2 秒、Paraformer 連續校正 1.5 秒、SenseVoice 2.4 秒排程預覽，加上實際推論時間；確認需停頓或達各模式切段上限後再次推論。不是零延遲字幕，慢電腦可能無法長時間跟上。
- **音量門檻**：RMS 分段較簡單，背景音或小聲語音可能誤判；Silero VAD 只在模型辨識階段再過濾。連續說話遇 12 秒切段可能截斷字詞，沒有重疊拼接或跨段上下文。
- **辨識品質**：無法保證逐字正確；可能漏字、幻覺或不理想的標點，短句／尾段尤其如此。Whisper 與 FunASR 的 OpenCC s2twp 也轉換臺灣詞彙，可能影響專有名詞；SenseVoice 使用 s2tw，轉為臺灣繁體字形，不做臺灣詞彙替換。
- **中斷與保存**：斷線後已接受的工作會嘗試完成，已辨識文字保存在 SQLite，收到的音訊另存 WAV 並標示中斷。重啟服務時會嘗試復原錄音長度；瀏覽器尚未送出或磁碟未成功寫入的音訊無法保證恢復。未確認文字維持暫定，TXT / JSON 明確標示。錄音寫入失敗時會停止收音並顯示錯誤，避免誤以為已完整保存。
- **單一收音者**：整台服務同時只允許一條收音連線。可在其他頁面讀取／校正，但不是完整多人協作系統。
- **本機範圍**：沒有登入或加密資料庫。預設只服務本機，有限制 Host／Origin；請勿把此 MVP 直接暴露到網際網路。
- **麥克風不能使用**：確認使用 `http://127.0.0.1:8000` 或 `http://localhost:8000`，不要用區網 IP；確認瀏覽器允許麥克風、裝置未被拔除。
- **正在收音但沒有字幕**：先看音量條。有變化而音量偏小時改用「高」靈敏度；完全不動時停止並改選麥克風。若顯示服務已收到音訊、正在辨識，請講一個完整句子並等候模型回覆；若模型回覆空白，畫面會提示確認收音來源與說話音量。
- **下載或 DLL 錯誤**：查看服務視窗的錯誤。確認網路可連 Hugging Face，Python 為 64 位元 3.11–3.13。若 CTranslate2 缺少 `VCRUNTIME`，安裝 Microsoft 官方 Visual C++ Redistributable x64，再重啟。
- **8000 已被占用**：先關閉之前的服務；或以 `.\.venv\Scripts\python.exe -m uvicorn caption.server:create_app --factory --host 127.0.0.1 --port 8001 --ws-max-size 65536` 啟動，改開 8001。
- **PyAV 相容性**：已限制 `av>=15,<17`，避免測試發現的 PyAV 19 與 faster-whisper 解碼參數不相容。請使用專案依賴安裝方式，不要單獨升級 PyAV。


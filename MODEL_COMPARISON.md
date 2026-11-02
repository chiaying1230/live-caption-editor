# 本機中文模型比較與改進紀錄

測試平台：Windows、i7-1260P、16 GB RAM、CPU 四執行緒，沒有 NVIDIA GPU。這是小樣本工程評估，不是模型排行榜，也不是實際課堂正確率承諾。

## 已採取的行動

- 找到並下載 FLEURS 中文與 Taiwan Tongues 臺灣華語公開語料，整理為 248 段、約 29.7 分鐘，區分訓練、驗證與測試集。Taiwan Tongues 選取不同說話者，避免本次訓練／測試說話者重疊。
- 實際執行 Paraformer CPU LoRA 小規模試驗：先 96 步，再以混合資料跑 160 步。驗證字錯率沒有優於原模型，因此保留原模型，沒有把無改善的權重套入服務。這份資料規模不足以證明跨課程泛化。
- 實測 SenseVoice Small INT8、Breeze ASR 25 INT8、Whisper small INT8、Qwen3-ASR 0.6B INT8，與既有 Paraformer 比較。
- 加入 SenseVoice 選用後端與 Windows 啟動檔；FunASR 啟動檔改用整句連續校正，原生串流仍可選用。

## 相同 48 段公開測試音訊

兩模型使用相同 24 段 FLEURS、24 段 Taiwan Tongues 測試集。CER 是替換／刪除／插入字數除以參考字數；比較前以 OpenCC 統一簡繁、轉小寫並去除標點與空白，保留數字形式差異。未測標點準確率。

| 資料 | 參考字數 | Paraformer 原模型 | SenseVoice Small INT8 |
| --- | ---: | ---: | ---: |
| FLEURS 中文 24 段 | 779 | 83 字錯誤，10.65% | 68 字錯誤，8.73% |
| Taiwan Tongues 24 段 | 193 | 6 字錯誤，3.11% | 7 字錯誤，3.63% |
| 合計 48 段 | 972 | 89 字錯誤，9.16% | 75 字錯誤，7.72% |

SenseVoice 合計較好，但臺灣短句多一個字錯誤；不能稱為全面勝出。兩組大多是清楚的朗讀音訊，和教室遠距離收音、口語停頓、術語不同。公開語料是否曾出現在上游預訓練資料中未知。

## 其他候選：共同 8 段初篩

較大的候選先跑相同 4 段 FLEURS、4 段 Taiwan Tongues，共 198 參考字。不能把這張表與上表不同樣本數的百分比直接排名。

| 模型 | 嚴格 CER | 本機觀察與決定 |
| --- | ---: | --- |
| Paraformer 原模型 | 23/198，11.62% | 保留為可選版本 |
| SenseVoice Small INT8 | 7/198，3.54% | 進一步跑完 48 段，加入試用 |
| Breeze ASR 25 INT8 | 11/198，5.56% | 18 秒課堂片段約需 23 秒推論，不適合這台電腦反覆預覽 |
| Whisper small INT8 | 29/198，14.65% | 這批資料沒有優勢，未改預設 |
| Qwen3-ASR 0.6B INT8 | 23/198，11.62% | 數字輸出格式造成明顯評分差異；18 秒課堂片段約需 9–10 秒推論，暫不接為即時後端 |

Qwen 常把 `2011` 寫成 `二零一一`。另對所有候選採相同的簡單中文數字轉換後，Qwen 此 8 段降至 7/198，SenseVoice 仍為 7/198。這是補充的格式敏感度檢查，不代表已驗證 Qwen 與 SenseVoice 整體品質相同。短熱詞提示也做了配對測試，沒有穩定改善，未當成修正方案。

另抽取課堂錄音片段比較輸出；由於沒有人工核對到逐字、逐段的參考稿，這些片段只供檢視，不計 CER，也不作為已改善課堂品質的證據。不同候選測試期間的背景負載不同，上述推論時間只供初篩，不是嚴格速度排名或字幕延遲。

## 暫定字幕連續校正

原生串流累加早期猜測，暫定文字可能把錯字一路保留下去。新增 `context` 模式：每 1.5 秒排程，重新辨識當前一句完整音訊；後文可修正前文，最長 12 秒切段。仍不會改動已確認或人工鎖定段落。不是原生 token streaming。

使用正式 AudioStream／SQLite、按真實速度每 100 ms 送音訊，測試 2 段 FLEURS、2 段 Taiwan Tongues、2 段課堂片段，模型預先載入：

| 指標（6 段） | 原生串流 1200 ms | 連續校正 1500 ms |
| --- | ---: | ---: |
| 首次有字時間中位數 | 2.10 秒 | 1.98 秒 |
| 最長文字更新間隔 | 2.08 秒 | 1.71 秒 |
| 音訊送完後最長等待 | 2.60 秒 | 0.81 秒 |

有個別片段首次出字反而稍慢，不能保證所有聲音更快。未驗證數小時連續收音；固定切段仍可能截斷詞語，沒有跨段重疊拼接。SenseVoice 則每 2.4 秒排程、最長 8 秒切段，保留標點與繁體轉換。

## 模型來源與固定版本

- [SenseVoice 上游](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)；使用 [sherpa-onnx 支援的匯出](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)：`csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17`，revision `2365baeacb507f821a0c8120fcee3d484dba7a07`。權重須遵守上游 `model-license`，不以 runtime 的 Apache 授權代替模型授權。
- [Breeze ASR 25 上游](https://huggingface.co/MediaTek-Research/Breeze-ASR-25)，revision `cffe7ccb404d025296a00758d0a33468bec3a9d0`、Apache 2.0；實測 [社群 CTranslate2 匯出](https://huggingface.co/shdennlin/breeze-asr-25-ct2)，revision `70660216b01a6f6b7b8c5690767a4763df61755f`。
- [SYSTRAN faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small)，revision `536b0662742c02347bc0e980a01041f333bce120`。
- [Qwen3-ASR 0.6B 上游](https://huggingface.co/Qwen/Qwen3-ASR-0.6B)；使用 [sherpa-onnx 文件列出的 INT8 匯出](https://k2-fsa.github.io/sherpa/onnx/qwen3-asr/pretrained.html)，檔名 `sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25.tar.bz2`。
- Paraformer 固定版本見 [TESTING.md](TESTING.md)。

公開語料來源：[Google FLEURS](https://huggingface.co/datasets/google/fleurs)，revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`、CC-BY 4.0；[Taiwan Tongues](https://huggingface.co/datasets/adi-gov-tw/Taiwan-Tongues-ASR-CE-dataset-zhtw)，revision `ff0e8047bdce71c881c6d26eec7b2bbab6381ac1`、TRAIL-D。資料版本與個別授權一併保存在本機語料輸出，不把音檔、私人聽打稿或模型權重提交到 GitHub。

## 仍需要解決的部分

目前最有把握的是可比較的新模型與較連續的暫定校正，還沒有通過實際教室的廣泛評估。真正要改善跨課程表現，需擴充多說話者、不同噪音與主題的配對語料，人工核對一份獨立課堂測試集，再決定是否投入更大訓練。單純加入文字稿、換更大模型或增加幾個熱詞，都不能保證解決遠距離收音與整句辨識錯誤。

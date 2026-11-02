# 語音辨識微調試驗

`tools/train_cpu_pilot.py` 是可在 CPU 執行的小規模訓練與評估工具。它只微調 **Paraformer 句尾辨識模型的 decoder q/v LoRA adapters**，不修改原始模型檔，也不替換即時字幕服務。

這個試驗用來確認資料與訓練流程，不能憑少量朗讀語料宣稱已能泛化到所有課程、自然對話或臺灣口音。即使句尾模型變準，也不代表串流模型或出字速度已改善。

## 資料格式

資料夾內需要 `train.jsonl`、`dev.jsonl`、`test.jsonl`，每行一筆：

```json
{"id":"sample-1","dataset":"source-name","audio":"train/sample-1.wav","duration":5.2,"text":"正確逐字稿。","training_text":"正確逐字稿","sha256":"audio-file-sha256","speaker_id":"anonymous-speaker-id"}
```

音訊需為 16 kHz mono WAV。相對路徑以 manifest 所在資料夾為起點。`text` 是評估答案；`training_text` 是送入 tokenizer 的答案。先統一繁簡並去除標點，保留英文詞間空白。未知 token 過多的訓練樣本會略過。

工具會檢查 train/dev/test 之間是否有重複的正規化文字、音訊雜湊，以及可用的說話者 ID。沒有說話者 ID 的來源，不能只憑此檢查宣稱說話者獨立。課堂整段錄音與經過刪改的聽打稿，必須先驗證對齊，不可把目前 ASR 輸出當成正確訓練答案。

## 執行

使用已安裝 FunASR 選用依賴的 Python 環境：

```powershell
python tools/train_cpu_pilot.py --model-dir .cache/funasr/offline --data-dir C:\ASR-data\mixed --output-dir work/training-pilot --steps 160 --validation-interval 80 --learning-rate 0.0001
```

預設為 CPU 4 執行緒、seed 42、LoRA rank 4、alpha 8、dropout 0.05，約 13 萬個可訓練參數。原模型約 2.2 億參數保持凍結。CPU 訓練適合小規模試驗；大批自然語音與串流模型微調需另行規劃記憶體、算力與測試。

## 評估與產出

- 先測原模型的 dev/test，再開始訓練。
- 僅以 dev 的各來源 CER 平均值挑選 checkpoint；若沒有改善，選回原模型。
- 完成後才測所選模型的 test，逐來源列出 CER。CER 是替換、插入與刪除字數除以答案字數，評分會統一繁簡、轉小寫並移除標點及空白。
- 保存各次辨識答案、訓練 loss、adapter checkpoints、原模型 SHA256 與 `result.json`。原模型可隨時繼續使用。
- 計算時間受暖機、磁碟與其他程式影響，不能把本次前後的時間差當作加速證據。出字幕延遲需另做完整串流測試。
- 不會上傳私人錄音、逐字稿或模型，也不會自動把候選模型部署到工作台。

## 已使用的公開語料來源

初步試驗採用下列官方來源的小樣本，並保留來源版本、授權與修改說明：

| 來源 | 用途 | 授權與注意事項 |
| --- | --- | --- |
| [Google FLEURS](https://huggingface.co/datasets/google/fleurs) `cmn_hans_cn` | 一般中文、多主題朗讀 | CC BY 4.0；不是臺灣專屬語料。保留官方 split |
| [Taiwan Tongues zh-TW](https://huggingface.co/datasets/adi-gov-tw/Taiwan-Tongues-ASR-CE-dataset-zhtw) | 臺灣華語、跨說話者樣本 | TRAIL-D，完整條款見來源 LICENSE；取樣保留來源路徑與 client_id，額外檢查說話者與句子不重疊 |

資料集可能已出現在原模型的預訓練資料中；無法據此宣稱對原模型完全未知。要評估跨課程泛化，仍需多個未參與微調的真實場次、不同說話者與獨立標註。

目前訓練工具不自動下載資料，也不會把任何語料包含在 repository 或程式 ZIP 中。使用自己的 manifest 前，應保留對應來源的授權、出處與切分規則。

訓練架構參考 [FunASR 官方 LoRA 設定](https://github.com/modelscope/FunASR/blob/main/examples/industrial_data_pretraining/paraformer/conf/paraformer_lora.yaml)。

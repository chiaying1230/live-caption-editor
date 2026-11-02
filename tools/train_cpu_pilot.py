"""Small CPU LoRA experiment; validates the provided train/dev/test split.

This tunes only decoder q/v adapters in the OFFLINE Paraformer final pass.
It is a pilot, not a claim of improved streaming ASR or Taiwan generalization.
"""
import argparse
import hashlib
import json
import random
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from opencc import OpenCC
from funasr import AutoModel
from funasr.utils.load_utils import extract_fbank


def normalize(text, converter):
    return ''.join(c for c in converter.convert(text).lower() if c.isalnum())


def distance(a, b):
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        row=[i]
        for j,y in enumerate(b,1):
            row.append(min(row[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        prev=row
    return prev[-1]


def read_rows(path):
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    for row in rows:
        audio=Path(row['audio'])
        if not audio.is_absolute():row['audio']=str((path.parent/audio).resolve())
    return rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model-dir',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--steps',type=int,default=96)
    parser.add_argument('--validation-interval',type=int,default=32)
    parser.add_argument('--learning-rate',type=float,default=0.00005)
    args=parser.parse_args()
    if args.steps<1 or args.validation_interval<1 or args.learning_rate<=0:
        parser.error('steps, validation interval and learning rate must be positive')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    random.seed(42);np.random.seed(42);torch.manual_seed(42);torch.set_num_threads(4)
    rows={s:read_rows(args.data_dir/(s+'.jsonl')) for s in ['train','dev','test']}
    converter=OpenCC('t2s')
    # Exclude repeated prompts across the experimental splits before any training.
    keys={s:{normalize(row['text'],converter) for row in items} for s,items in rows.items()}
    assert not(keys['train']&keys['dev'] or keys['train']&keys['test'] or keys['dev']&keys['test'])
    hashes={s:{row['sha256'] for row in items if row.get('sha256')} for s,items in rows.items()}
    assert not(hashes['train']&hashes['dev'] or hashes['train']&hashes['test'] or hashes['dev']&hashes['test'])
    speakers={s:{row['dataset']+':'+row['speaker_id'] for row in items if row.get('speaker_id')} for s,items in rows.items()}
    assert not(speakers['train']&speakers['dev'] or speakers['train']&speakers['test'] or speakers['dev']&speakers['test'])
    lora={'lora_list':['q','v'],'lora_rank':4,'lora_alpha':8,'lora_dropout':.05}
    auto=AutoModel(model=str(args.model_dir.resolve()),device='cpu',ncpu=4,disable_update=True,disable_pbar=True,trust_remote_code=False,decoder_conf=lora)
    model=auto.model
    for name,param in model.named_parameters():param.requires_grad=('lora_' in name)
    params=[p for p in model.parameters() if p.requires_grad]
    assert params,'No trainable LoRA adapters were created.'
    print(json.dumps({'phase':'loaded','trainable_parameters':sum(p.numel() for p in params),'total_parameters':sum(p.numel() for p in model.parameters()),'train':len(rows['train']),'dev':len(rows['dev']),'test':len(rows['test'])}),flush=True)
    base_sha=hashlib.file_digest((args.model_dir/'model.pt').open('rb'),'sha256').hexdigest()
    def adapters():return {k:v.detach().cpu().clone() for k,v in model.state_dict().items() if 'lora_' in k}
    initial=adapters()
    def evaluate(split,label):
        model.eval();results=[];groups={};errors=chars=0;start=time.perf_counter();duration=0.
        for record in rows[split]:
            audio,rate=sf.read(record['audio'],dtype='float32');assert rate==16000 and audio.ndim==1
            t=time.perf_counter();out=auto.generate(input=audio,disable_pbar=True)
            hyp=''.join(x.get('text','') for x in out);ref=normalize(record['text'],converter);prediction=normalize(hyp,converter)
            edit=distance(ref,prediction);errors+=edit;chars+=len(ref);duration+=len(audio)/rate
            group=groups.setdefault(record['dataset'],{'errors':0,'reference_chars':0,'clips':0});group['errors']+=edit;group['reference_chars']+=len(ref);group['clips']+=1
            results.append({'id':record['id'],'reference':record['text'],'hypothesis':hyp,'errors':edit,'reference_chars':len(ref),'compute_seconds':round(time.perf_counter()-t,4)})
        summary={'label':label,'split':split,'clips':len(results),'errors':errors,'reference_chars':chars,'cer':errors/max(chars,1),'compute_seconds':time.perf_counter()-start,'audio_seconds':duration}
        for group in groups.values():group['cer']=group['errors']/max(group['reference_chars'],1)
        summary['by_dataset']=groups;summary['selection_score']=sum(group['cer'] for group in groups.values())/len(groups)
        (args.output_dir/(label+'-'+split+'.json')).write_text(json.dumps({'summary':summary,'rows':results},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(summary),flush=True);return summary
    baseline_dev=evaluate('dev','baseline');baseline_test=evaluate('test','baseline')
    features=[]
    tokenizer=auto.kwargs['tokenizer'];frontend=auto.kwargs['frontend']
    for record in rows['train']:
        audio,rate=sf.read(record['audio'],dtype='float32')
        with torch.no_grad():speech,lengths=extract_fbank(audio,frontend=frontend,is_final=True)
        target=converter.convert(record['training_text'])
        target=''.join(c if c.isalnum() or c.isspace() else ' ' for c in target)
        ids=tokenizer.encode(target)
        if not ids or sum(i==tokenizer.unk_id for i in ids)/len(ids)>.05:continue
        features.append({'speech':speech,'speech_lengths':lengths,'text':torch.tensor([ids],dtype=torch.int64),'text_lengths':torch.tensor([len(ids)],dtype=torch.int32)})
    assert features,'No usable training labels.'
    optimizer=torch.optim.AdamW(params,lr=args.learning_rate,weight_decay=.01)
    order=list(range(len(features)));random.shuffle(order);history=[];best=baseline_dev['selection_score'];selected_step=0;best_state=initial
    start=time.perf_counter()
    for step in range(1,args.steps+1):
        model.train();model.encoder.eval()
        item=features[order[(step-1)%len(order)]]
        optimizer.zero_grad(set_to_none=True)
        with torch.enable_grad():
            loss,stats,weight=model(**item)
            assert torch.isfinite(loss).all(),'Non-finite loss.'
            loss.backward();torch.nn.utils.clip_grad_norm_(params,1.0);optimizer.step()
        history.append({'step':step,'loss':float(loss.detach()),'elapsed_seconds':time.perf_counter()-start})
        if step==1 or step%8==0:print(json.dumps({'phase':'training',**history[-1]}),flush=True)
        if step%args.validation_interval==0 or step==args.steps:
            score=evaluate('dev',f'step-{step}')
            state=adapters()
            torch.save({'adapters':state,'step':step,'base_sha256':base_sha,'lora':lora},args.output_dir/f'adapter-{step}.pt')
            if score['selection_score']<best:best=score['selection_score'];selected_step=step;best_state=state
        (args.output_dir/'training-history.json').write_text(json.dumps(history,indent=2),encoding='utf-8')
    model.train() # Unmerge old LoRA weights before replacing adapter tensors.
    model.load_state_dict(best_state,strict=False)
    after_test=evaluate('test','selected')
    model.train()
    torch.save({'adapters':best_state,'step':selected_step,'base_sha256':base_sha,'lora':lora},args.output_dir/'selected-adapter.pt')
    result={'experiment':'offline-decoder-LoRA CPU pilot','seed':42,'steps':args.steps,'usable_train_clips':len(features),'trainable_parameters':sum(p.numel() for p in params),'baseline_dev':baseline_dev,'baseline_test':baseline_test,'selected_step':selected_step,'selected_dev_macro_cer':best,'learning_rate':args.learning_rate,'validation_interval':args.validation_interval,'selected_test':after_test,'base_sha256':base_sha,'lora':lora,'promoted_to_live_service':False,'course_audio_used_for_training':False,'limitations':['Small read-speech samples; no proof of cross-course spontaneous-speech generalization.','Official splits and distinct normalized prompts; speaker IDs unavailable in this manifest.','This does not train the streaming model.','Results do not establish cross-course generalization.']}
    (args.output_dir/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)

if __name__=='__main__':main()

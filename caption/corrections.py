"""Find dictionary-backed contextual terms in human edits; do not infer meaning."""
from difflib import SequenceMatcher
from functools import lru_cache

NUMERALS=set('零〇一二三四五六七八九十百千萬億兩')
SUFFIXES=set('性者症病學化論法')
STOP_WORDS={'什么','什么样','怎样','他们','她们','我们','你们','不要','可以','所以',
            '但是','因为','就是','然后','这样','这种','一个','一位','自己','同样','其实',
            '很多','一般','不同','已经','应该','还是','不是','时候','这个','那个','算是'}

@lru_cache(maxsize=1)
def resources():
    import jieba
    from opencc import OpenCC
    jieba.setLogLevel(40)
    tokenizer=jieba.Tokenizer()
    tokenizer.initialize()
    return tokenizer,OpenCC('tw2s')

def term_changes(before, after):
    ops=SequenceMatcher(None,before,after,autojunk=False).get_opcodes()
    changes=[op for op in ops if op[0]!='equal']
    if not changes or len(changes)>3:
        return []
    changed=sum(max(b-a,d-c) for _,a,b,c,d in changes)
    if max(len(before),len(after))>=12 and changed>max(len(before),len(after))*.6:
        return []
    tokenizer,converter=resources()
    normalized=converter.convert(after)
    if len(normalized)!=len(after):
        return []
    tokens=list(tokenizer.tokenize(normalized,HMM=False))
    def lexical(token):
        word=token[0]
        return len(word)>=2 and word not in STOP_WORDS and not word.isdigit() and (
            tokenizer.FREQ.get(word,0)>0 or word.isascii() and word.isalnum())
    result=[]
    for k,(tag,a,b,c,d) in enumerate(ops):
        old,new=before[a:b],after[c:d]
        if tag!='replace' or not old or not new or not all(ch.isalnum() for ch in old+new):
            continue
        if old.isdigit() or new.isdigit() or set(old+new)<=NUMERALS:
            continue
        if max(len(old),len(new))>12 or '待確認' in new or '未辨識' in new:
            continue
        indices=[i for i,t in enumerate(tokens) if t[1]<d and t[2]>c]
        if not indices or not any(lexical(tokens[i]) for i in indices):
            continue
        if any(not lexical(tokens[i]) and tokens[i][0] not in SUFFIXES for i in indices):
            continue
        first,last=indices[0],indices[-1]
        lo,hi=tokens[first][1],tokens[last][2]
        left_len=a-ops[k-1][1] if k and ops[k-1][0]=='equal' else 0
        right_len=ops[k+1][2]-b if k+1<len(ops) and ops[k+1][0]=='equal' else 0
        if last+1<len(tokens) and tokens[last+1][1]==hi and lexical(tokens[last+1]) and len(tokens[last+1][0])<=3:
            candidate=tokens[last+1][2]
            if candidate<=d+right_len and candidate-lo<=12:
                last+=1;hi=candidate
        if last+1<len(tokens) and tokens[last+1][1]==hi and tokens[last+1][0] in SUFFIXES:
            if tokens[last+1][2]<=d+right_len:
                last+=1;hi=tokens[last][2]
        if lo<c-left_len or hi>d+right_len or lo>c or hi<d:
            continue
        source_a,source_b=a-(c-lo),b+(hi-d)
        source,target=before[source_a:source_b],after[lo:hi]
        if len(source)<2:
            continue  # One character becoming a new noun can be sentence rewriting.
        old_word=converter.convert(source)
        if len(source)<=2 and tokenizer.FREQ.get(old_word,0)>0 and old_word!=converter.convert(target):
            for i in range(first-1,max(-1,first-4),-1):
                word,start,end=tokens[i]
                if not word.isalnum() or start<c-left_len or hi-start>20:
                    break
                lo=start
            source_a=a-(c-lo)
            while lo<c and normalized[lo] in '的了與和及在於為':
                lo+=1
            source_a=a-(c-lo)
            source,target=before[source_a:source_b],after[lo:hi]
            if len(source)<=2:
                continue
        if 2<=len(source)<=30 and 2<=len(target)<=30 and source!=target:
            pair={'source':source,'target':target}
            if pair not in result:
                result.append(pair)
    return result

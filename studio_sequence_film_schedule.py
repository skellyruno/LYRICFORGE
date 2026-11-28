"""Narration-aware, bounded montage scheduling. Tags are owner metadata, not vision labels."""
from bisect import bisect_left
import re
from collections import Counter

STOP = set('the and for with from into this that your you our one all more are was have has can will sound audio video plugin effect effects rack show studio skelliere skelly motion'.split())


def terms(value):
    return set(re.findall(r'[a-z0-9]{3,}', str(value).casefold())) - STOP


def protected_intervals(state, spoken):
    # Protect intentional edits to the picture, transitions, and existing overlays.
    spans = [(x['at'], x['at']+x['length']) for x in state['layers'] if x['kind']=='visual']
    cursor = 0
    for p in state['base']['pieces']:
        if p['asset']!='source' or (p['audio'] is not None and (p['audio']!='source' or p['start']!=p['audio_start'])):
            spans.append((cursor,cursor+p['length']))
        cursor += p['length']
    spans.extend((x['at']-x['half'], x['at']+x['half']) for x in state['transitions'])
    cues=[]
    for w in spoken:
        if terms(w.get('text')) & {'listen','compare','before','after','dry','wet'}:
            cues.append((round(float(w['start'])*30),round(float(w['end'])*30)))
    for i,(a,b) in enumerate(cues):
        end=b+120
        # Paired demo cues can bracket several seconds of intentionally unspoken audio.
        if i+1<len(cues) and cues[i+1][0]-b<=900:
            end=max(end,cues[i+1][1]+120)
        spans.append((max(0,a-30),end))
    return spans


def schedule(candidates, spoken, total, occupied, budget, beats=()):
    """Choose a diverse set of cue-aligned intervals. Bounded beam, not a global optimum.

    candidates: (asset, length, (visual_score, offset, quality, motion), tags).
    Return rows with actual matched terms; never invent a cue for unmatched footage.
    """
    if not spoken or budget<=0:return []
    frequency=Counter(t for _,_,_,tags in candidates for t in tags if t not in STOP)
    events=[]
    for w in spoken:
        a,b=round(float(w['start'])*30),round(float(w['end'])*30)
        events.append((a,b,terms(w.get('text'))))
    events.sort(key=lambda x:x[0])
    starts_index=[x[0] for x in events];beats=sorted(set(beats));beat_set=set(beats)
    # Index words once, then evaluate only cue-adjacent candidate starts.
    result=[]
    for key,n,(score,off,q,m),tags in candidates:
        tags=set(tags)-STOP
        # Generic tags shared by most assets are not discriminative evidence.
        tags={t for t in tags if frequency[t]==1 or frequency[t]*2<len(candidates)}
        if not tags:continue
        rows=[];seen=set()
        for a,b,words in events:
            if not tags&words:continue
            for start in {a-12,a-6,a,b-n+12}:
                j=bisect_left(beats,start)
                beat=min(beats[max(0,j-1):j+1],key=lambda g:abs(g-start),default=start)
                starts=[start]+([beat] if abs(beat-start)<=6 and beat!=start else [])
                for at in starts:
                    if at in seen or at<15 or at+n>total-15 or any(at<hi and at+n>lo for lo,hi in occupied):continue
                    seen.add(at)
                    # Only cue words actually inside the proposed shot count.
                    lo=bisect_left(starts_index,at);hi=bisect_left(starts_index,at+n)
                    matches=set().union(*(tokens for s,e,tokens in events[lo:hi] if e<=at+n)) & tags
                    if not matches:continue
                    value=.50*score+.35*sum(1/frequency[t] for t in matches)+.10*(at in beat_set)+.05*(1-min(1,abs(a-at)/30))
                    rows.append((value,key,n,at,off,q,m,sorted(matches)))
        # Keep multiple possible occurrences to avoid a greedy scheduling collision.
        rows.sort(key=lambda r:(-r[0],r[3],r[1]))
        kept=[]
        for row in rows:
            if all(abs(row[3]-x[3])>=15 for x in kept):kept.append(row)
            if len(kept)>=12:break
        if kept:result.append(kept)
    # Beam across asset groups: at most one shot per asset, 12 candidates each,
    # 128 partial schedules. Reward usable distinct shots; preserve 0.4s breathing space.
    beam=[(0.,())]
    for group in sorted(result,key=lambda g:(len(g),g[0][1])):
        expanded=list(beam)
        for value,rows in beam:
            if len(rows)>=budget:continue
            for row in group:
                at,n=row[3],row[2]
                if any(at<r[3]+r[2]+12 and at+n+12>r[3] for r in rows):continue
                expanded.append((value+1.+row[0],rows+(row,)))
        expanded.sort(key=lambda x:(-x[0],tuple((r[3],r[1]) for r in x[1])))
        beam=expanded[:128]
    return sorted(beam[0][1],key=lambda x:(x[3],x[1]))

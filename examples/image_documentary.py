"""Original image science documentary, using caller-supplied genuine media.
Run: python examples/image_documentary.py OUT SCREENSHOT EXISTING_VIDEO
Add --narrate for newly synthesized Kokoro Michael narration (requires configured runtime).
Existing footage is labeled a previous production excerpt, not a raw recording.
"""
import argparse, json,sys,subprocess,wave,shutil,math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw,ImageOps
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_director as d
import studio_layers as layers
import studio_score as score
import studio_director_intelligence as intel
from examples.sound_documentary import L,A,track

FPS=60
PIC='a'*32+'.png';MOV='b'*32+'.mp4';DOC='c'*32+'.png';TEX='d'*32+'.png'

def title(ident,text,x,y,size=.06,*,w=.9,h=.15,face='serif',align='center',color='white',keys=None):
    return L(ident,'text',x,y,w,h,text=text,size=size,face=face,align=align,color=color,keys=keys or A(x,y,.08,.22),depth=-.4)

def annotation(ident,text,x,y,**kw):
    return title(ident,text,x,y,.032,face='mono',color='gold',h=.09,**kw)

def create_assets(folder,photo,video):
    folder.mkdir();im=ImageOps.exif_transpose(Image.open(photo)).convert('RGB');im.save(folder/PIC)
    # Original supplied production excerpt, no reference film copied. Re-encode a bounded strip.
    subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-i',str(video),'-an','-t','8','-vf','scale=960:540:force_original_aspect_ratio=decrease','-c:v','libx264','-threads','2','-pix_fmt','yuv420p',str(folder/MOV)],check=True,timeout=90)
    arr=np.asarray(im);h,w=arr.shape[:2];x,y=w//2,h//2;rgb=arr[y,x].tolist()
    # Genuine calculated document: coordinate, image dimensions, channels, and pixel count.
    document=Image.new('RGB',(820,640),'#e9e6db');dd=ImageDraw.Draw(document)
    dd.rectangle((0,0,820,66),fill='#242b30');dd.text((33,33),'SKELLYMOTION  /  IMAGE ANALYSIS',font=d.font(25,True),fill='#f3f0e4',anchor='lm')
    dd.text((36,104),'Pixel inspection report',font=d.font(48,True),fill='#16232a');dd.line((36,177,784,177),fill='#8b9995',width=2)
    rows=[('SOURCE DIMENSIONS',f'{w} × {h}'),('PIXEL COUNT',f'{w*h:,}'),('SAMPLE COORDINATE',f'({x}, {y})'),('RGB CHANNEL VALUES',f'{rgb[0]}, {rgb[1]}, {rgb[2]}')]
    for i,(a,b) in enumerate(rows):
        yy=208+i*89;dd.text((36,yy),a,font=d.font(20,False),fill='#535b5b');dd.text((36,yy+27),b,font=d.font(36,True),fill='#15252a')
    dd.rectangle((690,478,784,574),fill=tuple(rgb),outline='#243134',width=2);dd.text((36,594),'Computed directly from the supplied RGB image.',font=d.font(18,False),fill='#535b5b');document.save(folder/DOC)
    # A map made from the actual image's colors, not an imagined source or Earth map.
    pixel=im.resize((24,12),Image.Resampling.BOX);pixel=Image.fromarray(np.uint8(np.sqrt(np.asarray(pixel,dtype=np.float32)/255)*255));pixel.resize((1024,512),Image.Resampling.NEAREST).save(folder/TEX)
    return {'width':w,'height':h,'pixels':w*h,'coordinate':[x,y],'rgb':rgb,'texture':'24×12 area-averaged colors from source screenshot; display gamma lifted for illustration'}

def compositions(data):
    out=[]
    def add(name,source,ls,cam=None):out.append(layers.validate(dict(title=name,source=source,layers=ls,camera=cam or [[0,0,0,1],[1,0,0,1]])))
    add('Every image is a signal','ORIGINAL VISUAL STUDY  /  SOURCE-DERIVED, DISPLAY-LIFTED COLOR TEXTURE',[
        L('halo','rings',.64,.43,.72,.76,color='gold',depth=1.5,keys=track((0,.64,.43,1,.72),(1,.64,.43,1.13,.42))),
        L('orb','sphere',.71,.44,.61,.68,asset=TEX,spin=.45,roughness=.32,depth=.25,keys=track((0,.73,.47,.85,.0),(.14,.71,.44,1,1),(.70,.71,.44,1,1),(1,.76,.45,.75,.72))),
        annotation('episode','FIELD NOTES  /  02',.25,.17,w=.40,align='left'),
        title('hero','The anatomy of an image',.25,.39,.081,w=.40,h=.35,align='left',keys=A(.25,.39,.08,.23)),
        title('hook','Light becomes information.',.25,.71,.043,w=.40,h=.17,face='sans',align='left',keys=A(.25,.71,.32,.48)),
    ],[[0,-.015,0,1.02],[1,0,0,1]])
    add('From capture to picture','ACTUAL PREVIOUS SKELLYMOTION PRODUCTION EXCERPT  /  SOURCE FOOTAGE, NOT A LIVE DEMONSTRATION',[
        L('orb','sphere',.76,.45,.68,.75,asset=TEX,spin=.45,roughness=.32,depth=.25,keys=track((0,.76,.45,.75,.72),(.28,1.0,.46,.5,0),(1,1,.46,.5,0))),
        L('moving','footage',.61,.48,.71,.68,asset=MOV,trim=[0,8],fit='contain',depth=.40,keys=track((0,.70,.52,.88,0),(.16,.67,.49,.96,1),(.80,.67,.49,.96,1),(1,.62,.49,.83,1))),
        annotation('capture-label','01  /  CAPTURE',.21,.15,w=.34,align='left'),
        title('capture-title','A moving picture is a sequence of images.',.205,.42,.064,w=.30,h=.45,align='left',keys=A(.205,.42,.15,.34)),
        title('capture-sub','Every frame can be inspected.',.19,.73,.035,w=.31,h=.14,face='sans',align='left',keys=A(.19,.73,.38,.53))
    ])
    add('The pixel grid','ACTUAL SCREEN CAPTURE  /  ORIGINAL SOURCE DIMENSIONS',[
        L('still','image',.31,.48,.53,.65,asset=PIC,fit='contain',depth=.4,keys=track((0,.61,.48,.84,0),(.25,.31,.48,1,1),(1,.31,.48,1,1))),
        annotation('sample-label','02  /  INSPECT',.80,.15,w=.32,align='left'),
        title('sample-title','An image is a grid of samples.',.77,.33,.055,w=.35,h=.28,align='left',keys=A(.77,.33,.13,.27)),
        title('dimensions',f"{data['width']} × {data['height']}",.77,.58,.053,w=.35,h=.13,face='mono',align='left',color='mint',keys=A(.77,.58,.36,.52)),
        title('sample-sub',f"{data['pixels']:,} pixels in this capture.",.77,.74,.031,w=.35,h=.13,face='sans',align='left',keys=A(.77,.74,.53,.68))
    ])
    add('Measurement, not decoration','ACTUAL SCREEN CAPTURE + COMPUTED IMAGE ANALYSIS DOCUMENT',[
        L('still','image',.31,.48,.53,.65,asset=PIC,fit='contain',depth=.4,keys=track((0,.31,.48,1,1),(.35,.26,.36,.70,1),(1,.26,.36,.70,1))),
        L('report','document',.74,.50,.43,.70,asset=DOC,fit='contain',depth=-.05,keys=track((0,.76,.58,.88,0),(.24,.74,.48,1,1),(1,.74,.48,1,1))),
        annotation('evidence-label','03  /  EVIDENCE',.28,.13,w=.4,align='left'),
        title('report-title','Measure the source.',.28,.65,.058,w=.40,h=.18,align='left',keys=A(.28,.65,.18,.39)),
        title('report-sub','Dimensions and color values are computed from the original image.',.26,.79,.031,w=.38,h=.16,face='sans',align='left',keys=A(.26,.79,.38,.58))
    ])
    add('From pixels to a textured surface','24 × 12 AVERAGED COLORS, DISPLAY GAMMA LIFTED  /  PROJECTED 3D SPHERE',[
        L('report','document',.74,.50,.43,.70,asset=DOC,depth=-.05,keys=track((0,.74,.48,1,1),(.24,.91,.39,.73,0),(1,.91,.39,.73,0))),
        L('texture','image',.27,.47,.44,.48,asset=TEX,fit='contain',depth=.40,keys=track((0,.27,.48,.8,0),(.18,.27,.47,1,1),(.75,.27,.47,1,1),(1,.27,.47,.8,0))),
        L('orb','sphere',.73,.45,.54,.59,asset=TEX,spin=.45,roughness=.32,depth=.02,keys=track((0,.78,.48,.8,0),(.22,.73,.45,1,1),(.8,.73,.45,1,1),(1,.61,.48,1.05,1))),
        annotation('texture-label','04  /  RECONSTRUCT',.28,.14,w=.43,align='left'),
        title('texture-title','Map color onto geometry.',.28,.76,.051,w=.42,h=.18,align='left',keys=A(.28,.76,.25,.42)),
        title('texture-explain','The same color data can wrap a curved 3D surface.',.73,.83,.032,w=.42,h=.12,face='sans',keys=A(.73,.83,.43,.60))
    ])
    add('The image becomes a world','ORIGINAL ILLUSTRATION  /  SOURCE-DERIVED TEXTURE  ·  SKELLYMOTION',[
        L('orb','sphere',.61,.48,.62,.68,asset=TEX,spin=.45,roughness=.32,depth=.02,keys=track((0,.61,.48,1.05,1),(.40,.69,.43,1.1,1),(.75,.69,.43,1.1,.6),(1,.69,.43,.9,0))),
        L('rings','rings',.67,.43,.79,.76,color='mint',depth=1.2,keys=track((0,.67,.43,.9,0),(.3,.67,.43,1,.75),(.75,.67,.43,1.2,.4),(1,.67,.43,1.2,0))),
        title('closing','Information becomes a world.',.24,.43,.071,w=.40,h=.36,align='left',keys=track((0,.24,.46,1,0),(.22,.24,.43,1,1),(.66,.24,.43,1,1),(.82,.24,.40,1,0),(1,.24,.40,1,0))),
        title('endmark','SKELLYMOTION',.5,.48,.083,w=.82,h=.23,keys=track((0,.5,.5,1,0),(.68,.5,.5,1,0),(.86,.5,.48,1,1),(1,.5,.48,1,1))),
        annotation('end-sub','THE ART OF INFORMATION',.5,.65,w=.7,keys=track((0,.5,.65,1,0),(.80,.5,.65,1,0),(.96,.5,.65,1,1),(1,.5,.65,1,1)))
    ])
    return out

SCRIPT=[
    'Every image is a signal. A camera turns light into information, and a digital screen turns that information back into light.',
    'A moving picture is really a sequence of images. Each frame can be examined on its own, without guessing what the camera recorded.',
    'A digital image is a grid of samples. This original screen capture has a precise width and height, and every pixel has stored color values.',
    'Instead of inventing numbers, we can measure the source directly. This report calculates the dimensions, pixel count and red, green and blue values of a single sample.',
    'The same image can also become a texture. Here we averaged the colors into a smaller grid and mapped those values onto a curved three-dimensional surface.',
    'From a single sample to a moving picture, from a flat image to a world: information becomes something we can see. Skelly Motion.'
]

def plan_for(data,voice=None):
    graphics=compositions(data);cuts=[round(b*60/score.DOC_BPM*FPS) for b in [0,12,24,38,52,66,80]]
    if voice:
        # Narration clock supplies real scene durations; no synthetic word duration claims.
        starts={}
        for line in voice['lines']:starts.setdefault(line['chapter_title'],round(float(line['start'])*FPS))
        if len(starts)!=len(graphics):raise RuntimeError('Narration chapter timing mismatch')
        cuts=[0,*list(starts.values())[1:],round(voice['duration']*FPS)]
        if any(b<=a for a,b in zip(cuts,cuts[1:])):raise RuntimeError('Invalid narration clock')
    scenes=[]
    for i,(a,b,g) in enumerate(zip(cuts,cuts[1:],graphics)):
        scenes.append(dict(type='big_text',text=g['title'],start=a/FPS,end=b/FPS,frames=b-a,captions=[],camera='still',cinematic_finish=True,brand='SKELLYMOTION',chapter=i+1,editorial='graphic',editorial_look='midnight',graphic=g))
    p=dict(version=d.VERSION,preset='doc',fps=FPS,duration=cuts[-1]/FPS,frames=cuts[-1],scenes=scenes,director='local',audio_start=0.,silent=False,cinematic_finish=True,caption_style='off',caption_track=[],crossfades=False,sound_design=True,music_gain=1.65,cue_gain=0.,voice_style='natural')
    d.configure_spatial(scenes,FPS);return p

def main():
    ap=argparse.ArgumentParser();ap.add_argument('out',type=Path);ap.add_argument('photo',type=Path);ap.add_argument('video',type=Path);ap.add_argument('--narrate',action='store_true');args=ap.parse_args();root=args.out.resolve();root.mkdir(parents=True,exist_ok=False);assets=root/'assets';data=create_assets(assets,args.photo,args.video)
    (root/'script.json').write_text(json.dumps([{'title':f'Chapter {i+1}','narration':s} for i,s in enumerate(SCRIPT)],indent=2));voice=None;audio=root/'narration.wav'
    if args.narrate:
        import studio_creator as creator
        voice=creator.narration([{'title':f'Chapter {i+1}','narration':s} for i,s in enumerate(SCRIPT)],audio,voice='kokoro',delivery='documentary')
        if voice['provider']!='kokoro':raise RuntimeError('Neural narration fallback is forbidden')
    p=plan_for(data,voice)
    if not voice:
        audio=root/'silent-source.wav'
        with wave.open(str(audio),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(bytes(round(p['duration']*24000)*2))
    def enc(args,cwd,length,stage,*_):
        print('ENCODE',stage,round(length,3),flush=True);r=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=300)
        if r.returncode:raise RuntimeError(r.stderr[-5000:])
    output=root/'The-Anatomy-of-an-Image.mp4';(root/'plan.json').write_text(json.dumps(p,indent=2));print('START',p['duration'],p['frames'],flush=True)
    stats=d.render(p,audio,assets,root/'cache',output,{'fps':FPS},(960,540),lambda rows,path:path.write_text(''),enc,lambda:None,lambda *a:print('SCENES',a,flush=True));report=intel.review(p)
    (root/'plan.json').write_text(json.dumps(p,indent=2));(root/'report.json').write_text(json.dumps({'render':stats,'review':report,'source_data':data,'narrator':voice['provider'] if voice else 'none, music-led'},indent=2));score.write_score(p,root/'score.wav',music_gain=1.65,cue_gain=0.);print('RESULT',stats,report,flush=True)
if __name__=='__main__':main()

"""Original schematic frequency comparison on a shared one-second axis."""
import math
import numpy as np
from PIL import Image,ImageDraw

def pair(w,h,t,font):
    im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im);f=font(max(12,round(h*.075)),False);x0=w*.16;x1=w*.95
    for row,cycles in enumerate((2,4)):
        y=h*(.26+.46*row);amp=h*.15;x=np.linspace(0,1,400);phase=2*math.pi*(cycles*x-t*.25*cycles)
        for tick in np.linspace(0,1,9):d.line((x0+(x1-x0)*tick,y-amp,x0+(x1-x0)*tick,y+amp),fill='#263a40',width=max(1,h//240))
        d.line((x0,y,x1,y),fill='#435e63',width=max(1,h//200));d.line(list(zip(x0+(x1-x0)*x,y-amp*np.sin(phase))),fill=('#efce77' if row==0 else '#7ed7c2'),width=max(2,h//80),joint='curve')
        d.text((w*.025,y),f'{cycles} Hz',font=f,fill='#f2eee3',anchor='lm')
    d.text((x0,h*.96),'0 s',font=f,fill='#a8b7b5',anchor='lb');d.text((x1,h*.96),'1 s',font=f,fill='#a8b7b5',anchor='rb');return im

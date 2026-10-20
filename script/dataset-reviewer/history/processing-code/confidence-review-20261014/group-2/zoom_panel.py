from PIL import Image,ImageDraw,ImageFont
import json,pathlib,math,sys
b=pathlib.Path(__file__).parent;xs=json.load(open(b/'inventory.json'));f=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13);ids=list(map(int,sys.argv[2:]));name=sys.argv[1]
for p in range(math.ceil(len(ids)/24)):
 c=Image.new('RGB',(1280,6*235),'#ddd');d=ImageDraw.Draw(c)
 for z,i in enumerate(ids[p*24:(p+1)*24]):
  x=xs[i];bb=x['boxes'][0]['xyxy'];mx=(bb[0]+bb[2])/2;my=(bb[1]+bb[3])/2;l=max(0,min(612,int(mx-30)));t=max(0,min(316,int(my-30)))
  im=Image.open(x['image_path']).crop((l,t,l+60,t+60));dr=ImageDraw.Draw(im);dr.rectangle((bb[0]-l,bb[1]-t,bb[2]-l,bb[3]-t),outline='red',width=1);im=im.resize((210,210),Image.NEAREST)
  cx=(z%4)*320+55;cy=(z//4)*235;c.paste(im,(cx,cy));d.text(((z%4)*320+3,cy+212),f'#{i} {bb[2]-bb[0]:.1f}x{bb[3]-bb[1]:.1f} f{x["source_frame_idx"]}',fill='black',font=f)
 c.save(b/f'zoom_{name}_{p+1:02d}.png')

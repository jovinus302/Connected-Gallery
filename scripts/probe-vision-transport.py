"""Synthetic-only vision probe; no private gallery data is used."""
import asyncio,base64,io,json,secrets,sys,time
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage,SystemMessage
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'server'))
from connected_gallery.adapters.proxy import ProxyGateway
load_dotenv(root/'.env')

def card(background,shape,color):
    number=str(secrets.randbelow(90000)+10000)
    im=Image.new('RGB',(720,720),background)
    d=ImageDraw.Draw(im)
    if shape=='triangle': d.polygon([(360,90),(120,460),(600,460)],fill=color)
    else: d.ellipse((130,100,590,480),fill=color)
    d.rectangle((40,520,680,690),fill='white')
    try:
        font=ImageFont.truetype('arial.ttf',135)
    except OSError:
        font=ImageFont.load_default(size=135)
    d.text((100,535),number,font=font,fill='black')
    out=io.BytesIO();im.save(out,'JPEG',quality=90)
    return {'type':'image','source':{'type':'base64','media_type':'image/jpeg','data':base64.b64encode(out.getvalue()).decode()}},number

schema={'name':'submit_visual_observations','description':'Report what is visible in each numbered image.',
    'parameters':{'type':'object','properties':{'images':{'type':'array','items':{'type':'object',
    'properties':{k:{'type':'string'} for k in ['id','background_color','shape','shape_color','printed_number']},
    'required':['id','background_color','shape','shape_color','printed_number']}}},'required':['images']}}

async def main():
    source,n1=card('green','triangle','red');candidate,n2=card('blue','ellipse','yellow')
    prompt=SystemMessage(content='Read the actual images. Report English colors and visible shape and exact printed number. Never infer missing images from text; use unknown if an image is not available.')
    first=HumanMessage(content=[{'type':'text','text':'Image id: source'},source])
    block=[{'type':'text','text':'Image id: candidate'},candidate]
    modes={
      'nested_tool_result':[prompt,first,
          AIMessage(content='',tool_calls=[{'id':'inspect-candidate','type':'tool_call','name':'inspect_photos','args':{'photo_ids':['candidate']}}]),
          ToolMessage(content=block,tool_call_id='inspect-candidate'),HumanMessage(content='Report source and candidate images with the submit tool.')],
      'top_level_human':[prompt,first,HumanMessage(content=block),HumanMessage(content='Report source and candidate images with the submit tool.')],
    }
    report={'synthetic_only':True,'expected':{'source':{'background_color':'green','shape':'triangle','shape_color':'red','printed_number':n1},'candidate':{'background_color':'blue','shape':'ellipse','shape_color':'yellow','printed_number':n2}},'results':{}}
    gateway=ProxyGateway(attempt_timeout=45,repeat_primary=False,fallback=None)
    for name,messages in modes.items():
        start=time.monotonic()
        response=await gateway.invoke(messages,[schema])
        report['results'][name]={'seconds':round(time.monotonic()-start,2),'tool_calls':response.tool_calls,'text':response.content}
        print(name,json.dumps(response.tool_calls,ensure_ascii=True),flush=True)
    passed=True
    for value in report['results'].values():
        calls=value['tool_calls']
        observed={item['id']:item for item in calls[0]['args']['images']} if len(calls)==1 else {}
        value['passed']=set(observed)==set(report['expected']) and all(
            all(observed[pid].get(key)==expected[key] for key in ('background_color','shape_color','printed_number'))
            and observed[pid].get('shape') in ({'triangle'} if pid=='source' else {'circle','ellipse','oval'})
            for pid,expected in report['expected'].items())
        passed=passed and value['passed']
    destination=root/'.runtime/diagnostics/vision-transport.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Vision transport passed:',passed,'Report:',destination)
    if not passed:
        raise SystemExit(1)
asyncio.run(main())

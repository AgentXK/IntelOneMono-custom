#!/usr/bin/env python3
"""Render an exact, offline before/after specimen for customized Intel One Mono.

Run after building the modified fonts. Requires Pillow and fontTools.
No externally loaded images, scripts, fonts or styles are used in Preview.html.
"""
from __future__ import annotations
import base64
import html
import json
import os
from pathlib import Path
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
OUT = SCRIPT_DIR.parent if SCRIPT_DIR.name == "tools" else SCRIPT_DIR
UPSTREAM = OUT / "source-ttf"
MODIFIED = OUT / "fonts"

def find_cjk(bold=False):
    env = os.environ.get("FONT_SPECIMEN_CJK_BOLD" if bold else "FONT_SPECIMEN_CJK_FONT")
    candidates = [env] if env else []
    candidates += [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
    ]
    return next((Path(p) for p in candidates if Path(p).is_file()), None)

CJK, CJK_BOLD = find_cjk(), find_cjk(True)
SCALE = 2
WIDTH, HEIGHT = 1800, 1660
MARGIN, GAP, COLUMN = 64, 36, 818

CODE = """def choose_route(routes, forecast):
    scores = evaluate(routes, forecast)
    best = min(scores, key=lambda r: r.cost)
    if best.risk <= 0.05:
        return best.path
    return fallback_route()"""
HTML_CODE = """def choose_route(routes, forecast):
    scores = evaluate(routes, forecast)
    best = min(scores, key=lambda r: r.cost)
    if best.risk <= 0.05:
        return best.path
    return fallback_route()

# 字符对比（中文由系统字体补充）
# aegstfij  Il1|  O0o  {} [] ()  != => <=
# café  naïve  résumé  ắ  ộ  ǰ
"""

def font_path(side: str, style: str = "Regular") -> Path:
    return (UPSTREAM / f"IntelOneMono-{style}.ttf"
            if side == "before" else MODIFIED / f"IntelOneMono-{style}.ttf")

def metrics(path: Path) -> dict:
    font = TTFont(path)
    o, h = font["OS/2"], font["hhea"]
    result = {"xheight": o.sxHeight, "capheight": o.sCapHeight,
              "line": h.ascent - h.descent + h.lineGap,
              "upm": font["head"].unitsPerEm,
              "advance": font["hmtx"][font.getBestCmap()[ord("x")]][0]}
    font.close()
    return result

def ui(size: int, bold: bool = False):
    path = CJK_BOLD if bold and CJK_BOLD else CJK
    if path is None:
        raise RuntimeError("Chinese specimen labels need a CJK font. Set FONT_SPECIMEN_CJK_FONT to a local CJK TTF/TTC/OTF path.")
    return ImageFont.truetype(str(path), size * SCALE, index=2 if "NotoSansCJK" in path.name else 0)

def mono(side: str, size: int, style: str = "Regular"):
    return ImageFont.truetype(str(font_path(side, style)), size * SCALE,
                              layout_engine=ImageFont.Layout.RAQM)

def render_png(before: dict, after: dict) -> Path:
    bg, ink, muted = "#F5F4EF", "#182A2C", "#64706E"
    teal, gray = "#087F73", "#6C7777"
    image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), bg)
    draw = ImageDraw.Draw(image)
    def text(x, y, s, font, fill=ink, anchor="lt"):
        draw.text((round(x * SCALE), round(y * SCALE)), s, font=font, fill=fill, anchor=anchor)
    def line(x0, y0, x1, y1, fill, width=1):
        draw.line((round(x0*SCALE),round(y0*SCALE),round(x1*SCALE),round(y1*SCALE)),
                  fill=fill,width=max(1,round(width*SCALE)))
    def card(x,y,w,h,fill="#FFFFFF",border="#E3E6DF",radius=18):
        draw.rounded_rectangle((round(x*SCALE),round(y*SCALE),round((x+w)*SCALE),round((y+h)*SCALE)),
                               radius=radius*SCALE,fill=fill,outline=border,width=SCALE)
    def pill(x,y,w,title,value,note,color=ink):
        card(x,y,w,102)
        text(x+22,y+14,title,ui(18),muted)
        text(x+22,y+40,value,ui(31,True),color)
        text(x+w-22,y+64,note,ui(18),muted,anchor="rs")
    text(MARGIN,48,"TYPE SPECIMEN  /  定制字体对比",ui(19,True),teal)
    text(MARGIN,89,"Intel One Mono",ui(57,True))
    text(MARGIN,170,f'x-height {after["xheight"]} · 行高 {after["line"]/after["upm"]:.2f} em · AFDKO 导出',ui(28),muted)
    text(WIDTH-MARGIN,111,"基于 Intel One Mono 1.5.0",ui(21),muted,"rt")
    text(WIDTH-MARGIN,151,"两侧始终使用相同字号",ui(21),muted,"rt")
    pwidth=(WIDTH-2*MARGIN-2*20)/3
    delta=after["xheight"]/before["xheight"]-1
    shrink=1-after["line"]/before["line"]
    pill(MARGIN,229,pwidth,"小写 x-height",f'{before["xheight"]} → {after["xheight"]}',f"+{delta:.1%}",teal)
    pill(MARGIN+pwidth+20,229,pwidth,"推荐行高（每 em = 1000）",f'{before["line"]} → {after["line"]}',f"−{shrink:.1%}",teal)
    pill(MARGIN+2*(pwidth+20),229,pwidth,"等宽字符的前进宽度",f'{before["advance"]} → {after["advance"]}',"保持对齐")
    text(MARGIN,369,"01  字形比例",ui(25,True))
    text(WIDTH-MARGIN,374,"同字号 · 同基线 · 大写高度保持不变",ui(19),muted,"rt")
    for side,x,label,met,color in [
        ("before",MARGIN,"原版  Intel One Mono",before,gray),
        ("after",MARGIN+COLUMN+GAP,"修改版  Intel One Mono",after,teal)]:
        card(x,419,COLUMN,296)
        text(x+26,440,label,ui(24,True),color)
        size,baseline=100,596
        xh_y=baseline-size*met["xheight"]/met["upm"]
        cap_y=baseline-size*met["capheight"]/met["upm"]
        for yy,col in [(cap_y,"#D7DDD9"),(xh_y,"#7DBDB1"),(baseline,"#BAC8C2")]:
            line(x+25,yy,x+COLUMN-25,yy,col)
        text(x+29,baseline,"Hx aenomgp",mono(side,size),ink,"ls")
        text(x+COLUMN-28,cap_y-5,"cap",ui(15),muted,"rs")
        text(x+COLUMN-28,xh_y+17,"x-height",ui(15),teal,"rs")
        text(x+28,656,f'x-height {met["xheight"]}  /  cap-height {met["capheight"]}',ui(19),muted)
    text(MARGIN,754,"02  同字号代码",ui(25,True))
    text(WIDTH-MARGIN,759,"显式采用各自推荐行高；此图并非某个编辑器的截图",ui(19),muted,"rt")
    for side,x,met,color in [("before",MARGIN,before,"#A9B4B0"),
                            ("after",MARGIN+COLUMN+GAP,after,"#8DE0CC")]:
        card(x,805,COLUMN,304,fill="#142426",border="#142426")
        ratio=met["line"]/met["upm"];size=27
        text(x+27,825,f"27 px  /  行高 {ratio:.2f} em",ui(18),color)
        for index,code in enumerate(CODE.splitlines()):
            text(x+27,886+index*size*ratio,code,mono(side,size),"#E6EEEB","ls")
    text(MARGIN,1150,"03  字重、斜体与字符辨识",ui(25,True))
    for side,x in [("before",MARGIN),("after",MARGIN+COLUMN+GAP)]:
        card(x,1200,COLUMN,297)
        for i,(style,label) in enumerate([("Regular","Regular"),("Italic","Italic"),("Bold","Bold")]):
            yy=1246+i*64
            text(x+26,yy-2,label,ui(19),muted,"ls")
            text(x+147,yy+2,"aegstfij  Il1|  O0o",mono(side,38,style),ink,"ls")
        line(x+25,1416,x+COLUMN-25,1416,"#E3E6DF")
        text(x+27,1465,"á é ñ ö ü  č  ắ  ộ  ǰ",mono(side,33),ink,"ls")
    text(MARGIN,1532,"读图说明",ui(19,True),teal)
    text(MARGIN,1570,"x-height 为真实小写轮廓高度。行高数值是字体的推荐度量，实际显示仍取决于应用设置。",ui(21),muted)
    text(MARGIN,1608,"保留原字体名称；安装时请停用或替换旧版。更完整的文本、字号与行距对比见 Preview.html。",ui(20),muted)
    image=image.resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS)
    output=OUT/"Comparison.png";image.save(output,optimize=True)
    return output

def render_html(before:dict,after:dict)->Path:
    faces=[]
    for side,family in [("before","SpecimenOriginal"),("after","SpecimenTall")]:
        for style,weight,italic in [("Regular",400,"normal"),("Italic",400,"italic"),
                                    ("Bold",700,"normal"),("BoldItalic",700,"italic")]:
            data=base64.b64encode(font_path(side,style).read_bytes()).decode("ascii")
            faces.append(f"@font-face{{font-family:'{family}';font-style:{italic};font-weight:{weight};"
                         f"font-display:block;src:url(data:font/ttf;base64,{data}) format('truetype')}}")
    ratios=[before["line"]/before["upm"],after["line"]/after["upm"]]
    template=r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Intel One Mono · XH__XAFTER__ / LH__LAFTER__ / AFDKO 修改版对比</title>
<style>
__FONT_FACES__
:root{color-scheme:light;--paper:#f5f4ef;--ink:#182a2c;--muted:#64706e;--accent:#087f73;--rule:#dee4de}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI","Noto Sans CJK SC",sans-serif}
main{max-width:1480px;margin:0 auto;padding:48px 32px 40px}.eyebrow{color:var(--accent);font-size:12px;font-weight:750;letter-spacing:.15em;text-transform:uppercase}
h1{font-size:clamp(34px,5vw,62px);letter-spacing:-.055em;margin:12px 0 10px;font-weight:760}h1 small{font-size:.35em;letter-spacing:0;color:var(--muted);font-weight:500;margin-left:12px;white-space:nowrap}
.intro{font-size:17px;line-height:1.8;color:var(--muted);margin:0 0 28px;max-width:950px}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:22px 0 30px}
.metric{padding:18px 21px;border:1px solid var(--rule);border-radius:14px;background:#fff}.metric span{display:block;font-size:13px;color:var(--muted)}.metric strong{display:inline-block;font-size:28px;letter-spacing:-.03em;margin-top:7px}.metric em{font-style:normal;color:var(--accent);font-size:13px;margin-left:10px}
.controls{display:flex;flex-wrap:wrap;align-items:end;gap:16px;padding:20px;border:1px solid var(--rule);background:#fff;border-radius:14px;margin-bottom:24px}
label.control{display:grid;gap:8px;min-width:140px;font-size:13px;color:var(--muted)}label.control.wide{min-width:265px}.slider{display:flex;align-items:center;gap:12px;min-height:37px}.slider input{accent-color:var(--accent);width:170px}output{min-width:44px;font-size:14px;color:var(--ink);font-variant-numeric:tabular-nums}
select,button{font:inherit;font-size:14px;border:1px solid #cdd7d1;border-radius:8px;background:#fff;padding:9px 12px;color:var(--ink)}button{cursor:pointer}button:hover,select:hover{border-color:var(--accent)}button:focus-visible,select:focus-visible,input:focus-visible,pre:focus-visible{outline:3px solid #74cdb7;outline-offset:3px}.control.toggle{display:flex;align-items:center;gap:7px;padding-bottom:10px;min-width:110px;color:var(--ink)}.toggle input{accent-color:var(--accent)}
.columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:22px}.column{min-width:0}.column header{display:flex;gap:8px;align-items:center;justify-content:space-between;margin:0 3px 13px}.column h2{font-size:18px;margin:0}.column header span{font-size:12px;color:var(--muted);white-space:nowrap}.column.after h2{color:var(--accent)}
.sample{padding:25px 22px;border:1px solid var(--rule);border-radius:14px;background:#fff;min-height:142px;overflow:auto}.large{font-size:clamp(32px,3.6vw,54px);white-space:nowrap;line-height:1.5;margin:0}.before .font{font-family:SpecimenOriginal,monospace}.after .font{font-family:SpecimenTall,monospace}.caption{font-family:system-ui,sans-serif;font-size:12px;color:var(--muted);line-height:1.7;margin:8px 0 0}
.editor{padding:26px 22px;background:#142426;border:1px solid #142426;border-radius:14px;color:#e6eeeb;margin:17px 0 0;min-height:370px;overflow:auto;white-space:pre;tab-size:4;outline-offset:3px;font-synthesis:none;caret-color:#9fe8d5;font-feature-settings:"ss01" 0;font-variant-ligatures:none}
body.light-code .editor{background:#fff;border-color:var(--rule);color:var(--ink)}.styles{padding:20px 22px;border:1px solid var(--rule);border-radius:14px;background:#fff;margin-top:17px;overflow:auto}.styles p{margin:10px 0;white-space:nowrap;font-size:22px}.styles label{font:12px system-ui,sans-serif;color:var(--muted);display:inline-block;width:68px}.styles i{font-style:italic}.styles b{font-weight:700}
.note{font-size:13px;line-height:1.9;color:var(--muted);margin:21px 2px 30px}.note strong{color:var(--ink);font-weight:600}.section{margin-top:30px;padding-top:25px;border-top:1px solid var(--rule)}.section h3{font-size:16px;margin:0 0 14px}.stress{overflow:auto;font-size:22px;line-height:1.8;white-space:pre;min-height:100px;margin:0;padding:15px 0}.footer{font-size:12px;line-height:1.9;color:var(--muted);padding-top:22px;border-top:1px solid var(--rule)}a{color:var(--accent);text-underline-offset:3px}.badge{border-radius:99px;background:#e3f4ed;padding:4px 9px;color:var(--accent)!important}
@media(max-width:830px){main{padding:28px 16px}.columns{grid-template-columns:1fr;gap:28px}.metrics{gap:8px}.metric{padding:13px 12px}.metric strong{font-size:22px}.metric em{display:block;margin:5px 0 0}.controls{gap:13px;padding:16px}h1 small{display:block;margin:6px 0 0}.column header{align-items:start}.large{font-size:45px}}
@media print{body{background:#fff}main{max-width:none;padding:0}.controls,.note.edit-tip{display:none}.editor{min-height:0;background:#fff;color:#182a2c;border-color:#ddd;font-size:14px!important}.columns{grid-template-columns:1fr 1fr}.large{font-size:34px}.styles p,.stress{font-size:17px}.sample,.styles{break-inside:avoid}}
</style></head>
<body><main>
<div class="eyebrow">TYPE SPECIMEN / 离线字体对比</div>
<h1>Intel One Mono <small>XH__XAFTER__ / LH__LAFTER__ / AFDKO 修改版</small></h1>
<p class="intro">基于官方 OTF 修改并经 AFDKO otf2ttf 导出的版本：Regular x-height 为 __XAFTER__，保留原字体名称。左侧为官方原版 TTF，右侧为本次最终 TTF。两侧字号始终相同；你可以编辑任意一侧的代码，另一侧会同步显示，并切换行距模式单独比较字形。</p>
<section class="metrics" aria-label="度量变化">
<div class="metric"><span>Regular 小写 x-height</span><strong>__XBEFORE__ → __XAFTER__</strong><em>约 +__XPERCENT__%</em></div>
<div class="metric"><span>推荐行高 / 每 em = 1000</span><strong>__LBEFORE__ → __LAFTER__</strong><em>约 −__LPERCENT__%</em></div>
<div class="metric"><span>等宽字符的前进宽度</span><strong>__ADVANCE__ → __ADVANCE__</strong><em>保持对齐</em></div>
</section>
<section class="controls" aria-label="对比设置">
<label class="control">代码字号<div class="slider"><input id="size" type="range" min="12" max="32" step="1" value="18"><output id="size-value" for="size">18 px</output></div></label>
<label class="control">代码字样<select id="style"><option value="regular">Regular</option><option value="italic">Italic</option><option value="bold">Bold</option><option value="bolditalic">Bold Italic</option></select></label>
<label class="control wide">代码行距<select id="leading"><option value="recommended">各自推荐行高（__RBEFORE__ / __RAFTER__ em）</option><option value="same">两侧相同行高（__RBEFORE__ em）</option><option value="native">浏览器自动行高（normal）</option></select></label>
<label class="control toggle"><input id="light" type="checkbox">浅色代码背景</label>
<button id="reset" type="button">重置示例</button>
</section>
<div class="columns">
<section class="column before" aria-label="原版">
<header><h2>原版 Intel One Mono</h2><span>1.5.0</span></header>
<div class="sample"><p class="large font">Hx aenomgp</p><p class="caption">小写高度 __XBEFORE__ · 大写高度 __CAPHEIGHT__</p></div>
<pre id="original" class="editor font" contenteditable="true" spellcheck="false" aria-label="原版可编辑代码">__CODE__</pre>
<div class="styles"><p class="font"><label>Regular</label>aegstfij  Il1|  O0o</p><p class="font"><label>Italic</label><i>aegstfij  Il1|  O0o</i></p><p class="font"><label>Bold</label><b>aegstfij  Il1|  O0o</b></p></div>
</section>
<section class="column after" aria-label="修改版">
<header><h2>修改版 Intel One Mono</h2><span class="badge">x-height __XAFTER__</span></header>
<div class="sample"><p class="large font">Hx aenomgp</p><p class="caption">小写高度 __XAFTER__ · 大写高度 __CAPHEIGHT__</p></div>
<pre id="modified" class="editor font" contenteditable="true" spellcheck="false" aria-label="修改版可编辑代码">__CODE__</pre>
<div class="styles"><p class="font"><label>Regular</label>aegstfij  Il1|  O0o</p><p class="font"><label>Italic</label><i>aegstfij  Il1|  O0o</i></p><p class="font"><label>Bold</label><b>aegstfij  Il1|  O0o</b></p></div>
</section>
</div>
<p class="note edit-tip"><strong>可直接编辑代码。</strong>“各自推荐行高”显式使用字体所设的行高比例；“相同行高”便于只看字形变化；“浏览器自动行高”用于检查当前浏览器的实际表现。应用或编辑器可能采用自己的行距设置。</p>
<section class="section"><h3>重音字母、升部与降部</h3><div class="columns"><div class="column before"><pre class="stress font">café naïve résumé  àáâãäå
ç č ď éèêë  ñ ö ü  ắ  ộ  ǰ
b d f h k l  g j p q y
á / á    ë / ë    ñ / ñ</pre></div><div class="column after"><pre class="stress font">café naïve résumé  àáâãäå
ç č ď éèêë  ñ ö ü  ắ  ộ  ǰ
b d f h k l  g j p q y
á / á    ë / ë    ñ / ñ</pre></div></div></section>
<p class="note">保留原字体名称；安装时请停用或替换旧版。所有对比用字体均已嵌入本文件，断网也能打开。本页中的中文使用系统字体补充；修改对象是原字体覆盖的字符。表中数字使用字体设计单位，不是屏幕像素。</p>
<footer class="footer">原始字体：<a href="https://github.com/intel/intel-one-mono" target="_blank" rel="noopener">Intel One Mono</a> · Copyright 2023–2026 The Intel One Mono Project Authors。<br>原版与修改版遵循 <a href="https://openfontlicense.org/open-font-license-official-text/" target="_blank" rel="noopener">SIL Open Font License 1.1</a>。本文件对比官方原版 TTF 与本次 AFDKO 导出的定制 TTF；本次输出不含 TrueType hinting。安装包另有含 8 款样式的 TTC，TTF 与 TTC 任选一种安装。<details style="margin-top:12px"><summary>查看完整许可证</summary><pre style="white-space:pre-wrap;font:12px/1.7 system-ui,sans-serif">__LICENSE__</pre></details></footer>
</main>
<script>
'use strict';
const defaultSample=__SAMPLE_JSON__;
const ratios=__RATIOS_JSON__;
const original=document.getElementById('original');
const modified=document.getElementById('modified');
const samples=[original,modified];
const size=document.getElementById('size');
const style=document.getElementById('style');
const leading=document.getElementById('leading');
function update(){
 const px=Number(size.value); document.getElementById('size-value').textContent=px+' px';
 const s=style.value;
 samples.forEach((el,i)=>{
   el.style.fontSize=px+'px';
   el.style.fontWeight=s.includes('bold')?'700':'400';
   el.style.fontStyle=s.includes('italic')?'italic':'normal';
   el.style.lineHeight=leading.value==='native'?'normal':String(leading.value==='same'?ratios[0]:ratios[i]);
 });
}
size.addEventListener('input',update);style.addEventListener('change',update);leading.addEventListener('change',update);
document.getElementById('light').addEventListener('change',e=>document.body.classList.toggle('light-code',e.target.checked));
samples.forEach((el,i)=>{
 el.addEventListener('input',()=>{samples[1-i].textContent=el.innerText.replace(/\r\n/g,'\n');});
 el.addEventListener('paste',e=>{e.preventDefault();const raw=e.clipboardData.getData('text/plain');
   const selection=window.getSelection();if(!selection.rangeCount)return;
   const range=selection.getRangeAt(0);range.deleteContents();const node=document.createTextNode(raw);range.insertNode(node);range.setStartAfter(node);range.collapse(true);selection.removeAllRanges();selection.addRange(range);el.dispatchEvent(new Event('input',{bubbles:true}));
 });
});
document.getElementById('reset').addEventListener('click',()=>{samples.forEach(el=>el.textContent=defaultSample);size.value='18';style.value='regular';leading.value='recommended';document.getElementById('light').checked=false;document.body.classList.remove('light-code');update();});
update();
</script>
</body></html>'''
    replacements={
        "__FONT_FACES__":"\n".join(faces),
        "__XBEFORE__":str(before["xheight"]),"__XAFTER__":str(after["xheight"]),
        "__XPERCENT__":f'{(after["xheight"]/before["xheight"]-1)*100:.1f}',
        "__LBEFORE__":str(before["line"]),"__LAFTER__":str(after["line"]),
        "__LPERCENT__":f'{(1-after["line"]/before["line"])*100:.1f}',
        "__ADVANCE__":str(after["advance"]),"__CAPHEIGHT__":str(after["capheight"]),
        "__RBEFORE__":f"{ratios[0]:.2f}","__RAFTER__":f"{ratios[1]:.2f}",
        "__CODE__":html.escape(HTML_CODE),"__SAMPLE_JSON__":json.dumps(HTML_CODE,ensure_ascii=False),
        "__RATIOS_JSON__":json.dumps(ratios),
        "__LICENSE__":html.escape((OUT/"OFL.txt").read_text(encoding="utf-8"))}
    for key,value in replacements.items():template=template.replace(key,value)
    output=OUT/"Preview.html";output.write_text(template,encoding="utf-8")
    return output

def main():
    required=[font_path(side,style) for side in ["before","after"]
              for style in ["Regular","Italic","Bold","BoldItalic"]]
    missing=[str(p) for p in required if not p.is_file()]
    if missing:raise SystemExit("Build fonts first. Missing: "+", ".join(missing))
    OUT.mkdir(exist_ok=True,parents=True)
    before,after=metrics(font_path("before")),metrics(font_path("after"))
    for path in [render_png(before,after),render_html(before,after)]:
        print(f"{path}: {path.stat().st_size:,} bytes")

if __name__=="__main__":
    main()

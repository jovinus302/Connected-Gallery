// Package the approved ImageGen paper artwork into Android's 108dp adaptive layers.
// Requires sharp. The approved source and isolated foreground remain in assets/branding.
const fs=require('node:fs'),path=require('node:path'),sharp=require('sharp');
const root=path.resolve(__dirname,'..'),brand=path.join(root,'assets/branding'),res=path.join(root,'android/app/src/main/res'),out=path.join(root,'outputs/android-icon');
fs.mkdirSync(out,{recursive:true});
const bg=fs.readFileSync(path.join(res,'values/icon_colors.xml'),'utf8').match(/>(#[0-9a-f]+)</i)[1];
const monoPaths=[
'M30 35 L47 31 Q51 30 52 34 L53 38 L49 37 L48 35 L31 39 L37 67 L43 66 L43 70 L37 71 Q34 72 33 68 L27 40 Q26 36 30 35 Z',
'M55 38 L78 43 Q82 44 81 48 L75 76 Q74 80 70 79 L47 74 Q43 73 44 69 L50 42 Q51 37 55 38 Z M55 42 Q54 42 54 44 L48 69 Q47 70 49 71 L70 75 Q71 75 72 73 L77 48 Q78 47 76 47 Z',
'M49 64 Q55 56 61 62 Q66 68 74 65 L72 74 L48 69 Z',
'M70 53 C70 55.2 68.2 57 66 57 C63.8 57 62 55.2 62 53 C62 50.8 63.8 49 66 49 C68.2 49 70 50.8 70 53 Z',
'M44 51 L50 52 L49 57 L44 56 Q41 55 42 52 Z'
];
const mono=tint=>monoPaths.map(d=>`<path d="${d}" fill="${tint}" fill-rule="evenodd"/>`).join('');
const svg=(body,size=512,vb='18 18 72 72')=>`<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="${vb}">${body}</svg>`;
(async()=>{
 const source=sharp(path.join(brand,'butter-collage-foreground.png'));
 const meta=await source.metadata();if(!meta.hasAlpha)throw Error('Foreground must have transparent alpha');
 const trimmed=await source.trim({threshold:20}).toBuffer();
 // 58 x 50dp art is contained inside the adaptive safe circle (actual rounded corners inset).
 const art=await sharp(trimmed).resize(580,500,{fit:'inside'}).png().toBuffer();
 const m=await sharp(art).metadata();
 const foreground=await sharp({create:{width:1080,height:1080,channels:4,background:'#00000000'}}).composite([{input:art,left:Math.round((1080-m.width)/2),top:Math.round((1080-m.height)/2)}]).png().toBuffer();
 fs.mkdirSync(path.join(res,'drawable-nodpi'),{recursive:true});
 await sharp(foreground).resize(432,432).png().toFile(path.join(res,'drawable-nodpi/ic_gallery_paper.png'));
 fs.writeFileSync(path.join(res,'drawable/ic_gallery_foreground.xml'),'<?xml version="1.0" encoding="utf-8"?>\n<bitmap xmlns:android="http://schemas.android.com/apk/res/android" android:src="@drawable/ic_gallery_paper" android:gravity="fill" android:filter="true" />\n');
 fs.writeFileSync(path.join(res,'drawable/ic_gallery_monochrome.xml'),'<?xml version="1.0" encoding="utf-8"?>\n<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">\n'+monoPaths.map(d=>`    <path android:fillColor="#FFFFFF" android:fillType="evenOdd" android:pathData="${d}" />`).join('\n')+'\n</vector>\n');
 const color=`<rect width="108" height="108" fill="${bg}"/><image width="108" height="108" href="data:image/png;base64,${foreground.toString('base64')}"/>`;
 fs.writeFileSync(path.join(brand,'connected-gallery-icon.svg'),svg(color));
 fs.writeFileSync(path.join(brand,'connected-gallery-mark.svg'),svg(mono('#485D50')));
 await sharp(Buffer.from(svg(color))).png().toFile(path.join(brand,'connected-gallery-icon-512.png'));
 function icon(id,x,y,s,shape='rect',tint=null,background=bg){return `<svg x="${x}" y="${y}" width="${s}" height="${s}" viewBox="18 18 72 72"><defs><clipPath id="${id}">${shape==='circle'?'<circle cx="54" cy="54" r="36"/>':'<rect x="18" y="18" width="72" height="72" rx="18"/>'}</clipPath></defs><g clip-path="url(#${id})">${tint?`<rect width="108" height="108" fill="${background}"/>${mono(tint)}`:color}</g></svg>`}
 const preview=`<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="680"><rect width="1200" height="680" fill="#F4F0E7"/><g font-family="Segoe UI, sans-serif" fill="#394B42"><text x="48" y="59" font-size="29" font-weight="600">Connected Gallery / Butter Collage</text><text x="49" y="91" font-size="16">Paper texture · Butter yellow · Dusty blue · Sage · Terracotta</text>${icon('hero',48,136,380)}${icon('circle',497,153,200,'circle')}${icon('mono',747,153,170,'rect','#4D6053','#EAE9D8')}${icon('dark',976,173,130,'circle','#EAE9D8','#34483D')}<text x="550" y="392" font-size="16">Circle mask</text><text x="778" y="392" font-size="16">Themed icon</text><text x="1000" y="392" font-size="16">Dark theme</text>${icon('64',508,468,64)}${icon('48',664,476,48)}${icon('32',806,484,32)}<text x="518" y="564" font-size="14">64 px</text><text x="670" y="564" font-size="14">48 px</text><text x="804" y="564" font-size="14">32 px</text><text x="48" y="619" font-size="16">Adaptive foreground + background + monochrome / 108dp layers</text></g></svg>`;
 await sharp(Buffer.from(preview)).png().toFile(path.join(out,'connected-gallery-icon-preview.png'));
 fs.copyFileSync(path.join(out,'connected-gallery-icon-preview.png'),path.join(root,'docs/images/android-icon-2026-09-10.png'));
 console.log('Packaged Butter Collage adaptive icon, monochrome vector, exports and preview.');
})();

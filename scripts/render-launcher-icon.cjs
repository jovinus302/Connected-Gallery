// Render review/export assets from the Android vector source. Requires sharp.
const fs = require('node:fs');
const path = require('node:path');
const sharp = require('sharp');

const root = path.resolve(__dirname, '..');
const res = path.join(root, 'android/app/src/main/res');
const brand = path.join(root, 'assets/branding');
const output = path.join(root, 'outputs/android-icon');
fs.mkdirSync(brand, { recursive: true });
fs.mkdirSync(output, { recursive: true });

function paths(name) {
  const xml = fs.readFileSync(path.join(res, 'drawable', name), 'utf8');
  return [...xml.matchAll(/<path\s+([^>]+)\/>/g)].map(([, attributes]) => {
    const attr = Object.fromEntries([...attributes.matchAll(/android:(\w+)="([^"]*)"/g)].map(([, key, value]) => [key, value]));
    return { d: attr.pathData, fill: attr.fillColor, rule: attr.fillType === 'evenOdd' ? 'evenodd' : 'nonzero' };
  });
}
const foreground = paths('ic_gallery_foreground.xml');
const monochrome = paths('ic_gallery_monochrome.xml');
if (JSON.stringify(foreground.map(({ d, rule }) => [d, rule])) !== JSON.stringify(monochrome.map(({ d, rule }) => [d, rule]))) {
  throw new Error('Color and monochrome geometry differ. Update both Android vectors.');
}
const bg = fs.readFileSync(path.join(res, 'values/icon_colors.xml'), 'utf8').match(/>(#[0-9A-Fa-f]+)</)[1];
const geometry = (tint) => foreground.map(p => `<path fill="${tint || p.fill}" fill-rule="${p.rule}" d="${p.d}"/>`).join('');
const svg = (body, viewBox = '18 18 72 72', size = 512) => `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="${viewBox}">${body}</svg>`;
const color = `<rect width="108" height="108" fill="${bg}"/>${geometry()}`;
fs.writeFileSync(path.join(brand, 'connected-gallery-icon.svg'), svg(color));
fs.writeFileSync(path.join(brand, 'connected-gallery-mark.svg'), svg(geometry(bg), '20 20 68 68'));

async function main() {
  await sharp(Buffer.from(svg(color))).png().toFile(path.join(brand, 'connected-gallery-icon-512.png'));
  function icon(id, x, y, size, shape = 'roundrect', background = bg, tint) {
    const mask = shape === 'circle' ? '<circle cx="54" cy="54" r="36"/>' : '<rect x="18" y="18" width="72" height="72" rx="19"/>';
    return `<svg x="${x}" y="${y}" width="${size}" height="${size}" viewBox="18 18 72 72"><defs><clipPath id="${id}">${mask}</clipPath></defs><g clip-path="url(#${id})"><rect width="108" height="108" fill="${background}"/>${geometry(tint)}</g></svg>`;
  }
  const preview = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720">
    <rect width="1200" height="720" fill="#F2F1EC"/>
    <g font-family="Segoe UI, sans-serif" fill="#171A17">
      <text x="54" y="65" font-size="30" font-weight="600">Connected Gallery</text>
      <text x="54" y="94" font-size="15" fill="#65715E">APP ICON / TWO PHOTOS, ONE CONNECTION</text>
      <rect x="34" y="128" width="430" height="537" rx="28" fill="#FAF9F6"/>
      ${icon('hero', 84, 184, 330)}
      <text x="249" y="563" text-anchor="middle" font-size="23" font-weight="600">Connected Gallery</text>
      <text x="249" y="593" text-anchor="middle" font-size="15" fill="#65715E">Sage / Ivory / Photo frames</text>
      <text x="524" y="166" font-size="13" letter-spacing="2" fill="#65715E">ADAPTIVE SHAPES</text>
      ${icon('circle', 536, 206, 166, 'circle')}
      ${icon('themed', 766, 206, 166, 'roundrect', '#E6ECDF', '#31452E')}
      ${icon('night', 984, 234, 110, 'circle', '#283829', '#D3E2B5')}
      <text x="619" y="408" text-anchor="middle" font-size="15">Circle</text>
      <text x="849" y="408" text-anchor="middle" font-size="15">Monochrome</text>
      <text x="1039" y="408" text-anchor="middle" font-size="15">Dark theme</text>
      <path d="M524,454 L1138,454" stroke="#DDE0D5"/>
      <text x="524" y="496" font-size="13" letter-spacing="2" fill="#65715E">SMALL SIZE CHECK</text>
      ${icon('small64', 536, 528, 64)} ${icon('small48', 678, 536, 48)} ${icon('small32', 818, 544, 32)}
      <text x="568" y="620" text-anchor="middle" font-size="14">64 px</text>
      <text x="702" y="620" text-anchor="middle" font-size="14">48 px</text>
      <text x="834" y="620" text-anchor="middle" font-size="14">32 px</text>
    </g>
  </svg>`;
  await sharp(Buffer.from(preview)).png().toFile(path.join(output, 'connected-gallery-icon-preview.png'));
  console.log('Rendered launcher icon, editable SVGs, and color / monochrome / small-size preview.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });

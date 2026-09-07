// Regression for normalized hit targets collapsing into the image's top corner.
const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const vm = require('node:vm');

const source = readFileSync(resolve(__dirname, '../web/demo/app.js'), 'utf8');
const fit = source.slice(source.indexOf('function fitRegions(){'), source.indexOf('function highlightRegion(){'));
const layering = source.slice(source.indexOf('function regionLayers(regions){'), source.indexOf('function paintRegions(){'));

test('small objects remain clickable above broader regions without renumbering', () => {
  const regions = [
    {id: 'small', box: {width: .2, height: .2}},
    {id: 'medium', box: {width: .4, height: .3}},
    {id: 'background', box: {width: 1, height: 1}},
    {id: 'same-size', box: {width: .2, height: .2}},
  ];
  const order = regions.map(region => region.id);
  const context = {regions};
  vm.createContext(context);
  const result = vm.runInContext(layering + '\nregionLayers(regions);', context);
  assert.equal(result.get('background'), 1);
  assert.equal(result.get('medium'), 2);
  assert.equal(result.get('small'), 3);
  assert.equal(result.get('same-size'), 4);
  assert.deepEqual(regions.map(region => region.id), order);
});

for (const [name, naturalWidth, naturalHeight, width, height, expectedWidth, expectedHeight] of [
  ['desktop landscape', 1536, 1024, 600, 400, 600, 400],
  ['desktop portrait with side letterbox', 1024, 1536, 600, 480, 320, 480],
  ['phone portrait', 1024, 1536, 350, 525, 350, 525],
  ['phone landscape', 1536, 1024, 360, 240, 360, 240],
]) {
  test(`region plane follows actual rendered image: ${name}`, () => {
    const layer = {style: {}}, image = {naturalWidth, naturalHeight, clientWidth: width, clientHeight: height};
    const elements = {'source-photo': image, 'photo-stage': {clientWidth: width, clientHeight: height}, regions: layer};
    vm.runInNewContext(fit + '\nfitRegions();', {$: id => elements[id]});
    assert.equal(layer.style.width, `${expectedWidth}px`);
    assert.equal(layer.style.height, `${expectedHeight}px`);
    assert.equal(layer.style.left, `${(width - expectedWidth) / 2}px`);
    assert.equal(layer.style.top, `${(height - expectedHeight) / 2}px`);
    assert.equal(layer.style.right, 'auto');
    assert.equal(layer.style.bottom, 'auto');
  });
}

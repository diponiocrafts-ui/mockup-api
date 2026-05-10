const sharp = require('sharp');
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

const FRAMES = {
  1: [[618, 397, 1348, 1293]],
  2: [[505, 286, 1279, 1232]],
  3: [[505, 286, 1279, 1232]],
  4: [[607, 370, 1196, 1195]],
  5: [[512, 294, 1254, 1291]],
  6: [[320, 449, 799, 1167], [963, 449, 1441, 1167]],
  7: [[574, 400, 1239, 1284]],
  8: [[557, 149, 1223, 1203]],
  9: [[507, 230, 1173, 1295]],
};

const TEMPLATES_DIR = path.join(__dirname, 'templates');
const templateCache = {};

async function getTemplateBuffer(t) {
  if (!templateCache[t]) {
    templateCache[t] = fs.readFileSync(path.join(TEMPLATES_DIR, `${t}.png`));
  }
  return templateCache[t];
}

async function downloadImage(url) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith('https') ? https : http;
    const req = client.get(url, { timeout: 10000 }, (res) => {
      if (res.statusCode !== 200) { reject(new Error(`HTTP ${res.statusCode}`)); return; }
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve(Buffer.concat(chunks)));
      res.on('error', reject);
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Download timeout')); });
  });
}

async function generateMockup(t, designBuffer) {
  const templateBuffer = await getTemplateBuffer(t);
  const frames = FRAMES[t];
  const composites = [];
  for (const [x1, y1, x2, y2] of frames) {
    const frameW = x2 - x1;
    const frameH = y2 - y1;
    const designResized = await sharp(designBuffer)
      .resize(frameW, frameH, { fit: 'cover', position: 'center' })
      .toBuffer();
    composites.push({ input: designResized, left: x1, top: y1 });
  }
  const meta = await sharp(templateBuffer).metadata();
  let result = sharp(templateBuffer).composite(composites);
  if (meta.width > 800) {
    result = result.resize(800, null, { fit: 'inside' });
  }
  const jpegBuffer = await result.jpeg({ quality: 60 }).toBuffer();
  return jpegBuffer.toString('base64');
}

module.exports = async (req, res) => {
  if (req.method === 'GET') {
    res.json({ status: 'ok', templates: Object.keys(FRAMES).map(Number) });
    return;
  }
  try {
    let body = '';
    await new Promise((resolve, reject) => {
      req.on('data', chunk => { body += chunk; });
      req.on('end', resolve);
      req.on('error', reject);
    });
    const data = JSON.parse(body);
    const designUrl = (data.design_url || '').trim();
    const templates = (data.templates || [1, 2, 3]).map(Number);
    if (!designUrl) {
      res.json({ images: [], error: 'Missing design_url', step: 'validation' });
      return;
    }
    for (const t of templates) {
      if (!FRAMES[t]) {
        res.json({ images: [], error: `Invalid template: ${t}`, step: 'validation' });
        return;
      }
    }
    let designBuffer;
    try {
      designBuffer = await downloadImage(designUrl);
    } catch (e) {
      res.json({ images: [], error: `Download failed: ${e.message}`, step: 'download' });
      return;
    }
    try {
      const results = await Promise.all(templates.map(t => generateMockup(t, designBuffer)));
      res.json({ images: results, count: results.length });
    } catch (e) {
      res.json({ images: [], error: `Generation failed: ${e.message}`, step: 'generation' });
    }
  } catch (e) {
    res.json({ images: [], error: `Outer error: ${e.message}`, step: 'outer' });
  }
};

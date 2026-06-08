#!/usr/bin/env node
'use strict';

/*
 * html2mp4 — Convierte un HTML standalone en un MP4 respetando los tiempos
 * exactos de sus transiciones/animaciones (CSS + JS).
 *
 * Cómo funciona:
 *   Usa `timecut` (Puppeteer + ffmpeg). En vez de grabar en tiempo real,
 *   inyecta un reloj VIRTUAL (timeweb) que intercepta Date, performance.now,
 *   requestAnimationFrame, setTimeout/setInterval y la línea de tiempo de las
 *   animaciones/transiciones CSS. Avanza el tiempo en pasos fijos (1/fps),
 *   toma un screenshot por paso y los ensambla con ffmpeg. Resultado:
 *   timing perfecto y reproducible, independiente de la potencia de la máquina.
 *
 * Uso:
 *   node html2mp4.js <entrada.html> [opciones]
 *
 * Opciones:
 *   -o, --output <archivo>     Salida MP4 (def: <entrada>.mp4)
 *   -d, --duration <segundos>  Duración a capturar. Si se omite, se intenta
 *                              auto-detectar (ver "Auto-duración" abajo).
 *   -f, --fps <n>              Fotogramas por segundo (def: 30)
 *   -w, --width <px>           Ancho del viewport (def: 1920)
 *   -h, --height <px>          Alto del viewport (def: 1080)
 *   -s, --scale <n>            deviceScaleFactor / supersampling (def: 1)
 *       --start <segundos>     Tiempo virtual inicial (def: 0)
 *       --selector <css>       Captura sólo el elemento que matchee el selector
 *       --crf <n>              Calidad x264, menor = mejor (def: 18)
 *       --transparent          MP4/sin fondo no aplica; usa PNG+alpha (avanzado)
 *       --keep-frames          No borrar el caché de frames intermedios
 *
 * Auto-duración (si no se pasa --duration):
 *   El script busca, en este orden, dentro del HTML/página:
 *     1) <meta name="capture-duration" content="6">
 *     2) window.CAPTURE_DURATION  (número en segundos)
 *     3) atributo data-capture-duration en <body> o <html>
 *   Si no encuentra nada, usa 5 segundos por defecto y avisa.
 */

const path = require('path');
const fs = require('fs');
const timecut = require('timecut');

// ---- Chromium incluido por Puppeteer (sin depender del Chrome del sistema) --
function findChromium() {
  // Permite override por variable de entorno
  if (process.env.CHROME_PATH && fs.existsSync(process.env.CHROME_PATH)) {
    return process.env.CHROME_PATH;
  }
  const base = path.join(__dirname, 'node_modules', 'puppeteer', '.local-chromium');
  if (fs.existsSync(base)) {
    for (const rev of fs.readdirSync(base)) {
      const candidate = path.join(base, rev, 'chrome-linux', 'chrome');
      if (fs.existsSync(candidate)) return candidate;
    }
  }
  return undefined; // dejar que Puppeteer decida
}

// ---- Parseo de argumentos ---------------------------------------------------
function parseArgs(argv) {
  const opts = {
    fps: 30,
    width: 1920,
    height: 1080,
    scale: 1,
    start: 0,
    crf: 18,
    keepFrames: false,
  };
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => argv[++i];
    switch (a) {
      case '-o': case '--output': opts.output = next(); break;
      case '-d': case '--duration': opts.duration = parseFloat(next()); break;
      case '-f': case '--fps': opts.fps = parseFloat(next()); break;
      case '-w': case '--width': opts.width = parseInt(next(), 10); break;
      case '-h': case '--height': opts.height = parseInt(next(), 10); break;
      case '-s': case '--scale': opts.scale = parseFloat(next()); break;
      case '--start': opts.start = parseFloat(next()); break;
      case '--selector': opts.selector = next(); break;
      case '--crf': opts.crf = parseInt(next(), 10); break;
      case '--keep-frames': opts.keepFrames = true; break;
      case '--help': opts.help = true; break;
      default:
        if (a.startsWith('-')) {
          console.error(`Opción desconocida: ${a}`);
          process.exit(1);
        }
        positional.push(a);
    }
  }
  opts.input = positional[0];
  return opts;
}

const HELP = `html2mp4 — HTML standalone -> MP4 con timing exacto de transiciones

Uso:
  node html2mp4.js <entrada.html> [opciones]

  -o, --output <f>      Salida MP4 (def: <entrada>.mp4)
  -d, --duration <s>    Segundos a capturar (si se omite, auto-detecta)
  -f, --fps <n>         FPS (def: 30)
  -w, --width <px>      Ancho viewport (def: 1920)
  -h, --height <px>     Alto viewport (def: 1080)
  -s, --scale <n>       Supersampling / deviceScaleFactor (def: 1)
      --start <s>       Tiempo virtual inicial (def: 0)
      --selector <css>  Capturar sólo ese elemento
      --crf <n>         Calidad x264 (def: 18, menor = mejor)
      --keep-frames     Conservar frames intermedios
`;

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help || !opts.input) {
    console.log(HELP);
    process.exit(opts.input ? 0 : 1);
  }

  const inputPath = path.resolve(opts.input);
  if (!fs.existsSync(inputPath)) {
    console.error(`No existe el archivo: ${inputPath}`);
    process.exit(1);
  }

  const output = path.resolve(
    opts.output || inputPath.replace(/\.html?$/i, '') + '.mp4'
  );

  const executablePath = findChromium();
  const inputUrl = 'file://' + inputPath;

  // Config común para auto-duración y captura
  const baseConfig = {
    url: inputUrl,
    viewport: {
      width: opts.width,
      height: opts.height,
      deviceScaleFactor: opts.scale,
    },
    executablePath,
    launchArguments: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
  };

  // ---- Auto-detección de duración -----------------------------------------
  let duration = opts.duration;
  if (!duration || isNaN(duration)) {
    duration = await autoDetectDuration(inputUrl, executablePath);
    if (duration) {
      console.log(`Auto-duración detectada: ${duration}s`);
    } else {
      duration = 5;
      console.warn('No se pudo auto-detectar la duración. Usando 5s por defecto.');
      console.warn('Sugerencia: pasa --duration <s> o añade');
      console.warn('  <meta name="capture-duration" content="N"> al HTML.');
    }
  }

  console.log(`\nConvirtiendo: ${inputPath}`);
  console.log(`Salida:       ${output}`);
  console.log(`Ajustes:      ${opts.width}x${opts.height}@${opts.fps}fps, ${duration}s, x${opts.scale}, crf ${opts.crf}\n`);

  await timecut(Object.assign({}, baseConfig, {
    output,
    fps: opts.fps,
    duration,
    startTime: opts.start,
    selector: opts.selector,
    ffmpegPath: 'ffmpeg',
    pixFmt: 'yuv420p',
    roundToEvenWidth: true,
    roundToEvenHeight: true,
    keepFrames: opts.keepFrames,
    outputOptions: ['-c:v', 'libx264', '-crf', String(opts.crf), '-preset', 'slow'],
    screenshotType: 'png',
  }));

  console.log(`\n✓ Listo: ${output}`);
}

// Lanza el HTML en Chromium y lee la duración declarada por el propio documento.
async function autoDetectDuration(inputUrl, executablePath) {
  const puppeteer = require('puppeteer');
  const browser = await puppeteer.launch({
    executablePath,
    args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
  });
  try {
    const page = await browser.newPage();
    await page.goto(inputUrl, { waitUntil: 'networkidle0' });
    const d = await page.evaluate(() => {
      const meta = document.querySelector('meta[name="capture-duration"]');
      if (meta && meta.content) return parseFloat(meta.content);
      if (typeof window.CAPTURE_DURATION === 'number') return window.CAPTURE_DURATION;
      const el = document.body || document.documentElement;
      const attr = el && el.getAttribute('data-capture-duration');
      if (attr) return parseFloat(attr);
      return null;
    });
    return d && !isNaN(d) ? d : null;
  } catch (e) {
    return null;
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error('\nError:', err && err.message ? err.message : err);
  process.exit(1);
});

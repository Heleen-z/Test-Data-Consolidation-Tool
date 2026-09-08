// Synthetic fixtures for manual UI acceptance. No production data or services.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dest = path.join(root, 'outputs', 'ui-demo');
await fs.mkdir(path.dirname(dest), { recursive: true });
await fs.mkdir(dest); // Refuse to overwrite a previous acceptance session.
for (const name of ['input', 'output', 'templates', 'profile', 'previews']) {
  await fs.mkdir(path.join(dest, name));
}
const channels = ['TCK01', 'TCK_02', 'R_EC.SPEED', 'R_EC.TORQUE', 'R_EC.POWER', 'ACCELERATION', 'T gas in', 'Toal Flow'];
async function xlsx(relative, headers, rows = [], template = false) {
  const book = Workbook.create();
  const sheet = book.worksheets.add('Data');
  sheet.getRange('A1').write([headers, ...rows]);
  sheet.showGridLines = false;
  const header = sheet.getRangeByIndexes(0, 0, 1, headers.length);
  header.format = { fill: template ? '#FFFF00' : '#153E63', font: { name: 'Arial', size: 10, bold: true, color: template ? '#111111' : '#FFFFFF' }, wrapText: true, rowHeight: 34, columnWidth: 22 };
  if (rows.length) {
    sheet.getRangeByIndexes(1, 0, rows.length, headers.length).format.numberFormat = '0.000';
    sheet.freezePanes.freezeRows(1);
  }
  book.recalculate();
  console.log((await book.inspect({kind: 'region', sheetId: 'Data', range: 'A1:J4', maxChars: 1200})).ndjson);
  const png = await book.render({sheetName: 'Data', range: `A1:${String.fromCharCode(64 + headers.length)}${rows.length ? 5 : 1}`, scale: 1, format: 'png'});
  await fs.writeFile(path.join(dest, 'previews', path.basename(relative) + '.png'), new Uint8Array(await png.arrayBuffer()));
  await (await SpreadsheetFile.exportXlsx(book)).save(path.join(dest, relative));
}
function signals(i) {
  const phase = i / 100 * Math.PI * 2;
  return [
    550 + 250 * Math.sin(phase) + (i === 617 ? 240 : 0),
    490 + 200 * Math.sin(phase - .3),
    32 + 8 * Math.sin(phase / 2),
    4 + 1.5 * Math.cos(phase),
    1.2 + .4 * Math.sin(phase + .5),
    .2 * Math.sin(phase * 7),
    420 + 160 * Math.sin(phase - .7),
    12,
  ].map(v => Math.round(v * 1000) / 1000);
}
function absoluteRows(start, count) {
  return Array.from({length: count}, (_, n) => {
    const i = start + n;
    const stamp = new Date(Date.UTC(2026, 8, 8, 8, 0, i)).toISOString();
    const values = signals(i);
    if (i >= 850 && i < 860) values[1] = ''; // Deliberate missing-value gap.
    return [stamp.slice(0, 10), stamp.slice(11, 19), ...values];
  });
}
async function csv(name, headers, rows, separator = ',') {
  const quote = v => String(v).includes(separator) ? `"${String(v).replaceAll('"', '""')}"` : String(v);
  await fs.writeFile(path.join(dest, 'input', name), [headers, ...rows].map(r => r.map(quote).join(separator)).join('\n') + '\n', {encoding: 'utf8', flag: 'wx'});
}
await xlsx('templates/GANTER demo.xlsx', ['Date', 'Time', ...channels], [], true);
await xlsx('templates/T09 demo.xlsx', ['Cycles', ...channels], [], true);
await xlsx('templates/FAKT demo.xlsx', ['Timestamp [ms]', 'Runtime [ms]', ...channels], [], true);
await csv('GANTER_01_升温与转速.csv', ['Date', 'Time', ...channels], absoluteRows(0, 1200));
await csv('GANTER_02_连续数据_用于测试长文件名自动换行及来源选择.csv', ['Date', 'Time', ...channels], absoluteRows(1200, 1200));
await csv('GANTER_03_缺少部分通道_可合并警告.csv', ['Date', 'Time', ...channels.slice(0, 4)], absoluteRows(2400, 300).map(r => r.slice(0, 6)));
await csv('FAKT_01_相对时间.txt', ['Timestamp [ms]', 'Runtime [ms]', ...channels], Array.from({length: 600}, (_, i) => [i * 100, i * 100, ...signals(i)]), ';');
await xlsx('input/T09_01_20轮次.xlsx', ['Cycles', ...channels], Array.from({length: 2001}, (_, i) => [i / 100, ...signals(i)]));
await csv('GANTER_04_缺少时间轴_应排除.csv', ['TCK01', 'TCK_02'], [[100, 110], [101, 111]]);
await fs.writeFile(path.join(dest, 'input', 'GANTER_05_空文件_应排除.csv'), '');
await fs.copyFile(path.join(dest, 'input', 'GANTER_01_升温与转速.csv'), path.join(dest, 'input', 'GANTER_06_完全重复_应排除.csv'));
const config = {
  schema_version: 1,
  usage_logging: {mode: 'off'},
  defaults: {input_folder: path.join(dest, 'input'), output_folder: path.join(dest, 'output'), template_folder: path.join(dest, 'templates')},
  ui: {announcement: 'UI 模拟验收：全部为合成数据，使用记录已关闭。包含 20 轮次、单点尖峰、缺失值、警告和无效文件。'},
};
await fs.writeFile(path.join(dest, 'local-config.yaml'), JSON.stringify(config, null, 2));
await fs.writeFile(path.join(dest, 'expected.json'), JSON.stringify({synthetic: true, scanned: 8, mergeable: 5, rows: {GANTER: 2700, FAKT: 600, T09: 2001}, total: 5301}, null, 2));
await fs.copyFile(path.join(root, 'scripts', 'start_ui_demo.ps1'), path.join(dest, 'start_ui_demo.ps1'));
console.log(`Demo generated: ${dest}`);

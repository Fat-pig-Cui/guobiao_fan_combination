// Read-only adapter: execute only the supplied reference's scoring functions.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const [core, casesPath] = process.argv.slice(2);
if (!core || !casesPath) throw new Error('usage: node reference_runner.mjs CORE CASES_JSON');
const read = name => fs.readFileSync(path.join(core, name), 'utf8');
const source = read('calcFan.js'), exported = read('exportedUtils.js');
const constants = read('constants.js');
function arrow(src, name) {
  const begin = src.indexOf(`export const ${name} =`), end = src.indexOf('\n};', begin);
  if (begin < 0 || end < 0) throw new Error(`Cannot extract ${name}`);
  return src.slice(begin, end + 3).replace('export const', 'const');
}
const moduleText = constants.slice(0, constants.indexOf('export const DIYFans')).replace('export class Constants', 'class Constants') + '\n' +
  ['judgeTile','calcHupai','calcTingpai'].map(n => arrow(exported,n)).join('\n') + '\n' +
  arrow(read('utils.js'),'calcSudianGuobiao') + '\n' + arrow(source,'calcFanGuobiao') + '\n' +
  source.slice(source.indexOf('const dfs =')) + '\nglobalThis.score = calcFanGuobiao;';
const split = s => Array.isArray(s) ? s.map(t => `${t%9+1}${'mpsz'[Math.floor(t/9)]}`) :
  [...s.replace(/\s/g,'').matchAll(/([1-9]+)([mpsz])/g)].flatMap(m => [...m[1]].map(d => d+m[2]));
const output = [];
for (const input of JSON.parse(fs.readFileSync(casesPath,'utf8'))) {
  const seat = Number((input.seat_wind ?? '2z')[0])-1, ctx = input.context ?? {};
  const player_tiles = [[],[],[],[]]; player_tiles[seat] = [...split(input.hand), ...split(input.win)];
  const fulu = [[],[],[],[]];
  fulu[seat] = (input.melds ?? []).map(m => ({type:{chi:0,pon:1,minkan:2,kakan:2,ankan:3}[m.kind],
    tile:split(m.tiles), ...(m.kind!=='ankan' ? {from:(seat+1)%4} : {})}));
  const paihe = Array.from({length:4}, () => ({tiles:[]}));
  for (const meld of fulu[seat]) {
    if (meld.from !== undefined) paihe[meld.from].tiles.push(meld.tile[meld.tile.length-1]);
  }
  paihe[(seat+1)%4].tiles.push(...split(ctx.visible_before_win ?? ''));
  if (input.method!=='tsumo') paihe[(seat+1)%4].tiles.push(...split(input.win));
  const liqi_info = Array.from({length:4}, () => ({liqi:0,yifa:0}));
  if (ctx.opening==='heaven') liqi_info[seat].yifa=1;
  if (ctx.opening==='earth') liqi_info.forEach((x,i) => {if(i!==0)x.yifa=1;});
  if (ctx.opening==='human') liqi_info[seat].yifa=1;
  const simple = t => t.slice(0,2);
  const sandbox = {player_tiles,fulu,paihe,liqi_info,
    base_info:{player_cnt:4,ju:0,chang:Number((input.round_wind ?? '1z')[0])-1,lst_draw_type:ctx.draw_source==='kan_replacement'?0:1},
    paishan:Array(ctx.wall_empty?0:60).fill('1m'),
    simplify:simple, isEqualTile:(a,b)=>simple(a)===simple(b), separate:split,
    cmp:(a,b)=>'mpsz'.indexOf(a[1])-'mpsz'.indexOf(b[1]) || Number(a[0])-Number(b[0]),
    errRoundInfo:()=>'', scale_points:()=>1, is_guobiao:()=>true,
    is_chuanma:()=>false,is_wanxiangxiuluo:()=>false,is_yifanjieguyi:()=>false,
    isHuazhu:()=>false,no_lianfengsifu:()=>false,
    getLstAction:()=>({name:ctx.draw_source==='kakan_ron'?'RecordAnGangAddGang':input.method==='tsumo'?'RecordDealTile':'RecordDiscardTile'}),
    seat,tsumo:input.method==='tsumo'};
  vm.createContext(sandbox);
  vm.runInContext(moduleText,sandbox,{timeout:5000});
  try {output.push({result:vm.runInContext('score(seat,tsumo)',sandbox,{timeout:5000})});}
  catch(error) {output.push({error:String(error)});}
}
process.stdout.write(JSON.stringify(output));

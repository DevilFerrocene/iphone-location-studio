const $ = id => document.getElementById(id);
const map = L.map('map', {doubleClickZoom:false}).setView([39.9042,116.4074], 16);
const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19, attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
tiles.on('tileerror',()=>{$('message').textContent='地图瓦片加载失败，请检查网络；仍可通过经纬度跳转。'});
let points=[], segments=[], markers=[], preview=null, busy=false, status={mode:'idle',connected:false}, revision=0, routeSeed=0;
const planned=L.polyline([], {color:'#8d9db1',weight:3,dashArray:'5 7'}).addTo(map);
const simulated=L.polyline([], {color:'#285ccd',weight:3}).addTo(map);
const cursor=L.circleMarker([39.9042,116.4074], {radius:8,color:'white',weight:3,fillColor:'#208174',fillOpacity:1});
const active=()=>['playing','paused'].includes(status.mode);
function payload(){return {points,segments,speed:Number($('speed').value),interval:Number($('interval').value),noise:Number($('noise').value),bend:Number($('bend').value),speed_min:Number($('speed_min').value),speed_max:Number($('speed_max').value),seed:routeSeed};}
const routeKeys=['speed','interval','noise','bend','speed_min','speed_max'];
function routeDocument(data){
 if(!data||data.format!=='iphone-location-studio-route'||data.version!==1)throw Error('不支持的轨迹文件格式或版本');
 const route=data.route;
 if(!route||!Array.isArray(route.points)||route.points.length<2)throw Error('轨迹至少需要 2 个路线点');
 for(const point of route.points){
  if(!Array.isArray(point)||point.length!==2||!point.every(Number.isFinite)||Math.abs(point[0])>85||Math.abs(point[1])>180)throw Error('轨迹坐标格式错误或超出地图范围');
 }
 if(!Array.isArray(route.segments)||route.segments.length!==route.points.length-1)throw Error('轨迹分段数量与路线点不匹配');
 const settings=(value,label)=>{
  if(!value||typeof value!=='object'||Array.isArray(value)||!routeKeys.every(key=>Number.isFinite(value[key])))throw Error(label+'必须包含完整的数字参数');
  const {speed,interval,noise,speed_min:low,speed_max:high}=value;
  if(speed<=0||interval<=0||noise<0)throw Error(label+'：速度和间隔必须大于零，噪声必须非负');
  if((low!==0||high!==0)&&!(0<low&&low<=high))throw Error(label+'：随机速度需满足 0 < 最低 ≤ 最高；均为 0 使用固定速度');
  return Object.fromEntries(routeKeys.map(key=>[key,value[key]]));
 };
 const globals=settings(route,'全局参数');
 const overrides=route.segments.map((value,i)=>value===null?null:settings(value,`第 ${i+1} 段`));
 return {points:route.points,segments:overrides,...globals};
}
async function api(action,data={}){
 const r=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':window.LOCAL_TOKEN},body:JSON.stringify(data)});
 const result=await r.json(); if(!r.ok) throw Error(result.detail||'操作失败'); return result;
}
function dirty(){revision++;preview=null;simulated.setLatLngs([]);$('distance').textContent='—';$('duration').textContent='—';document.querySelectorAll('.segment-stats').forEach(el=>el.textContent='');}
function segmentEditors(){
 segments.length=Math.max(0,points.length-1);
 for(let i=0;i<segments.length;i++)if(segments[i]===undefined)segments[i]=null;
 $('segments').replaceChildren();
 segments.forEach((settings,i)=>{
  const row=document.createElement('details');row.className='segment-row';row.open=settings!==null;
  const summary=document.createElement('summary');summary.textContent=`第 ${i+1} 段 · 点 ${i+1} → ${i+2}`;row.append(summary);
  const label=document.createElement('label');label.className='inherit';
  const inherit=document.createElement('input');inherit.type='checkbox';inherit.checked=settings===null;
  label.append(inherit,document.createTextNode('沿用全局参数'));row.append(label);
  const fields=document.createElement('div');fields.className='segment-fields';
  const inputs={};
  for(const [key,title] of [['speed','速度 m/s'],['interval','间隔 秒'],['noise','噪声 米'],['bend','弯曲量 米'],['speed_min','最低 m/s'],['speed_max','最高 m/s']]){
   const wrap=document.createElement('label');wrap.textContent=title;
   const input=document.createElement('input');input.type='number';input.step='any';if(key!=='bend')input.min='0';
   input.value=settings?settings[key]:$(key).value;input.disabled=inherit.checked||active()||busy;
   input.setAttribute('aria-label',`第 ${i+1} 段 ${title}`);inputs[key]=input;
   input.oninput=()=>{segments[i][key]=Number(input.value);dirty();};wrap.append(input);fields.append(wrap);
  }
  inherit.disabled=active()||busy;
  inherit.onchange=()=>{segments[i]=inherit.checked?null:Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,Number(v.value)]));dirty();segmentEditors();};
  row.append(fields);const info=document.createElement('div');info.className='segment-stats';info.id=`segment-stats-${i}`;row.append(info);$('segments').append(row);
 });
}
function redraw(){
 markers.forEach(m=>map.removeLayer(m));markers=[];
 points.forEach((p,i)=>{const m=L.marker(p,{draggable:!active(),icon:L.divIcon({className:'waypoint',html:String(i+1),iconSize:[22,22],iconAnchor:[11,11]})}).addTo(map);
 m.on('dragend',()=>{const p=m.getLatLng();points[i]=[p.lat,p.lng];dirty();planned.setLatLngs(points);});markers.push(m);});
 segmentEditors();planned.setLatLngs(points);$('hint').textContent=points.length?`${points.length} 个途经点 · 点击地图继续添加`:'点击地图，选择起点';
}
map.on('click',e=>{if(active())return; points.push([e.latlng.lat,e.latlng.lng]);dirty();redraw();});
const modes={idle:'等待规划路线',playing:'正在发送位置',paused:'已暂停 · 保留当前位置',stopped:'已停止 · 保留最后位置',completed:'轨迹发送完成',cleared:'已清除模拟位置',error:'发送中断'};
function render(){
 $('device').innerHTML=`<i class="dot ${status.connected?'on':''}"></i>${status.connected?'iPhone 已连接 · iOS '+status.device:'尚未连接'}`;
 $('connect').disabled=busy||status.connected;
 $('start').disabled=busy||active()||!status.connected||points.length<2;
 $('pause').disabled=busy||!active();$('pause').textContent=status.mode==='paused'?'继续':'暂停';
 $('stop').disabled=busy||!active();$('clear').disabled=busy;
 ['reset','undo','speed','noise','interval','bend','speed_min','speed_max','preview'].forEach(id=>$(id).disabled=busy||active());
 $('save-route').disabled=busy||active()||points.length<2;
 $('import-route').disabled=busy||active();
 $('mode').textContent=modes[status.mode]||status.mode;
 $('progressText').textContent=`${status.sent||0} / ${status.total||0} 个点已发送`;
 $('progress').max=status.total||1;$('progress').value=status.sent||0;
 if(status.position){cursor.setLatLng(status.position).addTo(map);$('position').textContent=status.position.map(n=>n.toFixed(6)).join(', ');}
 else {map.removeLayer(cursor);$('position').textContent=status.mode==='cleared'?'手机重新使用真实定位':'尚未发送坐标';}
 if(status.error)$('message').textContent=status.error;
 markers.forEach(m=>active()?m.dragging.disable():m.dragging.enable());
 $('segments').querySelectorAll('input').forEach(input=>{const row=input.closest('details');input.disabled=busy||active()||(input.type!=='checkbox'&&row.querySelector('input[type=checkbox]').checked);});
}
async function run(fn){busy=true;$('message').textContent='';render();try{await fn();}catch(e){$('message').textContent=e.message;}finally{busy=false;render();}}
async function makePreview(){routeSeed=crypto.getRandomValues(new Uint32Array(1))[0];const rev=revision;const result=await api('preview',payload());if(rev!==revision)throw Error('路线已变化，请重新生成');preview=result;preview.segments.forEach((s,i)=>{const el=$(`segment-stats-${i}`);if(el)el.textContent=`${s.distance.toFixed(1)} 米 · ${s.duration.toFixed(1)} 秒`;});simulated.setLatLngs(preview.samples.map(p=>[p.lat,p.lon]));$('distance').textContent=preview.distance<1000?preview.distance.toFixed(0)+' m':(preview.distance/1000).toFixed(2)+' km';$('duration').textContent=preview.duration<60?Math.ceil(preview.duration)+' 秒':(preview.duration/60).toFixed(1)+' 分钟';}
$('jump').onclick=()=>{const a=Number($('lat').value),b=Number($('lon').value);if(!Number.isFinite(a)||!Number.isFinite(b)||Math.abs(a)>85||Math.abs(b)>180){$('message').textContent='请输入有效的纬度和经度';return;}map.setView([a,b],16);};
$('undo').onclick=()=>{points.pop();dirty();redraw();render();};
$('reset').onclick=()=>{points=[];dirty();redraw();render();};
$('fit').onclick=()=>{if(points.length)map.fitBounds(L.latLngBounds(points).pad(.2),{maxZoom:18});};
['speed','interval','noise','bend','speed_min','speed_max'].forEach(id=>$(id).oninput=()=>{dirty();segmentEditors();});
$('save-route').onclick=()=>run(async()=>{
 const data={format:'iphone-location-studio-route',version:1,route:payload()};
 data.route=routeDocument(data);
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)+'\n'],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download='行迹路线.json';document.body.append(link);
 try{link.click();}finally{link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 $('message').textContent='轨迹已导出，可通过“导入轨迹”重复使用。';
});
$('import-route').onclick=()=>{if(!busy&&!active())$('route-file').click();};
$('route-file').onchange=()=>{
 const file=$('route-file').files[0];$('route-file').value='';
 if(!file||busy||active())return;
 run(async()=>{
  const rev=revision;
  let data;
  try{data=JSON.parse(await file.text());}catch{throw Error('无法读取轨迹文件，请选择有效的 JSON 文件');}
  const route=routeDocument(data);
  if(active()||revision!==rev)throw Error('路线状态已变化，请重新导入');
  points=route.points;segments=route.segments;
  routeKeys.forEach(key=>$(key).value=route[key]);routeSeed=0;
  dirty();redraw();$('fit').click();
  $('message').textContent=`已导入 ${points.length} 个途经点，请生成轨迹预览。`;
 });
};
$('preview').onclick=()=>run(makePreview);
$('connect').onclick=()=>run(async()=>{status=await api('connect');});
$('start').onclick=()=>run(async()=>{if(!preview)await makePreview();status=await api('start',payload());});
$('pause').onclick=()=>run(async()=>{status=await api(status.mode==='paused'?'resume':'pause');});
$('stop').onclick=()=>run(async()=>{status=await api('stop');});
$('clear').onclick=()=>run(async()=>{status=await api('clear');});
async function poll(){try{const r=await fetch('/api/status');if(!r.ok)throw Error();status=await r.json();render();}catch{$('message').textContent='本地程序已断开，请重新启动行迹。';}finally{setTimeout(poll,700);}}
map.on('click',render);render();poll();

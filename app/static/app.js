'use strict';

const $ = (selector) => document.querySelector(selector);
const state = {id:null, summary:null, result:null, busy:'', revision:0, tab:'melody', playing:false, played:0,
  settings:{printer:'snapmaker_u1',speed:'medium',tempo:'medium',voice:'duet',startup:'xy_home',sound_mode:'step_cadence',foc_axis:'alternate',foc_x_min:12,foc_x_max:16,foc_y_min:.125,foc_y_max:.25}, controller:null,
  catalog:{profiles:[],library:[]},runtime:{mode:'local'},catalogReady:false,librarySong:null,profileLoading:false,unlockedMusicSettings:null};
const speedInfo = {slow:{cap:100,description:'Bir oktav daha kalın, daha sakin hareket.'},
  medium:{cap:180,description:'Özgün oktavlar, dengeli hareket.'},fast:{cap:360,description:'Bir oktav daha tiz, daha canlı hareket.'}};
const tempoInfo = {slow:'Yavaşlatılmış · %75',medium:'Orijinal · %100',fast:'Hızlandırılmış · %125'};
const canvas = $('#preview-canvas');
const context = canvas.getContext('2d');
const playIcon = $('#play-button').innerHTML;
let audioContext = null, oscillators = [], animationFrame = null, toastTimer = null;
const number = (n,digits=0) => new Intl.NumberFormat('tr-TR',{maximumFractionDigits:digits,minimumFractionDigits:digits}).format(n);
const duration = (seconds) => {const n=Math.round(seconds);return `${String(Math.floor(n/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;};
const noteName = (n) => ['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'][n%12]+(Math.floor(n/12)-1);

async function request(url, options={}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'İşlem tamamlanamadı. Yeniden dene.');
  return data;
}
const post = (url, payload, signal) => request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal});
function showError(message) {$('#error-message').textContent=message;$('#error-message').hidden=!message;}
function toast(message) {clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>{$('#toast').hidden=true;},3500);}

function selectedPrinter(){return state.catalog.profiles.find(p=>p.id===state.settings.printer)||{id:'snapmaker_u1',name:'Snapmaker U1',kinematics:'corexy'};}
function isNativePrinter(profile=selectedPrinter()){return profile.music_mode==='bambu_native'||profile.backend==='bambu_m1006';}
function isKePrinter(profile=selectedPrinter()){return profile.id==='creality_ender3_v3_ke';}
function isK2Printer(profile=selectedPrinter()){return ['creality_k2','creality_k2_pro','creality_k2_plus'].includes(profile.id);}
function isXOnlyPrinter(profile=selectedPrinter()){return profile.music_axes==='x';}
function isFocBand(profile=selectedPrinter()){return profile.foc_band_available===true&&state.settings.sound_mode==='foc_band';}
function restoreFocBands(profile){
  const bands=state.catalog.focBands||{x:[12,16],y:[.125,.25]};
  for(const axis of ['x']){state.settings[`foc_${axis}_min`]=bands[axis][0];state.settings[`foc_${axis}_max`]=bands[axis][1];}
  try{const saved=JSON.parse(localStorage.getItem('klippermidi.foc.'+profile.id));for(const key of ['foc_x_min','foc_x_max'])if(Number.isFinite(saved?.[key]))state.settings[key]=saved[key];}catch{}
}
function saveFocBands(){
  if(!isFocBand())return;
  try{localStorage.setItem('klippermidi.foc.'+state.settings.printer,JSON.stringify(Object.fromEntries(['foc_x_min','foc_x_max'].map(key=>[key,state.settings[key]]))));}catch{}
}
function applyMusicSettingsLock(profile=selectedPrinter()){
  const fixed=profile.music_settings_lock;
  if(fixed){state.settings.speed=fixed.speed;state.settings.tempo=fixed.tempo;}
}
function searchText(value){return String(value).toLocaleLowerCase('tr-TR').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/ı/g,'i').replace(/[^a-z0-9]/g,'');}
function externalLink(url,label,className=''){
  const link=document.createElement('a');
  try{const parsed=new URL(url);if(!['https:','http:'].includes(parsed.protocol))return null;link.href=parsed.href;}catch{return null;}
  link.textContent=label;link.target='_blank';link.rel='noopener noreferrer';link.className=className;return link;
}
function printerVolume(profile){const v=profile.build_volume_mm;return Array.isArray(v)?v.slice(0,3).join(' × '):v&&typeof v==='object'?[v.x,v.y,v.z].filter(Number.isFinite).join(' × '):'';}
function musicBounds(){
  const p=state.result?.printer||state.summary?.printer,b=p?.music_bounds;
  if(b?.x?.length===2&&b?.y?.length===2)return b;
  return {x:[55,215],y:[55,215]};
}
function renderPrinter(){
  const p=selectedPrinter(),u1=p.id==='snapmaker_u1',ke=isKePrinter(p),keAuto=ke&&state.settings.startup==='ke_auto_home_slow_z',k2=isK2Printer(p),xOnly=isXOnlyPrinter(p),native=isNativePrinter(p),foc=isFocBand(p),bambu=p.firmware_family==='bambu',locked=['upload','generate'].includes(state.busy);
  $('#printer-name').textContent=p.name;
  const volume=printerVolume(p);$('#printer-detail').textContent=[bambu?'BAMBU LAB':p.kinematics?.toUpperCase(),volume?volume+' mm':''].filter(Boolean).join(' · ')||'Profil bilgileri yükleniyor…';
  $('#printer-status').textContent=!state.catalogReady?'Profil yükleniyor':foc?'FOC · Yalnızca X':p.music_settings_lock?'FOC step-servo · Yavaş / Yavaş':xOnly?'Yalnızca X · Hız/tempo serbest':p.axis_priority==='y'?'Y öncelikli · Hız/tempo serbest':native?'Yerleşik müzik · firmware’e bağlı':p.id.startsWith('custom_')?'İçe aktarılan konfigürasyon':u1?'Varsayılan profil':'Kaynak konfigürasyonu';
  $('#printer-button').disabled=locked||!state.catalogReady;
  const link=externalLink(p.source?.url,'');$('#printer-source').hidden=!link;if(link)$('#printer-source').href=link.href;
  $('#startup-select option[value="xy_home"]').disabled=!u1;
  $('#startup-select option[value="ke_auto_home_slow_z"]').hidden=!ke;
  $('#startup-select option[value="ke_auto_home_slow_z"]').disabled=!ke;
  $('#startup-select option[value="k2_xy_home"]').hidden=!k2;
  $('#startup-select option[value="k2_xy_home"]').disabled=!k2;
  $('#startup-select option[value="prepared_no_z"]').disabled=native||k2;
  $('#startup-select option[value="prepared_no_z"]').hidden=k2;
  $('#startup-select option[value="native_sound"]').hidden=!native;
  $('#startup-select').disabled=locked||!(u1||ke);
  $('#startup-description').textContent=native?'Yerleşik X/Y ses kanalları kullanılır. Konumlandırma ve home komutu üretilmez; Z ses kanalı sessiz tutulur.':keAuto?'Home normal hızında çalışır; yalnızca ardından Z20 mm’ye yükselme 3 mm/sn ile yapılır. Genel hız sınırı düşürülmez; dosya sonunda normal limitler geri yüklenir.':k2?'Dosya G28 X Y ile otomatik home alır. Öncesinde ve müzik sonunda normal makine limitleri geri yüklenir. Tabla boş olmalı; homing sırasında stok Z güvenlik davranışı geçerlidir.':u1&&state.settings.startup==='xy_home'?'Otomatik başlangıç standart G28 X Y kullanır; homing sırasında yazıcının normal Z davranışı geçerlidir. En az 20 mm fiziksel nozul–tabla boşluğu gerekir.':'Bu başlangıç seçeneği otomatik home kullanmaz. Tüm eksenler önceden home alınmış, motorlar etkin ve nozul–tabla arası en az 20 mm olmalı.';
  $('#prepared-note').hidden=native||keAuto||k2||(u1&&state.settings.startup!=='prepared_no_z');
  $('#ke-slow-z-setup').hidden=!keAuto;
  $('#channels-label').textContent=native?'X/Y SES KANALLARI':xOnly?'YALNIZCA X HAREKETİ':'XY MOTORLARI';
  $('#voice-select option[value="x_melody"]').hidden=!xOnly||foc;
  for(const value of ['duet','melody'])$(`#voice-select option[value="${value}"]`).hidden=xOnly;
  $('#voice-select option[value="foc_melody"]').hidden=!foc;
  $('#bass-legend').hidden=xOnly||foc;
  $('#sound-mode-row').hidden=!p.foc_band_available;
  $('#sound-mode').value=state.settings.sound_mode;$('#sound-mode').disabled=locked;
  $('#foc-settings').hidden=!foc;$('#foc-axis').value='x';$('#foc-axis').disabled=true;
  $('#foc-scan-link').href='/api/foc-y-scan/'+encodeURIComponent(p.id);
  $('#foc-scan-link').hidden=xOnly;
  for(const key of ['foc_x_min','foc_x_max']){const input=document.querySelector(`[data-foc-setting="${key}"]`);if(document.activeElement!==input)input.value=state.settings[key];input.disabled=locked;}
  $('#motion-tab').textContent=xOnly?'X hareketi':'XY hareketi';
  $('#z-note-title').textContent=native?'Z ses kanalı kapalı.':xOnly?'Y ve Z, müzikte sabit.':'Z, müzikte hareket etmez.';
  $('#z-note-description').textContent=native?'Konumlandırma, home, ısıtma ve filament sürme komutu yok. Dosyayı aktarırken seçili modelin profil notlarını izle.':keAuto?'Home normal hızında çalışır; yalnızca sonraki Z20 mm yükseltmesi 3 mm/sn’dir. Müzikte Z sabittir. Tabla boş olmalı.':k2?'Dosyayı doğrudan başlatabilirsin; önce otomatik X/Y home yapılır. Tabla boş olmalı. Homing sırasında stok Z güvenlik davranışı geçerlidir; müzikte Z sabittir.':'Başlatmadan önce tabla boş, yazıcı soğuk ve nozul–tabla arası en az 20 mm olmalı. Dosya bu boşluğu oluşturmaz.';
  $('#workflow-footer-note').textContent=keAuto?'Isıtma/filament komutu üretilmez; stok homing davranışı firmware’e bağlı':'Isıtma ve filament sürme yok';
  $('#export-printer').textContent=p.name.toLocaleUpperCase('tr-TR')+' İÇİN G-CODE';
}
function renderPrinterList(){
  const q=searchText($('#printer-search').value.trim()),list=$('#printer-list');list.replaceChildren();
  const profiles=state.catalog.profiles.filter(p=>searchText(p.name+' '+p.manufacturer).includes(q));
  if(!profiles.length){const empty=document.createElement('p');empty.className='catalog-empty';empty.textContent=state.catalogReady?'Bu aramaya uygun yazıcı bulunamadı.':'Profiller yükleniyor…';list.append(empty);return;}
  profiles.forEach(p=>{
    const row=document.createElement('div');row.className='catalog-row printer-row';row.classList.toggle('selected',p.id===state.settings.printer);row.classList.toggle('unavailable',p.selectable!==true);
    const content=document.createElement('div');content.className='catalog-copy';
    const title=document.createElement('strong');title.textContent=p.name;
    const detail=document.createElement('span');detail.className='catalog-detail';const volume=printerVolume(p);detail.textContent=[p.firmware_family==='bambu'?'BAMBU LAB · Yerleşik müzik':p.kinematics?.toUpperCase(),volume?volume+' mm':null].filter(Boolean).join(' · ');
    const status=document.createElement('span');status.className='catalog-status';status.textContent=p.selectable===true?(p.id===state.settings.printer?'Seçili profil':isNativePrinter(p)?'Müzik şablonu doğrulandı · Fiziksel test yok':p.id==='snapmaker_u1'?'Varsayılan profil':'Konfigürasyon profili'):p.status==='unsupported_bambu_sound'?'Yerleşik müzik desteği doğrulanmadı · Seçilemez':p.status==='unsupported_kinematics'?'Bu kinematik desteklenmiyor · Seçilemez':'Konfigürasyon gerekli · Seçilemez';
    if(p.music_settings_lock)status.textContent+=' · FOC step-servo · Yavaş / Yavaş';
    else if(isXOnlyPrinter(p))status.textContent+=' · Yalnızca X · Ayarlar serbest';
    else if(p.axis_priority==='y')status.textContent+=' · Y hızlı / X yavaş · Ayarlar serbest';
    content.append(title,detail,status);
    const notes=Array.isArray(p.notes)?p.notes.join(' '):p.notes;if(notes){const note=document.createElement('p');note.className='catalog-note';note.textContent=notes;if(p.selectable===true){const details=document.createElement('details');details.className='profile-notes';const summary=document.createElement('summary');summary.textContent='Profil notları';details.append(summary,note);content.append(details);}else content.append(note);}
    const source=externalLink(p.source?.url,'Kaynak ↗','catalog-source');if(source)content.append(source);
    const choose=document.createElement('button');choose.className='catalog-choose';choose.textContent=p.id===state.settings.printer?'Seçili':'Seç';choose.disabled=p.selectable!==true||p.id===state.settings.printer;choose.addEventListener('click',()=>selectPrinter(p.id));
    row.append(content,choose);list.append(row);
  });
}
function renderLibrary(){
  const q=searchText($('#library-search').value.trim()),list=$('#library-list'),filter=$('#library-category');list.replaceChildren();
  const category=s=>s.category||(s.id==='mario'?'Oyun':'Klasik');
  const categories=[...new Set(state.catalog.library.map(category))].sort((a,b)=>a.localeCompare(b,'tr'));
  if(filter.dataset.categories!==JSON.stringify(categories)){
    const chosen=filter.value;filter.replaceChildren(new Option('Tüm türler',''));
    categories.forEach(name=>filter.append(new Option(name,name)));filter.value=categories.includes(chosen)?chosen:'';filter.dataset.categories=JSON.stringify(categories);
  }
  const songs=state.catalog.library.filter(s=>(!filter.value||category(s)===filter.value)&&searchText([s.title,s.artist,s.composer,category(s)].filter(Boolean).join(' ')).includes(q));
  songs.sort((a,b)=>(a.id==='mario'?-2:a.artist?-1:0)-(b.id==='mario'?-2:b.artist?-1:0));
  $('#library-count').textContent=`${number(songs.length)} / ${number(state.catalog.library.length)} eser`;
  if(!songs.length){const empty=document.createElement('p');empty.className='catalog-empty';empty.textContent=state.catalogReady?'Bu aramaya uygun eser bulunamadı.':'Kitaplık yükleniyor…';list.append(empty);return;}
  songs.forEach(song=>{
    const row=document.createElement('div');row.className='catalog-row song-row';const icon=document.createElement('span');icon.className='song-icon';icon.textContent='♪';icon.setAttribute('aria-hidden','true');
    const content=document.createElement('div');content.className='catalog-copy';const title=document.createElement('strong');title.textContent=song.title;const composer=document.createElement('span');composer.className='catalog-detail';composer.textContent=[song.artist||song.composer||'MIDI arşivi',category(song),Number.isFinite(song.duration_seconds)?duration(song.duration_seconds):null].filter(Boolean).join(' · ');
    const licensing=document.createElement('div');licensing.className='song-licensing';const license=document.createElement('span');license.className='license-tag';license.textContent=typeof song.license==='string'?song.license:(song.license?.name||'Kaynak lisansına bak');license.title=[song.attribution,song.notes].filter(Boolean).join(' · ');licensing.append(license);const source=externalLink(song.source_url,'Kaynak ↗','catalog-source');if(source)licensing.append(source);content.append(title,composer,licensing);
    let notes=Array.isArray(song.notes)?song.notes.join(' '):song.notes;
    if(song.origin==='local archive import')notes=notes?.split('Özgün MIDI')[0].trim();
    if(notes){const note=document.createElement('p');note.className='catalog-note';note.textContent=notes;content.append(note);}
    const choose=document.createElement('button');choose.className='catalog-choose';choose.textContent='Yükle';choose.addEventListener('click',()=>{$('#library-dialog').close();loadSong(null,song.id);});row.append(icon,content,choose);list.append(row);
  });
}
async function loadCatalog(){
  try{const data=await request('/api/catalog');state.catalog={profiles:data.profiles||[],library:data.library||[],focBands:data.foc_reference_bands};state.runtime=data.runtime||{mode:'local'};state.catalogReady=true;render();renderPrinterList();renderLibrary();}
  catch{showError('Yazıcı ve MIDI kitaplığı yüklenemedi. Uygulama sunucusunu kontrol edip sayfayı yenile.');}
}
function selectPrinter(id){
  const profile=state.catalog.profiles.find(p=>p.id===id);if(profile?.selectable!==true)return;
  const previousFixed=!!selectedPrinter().music_settings_lock;
  if(!previousFixed&&profile.music_settings_lock)state.unlockedMusicSettings={speed:state.settings.speed,tempo:state.settings.tempo};
  if(previousFixed&&!profile.music_settings_lock&&state.unlockedMusicSettings){Object.assign(state.settings,state.unlockedMusicSettings);state.unlockedMusicSettings=null;}
  const old=state.settings.printer;state.settings.printer=id;
  state.settings.sound_mode=profile.foc_band_available?'foc_band':'step_cadence';
  if(profile.foc_band_available)restoreFocBands(profile);
  if(isFocBand(profile)){state.settings.voice='foc_melody';state.settings.foc_axis='x';}
  else if(isXOnlyPrinter(profile))state.settings.voice='x_melody';
  else if(['foc_melody','x_melody'].includes(state.settings.voice))state.settings.voice='duet';
  if(isKePrinter(profile))state.settings.speed='fast';
  if(profile.default_speed)state.settings.speed=profile.default_speed;
  if(profile.default_tempo)state.settings.tempo=profile.default_tempo;
  if(profile.tempo_follows_speed)state.settings.tempo=state.settings.speed;
  applyMusicSettingsLock(profile);
  if(isNativePrinter(profile)){state.settings.startup='native_sound';state.tab='melody';}else if(isKePrinter(profile))state.settings.startup='ke_auto_home_slow_z';else if(isK2Printer(profile))state.settings.startup='k2_xy_home';else if(id!=='snapmaker_u1')state.settings.startup='prepared_no_z';else if(old!=='snapmaker_u1')state.settings.startup='xy_home';
  $('#printer-dialog').close();renderPrinterList();updatePreview();
}
async function importProfile(file){
  if(!file||state.profileLoading)return;if(!/\.cfg$/i.test(file.name))return showError('Lütfen printer.cfg biçiminde bir dosya seç.');
  state.profileLoading=true;$('#profile-import-button').disabled=true;$('#profile-import-status').textContent='Konfigürasyon okunuyor…';
  try{const data=await post('/api/profile',{filename:file.name,text:await file.text()});const profile=data.profile;if(!profile?.id)throw new Error('Yazıcı profili oluşturulamadı.');state.catalog.profiles=state.catalog.profiles.filter(p=>p.id!==profile.id);state.catalog.profiles.push(profile);$('#profile-import-status').textContent='';selectPrinter(profile.id);toast('Yazıcı konfigürasyonu içe aktarıldı.');}
  catch(error){$('#profile-import-status').textContent=error.message;}
  finally{state.profileLoading=false;$('#profile-import-button').disabled=false;}
}

function render() {
  applyMusicSettingsLock();
  const online=state.runtime.mode==='public';
  $('#runtime-label').textContent=online?'Çevrimiçi çalışıyor':'Bu bilgisayarda çalışıyor';
  $('#privacy-description').textContent=online?state.runtime.privacy:'MIDI dosyan bu bilgisayarda işlenir.';
  $('#deployment-label').textContent=online?'Çevrimiçi dönüştürücü':'Yerel çalışma';
  if(online||state.runtime.mode==='desktop'){document.title=state.runtime.name;$('#brand-name').textContent=state.runtime.name;$('.brand').setAttribute('aria-label',state.runtime.name+' ana sayfa');$('#demo-button').textContent=state.runtime.demo_label;}
  if(state.runtime.mode==='desktop'){$('#deployment-label').textContent='Windows · '+state.runtime.version;$('#build-label').textContent='WINDOWS';$('#build-version').textContent=state.runtime.version;$('#footer-brand').textContent='3DMidi';}
  const s=state.summary,native=isNativePrinter(),loading=!!state.busy,locked=['upload','generate'].includes(state.busy);
  const fixed=selectedPrinter().music_settings_lock;
  const foc=isFocBand(),xOnly=isXOnlyPrinter(),yPriority=!foc&&selectedPrinter().axis_priority==='y';
  document.querySelectorAll('[data-setting]').forEach(button=>{
    button.setAttribute('aria-pressed',String(state.settings[button.dataset.setting]===button.dataset.value));button.disabled=locked||!!fixed;
    button.title=fixed?'FOC step-servo profili: Yavaş / Yavaş olarak sabit.':'';
    if(button.dataset.setting==='speed')button.textContent=(native?{slow:'Kalın',medium:'Orijinal',fast:'İnce'}:{slow:'Yavaş',medium:'Orta',fast:'Hızlı'})[button.dataset.value];
  });
  $('#voice-select').value=state.settings.voice;$('#startup-select').value=state.settings.startup;
  $('#voice-select').disabled=locked||xOnly||foc;
  $('#demo-button').disabled=locked;$('#drop-zone').disabled=locked;$('#remove-file').disabled=locked;
  $('#library-button').disabled=locked||!state.catalogReady;
  renderPrinter();
  const samePrinter=s?.settings?.printer===state.settings.printer,cap=samePrinter?s?.speed_caps?.[state.settings.speed]:null;
  $('#speed-label').textContent=native?'Ses aralığı':'Hareket hızı';
  $('#speed-cap').textContent=native?'Yerleşik motor müziği':`${number(cap??Math.min(speedInfo[state.settings.speed].cap,selectedPrinter().music_max_velocity_mm_s||360))} mm/sn’ye kadar`;
  if(foc)$('#speed-cap').textContent='X ses aralığı';
  const transpose=samePrinter&&s?.valid&&Number.isFinite(s.transpose)?s.transpose:{slow:-12,medium:0,fast:12}[state.settings.speed];
  const shiftLabel=transpose%12===0?`${number(Math.abs(transpose)/12)} oktav`:`${number(Math.abs(transpose))} yarım ses`;
  $('#speed-description').textContent=(native||(samePrinter&&s?.valid))?(transpose===0?'Melodi özgün ses aralığında çalar.':`Melodi ${shiftLabel} daha ${transpose>0?'tiz':'kalın'} çalar.`):speedInfo[state.settings.speed].description;
  if(yPriority)$('#speed-description').textContent+=' X daha yavaş, Y daha hızlı hareket eder.';
  if(foc)$('#speed-description').textContent='Yavaş: aralığın alt bölümü · Orta: tam aralık · Hızlı: üst bölümü. Melodi çizgisi bu ses aralıklarına uyarlanır.';
  $('#tempo-value').textContent=tempoInfo[state.settings.tempo];
  $('#tempo-description').textContent=selectedPrinter().tempo_follows_speed?'U1’de hız seçimi tempoyu aynı seviyeye getirir. Tempoyu ayrıca değiştirebilirsin.':'Tempo ritmi değiştirir; hareket hızı seçimini korur.';
  $('#music-settings-lock-note').hidden=!fixed;
  if(fixed)$('#tempo-description').textContent='Bu FOC step-servo profilinde tempo Yavaş (%75) olarak sabittir.';
  $('#drop-zone').classList.toggle('loaded',!!s);
  $('#file-name').textContent=s?s.filename:state.busy==='upload'?'MIDI okunuyor…':'MIDI dosyanı buraya bırak';
  $('#file-meta').textContent=s?`${number(s.bytes/1024,1)} KB · ${number(s.tracks)} MIDI izi`:state.busy==='upload'?'Notalar ve tempo bilgisi alınıyor':'veya dosya seçmek için tıkla';
  $('#file-type').textContent=s?`${number(s.notes)} NOTA · ${duration(s.source_duration)} KAYNAK` : '.MID / .MIDI · EN FAZLA 4 MB';
  $('#remove-file').hidden=!s;
  const status=state.busy==='generate'?(native?'Sesler hazırlanıyor':'Hareketler planlanıyor'):state.busy==='upload'?'MIDI okunuyor':state.busy==='preview'?'Önizleme güncelleniyor':state.result?'Çıktı hazır':s?.valid===false?'Ayarları kontrol et':s?'Önizleme hazır':'MIDI bekleniyor';
  $('#preview-status').replaceChildren();const dot=document.createElement('i');$('#preview-status').append(dot,document.createTextNode(status));
  $('#preview-status').classList.toggle('loading',loading);
  $('#duration-metric').replaceChildren(document.createTextNode(s?duration(s.duration):'—'));
  $('#notes-metric').textContent=s?number(s.notes):'—';
  $('#bpm-metric').replaceChildren(document.createTextNode(s?(s.tempo_changes>1?'≈ ':'')+number(s.output_bpm,Number.isInteger(s.output_bpm)?0:1):'—'));
  const bpmUnit=document.createElement('small');bpmUnit.textContent=' BPM';$('#bpm-metric').append(bpmUnit);
  $('#range-label').textContent=native?'Ses kanalları':foc?'X ses hızı':yPriority?'X / Y hız aralığı':xOnly?'X hız aralığı':'XY hız aralığı';
  if((yPriority||foc)&&samePrinter&&s?.valid&&s.axis_speed_ranges){
    $('#range-metric').replaceChildren();
    for(const axis of xOnly?['x']:['x','y']){const range=s.axis_speed_ranges[axis],line=document.createElement('span');line.className='axis-speed-line';line.textContent=`${axis.toUpperCase()}: ${number(range[0],range[0]<1?3:1)}–${number(range[1],range[1]<1?3:1)}`;const unit=document.createElement('small');unit.textContent=' mm/sn';line.append(unit);$('#range-metric').append(line);}
  }else{
    $('#range-metric').replaceChildren(document.createTextNode(native?'X + Y':s?.speed_range?.length?`${number(s.speed_range[0],s.speed_range[0]<10?1:0)}–${number(s.speed_range[1],0)}`:'—'));
    const unit=document.createElement('small');unit.textContent=native?' · Z sessiz':' mm/sn';$('#range-metric').append(unit);
  }
  $('#arrangement-note').textContent=s&&s.warnings?.length?s.warnings.join(' '):native?`MIDI, ${selectedPrinter().name} yerleşik ses kanalları için düzenlenir. Ses desteği firmware sürümüne bağlıdır; sentetik önizleme fiziksel motor sesinden farklı olabilir.`:`MIDI, ${selectedPrinter().name} XY motorları için düzenlenir. Gerçek motor sesi sentetik önizlemeden farklı olabilir.`;
  $('#song-attribution').hidden=!state.librarySong;$('#song-attribution').textContent=state.librarySong?`${state.librarySong.title} · ${state.librarySong.artist||state.librarySong.composer||'MIDI arşivi'}`:'';
  $('#play-button').disabled=!s?.valid||loading;$('#play-time').innerHTML='';
  $('#synth-label').textContent=foc?'MIDI melodi referansı':'Sentetik önizleme';
  $('#play-time').append(document.createTextNode(duration(state.played)+' '));const end=document.createElement('em');end.textContent='/ '+duration(s?Math.min(12,s.duration):12);$('#play-time').append(end);
  $('#generate-button').disabled=!s?.valid||loading;
  $('#generate-button').classList.toggle('busy',state.busy==='generate');
  $('#generate-label').textContent=state.busy==='generate'?(native?'Notalar müziğe dönüşüyor…':'Notalar harekete dönüşüyor…'):state.busy==='preview'?'Önizleme hazırlanıyor…':'G-code oluştur';
  $('#generate-button').hidden=!!state.result;$('#download-actions').hidden=!state.result;$('#result-meta').hidden=!state.result;
  $('#export-title').textContent=state.result?'Dosyaların çalmaya hazır.':state.busy==='generate'?(native?'Müzik komutları hazırlanıyor.':'Hareketler hesaplanıyor.'):s?.valid===false?'Bu ayarları gözden geçir.':s?(native?'Melodin hazır.':'Melodin hazır. Sırada hareket var.'):'Çalmaya bir adım kaldı.';
  $('#export-description').textContent=native?(state.result?'Yerleşik müzik komutları ve süreleri kontrol edildi. Önce kısa testi dinle.':state.busy==='generate'?'Ses kanalları, nota süreleri ve çıktı komutları kontrol ediliyor.':s?`${duration(s.duration)} müzik · X/Y ses kanalları · Z sessiz`:'Dosyanı seçip ayarlarını yaptıktan sonra oluştur.'):(state.result?'Hareket sınırları ve nota zamanları kontrol edildi. Önce kısa testi dinle.':state.busy==='generate'?'XY yolu, nota zamanları ve çıktı sınırları kontrol ediliyor.':s?`${duration(s.duration)} müzik · ${s.acceleration} mm/sn² ${xOnly?'X':'XY'} ivmesi · ${xOnly?'ana melodi':'iki motor sesi'}`:'Dosyanı seçip ayarlarını yaptıktan sonra oluştur.');
  if(foc)$('#export-description').textContent=state.result?'Ses hız aralıkları ve zamanlama kontrol edildi. Gerçek perde ölçülmedi; önce kısa testi dinle.':'Ana melodi yalnızca X ekseninde çalar; Y ve Z sabittir. Önizleme MIDI referansıdır.';
  if (state.result) {
    $('#result-size').textContent=`${number(state.result.downloads.full.bytes/1024,1)} KB · .gcode`;
    $('#download-test').textContent=state.result.downloads.test.seconds<7.5?`${duration(state.result.downloads.test.seconds)} testi indir`:'8 sn testi indir';
  }
  $('#native-mode-note').hidden=!(native||xOnly);$('#native-mode-note').textContent=native?'Konumlandırma yolu yok; X/Y ses kanalları kullanılır, Z sessiz.':'Müzikte yalnızca X ekseni hareket eder; Y ve Z sabittir.';
  if(foc){$('#native-mode-note').hidden=false;$('#native-mode-note').textContent='FOC ses aralığı: yalnızca X ekseni çalar; Y ve Z sabittir. Dinletim MIDI referansıdır; gerçek motor perdesi farklı olabilir.';}
  $('#motion-tab').disabled=native;$('#motion-tab').title=native?'Konumlandırma yolu yok; X/Y ses kanalları kullanılır, Z sessiz.':'';
  $('#melody-tab').setAttribute('aria-selected',String(state.tab==='melody'));$('#motion-tab').setAttribute('aria-selected',String(state.tab==='motion'));
  const bounds=musicBounds();$('#preview-detail').textContent=state.tab==='melody'?'İlk 12 saniye':state.result?`${number(bounds.x[1]-bounds.x[0])} × ${number(bounds.y[1]-bounds.y[0])} mm hareket alanı`:'Oluşturulduğunda görünür';
  const empty = !s?.frames?.length || (state.tab==='motion'&&!state.result);
  $('#empty-preview').hidden=!empty;
  $('#empty-preview h3').textContent=state.tab==='motion'?'XY yolunu burada incele.':'Bir melodinin hareketini gör.';
  $('#empty-preview p').textContent=state.tab==='motion'?'G-code oluşturulduğunda hareket yolu görünecek.':s?'Hız ve tempo seçimine göre notalar hazırlanır.':'MIDI seçtiğinde notalar burada belirecek.';
  draw();
}

async function loadSong(file=null,songId=null) {
  if (file && !/\.(mid|midi)$/i.test(file.name)) return showError('Lütfen .mid veya .midi dosyası seç.');
  if (file && file.size>4*1024*1024) return showError('Dosya çok büyük. En fazla 4 MB MIDI seçebilirsin.');
  stopAudio();state.controller?.abort();const ticket=++state.revision;
  state.busy='upload';state.id=null;state.summary=null;state.result=null;state.librarySong=file?null:state.catalog.library.find(s=>s.id===songId)||null;showError('');render();
  try {
    const data=file?await request('/api/upload?name='+encodeURIComponent(file.name),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:await file.arrayBuffer()}):await post('/api/demo',songId?{id:songId}:{});
    if (ticket!==state.revision) return;
    state.id=data.id;state.summary=data;state.busy='';
    await updatePreview();
  } catch (error) {if(ticket===state.revision){state.busy='';showError(error.message);render();}}
}

async function updatePreview() {
  stopAudio();state.result=null;showError('');
  if (!state.id) return render();
  state.controller?.abort();state.controller=new AbortController();
  const ticket=++state.revision;state.busy='preview';render();
  try {
    const data=await post('/api/preview',{id:state.id,settings:{...state.settings}},state.controller.signal);
    if(ticket!==state.revision)return;
    state.summary=data;if(data.settings?.startup)state.settings.startup=data.settings.startup;state.busy='';saveFocBands();render();
  } catch(error){if(ticket===state.revision){state.busy='';if(state.summary){state.summary.valid=false;state.summary.frames=[];state.summary.speed_range=[];}if(error.name!=='AbortError')showError(error.message);render();}}
}

async function generate() {
  if (!state.id||state.busy) return;
  stopAudio();showError('');const ticket=++state.revision;state.busy='generate';render();
  try {
    const data=await post('/api/generate',{id:state.id,settings:{...state.settings}});
    if(ticket!==state.revision)return;
    state.result=data;state.summary=data;state.busy='';render();toast('G-code hazır. Önce kısa test dosyasını deneyebilirsin.');
  } catch(error){if(ticket===state.revision){state.busy='';showError(error.message);render();}}
}

function draw() {
  const bounds=canvas.getBoundingClientRect(),dpr=Math.min(window.devicePixelRatio||1,2);
  const width=Math.max(1,bounds.width),height=Math.max(1,bounds.height);
  if(canvas.width!==Math.round(width*dpr)||canvas.height!==Math.round(height*dpr)){canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);}
  context.setTransform(dpr,0,0,dpr,0,0);context.clearRect(0,0,width,height);
  if(state.tab==='motion')return drawMotion(width,height);
  const left=40,right=14,top=18,bottom=27,plotWidth=width-left-right,plotHeight=height-top-bottom;
  const frames=state.summary?state.summary.frames.filter(f=>f.start<12):[];
  const all=frames.flatMap(f=>f.pitches);const low=all.length?Math.floor((Math.min(...all)-2)/6)*6:48;
  const high=all.length?Math.ceil((Math.max(...all)+2)/6)*6:84;const rows=high-low+1;
  const maxTime=state.summary?Math.min(12,state.summary.duration):12;
  context.font='8px Consolas,monospace';context.textBaseline='middle';
  for(let p=low;p<=high;p++){
    const y=top+(high-p)*plotHeight/rows;
    context.fillStyle=[1,3,6,8,10].includes(p%12)?'#131a18':'#161d1a';context.fillRect(left,y,plotWidth,plotHeight/rows);
    context.strokeStyle=p%12===0?'#344032':'#222b25';context.lineWidth=.5;context.beginPath();context.moveTo(left,y);context.lineTo(width-right,y);context.stroke();
    if(p%12===0||p===low){context.fillStyle='#62705e';context.fillText(noteName(p),8,y+3);}
  }
  for(let t=0;t<=maxTime+.01;t+=maxTime<6?1:2){const x=left+t/maxTime*plotWidth;context.strokeStyle='#2a332b';context.lineWidth=.6;context.beginPath();context.moveTo(x,top);context.lineTo(x,height-bottom);context.stroke();context.fillStyle='#687764';context.textAlign='center';context.fillText(duration(t),x,height-12);}
  context.textAlign='left';
  for(const frame of frames){const x=left+frame.start/maxTime*plotWidth;const w=Math.max(1,(Math.min(maxTime,frame.end)-frame.start)/maxTime*plotWidth-1.2);
    frame.pitches.slice().reverse().forEach((pitch,index)=>{const y=top+(high-pitch)*plotHeight/rows;context.fillStyle=frame.pitches.length===1||index>0?'#c1e89a':'#5c7665';context.beginPath();context.roundRect(x,y+1,w,Math.max(2,plotHeight/rows-2),2);context.fill();});
  }
  if(state.playing){const x=left+state.played/maxTime*plotWidth;context.strokeStyle='#f1f8eb';context.lineWidth=1;context.beginPath();context.moveTo(x,top-6);context.lineTo(x,height-bottom);context.stroke();context.fillStyle='#edf6e6';context.beginPath();context.moveTo(x-3,top-8);context.lineTo(x+3,top-8);context.lineTo(x,top-3);context.fill();}
}

function drawMotion(width,height){
  const bounds=musicBounds(),xmin=bounds.x[0],xmax=bounds.x[1],ymin=bounds.y[0],ymax=bounds.y[1];
  const maxSize=Math.min(width-80,height-48),scale=maxSize/Math.max(xmax-xmin,ymax-ymin),w=(xmax-xmin)*scale,h=(ymax-ymin)*scale,left=(width-w)/2,top=14;
  const x=(v)=>left+(v-xmin)*scale,y=(v)=>top+(ymax-v)*scale;
  context.font='8px Consolas,monospace';context.fillStyle='#70816b';
  for(let i=0;i<=4;i++){const vx=xmin+(xmax-xmin)*i/4,vy=ymin+(ymax-ymin)*i/4;context.strokeStyle='#2a352b';context.lineWidth=.7;context.beginPath();context.moveTo(x(vx),top);context.lineTo(x(vx),top+h);context.moveTo(left,y(vy));context.lineTo(left+w,y(vy));context.stroke();context.fillText(number(vx),x(vx)-7,top+h+14);}
  context.strokeStyle='#52644c';context.strokeRect(left,top,w,h);context.fillStyle='#8fa385';context.fillText('X (mm)',left+w+12,top+h+14);context.fillText('Y',left-18,top+5);
  const path=state.result?.path;if(!path)return;
  const cx=(xmin+xmax)/2,cy=(ymin+ymax)/2;
  context.beginPath();context.moveTo(x(cx),y(cy));for(const p of path)context.lineTo(x(p[0]),y(p[1]));context.lineWidth=.7;context.strokeStyle='#b9dc8f90';context.stroke();
  context.beginPath();context.arc(x(cx),y(cy),3,0,Math.PI*2);context.fillStyle='#d2f4b7';context.fill();
  context.fillStyle='#9cad91';context.fillText(`${path.length} hareket`,14,height-12);
}

function stopAudio(){
  oscillators.forEach(node=>{try{node.stop();node.disconnect();}catch{}});oscillators=[];cancelAnimationFrame(animationFrame);
  state.playing=false;state.played=0;$('#play-button').innerHTML=playIcon;
  $('#play-button').setAttribute('aria-label','Sentetik nota önizlemesini dinle');
}
async function playAudio(){
  if(state.playing){stopAudio();return render();}
  if(!state.summary||state.busy)return;
  try {
    audioContext??=new AudioContext();await audioContext.resume();
    const beginning=audioContext.currentTime+.04,length=Math.min(12,state.summary.duration);
    for(const frame of state.summary.frames){if(frame.start>=length)break;
      const start=beginning+frame.start,end=beginning+Math.min(length,frame.end);if(end-start<.006)continue;
      frame.pitches.forEach((pitch,index)=>{const oscillator=audioContext.createOscillator(),gain=audioContext.createGain();oscillator.type='triangle';oscillator.frequency.setValueAtTime(440*2**((pitch-69)/12),start);const amp=index===0?.035:.019;const attack=Math.min(.008,(end-start)/4);gain.gain.setValueAtTime(0,start);gain.gain.linearRampToValueAtTime(amp,start+attack);gain.gain.setValueAtTime(amp,end-attack);gain.gain.linearRampToValueAtTime(0,end);oscillator.connect(gain);gain.connect(audioContext.destination);oscillator.start(start);oscillator.stop(end+.01);oscillators.push(oscillator);});
    }
    state.playing=true;$('#play-button').innerHTML='<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path d="M6 4h3v12H6zM12 4h3v12h-3z"/></svg>';
    $('#play-button').setAttribute('aria-label','Önizlemeyi durdur');
    function tick(){if(!state.playing)return;state.played=Math.max(0,audioContext.currentTime-beginning);if(state.played>=length){stopAudio();render();return;}$('#play-time').firstChild.textContent=duration(state.played)+' ';draw();animationFrame=requestAnimationFrame(tick);}tick();
  } catch {showError('Ses önizlemesi açılamadı. G-code dönüştürmeye devam edebilirsin.');}
}

async function download(which){
  if(!state.result)return;const file=state.result.downloads[which];
  if(!file?.url?.startsWith('/api/download/')){showError('İndirme bağlantısı yenilenmeli. Sayfayı yenileyip G-code’u yeniden oluştur.');return;}
  if(state.runtime.mode==='desktop'&&window.pywebview?.api?.save_export){
    try{const saved=await window.pywebview.api.save_export(file.url);if(saved.error)showError(saved.error);else if(!saved.cancelled)toast('Dosya kaydedildi: '+saved.name);}
    catch{showError('Dosya kaydedilemedi. Yeniden dene.');}
    return;
  }
  const link=document.createElement('a');link.href=file.url;link.download=file.name;document.body.append(link);link.click();link.remove();
  toast(which==='test'?'Kısa test dosyası indiriliyor.':'Dosyan indiriliyor.');
}

document.querySelectorAll('[data-setting]').forEach(button=>button.addEventListener('click',()=>{
  if(selectedPrinter().music_settings_lock)return;
  const {setting,value}=button.dataset;state.settings[setting]=value;
  if(setting==='speed'&&selectedPrinter().tempo_follows_speed)state.settings.tempo=value;
  updatePreview();
}));
$('#voice-select').addEventListener('change',event=>{state.settings.voice=event.target.value;updatePreview();});
$('#sound-mode').addEventListener('change',event=>{state.settings.sound_mode=event.target.value;state.settings.voice=isFocBand()?'foc_melody':isXOnlyPrinter()?'x_melody':'duet';updatePreview();});
$('#foc-axis').addEventListener('change',event=>{state.settings.foc_axis=event.target.value;updatePreview();});
document.querySelectorAll('[data-foc-setting]').forEach(input=>input.addEventListener('change',()=>{state.settings[input.dataset.focSetting]=Number(input.value);updatePreview();}));
$('#startup-select').addEventListener('change',event=>{state.settings.startup=event.target.value;updatePreview();});
$('#drop-zone').addEventListener('click',()=>$('#midi-file').click());
$('#midi-file').addEventListener('change',event=>{if(event.target.files[0])loadSong(event.target.files[0]);event.target.value='';});
$('#drop-zone').addEventListener('dragover',event=>{event.preventDefault();$('#drop-zone').classList.add('dragover');});
$('#drop-zone').addEventListener('dragleave',()=>$('#drop-zone').classList.remove('dragover'));
$('#drop-zone').addEventListener('drop',event=>{event.preventDefault();$('#drop-zone').classList.remove('dragover');if(!state.busy&&event.dataTransfer.files[0])loadSong(event.dataTransfer.files[0]);});
$('#demo-button').addEventListener('click',()=>loadSong());
$('#library-button').addEventListener('click',()=>{renderLibrary();$('#library-dialog').showModal();});
$('#printer-button').addEventListener('click',()=>{renderPrinterList();$('#printer-dialog').showModal();});
$('#printer-search').addEventListener('input',renderPrinterList);$('#library-search').addEventListener('input',renderLibrary);
$('#library-category').addEventListener('change',renderLibrary);
$('#profile-import-button').addEventListener('click',()=>$('#profile-file').click());
$('#profile-file').addEventListener('change',event=>{if(event.target.files[0])importProfile(event.target.files[0]);event.target.value='';});
$('#remove-file').addEventListener('click',()=>{stopAudio();state.controller?.abort();state.revision++;state.id=null;state.summary=null;state.result=null;state.librarySong=null;state.busy='';showError('');render();});
$('#generate-button').addEventListener('click',generate);$('#play-button').addEventListener('click',playAudio);
$('#download-full').addEventListener('click',()=>download('full'));$('#download-test').addEventListener('click',()=>download('test'));$('#report-button').addEventListener('click',()=>download('report'));
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{state.tab=button.dataset.tab;render();}));
$('#help-button').addEventListener('click',()=>$('#help-dialog').showModal());
$('#inspect-button').addEventListener('click',()=>{if(!state.result)return;$('#gcode-preview').textContent=state.result.downloads.full.text.split('\n').slice(0,120).join('\n');$('#code-dialog').showModal();});
document.querySelectorAll('dialog').forEach(dialog=>{dialog.querySelector('.dialog-close').addEventListener('click',()=>dialog.close());dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});});
new ResizeObserver(draw).observe($('#visualizer'));
window.addEventListener('pagehide',stopAudio);
render();
loadCatalog();

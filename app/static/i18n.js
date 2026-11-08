'use strict';

// English is the product default. Browser/OS language never changes that choice.
window.I18n = (() => {
  let catalog = {languages:{en:'English'}, messages:{}, source_aliases:{}}, language = 'en', revision = 0;
  const localeNames = {en:'en-US',tr:'tr-TR',de:'de-DE',es:'es-ES',fr:'fr-FR',pt:'pt-BR',zh:'zh-CN',ja:'ja-JP',ru:'ru-RU',ar:'ar'};
  const originals = new WeakMap(), attributes = new WeakMap(), cache = new Map();
  const ignored = 'script,style,pre,code,#brand-name,#footer-brand,#printer-name,.catalog-copy>strong,[data-no-i18n]';
  let aliases = [], observer;
  try { language = localStorage.getItem('3dmidi.language') || 'en'; } catch {}

  function english(value) {
    if(catalog.source_aliases[value])return catalog.source_aliases[value];
    // Legacy source notes are inert text, never code or user MIDI filenames.
    if(!/[ÇĞİÖŞÜçğıöşü]/u.test(value))return value;
    for(const [source,target] of aliases)if(value.includes(source))value=value.split(source).join(target);
    return value;
  }
  function t(value) {
    const source=String(value), key=language+'\u0000'+source;
    if(cache.has(key))return cache.get(key);
    const canonical=english(source), translations=catalog.messages[canonical];
    const translated=translations?.[language] || translations?.en || canonical;
    if(cache.size>4096)cache.clear();cache.set(key,translated);return translated;
  }
  function format(key, values={}) {
    return t(key).replace(/\{(\w+)\}/g, (match,name)=>Object.hasOwn(values,name)?String(values[name]):match);
  }
  function textNode(node) {
    if(!node.parentElement || node.parentElement.closest(ignored))return;
    if(node.parentElement.closest('#file-name') && /\.(mid|midi)$/iu.test(node.nodeValue))return;
    const current=node.nodeValue, saved=originals.get(node);
    const source=saved && saved.rendered===current?saved.source:current;
    const trimmed=source.trim();if(!trimmed)return;
    const rendered=source.replace(trimmed,t(trimmed));
    originals.set(node,{source,rendered});if(current!==rendered)node.nodeValue=rendered;
  }
  function translateElement(element) {
    if(element.closest(ignored))return;
    const previous=attributes.get(element)||{};
    for(const name of ['aria-label','title','placeholder']){
      if(!element.hasAttribute(name))continue;
      const current=element.getAttribute(name), saved=previous[name];
      const source=saved&&saved.rendered===current?saved.source:current, rendered=t(source);
      previous[name]={source,rendered};if(current!==rendered)element.setAttribute(name,rendered);
    }
    attributes.set(element,previous);
  }
  function apply(root=document.body) {
    if(root.nodeType===Node.TEXT_NODE){textNode(root);return;}
    if(root.nodeType!==Node.ELEMENT_NODE)return;
    translateElement(root);
    const walk=document.createTreeWalker(root,NodeFilter.SHOW_TEXT|NodeFilter.SHOW_ELEMENT);
    while(walk.nextNode())if(walk.currentNode.nodeType===Node.TEXT_NODE)textNode(walk.currentNode);else translateElement(walk.currentNode);
  }
  async function persist() {
    try{localStorage.setItem('3dmidi.language',language);}catch{}
    if(window.pywebview?.api?.set_preferences){
      try{await window.pywebview.api.set_preferences({language});}
      catch{document.dispatchEvent(new CustomEvent('3dmidi:preferenceerror'));}
    }
  }
  async function setLanguage(next,{save=true}={}) {
    if(!Object.hasOwn(catalog.languages,next))next='en';
    language=next;revision++;cache.clear();document.documentElement.lang=next;document.documentElement.dir=next==='ar'?'rtl':'ltr';
    const select=document.querySelector('#language-select');if(select)select.value=next;
    apply();window.dispatchEvent(new CustomEvent('3dmidi:languagechange',{detail:{language:next}}));
    if(save)await persist();
  }
  async function nativePreferences() {
    const ticket=revision;
    if(!window.pywebview?.api?.get_preferences)return;
    try{const saved=await window.pywebview.api.get_preferences();if(ticket===revision)await setLanguage(saved.language,{save:false});}catch{}
  }
  const ready=fetch('/locales.json').then(response=>{if(!response.ok)throw new Error('Language catalog unavailable');return response.json();}).then(async data=>{
    catalog=data;aliases=Object.entries(data.source_aliases).filter(([source,target])=>source.length>3&&source!==target).sort((a,b)=>b[0].length-a[0].length);
    const select=document.querySelector('#language-select');
    select.replaceChildren(...Object.entries(catalog.languages).map(([id,name])=>new Option(name,id)));
    select.addEventListener('change',event=>setLanguage(event.target.value));
    await setLanguage(language,{save:false});
    observer=new MutationObserver(records=>{
      for(const record of records){
        if(record.type==='characterData')textNode(record.target);
        else if(record.type==='attributes')translateElement(record.target);
        else for(const node of record.addedNodes)apply(node);
      }
    });
    observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['aria-label','placeholder','title']});
    document.querySelector('#settings-button').addEventListener('click',()=>document.querySelector('#settings-dialog').showModal());
    document.querySelector('#settings-done').addEventListener('click',()=>document.querySelector('#settings-dialog').close());
    await nativePreferences();
  }).catch(error=>console.error('3DMidi language settings:',error));
  window.addEventListener('pywebviewready',()=>ready.then(nativePreferences));
  return {t,format,apply,ready,setLanguage,language:()=>language,locale:()=>localeNames[language]||'en-US'};
})();

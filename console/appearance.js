/* Browser preferences apply to console UI, not tenant content or model output. */
(()=>{
 const keyTheme='kf-ui-theme',keyLanguage='kf-ui-language',root=document.documentElement;
 const read=(key,fallback)=>{try{return localStorage.getItem(key)||fallback;}catch(_){return fallback;}};
 let theme=read(keyTheme,'light'),language=read(keyLanguage,'zh');
 if(!['light','dark','system'].includes(theme))theme='system';if(!['zh','en'].includes(language))language='zh';
 const media=matchMedia('(prefers-color-scheme: dark)');
 function paintTheme(){root.dataset.theme=theme==='system'?(media.matches?'dark':'light'):theme;root.style.colorScheme=root.dataset.theme;}
 paintTheme();root.lang=language==='en'?'en':'zh-CN';
 const css=document.createElement('style');css.textContent=`
 :root{--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#e6edf3;--dim:#8b949e;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--acc:#58a6ff;--surface:#21262d;--selected:#1c2d42;--selected-text:#9acbff;--input:#0d1117;--callout:#1c2530}
 html[data-theme=light]{--bg:#f7f8fa;--card:#ffffff;--line:#d5d8de;--fg:#20242d;--dim:#596273;--ok:#187437;--warn:#875b00;--bad:#b42318;--acc:#005bd3;--surface:#f1f3f6;--selected:#eaf2ff;--selected-text:#004db3;--input:#fff;--callout:#f1f6ff}
 body{background:var(--bg)!important;color:var(--fg)!important}
 .ui-preferences{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 18px;justify-content:flex-end}
 .ui-preferences label{display:flex;gap:6px;align-items:center;margin:0;font-size:12px;color:var(--dim)}
 .ui-preferences select{width:auto!important;min-height:36px;padding:6px 8px;border-radius:6px;border:1px solid var(--line);background:var(--input);color:var(--fg);font-size:13px}
 .box{background:var(--card)!important;border-color:var(--line)!important;color:var(--fg)!important}
 .box label,.box .sub,.box details{color:var(--dim)!important}.box input{background:var(--input)!important;border-color:var(--line)!important;color:var(--fg)!important}
 .err{background:var(--card)!important;color:var(--bad)!important;border:1px solid var(--bad)}
 html[data-theme=light] .tab.on{background:var(--selected);color:var(--selected-text)}
 html[data-theme=light] .tab:hover,html[data-theme=light] .sec-row.on{background:var(--selected)}
 html[data-theme=light] .callout{background:var(--callout)}
 html[data-theme=light] input,html[data-theme=light] select,html[data-theme=light] textarea{background:var(--input);color:var(--fg)}
 html[data-theme=light] button.ghost,html[data-theme=light] .sec-row button,html[data-theme=light] .dom-row button,html[data-theme=light] .share-row button,html[data-theme=light] .tile .ops button,html[data-theme=light] .fld .sub button{background:var(--surface);color:var(--fg);border-color:var(--line)}
 html[data-theme=light] .sec-row .section-select{background:transparent}
 html[data-theme=light] button.danger{color:var(--bad)}
 :where(button,input,select,textarea,summary,a):focus-visible{outline:2px solid var(--acc);outline-offset:3px}
 @media(max-width:600px){.ui-preferences{justify-content:flex-start}.ui-preferences select{font-size:16px;min-height:44px}}


 .style-library{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr));gap:20px;margin-top:24px}
 .style-card{border:1px solid var(--line);border-radius:6px;overflow:hidden;background:var(--card)}
 .style-card-art{padding:24px;min-height:170px;display:flex;flex-direction:column;gap:16px;overflow:hidden}.style-card-art b{font-family:inherit;font-size:24px;line-height:1.2}
 .style-mini-line{width:40px;height:4px;display:block}.style-mini-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.style-mini-grid span{height:44px;opacity:.7}
 .style-card-body{padding:20px}.style-card-body h3{margin:0 0 6px!important}.style-description{font-size:14px;line-height:1.6;overflow-wrap:anywhere;min-height:4.8em}
 .style-source{display:inline-block;margin:0 0 16px;font-size:13px}
 .style-card-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.style-card-actions button{min-width:0;white-space:nowrap;padding:8px 6px!important;font-size:12px!important}
 #stylePreviewPanel{margin-top:24px;border:1px solid var(--line);padding:16px;background:var(--card);border-radius:6px}
 #stylePreviewWidth{width:auto}#stylePreviewFrame{display:block;width:100%;max-width:100%;height:650px;border:1px solid var(--line);margin:16px auto 0;background:#fff}
 #styleAdvanced .field{flex:1 1 210px}#styleColors .field{flex:1 1 100px;min-width:100px}#styleEditForm input[type=color]{width:100%;height:44px}
 .sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip-path:inset(50%)!important;white-space:nowrap!important;border:0!important}
 .admin-modal-heading{position:sticky;top:-24px;background:var(--card);z-index:2;padding:8px 0;margin-top:0}.admin-modal-heading h3{margin:0}.admin-modal-heading button{min-height:44px}@media(max-width:700px){.admin-modal-heading{top:-16px}}
 .site-archive-toggle{display:flex;align-items:center;gap:8px;margin-top:8px;font-size:13px;color:var(--dim)}.table-wrap{overflow-x:auto}.domain-dialog input,.domain-dialog select,.domain-dialog textarea{max-width:100%;box-sizing:border-box}
 .domain-dialog{width:min(900px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;padding:24px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg)}.domain-dialog::backdrop{background:#10182099}.domain-dialog-heading,.domain-row-actions,.domain-form-actions,.domain-pagination{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.domain-dialog-heading{justify-content:space-between;margin-bottom:16px}.domain-pagination{justify-content:flex-end;margin-top:16px}.domain-meta{display:grid;grid-template-columns:110px minmax(0,1fr);gap:12px}.domain-meta dt{color:var(--dim)}.domain-meta dd{margin:0;overflow-wrap:anywhere}.domain-table td{overflow-wrap:anywhere}.domain-table pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit;max-width:350px}.domain-table .hint{margin:4px 0 0}.domain-table button{white-space:normal}.domain-dialog .field{min-width:0}.domain-dialog .field input,.domain-dialog .field textarea{width:100%}.domain-form-actions{margin-top:20px}
 @media(max-width:700px){body .domain-toolbar .status-field{flex:1 1 100%;width:100%}.domain-dialog{padding:16px}.domain-meta{grid-template-columns:90px minmax(0,1fr)}.domain-toolbar>button{flex:1}.domain-table pre{max-width:100%}}
 .style-intro{display:flex;align-items:center;justify-content:space-between;gap:24px;margin:8px 0 32px}.style-intro h3{font-size:32px;line-height:1.2;letter-spacing:-.7px;margin:8px 0}.style-intro .eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--dim)}
 .style-browser-toolbar{display:grid;grid-template-columns:1.6fr 1fr 1fr 1fr;gap:16px;align-items:end}.style-browser-tools{display:flex;align-items:center;flex-wrap:wrap;gap:16px;padding:16px 0;border-bottom:1px solid var(--line)}.style-browser-tools>p{margin:0 auto 0 0}.style-browser-tools>select{width:auto}.style-browser-tools>label{display:flex;align-items:center;gap:8px;margin:0}
 .style-admin-tools{position:relative}.style-admin-tools>summary,.style-card-menu>summary{cursor:pointer;min-height:44px;display:flex;align-items:center;justify-content:center;padding:8px 14px;border:1px solid var(--line);border-radius:6px;list-style:none}.style-admin-tools>div{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
 .style-library{grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr));gap:28px}.style-card{overflow:visible;border:0;background:transparent}.style-card-preview{position:relative;display:block;width:100%;aspect-ratio:3/2;padding:0!important;border:1px solid var(--line)!important;border-radius:8px!important;overflow:hidden;background:var(--surface)!important;color:var(--dim)!important;cursor:pointer;box-shadow:0 4px 16px #00000008}.style-card-preview:hover{box-shadow:0 8px 24px #00000018}.style-card-preview iframe{position:absolute;inset:0;width:1200px;height:800px;border:0;transform:scale(var(--preview-scale,.3));transform-origin:top left;pointer-events:none;background:#fff}.style-thumb-loading{font-size:13px}.style-card-body{padding:16px 0 0}.style-card-heading{display:flex;gap:12px;align-items:center;justify-content:space-between}.style-card-heading h3{font-size:18px!important}.style-card-heading .style-favorite{font-size:12px;padding:8px!important;white-space:nowrap;min-height:36px}.style-favorite[aria-pressed=true]{color:var(--action)!important;background:var(--selected)!important}.style-card-body>.hint{font-size:13px;margin:4px 0 14px}.style-card-actions{grid-template-columns:1fr 1fr auto}.style-card-actions button{font-size:13px!important;min-height:44px}.style-card-menu{position:relative}.style-card-menu>summary{font-size:13px}.style-card-menu>div{position:absolute;right:0;top:calc(100% + 6px);z-index:5;background:var(--card);padding:8px;border:1px solid var(--line);border-radius:6px;box-shadow:0 8px 28px #00000020;min-width:150px;display:grid;gap:4px}.style-card-menu button{text-align:left!important;width:100%}.style-empty{grid-column:1/-1;text-align:center;padding:64px 24px;border:1px dashed var(--line);border-radius:8px}
 .style-compare-bar.hidden{display:none}.style-compare-bar{position:sticky;top:0;z-index:6;display:flex;align-items:center;justify-content:flex-end;gap:12px;padding:12px 16px;margin-top:16px;background:var(--card);border:1px solid var(--line);border-radius:6px}.style-compare-bar>span{margin-right:auto}.style-compare-scroll{overflow:auto;max-width:100%}.style-compare-scroll table{min-width:700px;width:100%}.style-compare-scroll th,.style-compare-scroll td{padding:16px;vertical-align:top;text-align:left}.style-compare-scroll td button{display:block;margin-bottom:8px}
 dialog.style-detail-dialog{width:calc(100vw - 48px);max-width:1536px;max-height:calc(100vh - 48px);padding:0;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);overflow:auto}dialog.style-detail-dialog::backdrop{background:#10182099}dialog.style-detail-dialog.expanded{width:100vw;max-width:none;height:100vh;max-height:100vh;border-radius:0;margin:0}
 #styleDetailDialog #stylePreviewPanel{margin:0;padding:0;border:0;border-radius:0}.style-preview-toolbar{display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid var(--line);flex-wrap:wrap}.style-preview-toolbar h3{font-size:18px;margin:0 auto 0 0}.style-preview-toolbar select{width:auto;max-width:180px}.style-detail-layout{display:grid;grid-template-columns:minmax(0,1fr) 270px}.style-preview-stage{padding:20px;background:var(--bg);min-width:0}.style-detail-info{padding:24px;border-left:1px solid var(--line);font-size:14px}.style-detail-info h4{margin:24px 0 8px}.style-detail-info>button{display:block;width:100%;margin-bottom:12px}.style-detail-info>a{display:block;margin:18px 0}.style-detail-info details{margin-top:20px}.style-detail-info ul{padding-left:20px}.style-detail-info p{overflow-wrap:anywhere}.style-detail-swatches{display:flex;gap:8px;margin:20px 0}.style-detail-swatches span{width:28px;height:28px;border-radius:50%;border:1px solid #8888}
 #styleDetailDialog #stylePreviewFrame{height:70vh;min-height:400px;margin:0 auto;background:white;box-shadow:0 5px 24px #00000012}.style-type-editor{margin:20px 0}.style-type-editor>div{display:flex;gap:16px;flex-wrap:wrap}.style-type-editor label{display:flex;gap:8px;align-items:center}.style-page-row{display:grid;grid-template-columns:1fr 1fr 2fr auto;gap:12px;align-items:end;padding:16px 0;border-bottom:1px solid var(--line)}
 @media(max-width:1100px){.style-browser-toolbar{grid-template-columns:1fr 1fr}.style-detail-layout{grid-template-columns:minmax(0,1fr) 230px}.style-detail-info{padding:16px}.style-page-row{grid-template-columns:1fr 1fr}.style-page-row>.field:nth-child(3){grid-column:1/-1}}
 @media(max-width:700px){.style-intro{display:flex;gap:12px;margin:0 0 16px}.style-intro .eyebrow,.style-intro h3{display:none}.style-intro>div{flex:1}.style-intro>button{flex-shrink:0}.style-intro .hint{font-size:13px;margin:0}.style-browser-toolbar{grid-template-columns:1fr 1fr}.style-search-field{grid-column:1/-1}.style-library{grid-template-columns:minmax(0,1fr)}.style-browser-tools{gap:10px}.style-browser-tools>p{width:100%}.style-browser-tools>select{max-width:150px}.style-detail-layout{display:block}.style-detail-info{border-left:0;border-top:1px solid var(--line)}dialog.style-detail-dialog{width:calc(100vw - 16px);max-height:calc(100vh - 16px)}.style-preview-toolbar{padding:12px;gap:8px}.style-preview-toolbar h3{width:100%;margin:0 0 8px}.style-preview-stage{padding:10px}.style-preview-toolbar button{font-size:12px!important;padding:8px!important}.style-preview-toolbar select{max-width:125px}.style-compare-bar{flex-wrap:wrap}.style-compare-scroll thead{display:table-header-group!important}.style-compare-scroll tr{display:table-row!important}.style-compare-scroll td,.style-compare-scroll th{display:table-cell!important}.style-compare-scroll td:before{display:none!important}}

 /* Shared console system: quiet surfaces, readable controls, task-first navigation. */
 html{--brand:#f48120;--control-border:#8993a3;--action:#005bd3;--action-hover:#0044a0}
 html[data-theme=dark]{--control-border:#687589;--action:#176bd7;--action-hover:#247deb}
 body .wrap{max-width:none;padding:0}
 body .topbar{min-height:72px;padding:14px 28px;display:flex;align-items:center;gap:24px;background:var(--card);border-bottom:1px solid var(--line)}
 .topbar h1{display:flex;align-items:center;gap:10px;font-size:18px;white-space:nowrap;margin:0;font-weight:700;letter-spacing:-.3px}
 .brand-mark{width:26px;height:26px;border-radius:6px;background:var(--brand);display:inline-grid;place-items:center;color:#20242d;font-size:17px;flex:none}
 body .topbar .ui-preferences{margin:0 0 0 auto;gap:16px}
 body .who{display:flex;gap:10px;align-items:center;font-size:13px;white-space:normal}
 .who a{padding:8px 0;white-space:nowrap}
 body .console-shell{grid-template-columns:240px minmax(0,1fr);gap:0;min-height:calc(100dvh - 72px)}
 body .sidebar{position:sticky;top:0;max-height:100dvh;border:0;border-right:1px solid var(--line);border-radius:0;padding:20px 12px;background:var(--card)}
 body .nav-group{border:0;padding:0 0 12px}
 body .nav-group summary{display:flex;align-items:center;gap:10px;list-style:none;padding:12px;font-size:13px;font-weight:650;color:var(--fg);border-radius:4px}
 .nav-group summary::-webkit-details-marker{display:none}
 .nav-group summary::after{content:'';margin-left:auto;width:6px;height:6px;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:rotate(-45deg)}
 .nav-group[open] summary::after{transform:rotate(45deg)}
 .nav-icon{width:18px;height:18px;flex:none;stroke:currentColor;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
 body .submenu{padding:4px 0;gap:2px}
 body .tab{border-radius:4px;min-height:40px;padding:9px 14px 9px 40px;font-size:14px;color:var(--dim)}
 body .tab.on{background:var(--selected);color:var(--selected-text);box-shadow:inset 3px 0 var(--acc);font-weight:600}
 .nav-group summary:hover{background:var(--surface)}
 body .workspace{padding:32px 36px 64px;width:100%;max-width:1500px;margin:0 auto}
 body .page-heading{margin-bottom:24px;align-items:flex-start}
 body .page-heading h2{font-size:28px;line-height:1.25;letter-spacing:-.6px;font-weight:650}
 body .breadcrumb{font-size:13px;margin-bottom:10px}
 body h3{font-size:18px;line-height:1.4;font-weight:600;margin:24px 0 12px}
 body form h3:first-child{margin-top:0}
 body .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin-bottom:24px}
 body .stat{border-radius:6px;padding:20px 24px;display:flex;flex-direction:column-reverse;gap:10px;min-width:0}
 body .stat b{font-size:30px;font-weight:600;font-variant-numeric:tabular-nums;line-height:1.2}
 body .stat span{font-size:14px;color:var(--dim)}
 body form{padding:24px;border-radius:6px;margin-top:20px}
 body .formrow{gap:16px;row-gap:20px}
 body label,body .fld label{font-size:14px;color:var(--fg);font-weight:500;margin-bottom:7px}
 body input,body select,body .fld input[type=text],body .fld select,body .fld textarea,body textarea{border-color:var(--control-border);border-radius:4px;font:inherit;font-size:14px;min-height:40px;padding:9px 12px;line-height:1.4}
 body textarea{width:100%;background:var(--input);color:var(--fg);resize:vertical}
 body input[type=checkbox],body input[type=radio]{min-height:18px;padding:0}
 body input[type=color]{padding:3px}
 body button{border:1px solid transparent;border-radius:4px;background:var(--action);color:#fff;font-size:14px;font-weight:600;min-height:40px;padding:9px 16px;line-height:1.4}
 body button:hover:not(:disabled):not(.tab):not(.ghost):not(.section-select){background:var(--action-hover)}
 body button.ghost{background:var(--card);border-color:var(--control-border);color:var(--fg);font-size:13px;padding:7px 12px;min-height:36px}
 html[data-theme=light] body button.ghost{background:var(--card)}
 body button.ghost:hover:not(:disabled){background:var(--surface);border-color:var(--acc)}
 body button.danger{color:var(--bad);border-color:var(--bad)}
 body button:disabled{opacity:.55;cursor:not-allowed}
 body table{border-radius:6px;overflow:hidden}
 body th{padding:14px 16px;background:var(--surface);color:var(--dim);font-size:12px;text-transform:none;letter-spacing:0;font-weight:600}
 body td{padding:16px;font-size:14px;line-height:1.55;overflow-wrap:anywhere}
 body tbody tr:hover{background:var(--surface)}
 body .mono{font-size:13px;font-variant-numeric:tabular-nums}
 body .pill{padding:3px 9px;font-size:12px;line-height:1.4}
 body .dom-row,body .lead-card,body .share-row{padding:18px 20px;border-radius:6px;margin-bottom:12px}
 body .dom-row .hint{word-break:normal;overflow-wrap:anywhere;font-family:inherit;font-size:13px}
 body .hint,body .sub,body .page-help,body .msg{font-size:14px;line-height:1.65}
 body .page-help{margin:0 0 20px}
 body .page-help>summary{min-height:36px}
 body .callout{overflow-wrap:anywhere;border-radius:4px;font-size:14px;padding:14px 16px}
 body .optional-options{border-radius:6px;background:var(--card)}
 body .optional-options>summary{font-size:14px}
 body .editor-actions{border-radius:6px;box-shadow:0 3px 12px #00000010;padding:16px}
 .ai-build-steps,.ai-build-controls{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:20px}.ai-build-controls{margin-top:20px}.ai-build-steps [aria-current=step]{border-color:var(--acc);color:var(--acc)}.ai-build-review{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px}.ai-build-review dt{color:var(--dim);font-size:13px}.ai-build-review dd{margin:4px 0 0;overflow-wrap:anywhere}.ai-build-prompt{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}
 .site-toolbar{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end;margin:0 0 20px}
 .site-toolbar .search-field{flex:1;min-width:200px}
 .site-toolbar .status-field{width:180px}
 .site-toolbar .mine-filter{display:flex;align-items:center;gap:8px;min-height:40px;margin:0;font-size:14px;font-weight:400}
 .site-create{margin-top:24px;border:1px solid var(--line);border-radius:6px;background:var(--card)}
 .site-create>summary{font-size:16px;font-weight:600;cursor:pointer;padding:18px 24px;min-height:56px}
 body .site-create form{border:0;border-top:1px solid var(--line);border-radius:0;margin:0}
 .site-create .formrow{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}
 .site-create button{justify-self:start;align-self:end}
 .empty-results{text-align:center;padding:32px 16px!important}
 .empty-results p{margin:0 0 12px;color:var(--dim)}
 body .box{max-width:420px;border-radius:8px;padding:32px;box-shadow:0 8px 24px #20242d08}
 body .box form{padding:0;border:0;margin:0;background:transparent}
 body .box h1{font-size:26px;margin:12px 0 4px;letter-spacing:-.5px}
 body .box .sub{margin-bottom:24px;font-size:15px}
 body .box input{font-size:16px;min-height:44px}
 body .box .ui-preferences{padding-bottom:16px;border-bottom:1px solid var(--line);gap:12px}
 body .box button{min-height:44px;background:var(--action)}
 body .box .ui-preferences label{font-size:12px}
 body footer{border-top:1px solid var(--line);padding-top:20px;margin-top:32px;font-size:12px}
 :where(a,button,input,select,textarea,summary,[tabindex]){scroll-margin:16px}
 @media(min-width:901px){body .sidebar{min-height:calc(100dvh - 72px)}}
 @media(max-width:1100px){body .workspace{padding:28px 24px}body .topbar{gap:16px;padding:14px 20px}body .console-shell{grid-template-columns:216px minmax(0,1fr)}body .topbar h1{font-size:16px}}
 @media(max-width:900px){
  body .topbar{flex-wrap:wrap;flex-direction:row;gap:12px;padding:16px}body .topbar .ui-preferences{order:3;width:100%;margin:0;justify-content:flex-start}body .who{margin-left:auto}
  body .console-shell{grid-template-columns:minmax(0,1fr);gap:0}body .sidebar{position:static;max-height:none;padding:8px 16px;border-right:0;border-bottom:1px solid var(--line)}
  body .nav-toggle{background:var(--card);border:0;padding:10px 0}body .workspace{padding:24px 20px 48px}body .tab{min-height:44px}
  body .page-heading h2{font-size:25px}body .stats{gap:12px}body .stat{padding:16px}
 }
 @media(max-width:600px){
  body .topbar h1{font-size:16px}.brand-mark{width:24px;height:24px}body .who{font-size:12px;gap:8px}body .workspace{padding:24px 16px 48px}
  #p-sites .stats{grid-template-columns:repeat(2,minmax(0,1fr))}
  body .stats{grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}body .stat{padding:14px 10px}body .stat b{font-size:23px}body .stat span{font-size:12px}
  body form{padding:20px 16px}body .dom-row,body .lead-card,body .share-row{padding:16px}body .page-heading{gap:8px;flex-wrap:wrap}
  body input,body select,body textarea,body .fld input[type=text],body .fld textarea{font-size:16px;min-height:44px}body button,body button.ghost{min-height:44px}
  body td{padding:6px 0;font-size:14px}body table{border:0;background:transparent}body tbody tr{border-radius:6px;padding:16px}body tbody td:first-child{font-size:15px}
  .site-toolbar{gap:12px}.site-toolbar .search-field{min-width:100%}.site-toolbar .status-field{flex:1 1 140px;min-width:140px;width:auto}.site-toolbar .mine-filter{font-size:13px}
  .site-create .formrow{grid-template-columns:minmax(0,1fr)}.site-create>summary{padding:16px}.site-create button{width:100%}
  body .box{padding:24px}body .ui-preferences select{font-size:16px}
 }
 `;document.head.append(css);
 const messages=window.KF_MESSAGES||{},reverse=Object.fromEntries(Object.entries(messages).map(([zh,en])=>[en,zh]));
 const patterns=[
  [/^预览 (.+)$/,name=>`Preview ${name}`],
  [/^(工具|资源|提示词)（(\d+)）$/,(label,n)=>`${translate(label)} (${n})`],
  [/^版本 (\d+)$/,n=>`Version ${n}`],
  [/^到期日 (.+)$/,v=>`Expiry date ${v}`],
  [/^协议：(.+)$/,v=>`Protocol: ${v}`],
  [/^已保存模板 · (.+)$/,v=>`Saved template · ${translate(v)}`],
  [/^已选择 (.+)$/,v=>`Selected ${v}`],
  [/^请先修正工具规则 JSON：(.+)$/,v=>`Correct the tool rules JSON first: ${v}`],
  [/^(.+)（留空保留已保存值）$/,v=>`${translate(v)} (leave blank to keep existing)`],
  [/^(\d+) 个站点$/,n=>`${n} site(s)`],[/^(\d+) 个邮箱$/,n=>`${n} mailbox(es)`],
  [/^(\d+) 个账号未开两步验证$/,n=>`${n} account(s) without two-step verification`],
  [/^(\d+) 天前$/,n=>`${n} day(s) ago`],
  [/^· 登录 (.+)$/,v=>`· Sign-in: ${translate(v)}`],
  [/^(?:恢复码|码) (\d+)$/,n=>`Recovery codes: ${n}`],
  [/^(.+)（我）$/,v=>`${v} (me)`],
  [/^收支流水（(\d+)）$/,n=>`Transactions (${n})`],
  [/^第 (\d+) 项$/,n=>`Item ${n}`],
  [/^续费待办 · 共 (\d+) 个域名，(\d+) 个 (\d+) 天内到期$/,(n,d,days)=>`Renewals · ${n} domains, ${d} due within ${days} days`],
  [/^(管理员|运营|财务)（(admin|ops|finance)）$/,(r,id)=>`${translate(r)} (${id})`],
  [/^未保存 · (\d+) 页$/,n=>`Unsaved · ${n} page(s)`],
  [/^已发布 (\d+) 个页面$/,n=>`Published ${n} page(s)`],
  [/^导航菜单 · (.+)$/,v=>'Navigation · '+translate(v)],
  [/^请检查以下 (\d+) 项$/,n=>`Please check ${n} field(s)`],
  [/^上移区块 (\d+)$/,n=>`Move section ${n} up`],[/^下移区块 (\d+)$/,n=>`Move section ${n} down`],[/^删除区块 (\d+)$/,n=>`Delete section ${n}`],
  [/^编辑区块 (\d+)：(.+)$/,(n,v)=>`Edit section ${n}: ${v}`],
  [/^(.+) 天后$/,n=>`In ${n} days`],[/^已过期 (\d+) 天$/,n=>`Expired ${n} days ago`],
  [/^最后刷新 (.+)$/,v=>`Last refreshed ${v}`],
  [/^新建(场景模板|可复用模块)$/,v=>'New '+translate(v)],[/^编辑(场景模板|可复用模块)$/,v=>'Edit '+translate(v)],
  [/^已校验组合 · (\d+) 个模块 · (\d+) 字$/,(n,c)=>`Validated · ${n} modules · ${c} characters`],
  [/^(\d+) 个模块$/,n=>`${n} modules`],
  [/^(.+)，可跨场景复用$/,v=>`${translate(v)}; reusable across scenarios`],
  [/^(.+) · 模板 v(\d+)$/,(v,n)=>`${translate(v)} · Template v${n}`],
  [/^(上移|下移) (.+)$/,(direction,v)=>`Move ${translate(v)} ${direction==='上移'?'up':'down'}`],
  [/^(停用|启用)「(.+)」？已创建任务保留原版本。$/,(action,v)=>`${action==='停用'?'Disable':'Enable'} “${v}”? Existing jobs retain their original version.`],
  [/^(.+) · v(\d+)$/,(v,n)=>`${translate(v)} · v${n}`],
  [/^提示词：(.+) · v(\d+)$/,(v,n)=>`Prompt: ${translate(v)} · v${n}`],
  [/^将调用 (.+) 生成内容，企业名称和建站要求会发送至该配置的接口。$/,v=>`Using ${v}. Business information and the brief will be sent to this endpoint.`],
  [/^发布站点「(.+)」的「(.+)」？\n将先保存编辑内容，再更新线上页面。客户会立即看到。$/,(site,pages)=>`Publish “${pages}” on site “${site}”?\nEdits will be saved before updating the live pages. Customers will see them immediately.`],
  [/^发布失败：(.+)；草稿已保留，请查看改动后重试。$/,v=>`Publish failed: ${translate(v)}. Draft retained; review changes and retry.`],
  [/^JSON 无效：(.+)$/,v=>`Invalid JSON: ${v}`],
  [/^数据刷新失败：(.+)。请检查网络，稍后会自动重试。$/,v=>`Refresh failed: ${translate(v)}. Check your connection; retrying automatically.`],
  [/^(.+)（(管理员|运营|财务)）$/,(v,r)=>`${v} (${translate(r)})`],
 ];

 function translate(value){
  if(language!=='en')return reverse[value]||value;
  if(messages[value])return messages[value];
  for(const [regex,render] of patterns){const match=value.match(regex);if(match)return render(...match.slice(1));}
  // Translate known UI status prefixes while keeping names and free text intact.
  for(const [prefix,label] of [['失败：','Failed: '],['已保存','Saved'],['编辑中：','Editing: '],['已复制：','Copied: '],['已发送到 ','Sent to '],['已生成，有效期至 ','Created, valid until '],['有效至 ','Valid until '],['上次检查：','Last checked: '],['已创建 ','Created '],['新密码：','New password: ']]){
   if(value.startsWith(prefix))return label+translate(value.slice(prefix.length));
  }
  for(const separator of [' · ',' / ','、']){
   if(value.includes(separator))return value.split(separator).map(v=>translate(v.trim())).join(separator==='、'?', ':separator);
  }
  return value;
 }
 window.kfText=translate;window.kfLanguage=()=>language;
 const original=new WeakMap(),attributes=new WeakMap();
 function renderText(node){
  const old=original.get(node),current=node.nodeValue;
  const source=old&&current===old.rendered?old.source:(reverse[current.trim()]||current);
  const trim=source.trim(),translated=language==='en'?translate(trim):trim;
  const rendered=source.replace(trim,translated);
  original.set(node,{source,rendered});if(node.nodeValue!==rendered)node.nodeValue=rendered;
 }
 let rendering=false;
 function localize(){
  if(rendering||!document.body)return;rendering=true;
  try{
   const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,{acceptNode:n=>n.parentElement.closest('script,style,textarea,pre,[data-user-content]')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});
   const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
   for(const n of nodes){
    const parent=n.parentElement;
    if(parent.tagName==='OPTION'&&!parent.hasAttribute('value'))parent.setAttribute('value',parent.textContent);
    renderText(n);
   }
   document.querySelectorAll('[placeholder],[title],[aria-label],[data-label]').forEach(e=>{
    if(e.closest('[data-user-content]'))return;
    const map=attributes.get(e)||{};
    for(const key of ['placeholder','title','aria-label','data-label']){
     if(!e.hasAttribute(key))continue;
     const current=e.getAttribute(key),old=map[key],source=old&&current===old.rendered?old.source:(reverse[current]||current);
     const rendered=language==='en'?translate(source):source;map[key]={source,rendered};if(current!==rendered)e.setAttribute(key,rendered);
    }attributes.set(e,map);
   });
   const title=document.querySelector('title');if(title)renderText(title.firstChild);
  }finally{rendering=false;}
 }
 // Native dialogs are UI too; preserve their synchronous behavior.
 for(const name of ['alert','confirm','prompt']){const native=window[name].bind(window);window[name]=(message,...args)=>native(translate(String(message)),...args);}
 let scheduled=false;
 const observer=new MutationObserver(()=>{if(!scheduled){scheduled=true;queueMicrotask(()=>{scheduled=false;localize();});}});
 function apply(){root.lang=language==='en'?'en':'zh-CN';paintTheme();localize();document.querySelectorAll('[data-ui-theme]').forEach(e=>e.value=theme);document.querySelectorAll('[data-ui-language]').forEach(e=>e.value=language);}
 document.addEventListener('DOMContentLoaded',()=>{
  document.head.append(css);
  const target=document.querySelector('.topbar')||document.querySelector('.box');if(!target)return;
  const bar=document.createElement('div');bar.className='ui-preferences';
  bar.innerHTML='<label for="uiTheme">主题 <select id="uiTheme" data-ui-theme><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option></select></label><label for="uiLanguage">语言 <select id="uiLanguage" data-ui-language><option value="zh">中文</option><option value="en">English</option></select></label>';
  if(target.classList.contains('box'))target.prepend(bar);else target.insertBefore(bar,target.querySelector('.who'));
  bar.addEventListener('change',e=>{
   if(e.target.matches('[data-ui-theme]'))theme=e.target.value;
   if(e.target.matches('[data-ui-language]'))language=e.target.value;
   try{localStorage.setItem(keyTheme,theme);localStorage.setItem(keyLanguage,language);}catch(_){}
   apply();
  });
  observer.observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['placeholder','title','aria-label','data-label']});apply();
 });
 media.addEventListener('change',paintTheme);
 window.addEventListener('storage',e=>{if(e.key===keyTheme&&['system','light','dark'].includes(e.newValue))theme=e.newValue;if(e.key===keyLanguage&&['zh','en'].includes(e.newValue))language=e.newValue;apply();});
})();

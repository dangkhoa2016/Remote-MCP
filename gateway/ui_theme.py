"""Shared responsive styling and safe username normalization for owner pages."""
from __future__ import annotations

import html


def normalize_username(value: str) -> str:
    """Remove all Unicode whitespace from a supplied username, not passwords."""
    return "".join(value.split()) if isinstance(value, str) else ""


STYLES = """
:root{color-scheme:light;--ink:#19283f;--muted:#62748b;--line:#dce5f1;--blue:#2856ad;--blue-dark:#173c80;--bg:#f3f7fc;--paper:#fff}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 90% 0,#e5edff,transparent 43%),var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
h1,h2,p{margin-top:0}h1{font-size:clamp(1.7rem,3vw,2.2rem);line-height:1.16;letter-spacing:-.035em}h2{font-size:1.14rem;line-height:1.3}
p{color:var(--muted)}a{color:var(--blue);text-underline-offset:3px}button,input{font:inherit}
.page{width:min(100%,1020px);margin:auto;padding:clamp(20px,4vw,44px) 18px 70px}
.brand{display:flex;align-items:center;gap:12px;min-width:0}
.brand-icon{display:grid;place-items:center;flex:none;width:43px;height:43px;border-radius:13px;background:#203e7e;color:#fff;font-size:13px;font-weight:800}
.brand-title{display:block;color:var(--ink);font-size:1rem;font-weight:800}.brand-subtitle{display:block;font-size:.78rem;color:var(--muted)}
.card{background:var(--paper);border:1px solid var(--line);border-radius:19px;padding:clamp(20px,4vw,32px);box-shadow:0 22px 60px -45px #183b67}
.eyebrow{color:var(--blue);font-size:.73rem;letter-spacing:.12em;text-transform:uppercase;font-weight:800;margin:0 0 10px}
.auth{max-width:485px;margin:clamp(22px,6vh,65px) auto 0}.auth>.brand{margin:0 0 25px 3px}.auth-card{padding:clamp(24px,5vw,40px)}
.lead{line-height:1.6;font-size:.94rem}.field{margin:0 0 18px}.field label{display:block;font-weight:700;font-size:.88rem;margin-bottom:7px}
.field input{display:block;width:100%;min-height:46px;padding:10px 13px;border:1px solid #bdcadb;border-radius:10px;color:var(--ink);background:white}
.field input:focus-visible,.btn:focus-visible{outline:3px solid #a4c4ff;outline-offset:2px;border-color:var(--blue)}
.hint{display:block;font-size:.78rem;color:var(--muted);margin-top:6px}
.btn{appearance:none;display:inline-flex;align-items:center;justify-content:center;min-height:44px;border-radius:10px;padding:10px 17px;border:1px solid transparent;font-weight:750;text-decoration:none;cursor:pointer}
.btn-primary{background:var(--blue);color:white}.btn-primary:hover{background:var(--blue-dark)}
.btn-secondary{background:white;color:var(--ink);border-color:#cbd5e1}.btn-secondary:hover{background:#f0f4fa}
.btn:disabled{opacity:.6;cursor:wait}.btn-block{width:100%}
.help{margin:22px 0 0;padding:13px 15px;background:#eef4ff;border:1px solid #dce7ff;border-radius:12px;font-size:.82rem;color:#4a6285}
.topbar{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:36px}.intro{max-width:750px;margin-bottom:25px}
.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-bottom:23px}
.stat{background:white;border:1px solid var(--line);border-radius:15px;padding:18px 22px}
.stat-label{display:block;color:var(--muted);font-size:.8rem;font-weight:650}.stat-value{display:block;font-size:1.65rem;font-weight:800;letter-spacing:-.035em}
.section{margin-top:18px}.section-head{display:flex;align-items:baseline;justify-content:space-between;gap:14px;margin-bottom:18px}.section-head h2{margin:0}
.small{color:var(--muted);font-size:.82rem}.devices{display:grid;gap:12px}
.device{display:grid;grid-template-columns:minmax(0,1fr) minmax(210px,320px);gap:22px;padding:18px;border:1px solid var(--line);border-radius:13px;background:#f8fafd}
.device-title{margin:0 0 10px;color:var(--ink);font-weight:800}.device-meta{display:grid;gap:5px;font-size:.82rem;color:var(--muted)}
.device-meta strong{color:#415471}code{font:600 .84rem/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}
.device form{min-width:0}.device form .field{margin-bottom:10px}.device form .btn{width:100%}
.enrolled{list-style:none;padding:0;margin:0;display:grid;gap:9px}
.enrolled li{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 15px;border:1px solid var(--line);border-radius:11px}
.pill{display:inline-flex;padding:4px 10px;border-radius:99px;background:#edf1f7;color:#53657c;font-size:.75rem;font-weight:750}
.pill-active{background:#e9f7ed;color:#166534}
.empty{text-align:center;padding:26px 12px;background:#f8fafd;border-radius:12px}.empty strong{display:block;color:var(--ink)}
.notice{padding:13px 17px;border:1px solid;border-radius:12px;margin:0 0 18px}
.notice-success{color:#166534;background:#edf9f0;border-color:#b8e9c5}.notice-error{color:#b42318;background:#fff1f1;border-color:#ffc8c8}
.footnote{margin:18px 0 0;font-size:.79rem}
@media(max-width:720px){.page{padding:20px 14px 55px}.topbar{flex-wrap:wrap}.device{grid-template-columns:1fr;gap:16px}.auth{margin-top:27px}}
@media(max-width:420px){.stats{gap:9px}.stat{padding:15px}.topbar .btn{width:100%}.section-head{display:block}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important}}
"""


def login_form(*, action: str, nonce: str, title: str, description: str,
               button_text: str, help_text: str) -> str:
    """Use identical, escaped sign-in components for OAuth and device admin."""
    esc = lambda s: html.escape(s, quote=True)
    return f"""<section class="auth">
<header class="brand"><span class="brand-icon" aria-hidden="true">RM</span>
<span><span class="brand-title">Remote-MCP</span>
<span class="brand-subtitle">Secure connection</span></span></header>
<div class="card auth-card">
<p class="eyebrow">Secure sign-in</p><h1>{esc(title)}</h1>
<p class="lead">{esc(description)}</p>
<form id="krw-login-form" action="{esc(action)}" method="post">
<input type="hidden" name="nonce" value="{esc(nonce)}">
<div class="field"><label for="username">Username</label>
<input id="username" name="username" type="text" autocomplete="username"
maxlength="256" autocapitalize="off" spellcheck="false" required>
<span class="hint">Spaces and line breaks are removed automatically.</span></div>
<div class="field"><label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required></div>
<button class="btn btn-primary btn-block" type="submit">{esc(button_text)}</button>
</form><p class="help">{esc(help_text)}</p></div></section>"""

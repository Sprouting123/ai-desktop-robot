#pragma once
#include <Arduino.h>

// Single-file control page. It is stored in flash and served from this device:
// no CDN, web font, analytics or other external request is used. The access
// token is entered by the user and kept in a JavaScript variable only; it is
// never written into the URL, localStorage or sessionStorage.
const char kControlPage[] PROGMEM = R"HTML(<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>ESP32-S3 桌宠控制台</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f3f5f9;
    --card: #ffffff;
    --text: #1b2330;
    --muted: #667085;
    --line: #dfe4ec;
    --accent: #2f6fed;
    --accent-soft: #e8efff;
    --danger: #c62828;
    --danger-soft: #fdecec;
    --ok: #177245;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #11161f;
      --card: #1a2230;
      --text: #e8edf5;
      --muted: #9aa6b8;
      --line: #2c384b;
      --accent: #7aa2ff;
      --accent-soft: #1e2c46;
      --danger: #ff6b6b;
      --danger-soft: #3a1f24;
      --ok: #6fd6a0;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 18px 16px calc(28px + env(safe-area-inset-bottom));
    background: var(--bg);
    color: var(--text);
    font: 15px/1.55 system-ui, -apple-system, "Segoe UI", "Noto Sans SC", sans-serif;
  }
  main { width: 100%; max-width: 640px; margin: 0 auto; }
  header { margin: 4px 2px 16px; }
  h1 { margin: 0; font-size: 1.45rem; letter-spacing: .01em; }
  .sub { margin: 4px 0 0; color: var(--muted); font-size: .92rem; }
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 14px 16px;
    margin: 0 0 12px;
    box-shadow: 0 1px 2px rgba(16, 24, 40, .04);
  }
  h2 { margin: 0 0 10px; font-size: 1rem; }
  .rows { display: grid; gap: 7px; }
  .row { display: flex; gap: 12px; justify-content: space-between; align-items: baseline; }
  .row span { color: var(--muted); flex: 0 0 auto; }
  .row strong { font-weight: 600; text-align: right; overflow-wrap: anywhere; }
  .hint { margin: 8px 0 0; color: var(--muted); font-size: .85rem; }
  .token-row { display: flex; gap: 8px; flex-wrap: wrap; }
  input[type=password] {
    flex: 1 1 190px;
    min-width: 0;
    padding: 10px 12px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--bg);
    color: var(--text);
    font: inherit;
  }
  button {
    padding: 10px 14px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--card);
    color: var(--text);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  button:active { transform: translateY(1px); }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .buttons { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 8px; }
  .buttons button { background: var(--accent-soft); border-color: transparent; }
  .stop {
    display: block;
    width: 100%;
    margin: 4px 0 8px;
    padding: 16px;
    font-size: 1.08rem;
    background: var(--danger);
    border-color: var(--danger);
    color: #fff;
    border-radius: 14px;
  }
  pre {
    margin: 0;
    padding: 10px 12px;
    background: var(--bg);
    border: 1px solid var(--line);
    border-radius: 10px;
    color: var(--muted);
    font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    min-height: 2.7em;
  }
  .ok { color: var(--ok); }
  .bad { color: var(--danger); }
</style>
</head>
<body>
<main>
  <header>
    <h1>ESP32-S3 桌宠控制台</h1>
    <p class="sub">仅限可信家庭局域网 · HTTP 明文，请勿映射到公网</p>
  </header>

  <section class="card">
    <h2>设备状态</h2>
    <div class="rows">
      <div class="row"><span>Wi-Fi</span><strong id="wifi">读取中…</strong></div>
      <div class="row"><span>IP / RSSI</span><strong id="net">—</strong></div>
      <div class="row"><span>表情</span><strong id="expression">—</strong></div>
      <div class="row"><span>情绪标签</span><strong id="mood">—</strong></div>
      <div class="row"><span>动作</span><strong id="motion">—</strong></div>
      <div class="row"><span>舵机 1</span><strong id="servo1">—</strong></div>
      <div class="row"><span>舵机 2</span><strong id="servo2">—</strong></div>
      <div class="row"><span>运行时间</span><strong id="uptime">—</strong></div>
    </div>
  </section>

  <section class="card">
    <h2>访问令牌</h2>
    <p class="hint">写入动作必须携带令牌。令牌只保存在本页内存，刷新后需重新输入；不会写入网址或浏览器存储。</p>
    <div class="token-row">
      <input id="token" type="password" autocomplete="off" autocapitalize="off"
             spellcheck="false" placeholder="粘贴 X-Auth-Token">
      <button id="save" class="primary" type="button">保存到本页</button>
    </div>
    <p class="hint" id="tokenState">未设置令牌</p>
  </section>

  <section class="card">
    <h2>情绪与表情</h2>
    <div class="buttons">
      <button type="button" data-mood="happy">开心</button>
      <button type="button" data-mood="sad">难过</button>
      <button type="button" data-mood="angry">生气</button>
      <button type="button" data-mood="normal">平静</button>
    </div>
  </section>

  <section class="card">
    <h2>动作</h2>
    <div class="buttons">
      <button type="button" data-motion="wiggle">摆动</button>
      <button type="button" data-motion="together">同步</button>
      <button type="button" data-motion="alternate">交替</button>
    </div>
    <p class="hint">动作有固定步数，结束后回到中位并保持输出。</p>
  </section>

  <button id="stop" class="stop" type="button">立即停止动作（保留表情）</button>
  <p class="hint">停止只关闭软件 PWM 输出，不会切断外部 5V，也不是机械制动。</p>

  <section class="card">
    <h2>最近响应</h2>
    <pre id="log">—</pre>
  </section>
</main>
<script>
(function () {
  "use strict";
  var token = "";
  var $ = function (id) { return document.getElementById(id); };

  function setLog(text, bad) {
    var el = $("log");
    el.textContent = text;
    el.className = bad ? "bad" : "";
  }

  function servoText(s) {
    if (!s) return "—";
    return s.angle + "° → " + s.target + "° · " +
      (s.moving ? "运动中" : (s.output === "on" ? "保持" : "输出关闭"));
  }

  function update(data) {
    var wifiNames = {
      connected: "已连接", connecting: "连接中", backoff: "等待重试",
      disabled: "未配置"
    };
    $("wifi").textContent = wifiNames[data.wifi.state] || data.wifi.state;
    $("net").textContent = data.wifi.state === "connected"
      ? data.wifi.ip + " · " + data.wifi.rssi + " dBm"
      : data.wifi.ip;
    $("expression").textContent = data.expression;
    $("mood").textContent = data.mood;
    $("motion").textContent = data.motion.name + " · " + data.motion.state +
      (data.motion.total ? " · " + data.motion.step + "/" + data.motion.total : "");
    $("servo1").textContent = servoText(data.servo1);
    $("servo2").textContent = servoText(data.servo2);
    $("uptime").textContent = Math.floor(data.uptime_ms / 1000) + " 秒";
  }

  function poll() {
    fetch("/api/status", { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(update)
      .catch(function () { $("wifi").textContent = "设备不可达"; });
  }

  function send(path, name) {
    if (!token) {
      setLog("请先输入并保存访问令牌。", true);
      return;
    }
    fetch(path, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Auth-Token": token
      },
      body: JSON.stringify({ name: name })
    }).then(function (res) {
      return res.text().then(function (text) {
        var bad = res.status !== 200;
        var prefix = "";
        if (res.status === 401) prefix = "缺少令牌：";
        else if (res.status === 403) prefix = "令牌无效：";
        else if (res.status === 429) prefix = "请求过于频繁：";
        else if (res.status === 503) prefix = "服务未就绪：";
        setLog(prefix + "HTTP " + res.status + "\n" + text, bad);
        poll();
      });
    }).catch(function (err) {
      setLog("请求失败：" + err, true);
    });
  }

  $("save").addEventListener("click", function () {
    token = $("token").value.trim();
    $("token").value = "";
    $("tokenState").textContent = token ? "令牌已保存在本页内存" : "未设置令牌";
  });

  Array.prototype.forEach.call(document.querySelectorAll("[data-mood]"), function (b) {
    b.addEventListener("click", function () { send("/api/mood", b.dataset.mood); });
  });
  Array.prototype.forEach.call(document.querySelectorAll("[data-motion]"), function (b) {
    b.addEventListener("click", function () { send("/api/motion", b.dataset.motion); });
  });
  $("stop").addEventListener("click", function () { send("/api/mood", "stop"); });

  poll();
  setInterval(poll, 2000);
})();
</script>
</body>
</html>
)HTML";

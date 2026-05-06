/* XiaoHuang Voice Dock — Canvas waveform HUD */
(function () {
  'use strict';

  /* ─── State config ──────────────────────────────────── */
  var STATES = {
    idle:           { color: '#4dd0e1', glow: 'rgba(77,208,225,0.22)',  amp: 4,  speed: 1.0,  barCount: 42 },
    wake_checking:  { color: '#40c4ff', glow: 'rgba(64,196,255,0.25)',  amp: 5,  speed: 1.2,  barCount: 42 },
    wake_detected:  { color: '#00e5ff', glow: 'rgba(0,229,255,0.35)',   amp: 24, speed: 2.0,  barCount: 42 },
    listening:      { color: '#00e5ff', glow: 'rgba(0,229,255,0.38)',   amp: 32, speed: 2.4,  barCount: 42 },
    transcribing:   { color: '#18ffff', glow: 'rgba(24,255,255,0.32)',  amp: 20, speed: 1.8,  barCount: 42 },
    replying:       { color: '#448aff', glow: 'rgba(68,138,255,0.30)',  amp: 20, speed: 1.7,  barCount: 42 },
    speaking:       { color: '#b388ff', glow: 'rgba(179,136,255,0.32)', amp: 28, speed: 2.2,  barCount: 42 },
    result:         { color: '#00e676', glow: 'rgba(0,230,118,0.22)',   amp: 6,  speed: 0.9,  barCount: 42 },
    error:          { color: '#ff5252', glow: 'rgba(255,82,82,0.30)',   amp: 14, speed: 2.8,  barCount: 42 }
  };

  var stateKey = 'idle';
  var stateCfg = STATES.idle;
  var targetCfg = STATES.idle;
  var visible = true;
  var phase = 0;
  var animId = null;
  var flashPhase = 0;
  var flashIntensity = 0;

  /* ─── DOM refs ─────────────────────────────────────── */
  var anchor = document.getElementById('hud-anchor');
  var canvas = document.getElementById('waveCanvas');
  var ctx = canvas.getContext('2d');
  var W = canvas.width;
  var H = canvas.height;

  /* ─── Color interpolation ──────────────────────────── */
  function hexToRgb(hex) {
    var v = parseInt(hex.slice(1), 16);
    return { r: (v >> 16) & 255, g: (v >> 8) & 255, b: v & 255 };
  }

  function lerpColor(c1, c2, t) {
    t = Math.max(0, Math.min(1, t));
    return {
      r: Math.round(c1.r + (c2.r - c1.r) * t),
      g: Math.round(c1.g + (c2.g - c1.g) * t),
      b: Math.round(c1.b + (c2.b - c1.b) * t)
    };
  }

  function rgbStr(c) { return 'rgb(' + c.r + ',' + c.g + ',' + c.b + ')'; }
  function rgbaStr(c, a) { return 'rgba(' + c.r + ',' + c.g + ',' + c.b + ',' + a + ')'; }

  var curColor = hexToRgb(STATES.idle.color);
  var curGlow = STATES.idle.glow;
  var curAmp = STATES.idle.amp;
  var curSpeed = STATES.idle.speed;

  /* ─── Flash on state change ────────────────────────── */
  function flashOnChange(newKey) { flashPhase = 0; flashIntensity = 1.0; }

  /* ─── Apply state ──────────────────────────────────── */
  function applyState(key) {
    if (!STATES[key]) return;
    if (key !== stateKey) flashOnChange(key);
    stateKey = key;
    targetCfg = STATES[key];
  }

  /* ─── Render frame ─────────────────────────────────── */
  function frame() {
    if (!visible && flashIntensity <= 0.01) {
      ctx.clearRect(0, 0, W, H);
      animId = requestAnimationFrame(frame);
      return;
    }

    ctx.clearRect(0, 0, W, H);

    /* Smoothly blend toward target */
    var t = 0.12;
    var tc = hexToRgb(targetCfg.color);
    curColor = lerpColor(curColor, tc, t);
    curGlow = interpolateGlow(curGlow, targetCfg.glow, t);
    curAmp = curAmp + (targetCfg.amp - curAmp) * t;
    curSpeed = curSpeed + (targetCfg.speed - curSpeed) * t;

    /* Flash decay */
    flashIntensity = Math.max(0, flashIntensity - 0.04);
    var flashColor = flashIntensity > 0
      ? { r: 255, g: 255, b: 255 } : null;

    var baseColor = flashColor
      ? lerpColor(curColor, flashColor, flashIntensity * 0.6)
      : curColor;

    phase += curSpeed * 0.05;

    var n = Math.round(curAmp > 16 ? targetCfg.barCount + 10 : targetCfg.barCount);
    var barW = 3;
    var gap = (W - 10) / n - barW;
    var cx = W / 2;
    var cy = H / 2;

    /* ── Glow underlay ── */
    ctx.save();
    ctx.globalAlpha = 0.45;
    for (var i = 0; i < n; i++) {
      var off = 0.25 + 0.75 * Math.abs(Math.sin(phase * 1.3 + i * 0.55));
      var h = 3 + (curAmp * 1.5) * off;
      var x = 5 + i * (barW + gap);
      var y1 = cy - h / 2;
      ctx.fillStyle = rgbStr(baseColor);
      ctx.fillRect(x, y1, barW, h);
    }
    ctx.restore();

    /* ── Main waveform bars ── */
    for (var i2 = 0; i2 < n; i2++) {
      var off2 = 0.22 + 0.78 * Math.abs(Math.sin(phase * 1.5 + i2 * 0.5));
      var h2 = Math.max(2, 2 + curAmp * off2);
      var x2 = 5 + i2 * (barW + gap);
      var y2 = cy - h2 / 2;
      ctx.fillStyle = rgbStr(baseColor);
      ctx.fillRect(x2, y2, barW, h2);
    }

    /* ── Center glow line ── */
    ctx.save();
    ctx.globalAlpha = 0.35 + 0.15 * Math.sin(phase * 2);
    ctx.strokeStyle = rgbStr(baseColor);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (var i3 = 0; i3 < n; i3++) {
      var off3 = 0.22 + 0.78 * Math.abs(Math.sin(phase * 1.5 + i3 * 0.5));
      var h3 = Math.max(2, 2 + curAmp * off3);
      var x3 = 5 + i3 * (barW + gap);
      var yTop = cy - h3 / 2;
      if (i3 === 0) ctx.moveTo(x3 + barW / 2, yTop);
      else ctx.lineTo(x3 + barW / 2, yTop);
    }
    ctx.stroke();
    ctx.restore();

    /* ── Mirror bottom glow ── */
    ctx.save();
    ctx.globalAlpha = 0.18;
    ctx.strokeStyle = rgbStr(baseColor);
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (var i4 = 0; i4 < n; i4++) {
      var off4 = 0.22 + 0.78 * Math.abs(Math.sin(phase * 1.5 + i4 * 0.5));
      var h4 = Math.max(2, 2 + curAmp * off4);
      var x4 = 5 + i4 * (barW + gap);
      var yBot = cy + h4 / 2;
      if (i4 === 0) ctx.moveTo(x4 + barW / 2, yBot);
      else ctx.lineTo(x4 + barW / 2, yBot);
    }
    ctx.stroke();
    ctx.restore();

    animId = requestAnimationFrame(frame);
  }

  function interpolateGlow(from, to, t) {
    var fr = parseGlow(from);
    var tr = parseGlow(to);
    var r = Math.round(fr[0] + (tr[0] - fr[0]) * t);
    var g = Math.round(fr[1] + (tr[1] - fr[1]) * t);
    var b = Math.round(fr[2] + (tr[2] - fr[2]) * t);
    var a = fr[3] + (tr[3] - fr[3]) * t;
    return 'rgba(' + r + ',' + g + ',' + b + ',' + a.toFixed(3) + ')';
  }

  function parseGlow(g) {
    var m = g.match(/[\d.]+/g);
    if (!m || m.length < 4) return [77, 208, 225, 0.22];
    return [parseInt(m[0]), parseInt(m[1]), parseInt(m[2]), parseFloat(m[3])];
  }

  /* ─── Visibility ───────────────────────────────────── */
  function fadeIn() {
    visible = true;
    anchor.classList.add('visible');
    anchor.classList.remove('hiding');
  }

  function fadeOut() {
    anchor.classList.add('hiding');
    anchor.classList.remove('visible');
    setTimeout(function () { visible = false; }, 500);
  }

  /* ─── Resize handler ──────────────────────────────── */
  function onResize() {
    W = canvas.width = canvas.clientWidth || 660;
    H = canvas.height = canvas.clientHeight || 110;
  }
  window.addEventListener('resize', onResize);

  /* ─── Public API ───────────────────────────────────── */
  window.XiaoHuangHUD = {
    setState: function (key) { applyState(key); },
    fadeIn: fadeIn,
    fadeOut: fadeOut,
    setVisible: function (v) { if (v) fadeIn(); else fadeOut(); },
    getState: function () { return stateKey; }
  };

  /* ─── Init ─────────────────────────────────────────── */
  onResize();
  applyState('idle');
  visible = true;
  fadeIn();
  animId = requestAnimationFrame(frame);
})();

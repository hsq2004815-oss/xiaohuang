/* 小黄 · 纯音波浮窗 — Canvas waveform engine */
(function () {
  'use strict';

  /* ══════════════════════════════════════════════════════════
     STATES — exact copy from prototype
     ══════════════════════════════════════════════════════════ */
  var STATES = {
    idle: {
      tag: 'IDLE', name: '空闲',
      color: '#4a9eff',
      amp: 3.2, speed: 0.65, layers: 3, style: 'breathe', pulse: 2.6
    },
    wake_checking: {
      tag: 'WAKE CHECK', name: '唤醒检测',
      color: '#3d8bfd',
      amp: 5.5, speed: 1.1, layers: 4, style: 'scan', pulse: 1.7
    },
    wake_detected: {
      tag: 'DETECTED', name: '已唤醒',
      color: '#00e5a0',
      amp: 13, speed: 1.5, layers: 5, style: 'active', pulse: 1.1
    },
    listening: {
      tag: 'LISTENING', name: '正在听',
      color: '#00e5a0',
      amp: 15, speed: 1.65, layers: 5, style: 'active', pulse: 0.9
    },
    transcribing: {
      tag: 'TRANSCRIBING', name: '正在转写',
      color: '#7c6fff',
      amp: 8, speed: 1.2, layers: 4, style: 'mid', pulse: 1.4
    },
    replying: {
      tag: 'REPLYING', name: '正在回答',
      color: '#00b4ff',
      amp: 9, speed: 1.15, layers: 4, style: 'mid', pulse: 1.4
    },
    speaking: {
      tag: 'SPEAKING', name: '正在播报',
      color: '#9b6dff',
      amp: 20, speed: 1.9, layers: 6, style: 'heavy', pulse: 0.7
    },
    result: {
      tag: 'RESULT', name: '完成',
      color: '#00d68f',
      amp: 4.5, speed: 0.75, layers: 3, style: 'soft', pulse: 2.0
    },
    error: {
      tag: 'ERROR', name: '错误',
      color: '#ff4757',
      amp: 12, speed: 3.5, layers: 3, style: 'alert', pulse: 0.35
    }
  };

  /* ── DOM ─────────────────────────────────────────────── */
  var canvas = document.getElementById('waveCanvas');
  var ctx = canvas.getContext('2d');
  var hudAnchor = document.getElementById('hudAnchor');

  /* ── Live interpolation state ────────────────────────── */
  var currentKey = 'idle';
  var cfg = STATES.idle;
  var liveAmp = 0;
  var liveSpeed = cfg.speed;
  var liveR = 74, liveG = 158, liveB = 255;
  var tgtR = 74, tgtG = 158, tgtB = 255;
  var time = 0;
  var lastTs = 0;
  var flashAlpha = 0;
  var isVisible = false;
  var animId = null;

  /* ── hex2rgb ─────────────────────────────────────────── */
  function hex2rgb(hex) {
    return {
      r: parseInt(hex.slice(1, 3), 16),
      g: parseInt(hex.slice(3, 5), 16),
      b: parseInt(hex.slice(5, 7), 16)
    };
  }

  /* ══════════════════════════════════════════════════════════
     edgeFade — exact copy from prototype
     Smoothstep envelope: wide fade at ends, flat center
     ══════════════════════════════════════════════════════════ */
  function edgeFade(nx) {
    var fadeZone = 0.18;
    if (nx <= 0) return 0;
    if (nx >= 1) return 0;
    if (nx < fadeZone) {
      var t = nx / fadeZone;
      return t * t * (3 - 2 * t);
    }
    if (nx > 1 - fadeZone) {
      var t2 = (1 - nx) / fadeZone;
      return t2 * t2 * (3 - 2 * t2);
    }
    return 1;
  }

  /* ── fadeIn / fadeOut ────────────────────────────────── */
  function fadeIn() {
    hudAnchor.classList.remove('hiding');
    void hudAnchor.offsetHeight;
    hudAnchor.classList.add('visible');
    isVisible = true;
  }

  function fadeOut() {
    hudAnchor.classList.remove('visible');
    hudAnchor.classList.add('hiding');
    isVisible = false;
  }

  /* ── sizeCanvas with devicePixelRatio ────────────────── */
  function sizeCanvas() {
    var rect = canvas.getBoundingClientRect();
    var dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  window.addEventListener('resize', sizeCanvas);

  /* ── applyState ──────────────────────────────────────── */
  function applyState(key) {
    if (!STATES[key]) return;
    currentKey = key;
    cfg = STATES[key];
    var rgb = hex2rgb(cfg.color);
    tgtR = rgb.r; tgtG = rgb.g; tgtB = rgb.b;
    flashAlpha = 0.18;
  }

  /* ══════════════════════════════════════════════════════════
     frame(ts) — exact rendering loop from prototype
     ══════════════════════════════════════════════════════════ */
  function frame(ts) {
    if (!lastTs) lastTs = ts;
    var dt = Math.min((ts - lastTs) / 1000, 0.05);
    lastTs = ts;
    var k = 1 - Math.pow(0.035, dt);
    liveAmp += (cfg.amp - liveAmp) * k;
    liveSpeed += (cfg.speed - liveSpeed) * k;
    liveR += (tgtR - liveR) * k;
    liveG += (tgtG - liveG) * k;
    liveB += (tgtB - liveB) * k;
    if (flashAlpha > 0) flashAlpha = Math.max(0, flashAlpha - dt * 1.6);
    time += dt * liveSpeed;
    var w = canvas.getBoundingClientRect().width;
    var h = canvas.getBoundingClientRect().height;
    var cy = h / 2;
    ctx.clearRect(0, 0, w, h);
    var r = Math.round(liveR);
    var g = Math.round(liveG);
    var b = Math.round(liveB);
    var style = cfg.style;
    var layers = cfg.layers;

    /* --- 多层音波 --- */
    for (var i = layers - 1; i >= 0; i--) {
      var t = i / layers;
      var opacity = 0.06 + (1 - t) * 0.28;
      var phOff = i * 0.62;
      var fMul = 1 + i * 0.18;
      var lw = Math.max(0.5, 1.7 - i * 0.18);
      var amp = liveAmp;
      switch (style) {
        case 'breathe': amp *= 0.42 + 0.58 * Math.sin(time * 0.55 + i * 0.32); break;
        case 'scan':    amp *= 0.5  + 0.5  * Math.sin(time * 0.8  + i * 0.28); break;
        case 'active':  amp *= 0.62 + 0.38 * Math.sin(time * 1.25 + i * 0.48); break;
        case 'mid':     amp *= 0.68 + 0.32 * Math.sin(time * 0.95 + i * 0.38); break;
        case 'heavy':   amp *= (0.52 + 0.48 * Math.sin(time * 1.55 + i * 0.52)) * 1.18; break;
        case 'soft':    amp *= 0.38 + 0.62 * Math.sin(time * 0.42 + i * 0.22); break;
        case 'alert':   amp *= Math.abs(Math.sin(time * 5.5)) > 0.35 ? 1.0 : 0.12; break;
      }
      ctx.beginPath();
      ctx.strokeStyle = 'rgba(' + r + ',' + g + ',' + b + ',' + opacity.toFixed(3) + ')';
      ctx.lineWidth = lw;
      for (var x = 0; x <= w; x += 2) {
        var nx = x / w;
        var env = edgeFade(nx);
        var s1 = Math.sin(nx * 6.8  * fMul + time * 2.05 + phOff);
        var s2 = Math.sin(nx * 10.2 * fMul + time * 1.62 + phOff * 1.35);
        var s3 = Math.sin(nx * 3.4  * fMul + time * 2.55 + phOff * 0.75);
        var s4 = Math.sin(nx * 15.0 * fMul + time * 1.15 + phOff * 0.45) * 0.12;
        var val = (s1 * 0.54 + s2 * 0.24 + s3 * 0.14 + s4) * amp * env;
        var y = cy + val;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    /* --- 中心发光主线 --- */
    ctx.save();
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(' + r + ',' + g + ',' + b + ',0.78)';
    ctx.lineWidth = 2.2;
    ctx.shadowColor = 'rgba(' + r + ',' + g + ',' + b + ',0.85)';
    ctx.shadowBlur = 18;
    for (var x2 = 0; x2 <= w; x2 += 2) {
      var nx2 = x2 / w;
      var env2 = edgeFade(nx2);
      var s1_2 = Math.sin(nx2 * 7.2 + time * 2.2);
      var s2_2 = Math.sin(nx2 * 11.5 + time * 1.68);
      var val2 = (s1_2 * 0.58 + s2_2 * 0.42) * liveAmp * 0.82 * env2;
      var y2 = cy + val2;
      if (x2 === 0) ctx.moveTo(x2, y2);
      else ctx.lineTo(x2, y2);
    }
    ctx.stroke();
    ctx.restore();

    /* --- 下方渐变填充 --- */
    ctx.save();
    ctx.beginPath();
    for (var x3 = 0; x3 <= w; x3 += 3) {
      var nx3 = x3 / w;
      var env3 = edgeFade(nx3);
      var s1_3 = Math.sin(nx3 * 7.2 + time * 2.2);
      var s2_3 = Math.sin(nx3 * 11.5 + time * 1.68);
      var val3 = (s1_3 * 0.58 + s2_3 * 0.42) * liveAmp * 0.82 * env3;
      var y3 = cy + val3;
      if (x3 === 0) ctx.moveTo(x3, y3);
      else ctx.lineTo(x3, y3);
    }
    ctx.lineTo(w, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    var gf = ctx.createLinearGradient(0, cy, 0, h);
    gf.addColorStop(0, 'rgba(' + r + ',' + g + ',' + b + ',0.06)');
    gf.addColorStop(1, 'rgba(' + r + ',' + g + ',' + b + ',0.0)');
    ctx.fillStyle = gf;
    ctx.fill();
    ctx.restore();

    /* --- 上方淡填充 --- */
    ctx.save();
    ctx.beginPath();
    for (var x4 = 0; x4 <= w; x4 += 3) {
      var nx4 = x4 / w;
      var env4 = edgeFade(nx4);
      var s1_4 = Math.sin(nx4 * 7.2 + time * 2.2);
      var s2_4 = Math.sin(nx4 * 11.5 + time * 1.68);
      var val4 = (s1_4 * 0.58 + s2_4 * 0.42) * liveAmp * 0.82 * env4;
      var y4 = cy + val4;
      if (x4 === 0) ctx.moveTo(x4, y4);
      else ctx.lineTo(x4, y4);
    }
    ctx.lineTo(w, 0);
    ctx.lineTo(0, 0);
    ctx.closePath();
    var gt = ctx.createLinearGradient(0, cy, 0, 0);
    gt.addColorStop(0, 'rgba(' + r + ',' + g + ',' + b + ',0.035)');
    gt.addColorStop(1, 'rgba(' + r + ',' + g + ',' + b + ',0.0)');
    ctx.fillStyle = gt;
    ctx.fill();
    ctx.restore();

    /* --- 边缘渐隐遮罩 (destination-out) --- */
    ctx.save();
    ctx.globalCompositeOperation = 'destination-out';
    var fadeW = w * 0.15;
    var lg = ctx.createLinearGradient(0, 0, fadeW, 0);
    lg.addColorStop(0, 'rgba(0,0,0,1)');
    lg.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = lg;
    ctx.fillRect(0, 0, fadeW, h);
    var rg = ctx.createLinearGradient(w - fadeW, 0, w, 0);
    rg.addColorStop(0, 'rgba(0,0,0,0)');
    rg.addColorStop(1, 'rgba(0,0,0,1)');
    ctx.fillStyle = rg;
    ctx.fillRect(w - fadeW, 0, fadeW, h);
    ctx.restore();

    /* --- 状态切换闪光 --- */
    if (flashAlpha > 0.005) {
      ctx.save();
      ctx.globalCompositeOperation = 'source-over';
      ctx.fillStyle = 'rgba(' + r + ',' + g + ',' + b + ',' + (flashAlpha * 0.12).toFixed(4) + ')';
      ctx.fillRect(0, 0, w, h);
      ctx.restore();
    }

    animId = requestAnimationFrame(frame);
  }

  /* ── Public API for Python bridge ─────────────────────── */
  window.XiaoHuangHUD = {
    setState: function (key) { applyState(key); },
    fadeIn: fadeIn,
    fadeOut: fadeOut,
    setVisible: function (v) { if (v) fadeIn(); else fadeOut(); },
    getState: function () { return currentKey; }
  };

  /* ── Init ─────────────────────────────────────────────── */
  sizeCanvas();
  applyState('idle');
  fadeIn();
  animId = requestAnimationFrame(frame);
})();

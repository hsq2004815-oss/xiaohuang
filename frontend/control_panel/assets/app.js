/* XiaoHuang Control Center — app.js */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var opHistory = [];
  var bridgeReady = false;
  var initDone = false;

  /* ─── API: lazy bridge lookup ─── */
  function getApi() {
    if (window.pywebview && window.pywebview.api) return window.pywebview.api;
    return null;
  }

  function call(method) {
    var args = Array.prototype.slice.call(arguments, 1);
    var api = getApi();
    if (api) {
      try { return api[method].apply(api, args); }
      catch (e) { return Promise.resolve({ ok: false, error: String(e), code: 'js_error' }); }
    }
    return Promise.resolve({ ok: false, error: '桌面桥接未连接', code: 'NO_BRIDGE' });
  }

  /* ─── Toast ─── */
  function toast(msg, type) {
    var el = document.createElement('div');
    el.className = 'glass-toast ' + (type || 'info');
    el.textContent = msg;
    $('toast-container').appendChild(el);
    setTimeout(function () { el.remove(); }, 4200);
  }

  /* ─── Diagnostic drawer ─── */
  function drawerLog(op, ok, detail) {
    var now = new Date().toLocaleTimeString();
    opHistory.unshift({ time: now, op: op, ok: ok, detail: detail || '' });
    if (opHistory.length > 20) opHistory.length = 20;
    var html = '';
    opHistory.forEach(function (e) {
      html += '<div class="drawer-entry ' + (e.ok ? 'ok' : 'err') + '"><span class="ts">' + e.time + '</span>' + e.op + (e.detail ? ' — ' + e.detail : '') + '</div>';
    });
    $('drawer-history').innerHTML = html || '暂无操作记录';
    $('drawer-last-op').textContent = op + (ok ? ' ✓' : ' ✗');
  }

  /* ─── setVal / getVal ─── */
  function setVal(id, val) { var el = $(id); if (el) el.value = (val !== null && val !== undefined) ? val : ''; }
  function getVal(id) { var el = $(id); return el ? el.value : ''; }
  function setChecked(id, v) { var el = $(id); if (el) el.checked = !!v; }
  function getChecked(id) { var el = $(id); return el ? el.checked : false; }

  /* ─── Status text ─── */
  var S = {
    running: '运行中', stopped: '已停止', ready: '已就绪',
    unknown: '未知', error: '错误', loading: '加载中...',
    notDetected: '未检测到', notInstalled: 'pywebview 未安装',
  };

  /* ─── Bridge status ─── */
  function updateBridgeIndicator() {
    var api = getApi();
    var el = $('drawer-bridge-status');
    if (!el) return;
    if (api) {
      el.textContent = '已连接';
      el.className = 'drawer-value ok';
      enableControls(true);
    } else if (bridgeReady) {
      el.textContent = '等待注入...';
      el.className = 'drawer-value warn';
    } else {
      el.textContent = '连接中...';
      el.className = 'drawer-value';
    }
  }

  function enableControls(on) {
    $('btn-refresh').disabled = !on;
    $('btn-top-refresh').disabled = !on;
    $('btn-save-config').disabled = !on;
    // start/stop/restart controlled by status, not bridge
    if (on) {
      $('btn-start').disabled = false;
      $('btn-stop').disabled = true;
      $('btn-restart').disabled = true;
    } else {
      $('btn-start').disabled = true;
      $('btn-stop').disabled = true;
      $('btn-restart').disabled = true;
    }
  }

  /* ─── Render status ─── */
  function renderStatus(data) {
    var d = (data && data.ok && data.data) ? data.data : null;

    if (!d) {
      setStatusBadge(S.loading, 'off');
      if (data && !data.ok) {
        $('drawer-last-error').textContent = (data.error || '未知错误');
        $('drawer-last-error').style.color = 'var(--error)';
      }
      return;
    }

    var os = d.overall_status || 'UNKNOWN';
    var badgeCls = os === 'READY' ? '' : os === 'NOT_RUNNING' ? 'off' : os === 'ERROR' ? 'error' : 'warn';
    setStatusBadge(d.overall_message || os, badgeCls);
    setWakeBadge((d.wake_engine || 'stt_text'));

    // Neon status cards
    setCard('card-stt', d.stt_running ? S.running : S.notDetected, d.stt_running ? 'ok' : 'err');
    setCard('card-overlay', d.overlay_running ? S.running : S.notDetected, d.overlay_running ? 'ok' : 'err');
    setCard('card-wake', d.wake_engine || 'stt_text', d.can_wake_now ? 'ok' : 'off');
    setCard('card-assistant', d.assistant_display_name || '小黄', 'ok');

    // Action buttons
    var running = d.stt_running || d.overlay_running;
    if (getApi()) {
      $('btn-start').disabled = running;
      $('btn-stop').disabled = !running;
      $('btn-restart').disabled = !running;
    }

    // Wake settings form
    setVal('wake-engine', d.wake_engine || 'stt_text');
    setChecked('wake-fallback', d.wake_fallback_enabled !== false);
    setVal('wake-device', d.wake_device_index);
    setVal('wake-cooldown', d.wake_cooldown_seconds);
    setVal('wake-sensitivity', d.wake_sensitivity);

    // Runtime detail
    var rows = [
      ['STT 服务运行', d.stt_running], ['STT 就绪', d.stt_ready], ['模型已加载', d.stt_model_loaded],
      ['健康状态', d.stt_health_status], ['可唤醒', d.can_wake_now], ['TTS 启用', d.tts_enabled],
      ['LLM 提供方', d.llm_provider], ['配置文件路径', d.config_path], ['最近错误', d.last_error || '无'],
    ];
    $('runtime-detail').innerHTML = rows.map(function (r) {
      return '<div class="event-row"><span class="event-label">' + r[0] + '</span><span class="event-val">' + fmtVal(r[1]) + '</span></div>';
    }).join('');

    // Wake & Voice detail
    $('wake-voice-detail').innerHTML = [
      ['引擎', d.wake_engine],['兜底唤醒', d.wake_fallback_enabled],['设备', d.wake_device_index],
      ['冷却时间', (d.wake_cooldown_seconds || 0) + 's'],['灵敏度', d.wake_sensitivity],
      ['模型标签', d.wake_model_label || '--'],['唤醒词', (d.wake_phrases || []).join(', ')],
    ].map(function (r) { return '<div class="event-row"><span class="event-label">' + r[0] + '</span><span class="event-val">' + fmtVal(r[1]) + '</span></div>'; }).join('');

    // Recent events
    var ev = [
      ['总体状态', d.overall_message || os],['上次操作', d.last_operation || '无'],
      ['操作耗时', d.last_operation_elapsed_seconds ? d.last_operation_elapsed_seconds + 's' : '--'],
    ];
    $('events-list').innerHTML = ev.map(function (r) {
      return '<div class="event-row"><span class="event-label">' + r[0] + '</span><span class="event-val">' + r[1] + '</span></div>';
    }).join('');

    // Diagnostic drawer
    $('drawer-config-path').textContent = d.config_path || '--';
    $('drawer-last-error').textContent = d.last_error || '无';
    if (d.last_error) $('drawer-last-error').style.color = 'var(--error)';
  }

  function fmtVal(v) {
    if (v === undefined || v === null) return '--';
    if (typeof v === 'boolean') return v ? '是' : '否';
    return String(v);
  }

  function setStatusBadge(text, cls) {
    var b = $('top-status'); b.textContent = text; b.className = 'status-badge' + (cls ? ' ' + cls : '');
  }
  function setWakeBadge(text) { $('top-wake').textContent = text; }
  function setCard(id, text, cls) {
    var el = $(id); if (!el) return;
    el.textContent = text || '--'; el.className = 'card-value' + (cls ? ' ' + cls : '');
  }

  /* ─── Sidebar navigation ─── */
  function initNav() {
    document.querySelectorAll('.sidebar-item').forEach(function (item) {
      item.addEventListener('click', function () {
        document.querySelectorAll('.sidebar-item').forEach(function (i) { i.classList.remove('active'); });
        item.classList.add('active');
        var sec = item.getAttribute('data-section');
        document.querySelectorAll('.content-section').forEach(function (s) { s.classList.remove('active'); });
        var target = document.getElementById('section-' + sec);
        if (target) target.classList.add('active');
      });
    });
  }

  /* ─── Actions ─── */
  function refreshStatus() {
    updateBridgeIndicator();
    call('get_status').then(renderStatus).catch(function (e) { toast('刷新失败', 'err'); });
    call('get_log_paths').then(function (r) {
      if (r && r.ok && r.data) $('drawer-logs-path').textContent = r.data.logs_directory || '--';
    });
  }

  function doStart() {
    $('btn-start').disabled = true; $('btn-start').textContent = '启动中...';
    call('start_xiaohuang').then(function (r) {
      if (r && r.ok) { toast('启动成功', 'ok'); drawerLog('启动小黄', true); }
      else { toast((r && r.error) || '启动失败', 'err'); drawerLog('启动小黄', false, (r && r.error)); }
      setTimeout(refreshStatus, 3000);
    }).catch(function (e) { toast('启动出错', 'err'); });
  }

  function doStop() {
    $('btn-stop').disabled = true; $('btn-stop').textContent = '停止中...';
    call('stop_xiaohuang').then(function (r) {
      if (r && r.ok) { toast('已停止', 'ok'); drawerLog('停止小黄', true); }
      else { toast((r && r.error) || '停止失败', 'err'); drawerLog('停止小黄', false, (r && r.error)); }
      setTimeout(refreshStatus, 2000);
    }).catch(function (e) { toast('停止出错', 'err'); });
  }

  function doRestart() {
    $('btn-restart').disabled = true; $('btn-restart').textContent = '重启中...';
    call('restart_xiaohuang').then(function (r) {
      if (r && r.ok) { toast('重启成功', 'ok'); drawerLog('重启小黄', true); }
      else { toast((r && r.error) || '重启失败', 'err'); drawerLog('重启小黄', false, (r && r.error)); }
      setTimeout(refreshStatus, 5000);
    }).catch(function (e) { toast('重启出错', 'err'); });
  }

  function doSaveConfig() {
    var payload = {
      engine: getVal('wake-engine'), fallback_enabled: getChecked('wake-fallback'),
      device_index: getVal('wake-device'), cooldown_seconds: getVal('wake-cooldown'),
      sensitivity: getVal('wake-sensitivity'),
    };
    $('btn-save-config').disabled = true;
    call('save_wake_config', payload).then(function (r) {
      if (r && r.ok) { toast('配置已保存', 'ok'); $('wake-hint').textContent = '已保存，需重启小黄生效。'; drawerLog('保存配置', true); }
      else { toast((r && r.error) || '保存失败', 'err'); drawerLog('保存配置', false, (r && r.error)); }
      $('btn-save-config').disabled = false;
      refreshStatus();
    }).catch(function (e) { toast('保存出错', 'err'); $('btn-save-config').disabled = false; });
  }

  function doSaveAndRestart() {
    var payload = {
      engine: getVal('wake-engine'), fallback_enabled: getChecked('wake-fallback'),
      device_index: getVal('wake-device'), cooldown_seconds: getVal('wake-cooldown'),
      sensitivity: getVal('wake-sensitivity'),
    };
    $('btn-save-restart').disabled = true;
    call('save_wake_config', payload).then(function (r) {
      if (r && r.ok) { $('wake-hint').textContent = ''; doRestart(); }
      else { toast((r && r.error) || '保存失败', 'err'); drawerLog('保存并重启', false, (r && r.error)); $('btn-save-restart').disabled = false; }
    }).catch(function (e) { toast('保存出错', 'err'); $('btn-save-restart').disabled = false; });
  }

  /* ─── Init: pywebviewready-based ─── */
  function doInit() {
    if (initDone) return;
    initDone = true;
    initNav();
    updateBridgeIndicator();
    refreshStatus();
    drawerLog('面板启动', true);
  }

  // Event listener for pywebview bridge ready
  window.addEventListener('pywebviewready', function () {
    bridgeReady = true;
    doInit();
  });

  // Fallback: if DOM loads before pywebviewready, show connecting state
  document.addEventListener('DOMContentLoaded', function () {
    updateBridgeIndicator();
    // If pywebviewready never fires (browser preview), init after delay
    setTimeout(function () {
      if (!initDone) doInit();
    }, 800);
  });
})();

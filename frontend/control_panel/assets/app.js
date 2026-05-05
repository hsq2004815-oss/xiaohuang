/* XiaoHuang Control Center — app.js */
(function () {
  'use strict';

  var api = (window.pywebview && window.pywebview.api) || null;
  var $ = function (id) { return document.getElementById(id); };
  var opHistory = [];

  /* ─── Toast ─── */
  function toast(msg, type) {
    var el = document.createElement('div');
    el.className = 'glass-toast ' + (type || 'info');
    el.textContent = msg;
    $('toast-container').appendChild(el);
    setTimeout(function () { el.remove(); }, 4200);
  }

  /* ─── API wrapper ─── */
  function call(method) {
    var args = Array.prototype.slice.call(arguments, 1);
    if (api) return api[method].apply(api, args);
    return Promise.resolve({ ok: false, error: '桌面桥接未就绪', _mock: true });
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

  /* ─── Render status ─── */
  function renderStatus(data) {
    var d = (data && data.ok && data.data) ? data.data : null;
    var isMock = !!(data && data._mock);

    if (!d) {
      if (isMock) setStatusBadge('预览模式', 'off');
      else setStatusBadge('加载失败', 'error');
      return;
    }

    var os = d.overall_status || 'UNKNOWN';
    var badgeCls = os === 'READY' ? '' : os === 'NOT_RUNNING' ? 'off' : os === 'ERROR' ? 'error' : 'warn';
    setStatusBadge(d.overall_message || os, badgeCls);
    setWakeBadge((d.wake_engine || 'stt_text') + ' wake');

    // Neon status cards
    setCard('card-stt', d.stt_running ? '运行中' : '未检测到', d.stt_running ? 'ok' : 'err');
    setCard('card-overlay', d.overlay_running ? '运行中' : '未检测到', d.overlay_running ? 'ok' : 'err');
    setCard('card-wake', d.wake_engine || 'stt_text', d.can_wake_now ? 'ok' : 'off');
    setCard('card-assistant', d.assistant_display_name || '小黄', 'ok');

    // Action buttons
    var running = d.stt_running || d.overlay_running;
    $('btn-start').disabled = running;
    $('btn-stop').disabled = !running;
    $('btn-restart').disabled = !running;

    // Wake settings form
    setVal('wake-engine', d.wake_engine || 'stt_text');
    setChecked('wake-fallback', d.wake_fallback_enabled !== false);
    setVal('wake-device', d.wake_device_index);
    setVal('wake-cooldown', d.wake_cooldown_seconds);
    setVal('wake-sensitivity', d.wake_sensitivity);

    // Runtime detail
    var rows = [
      ['STT Server Running', d.stt_running],
      ['STT Ready', d.stt_ready],
      ['Model Loaded', d.stt_model_loaded],
      ['Health Status', d.stt_health_status],
      ['Can Wake', d.can_wake_now],
      ['TTS Enabled', d.tts_enabled],
      ['LLM Provider', d.llm_provider],
      ['Config Path', d.config_path],
      ['Last Error', d.last_error || '无'],
    ];
    $('runtime-detail').innerHTML = rows.map(function (r) {
      return '<div class="event-row"><span class="event-label">' + r[0] + '</span><span class="event-val">' + (r[1] !== undefined ? (r[1] ? '✓' : '✗') : '--') + '</span></div>';
    }).join('');

    // Wake & Voice detail
    $('wake-voice-detail').innerHTML = [
      ['Engine', d.wake_engine],['Fallback', d.wake_fallback_enabled],['Device', d.wake_device_index],
      ['Cooldown', (d.wake_cooldown_seconds || 0) + 's'],['Sensitivity', d.wake_sensitivity],
      ['Model Label', d.wake_model_label || '--'],['Phrases', (d.wake_phrases || []).join(', ')],
    ].map(function (r) { return '<div class="event-row"><span class="event-label">' + r[0] + '</span><span class="event-val">' + (r[1] !== undefined ? r[1] : '--') + '</span></div>'; }).join('');

    // Recent events
    var ev = [
      ['Overall', d.overall_message || os],['Last Op', d.last_operation || '无'],
      ['Last Op Time', d.last_operation_elapsed_seconds ? d.last_operation_elapsed_seconds + 's' : '--'],
    ];
    $('events-list').innerHTML = ev.map(function (r) {
      return '<div class="event-row"><span class="event-label">' + r[0] + '</span><span class="event-val">' + r[1] + '</span></div>';
    }).join('');

    // Diagnostic drawer
    $('drawer-config-path').textContent = d.config_path || '--';
    $('drawer-last-error').textContent = d.last_error || '无';
    if (d.last_error) $('drawer-last-error').style.color = 'var(--error-glow)';
  }

  function setStatusBadge(text, cls) {
    var b = $('top-status');
    b.textContent = text;
    b.className = 'status-badge' + (cls ? ' ' + cls : '');
  }

  function setWakeBadge(text) {
    $('top-wake').textContent = text;
  }

  function setCard(id, text, cls) {
    var el = $(id);
    if (!el) return;
    el.textContent = text || '--';
    el.className = 'card-value' + (cls ? ' ' + cls : '');
  }

  /* ─── Sidebar navigation ─── */
  function initNav() {
    var items = document.querySelectorAll('.sidebar-item');
    var sections = document.querySelectorAll('.content-section');
    items.forEach(function (item) {
      item.addEventListener('click', function () {
        items.forEach(function (i) { i.classList.remove('active'); });
        item.classList.add('active');
        var sec = item.getAttribute('data-section');
        sections.forEach(function (s) { s.classList.remove('active'); });
        var target = document.getElementById('section-' + sec);
        if (target) target.classList.add('active');
      });
    });
  }

  /* ─── Actions ─── */
  function refreshStatus() {
    call('get_status').then(renderStatus).catch(function (e) { toast('刷新失败', 'err'); });
    call('get_log_paths').then(function (r) {
      if (r && r.ok && r.data) {
        $('drawer-logs-path').textContent = r.data.logs_directory || '--';
      }
    });
  }

  function doStart() {
    $('btn-start').disabled = true;
    call('start_xiaohuang').then(function (r) {
      if (r && r.ok) { toast('启动成功', 'ok'); drawerLog('启动小黄', true); }
      else { toast((r && r.error) || '启动失败', 'err'); drawerLog('启动小黄', false, (r && r.error)); }
      setTimeout(refreshStatus, 3000);
    }).catch(function (e) { toast('启动出错', 'err'); $('btn-start').disabled = false; });
  }

  function doStop() {
    $('btn-stop').disabled = true;
    call('stop_xiaohuang').then(function (r) {
      if (r && r.ok) { toast('已停止', 'ok'); drawerLog('停止小黄', true); }
      else { toast((r && r.error) || '停止失败', 'err'); drawerLog('停止小黄', false, (r && r.error)); }
      setTimeout(refreshStatus, 2000);
    }).catch(function (e) { toast('停止出错', 'err'); });
  }

  function doRestart() {
    $('btn-restart').disabled = true;
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
    call('save_wake_config', payload).then(function (r) {
      if (r && r.ok) { toast('配置已保存', 'ok'); $('wake-hint').textContent = '已保存，需重启小黄生效。'; drawerLog('保存配置', true); }
      else { toast((r && r.error) || '保存失败', 'err'); drawerLog('保存配置', false, (r && r.error)); }
    }).catch(function (e) { toast('保存出错', 'err'); });
  }

  function doSaveAndRestart() {
    var payload = {
      engine: getVal('wake-engine'), fallback_enabled: getChecked('wake-fallback'),
      device_index: getVal('wake-device'), cooldown_seconds: getVal('wake-cooldown'),
      sensitivity: getVal('wake-sensitivity'),
    };
    call('save_wake_config', payload).then(function (r) {
      if (r && r.ok) { $('wake-hint').textContent = ''; doRestart(); }
      else { toast((r && r.error) || '保存失败', 'err'); drawerLog('保存并重启', false, (r && r.error)); }
    }).catch(function (e) { toast('保存出错', 'err'); });
  }

  /* ─── Bind ─── */
  $('btn-refresh').addEventListener('click', refreshStatus);
  $('btn-top-refresh').addEventListener('click', refreshStatus);
  $('btn-start').addEventListener('click', doStart);
  $('btn-stop').addEventListener('click', doStop);
  $('btn-restart').addEventListener('click', doRestart);
  $('btn-save-config').addEventListener('click', doSaveConfig);
  $('btn-save-restart').addEventListener('click', doSaveAndRestart);

  /* ─── Init ─── */
  initNav();
  refreshStatus();
})();

/* XiaoHuang Control Center — app.js */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var opHistory = [];
  var bridgeReady = false;
  var initDone = false;
  var currentAction = null;

  /* ─── API ─── */
  function getApi() {
    if (window.pywebview && window.pywebview.api) return window.pywebview.api;
    return null;
  }

  function apiCall(name) {
    var startTime = Date.now();
    var args = Array.prototype.slice.call(arguments, 1);
    var api = getApi();

    drawerLog('API → ' + name, null, '调用中');

    if (!api) {
      var err = '桌面桥接未连接（无法调用 ' + name + '）';
      toast(err, 'err');
      drawerLog('API → ' + name, false, err);
      return Promise.resolve({ ok: false, error: err, code: 'NO_BRIDGE' });
    }

    if (typeof api[name] !== 'function') {
      var err2 = '桌面桥接未提供方法: ' + name;
      toast(err2, 'err');
      drawerLog('API → ' + name, false, err2);
      return Promise.resolve({ ok: false, error: err2, code: 'NO_METHOD' });
    }

    try {
      var result = api[name].apply(api, args);
      if (result && typeof result.then === 'function') {
        return result.then(function (r) {
          finishApiCall(name, r, startTime);
          return r;
        }).catch(function (e) {
          finishApiCall(name, null, startTime, String(e));
          return { ok: false, error: String(e), code: 'JS_ERROR' };
        });
      }
      finishApiCall(name, result, startTime);
      return Promise.resolve(result);
    } catch (e) {
      finishApiCall(name, null, startTime, String(e));
      return Promise.resolve({ ok: false, error: String(e), code: 'JS_ERROR' });
    }
  }

  function finishApiCall(name, result, startTime, error) {
    var elapsed = Date.now() - startTime;
    if (error) {
      drawerLog(name, false, error + ' (' + elapsed + 'ms)');
    } else if (result && result.ok) {
      drawerLog(name, true, result.message || '完成 (' + elapsed + 'ms)');
    } else if (result && !result.ok) {
      drawerLog(name, false, (result.error || '失败') + ' (' + elapsed + 'ms)');
    } else {
      drawerLog(name, true, '完成 (' + elapsed + 'ms)');
    }
  }

  /* ─── Toast ─── */
  function toast(msg, type) {
    var el = document.createElement('div');
    el.className = 'glass-toast ' + (type || 'info');
    el.textContent = msg;
    $('toast-container').appendChild(el);
    setTimeout(function () { el.remove(); }, 5000);
  }

  /* ─── Diagnostic drawer ─── */
  function drawerLog(op, ok, detail) {
    var now = new Date().toLocaleTimeString();
    opHistory.unshift({ time: now, op: op, ok: ok, detail: detail || '' });
    if (opHistory.length > 30) opHistory.length = 30;
    var html = '';
    opHistory.forEach(function (e) {
      var cls = e.ok === null ? '' : e.ok ? 'ok' : 'err';
      html += '<div class="drawer-entry ' + cls + '"><span class="ts">' + e.time + '</span>' + e.op + (e.detail ? ' — ' + e.detail : '') + '</div>';
    });
    $('drawer-history').innerHTML = html || '暂无操作记录';
    var lastOk = opHistory.length > 0 ? opHistory[0].ok : null;
    $('drawer-last-op').textContent = op + (lastOk === true ? ' ✓' : lastOk === false ? ' ✗' : '');
  }

  /* ─── Helpers ─── */
  function setVal(id, val) { var el = $(id); if (el) el.value = (val !== null && val !== undefined) ? val : ''; }
  function getVal(id) { var el = $(id); return el ? el.value : ''; }
  function setChecked(id, v) { var el = $(id); if (el) el.checked = !!v; }
  function getChecked(id) { var el = $(id); return el ? el.checked : false; }

  var S = { running: '运行中', stopped: '已停止', ready: '已就绪', unknown: '未知', error: '错误', loading: '加载中...', notDetected: '未检测到' };

  /* ─── Button feedback ─── */
  function setButtonLoading(btn, text) {
    if (!btn) return;
    currentAction = text;
    btn.disabled = true;
    btn.textContent = text;
    btn.classList.add('loading');
    $('drawer-last-op').textContent = text + '...';
  }

  function restoreButton(btn, origText) {
    if (!btn) return;
    currentAction = null;
    btn.disabled = false;
    btn.textContent = origText;
    btn.classList.remove('loading');
  }

  function getButtonText(action) {
    var map = { start: '启动小黄', stop: '停止小黄', restart: '重启小黄', refresh: '刷新状态', 'save-config': '保存配置', 'save-restart': '保存并重启' };
    return map[action] || action;
  }
  function getLoadingText(action) {
    var map = { start: '启动中...', stop: '停止中...', restart: '重启中...', refresh: '刷新中...', 'save-config': '保存中...', 'save-restart': '保存中...' };
    return map[action] || (action + '...');
  }

  /* ─── Bridge indicator ─── */
  function updateBridgeIndicator() {
    var api = getApi();
    var el = $('drawer-bridge-status');
    if (!el) return;
    if (api) { el.textContent = '已连接'; el.className = 'drawer-value ok'; enableControls(true); }
    else if (bridgeReady) { el.textContent = '等待注入...'; el.className = 'drawer-value warn'; }
    else { el.textContent = '连接中...'; el.className = 'drawer-value'; }
  }

  function enableControls(on) {
    ['btn-refresh','btn-top-refresh','btn-save-config','btn-save-restart'].forEach(function (id) {
      var el = $(id); if (el) el.disabled = !on;
    });
    if (on) {
      var s = $('btn-start'); if (s) s.disabled = false;
      var t = $('btn-stop'); if (t) t.disabled = true;
      var r = $('btn-restart'); if (r) r.disabled = true;
    } else {
      ['btn-start','btn-stop','btn-restart'].forEach(function (id) {
        var el = $(id); if (el) el.disabled = true;
      });
    }
  }

  /* ─── Render status ─── */
  function renderStatus(data) {
    var d = (data && data.ok && data.data) ? data.data : null;
    if (!d) { setStatusBadge(S.loading, 'off'); return; }
    var os = d.overall_status || 'UNKNOWN';
    var badgeCls = os === 'READY' ? '' : os === 'NOT_RUNNING' ? 'off' : os === 'ERROR' ? 'error' : 'warn';
    setStatusBadge(d.overall_message || os, badgeCls);
    setWakeBadge((d.wake_engine || 'stt_text'));
    setCard('card-stt', d.stt_running ? S.running : S.notDetected, d.stt_running ? 'ok' : 'err');
    setCard('card-overlay', d.overlay_running ? S.running : S.notDetected, d.overlay_running ? 'ok' : 'err');
    setCard('card-wake', d.wake_engine || 'stt_text', d.can_wake_now ? 'ok' : 'off');
    setCard('card-assistant', d.assistant_display_name || '小黄', 'ok');
    var running = d.stt_running || d.overlay_running;
    if (getApi() && !currentAction) {
      var s = $('btn-start'); if (s) s.disabled = running;
      var t = $('btn-stop'); if (t) t.disabled = !running;
      var r = $('btn-restart'); if (r) r.disabled = !running;
    }
    setVal('wake-engine', d.wake_engine || 'stt_text');
    setChecked('wake-fallback', d.wake_fallback_enabled !== false);
    setVal('wake-device', d.wake_device_index);
    setVal('wake-cooldown', d.wake_cooldown_seconds);
    setVal('wake-sensitivity', d.wake_sensitivity);

    $('runtime-detail').innerHTML = [
      ['STT 服务运行', d.stt_running],['STT 就绪', d.stt_ready],['模型已加载', d.stt_model_loaded],
      ['健康状态', d.stt_health_status],['可唤醒', d.can_wake_now],['TTS 启用', d.tts_enabled],
      ['LLM 提供方', d.llm_provider],['配置文件路径', d.config_path],['最近错误', d.last_error || '无'],
    ].map(function (r) { return '<div class="event-row"><span class="event-label">' + r[0] + '</span><span class="event-val">' + fmtVal(r[1]) + '</span></div>'; }).join('');

    $('wake-voice-detail').innerHTML = [
      ['引擎', d.wake_engine],['兜底唤醒', d.wake_fallback_enabled],['设备', d.wake_device_index],
      ['冷却时间', (d.wake_cooldown_seconds || 0) + 's'],['灵敏度', d.wake_sensitivity],
      ['模型标签', d.wake_model_label || '--'],['唤醒词', (d.wake_phrases || []).join(', ')],
    ].map(function (r) { return '<div class="event-row"><span class="event-label">' + r[0] + '</span><span class="event-val">' + fmtVal(r[1]) + '</span></div>'; }).join('');

    $('events-list').innerHTML = [
      ['总体状态', d.overall_message || os],['上次操作', d.last_operation || '无'],
      ['操作耗时', d.last_operation_elapsed_seconds ? d.last_operation_elapsed_seconds + 's' : '--'],
    ].map(function (r) { return '<div class="event-row"><span class="event-label">' + r[0] + '</span><span class="event-val">' + r[1] + '</span></div>'; }).join('');

    $('drawer-config-path').textContent = d.config_path || '--';
    $('drawer-last-error').textContent = d.last_error || '无';
    if (d.last_error) $('drawer-last-error').style.color = 'var(--error)';
  }

  function fmtVal(v) { if (v === undefined || v === null) return '--'; if (typeof v === 'boolean') return v ? '是' : '否'; return String(v); }
  function setStatusBadge(text, cls) { var b = $('top-status'); b.textContent = text; b.className = 'status-badge' + (cls ? ' ' + cls : ''); }
  function setWakeBadge(text) { $('top-wake').textContent = text; }
  function setCard(id, text, cls) { var el = $(id); if (!el) return; el.textContent = text || '--'; el.className = 'card-value' + (cls ? ' ' + cls : ''); }

  /* ─── Sidebar ─── */
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
    apiCall('get_status').then(renderStatus);
    apiCall('get_log_paths').then(function (r) {
      if (r && r.ok && r.data) $('drawer-logs-path').textContent = r.data.logs_directory || '--';
    });
  }

  function handleButtonClick(action) {
    if (!action) return;
    if (action === 'refresh') { doRefresh(); return; }
    if (action === 'start') { doStart(); return; }
    if (action === 'stop') { doStop(); return; }
    if (action === 'restart') { doRestart(); return; }
    if (action === 'save-config') { doSaveConfig(); return; }
    if (action === 'save-restart') { doSaveAndRestart(); return; }
    toast('未识别的操作: ' + action, 'err');
  }

  function doRefresh() {
    var btn = document.querySelector('[data-action="refresh"]');
    setButtonLoading(btn, '刷新中...');
    toast('正在刷新状态...', 'info');
    refreshStatus();
    setTimeout(function () { restoreButton(btn, getButtonText('refresh')); }, 500);
  }

  function doStart() {
    var btn = document.querySelector('[data-action="start"]');
    if (!btn || btn.disabled) return;
    setButtonLoading(btn, getLoadingText('start'));
    toast('正在启动小黄，请稍候...', 'info');
    drawerLog('启动小黄', null, '已发送启动请求');

    apiCall('start_xiaohuang').then(function (r) {
      if (r && r.ok) { toast(r.message || '启动成功', 'ok'); drawerLog('启动小黄', true, r.message); setTimeout(refreshStatus, 3000); }
      else { toast((r && r.error) || '启动失败', 'err'); drawerLog('启动小黄', false, (r && r.error)); refreshStatus(); }
    }).catch(function (e) { toast('启动出错: ' + e, 'err'); drawerLog('启动小黄', false, String(e)); }).finally(function () {
      restoreButton(btn, getButtonText('start'));
    });

    // 8s timeout hint
    setTimeout(function () {
      if (currentAction === '启动中...') toast('启动仍在进行，请查看日志或稍后刷新状态', 'info');
    }, 8000);
  }

  function doStop() {
    var btn = document.querySelector('[data-action="stop"]');
    if (!btn || btn.disabled) return;
    setButtonLoading(btn, getLoadingText('stop'));
    toast('正在停止小黄...', 'info');

    apiCall('stop_xiaohuang').then(function (r) {
      if (r && r.ok) { toast('已停止', 'ok'); drawerLog('停止小黄', true); setTimeout(refreshStatus, 2000); }
      else { toast((r && r.error) || '停止失败', 'err'); drawerLog('停止小黄', false, (r && r.error)); refreshStatus(); }
    }).catch(function (e) { toast('停止出错: ' + e, 'err'); }).finally(function () {
      restoreButton(btn, getButtonText('stop'));
    });
  }

  function doRestart() {
    var btn = document.querySelector('[data-action="restart"]');
    if (!btn || btn.disabled) return;
    setButtonLoading(btn, getLoadingText('restart'));
    toast('正在重启小黄，请稍候...', 'info');

    apiCall('restart_xiaohuang').then(function (r) {
      if (r && r.ok) { toast('重启成功', 'ok'); drawerLog('重启小黄', true); setTimeout(refreshStatus, 5000); }
      else { toast((r && r.error) || '重启失败', 'err'); drawerLog('重启小黄', false, (r && r.error)); refreshStatus(); }
    }).catch(function (e) { toast('重启出错: ' + e, 'err'); }).finally(function () {
      restoreButton(btn, getButtonText('restart'));
    });
  }

  function doSaveConfig() {
    var btn = document.querySelector('[data-action="save-config"]');
    if (!btn || btn.disabled) return;
    var payload = { engine: getVal('wake-engine'), fallback_enabled: getChecked('wake-fallback'), device_index: getVal('wake-device'), cooldown_seconds: getVal('wake-cooldown'), sensitivity: getVal('wake-sensitivity') };
    setButtonLoading(btn, getLoadingText('save-config'));

    apiCall('save_wake_config', payload).then(function (r) {
      if (r && r.ok) { toast('配置已保存', 'ok'); $('wake-hint').textContent = '已保存，需重启小黄生效。'; drawerLog('保存配置', true); refreshStatus(); }
      else { toast((r && r.error) || '保存失败', 'err'); drawerLog('保存配置', false, (r && r.error)); }
    }).catch(function (e) { toast('保存出错: ' + e, 'err'); }).finally(function () {
      restoreButton(btn, getButtonText('save-config'));
    });
  }

  function doSaveAndRestart() {
    var btn = document.querySelector('[data-action="save-restart"]');
    if (!btn || btn.disabled) return;
    var payload = { engine: getVal('wake-engine'), fallback_enabled: getChecked('wake-fallback'), device_index: getVal('wake-device'), cooldown_seconds: getVal('wake-cooldown'), sensitivity: getVal('wake-sensitivity') };
    setButtonLoading(btn, getLoadingText('save-restart'));

    apiCall('save_wake_config', payload).then(function (r) {
      if (r && r.ok) { $('wake-hint').textContent = ''; doRestart(); }
      else { toast((r && r.error) || '保存失败', 'err'); drawerLog('保存并重启', false, (r && r.error)); restoreButton(btn, getButtonText('save-restart')); }
    }).catch(function (e) { toast('保存出错: ' + e, 'err'); restoreButton(btn, getButtonText('save-restart')); });
  }

  /* ─── Event Delegation ─── */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    e.preventDefault();
    var action = btn.getAttribute('data-action');
    if (action) handleButtonClick(action);
  });

  /* ─── Init ─── */
  function doInit() {
    if (initDone) return;
    initDone = true;
    initNav();
    updateBridgeIndicator();
    refreshStatus();
    drawerLog('面板启动', true);
  }

  window.addEventListener('pywebviewready', function () {
    bridgeReady = true;
    doInit();
  });

  document.addEventListener('DOMContentLoaded', function () {
    updateBridgeIndicator();
    setTimeout(function () { if (!initDone) doInit(); }, 800);
  });
})();

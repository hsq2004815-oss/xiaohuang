/* XiaoHuang Control Center — app.js */

(function () {
  'use strict';

  var api = (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;

  function toast(message, type) {
    type = type || 'info';
    var container = document.getElementById('toast-container');
    var el = document.createElement('div');
    el.className = 'toast ' + type;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(function () { el.remove(); }, 4200);
  }

  function call(method) {
    var args = Array.prototype.slice.call(arguments, 1);
    if (api) {
      return api[method].apply(api, args);
    }
    return Promise.resolve({ ok: false, error: '桌面桥接未就绪' });
  }

  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function setHTML(id, html) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = html;
  }

  function statusClass(ok) {
    return ok ? 'ok' : 'err';
  }

  function renderStatus(data) {
    var d = (data && data.ok && data.data) ? data.data : {};
    setText('status-detail', '加载失败');
    if (!d.overall_status) return;

    // Badge
    var badge = document.getElementById('status-badge');
    var os = d.overall_status;
    badge.textContent = d.overall_message || os;
    badge.className = 'status-badge';
    if (os === 'READY') badge.classList.add('warn');  // "warm" ready
    else if (os === 'NOT_RUNNING' || os === 'PARTIAL') badge.classList.add('off');
    else if (os === 'ERROR') badge.classList.add('error');

    // Wake engine badge
    var weBadge = document.getElementById('wake-engine-badge');
    weBadge.textContent = (d.wake_engine || 'stt_text') + ' wake';
    weBadge.className = 'wake-engine-badge';

    // Detail rows
    var rows = [
      ['STT Server', d.stt_running ? '运行中' : '未检测到', d.stt_running ? 'ok' : 'err'],
      ['STT Ready', d.stt_ready ? '是' : '否', d.stt_ready ? 'ok' : 'err'],
      ['Voice Overlay', d.overlay_running ? '运行中' : '未检测到', d.overlay_running ? 'ok' : 'err'],
      ['Heath Status', d.stt_health_status || '--', ''],
      ['Model Loaded', d.stt_model_loaded ? '已加载' : '未加载', d.stt_model_loaded ? 'ok' : 'err'],
      ['Can Wake', d.can_wake_now ? '是' : '否', d.can_wake_now ? 'ok' : 'err'],
      ['Last Error', d.last_error || '无', d.last_error ? 'err' : ''],
      ['Config Path', d.config_path || '--', ''],
    ];
    var html = '';
    rows.forEach(function (r) {
      var cls = r[2] ? ' status-value ' + r[2] : ' status-value';
      html += '<div class="status-row"><span class="status-label">' + r[0] + '</span><span class="' + cls + '">' + r[1] + '</span></div>';
    });
    setHTML('status-detail', html);

    // Config summary
    var configRows = [
      ['Assistant', (d.assistant_display_name || '') + ' (' + (d.llm_provider || '') + ')'],
      ['TTS', d.tts_enabled ? '启用' : '禁用'],
      ['Fallback', d.wake_fallback_enabled ? '启用' : '禁用'],
      ['Device', d.wake_device_index !== null ? d.wake_device_index : '默认'],
      ['Cooldown', (d.wake_cooldown_seconds !== undefined ? d.wake_cooldown_seconds + 's' : '--')],
      ['Sensitivity', d.wake_sensitivity !== undefined ? d.wake_sensitivity : '--'],
      ['Model Label', d.wake_model_label || '--'],
    ];
    var chtml = '';
    configRows.forEach(function (r) {
      chtml += '<div class="status-row"><span class="status-label">' + r[0] + '</span><span class="status-value">' + r[1] + '</span></div>';
    });
    setHTML('config-detail', chtml);

    // Wake settings form
    var engine = d.wake_engine || 'stt_text';
    setVal('wake-engine', engine);
    setChecked('wake-fallback', d.wake_fallback_enabled !== false);
    setVal('wake-device', d.wake_device_index !== null ? d.wake_device_index : '');
    setVal('wake-cooldown', d.wake_cooldown_seconds !== undefined ? d.wake_cooldown_seconds : '');
    setVal('wake-sensitivity', d.wake_sensitivity !== undefined ? d.wake_sensitivity : '');

    // Enable/disable action buttons based on state
    var running = d.stt_running || d.overlay_running;
    document.getElementById('btn-start').disabled = running;
    document.getElementById('btn-stop').disabled = !running;
    document.getElementById('btn-restart').disabled = !running;
  }

  function setVal(id, val) {
    var el = document.getElementById(id);
    if (el) el.value = val;
  }

  function setChecked(id, checked) {
    var el = document.getElementById(id);
    if (el) el.checked = checked;
  }

  function getVal(id) {
    var el = document.getElementById(id);
    return el ? el.value : '';
  }

  function getChecked(id) {
    var el = document.getElementById(id);
    return el ? el.checked : false;
  }

  function refreshStatus() {
    toast('正在刷新...', 'info');
    call('get_status').then(renderStatus).catch(function (e) {
      toast('刷新失败: ' + e, 'err');
    });
  }

  function doStart() {
    toast('正在启动小黄...', 'info');
    call('start_xiaohuang').then(function (r) {
      if (r && r.ok) toast(r.message || '启动成功', 'ok');
      else toast((r && r.error) || '启动失败', 'err');
      setTimeout(refreshStatus, 3000);
    }).catch(function (e) { toast('启动出错: ' + e, 'err'); });
  }

  function doStop() {
    toast('正在停止小黄...', 'info');
    call('stop_xiaohuang').then(function (r) {
      if (r && r.ok) toast(r.message || '已停止', 'ok');
      else toast((r && r.error) || '停止失败', 'err');
      setTimeout(refreshStatus, 2000);
    }).catch(function (e) { toast('停止出错: ' + e, 'err'); });
  }

  function doRestart() {
    toast('正在重启小黄...', 'info');
    call('restart_xiaohuang').then(function (r) {
      if (r && r.ok) toast(r.message || '重启成功', 'ok');
      else toast((r && r.error) || '重启失败', 'err');
      setTimeout(refreshStatus, 5000);
    }).catch(function (e) { toast('重启出错: ' + e, 'err'); });
  }

  function doSaveConfig() {
    var payload = {
      engine: getVal('wake-engine'),
      fallback_enabled: getChecked('wake-fallback'),
      device_index: getVal('wake-device'),
      cooldown_seconds: getVal('wake-cooldown'),
      sensitivity: getVal('wake-sensitivity'),
    };
    call('save_wake_config', payload).then(function (r) {
      if (r && r.ok) {
        toast(r.message || '配置已保存', 'ok');
        setText('wake-restart-hint', '配置已保存，需要重启小黄生效。');
      } else {
        toast((r && r.error) || '保存失败', 'err');
      }
    }).catch(function (e) { toast('保存出错: ' + e, 'err'); });
  }

  function doSaveAndRestart() {
    var payload = {
      engine: getVal('wake-engine'),
      fallback_enabled: getChecked('wake-fallback'),
      device_index: getVal('wake-device'),
      cooldown_seconds: getVal('wake-cooldown'),
      sensitivity: getVal('wake-sensitivity'),
    };
    call('save_wake_config', payload).then(function (r) {
      if (r && r.ok) {
        setText('wake-restart-hint', '');
        doRestart();
      } else {
        toast((r && r.error) || '保存失败', 'err');
      }
    }).catch(function (e) { toast('保存出错: ' + e, 'err'); });
  }

  function showLogPaths() {
    call('get_log_paths').then(function (r) {
      if (r && r.ok && r.data) {
        toast('日志: ' + (r.data.logs_directory || 'N/A'), 'info');
      } else {
        toast('无法获取日志路径', 'err');
      }
    }).catch(function (e) { toast('出错: ' + e, 'err'); });
  }

  // Bind buttons
  document.getElementById('btn-refresh').addEventListener('click', refreshStatus);
  document.getElementById('btn-start').addEventListener('click', doStart);
  document.getElementById('btn-stop').addEventListener('click', doStop);
  document.getElementById('btn-restart').addEventListener('click', doRestart);
  document.getElementById('btn-save-config').addEventListener('click', doSaveConfig);
  document.getElementById('btn-save-restart').addEventListener('click', doSaveAndRestart);
  document.getElementById('btn-logs').addEventListener('click', showLogPaths);

  // Logs detail section
  call('get_log_paths').then(function (r) {
    if (r && r.ok && r.data) {
      var html = '';
      html += '<div class="status-row"><span class="status-label">日志目录</span><span class="status-value">' + (r.data.logs_directory || '--') + '</span></div>';
      html += '<div class="status-row"><span class="status-label">项目根目录</span><span class="status-value">' + (r.data.project_root || '--') + '</span></div>';
      html += '<div class="status-row"><span class="status-label">配置文件</span><span class="status-value">' + (r.data.config_path || '--') + '</span></div>';
      setHTML('logs-detail', html);
    }
  });

  // Footer info
  setText('footer-info', 'XiaoHuang V1.3 — Web Control Panel' + (api ? '' : ' (浏览器预览模式)'));

  // Initial load
  refreshStatus();
})();

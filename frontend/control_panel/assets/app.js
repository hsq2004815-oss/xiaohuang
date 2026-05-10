/* XiaoHuang Control Center — app.js */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var opHistory = [];
  var bridgeReady = false;
  var initDone = false;
  var activeAction = null;
  var activeButton = null;
  var lastStatusData = null;
  var lastLogPaths = null;
  var lastRuntimeEvents = [];
  var lastStartupDiagnostic = null;
  var lastPreflightCheck = null;
  var DRAWER_STORAGE_KEY = 'xiaohuang.controlPanel.drawerCollapsed';
  var SIDEBAR_STORAGE_KEY = 'xiaohuang.controlPanel.sidebarCollapsed';
  var currentShell = 'control';
  var currentSection = 'home';
  var textChatSessionId = 'control_panel';
  var textChatMessages = [];
  var textChatSending = false;
  var textChatInitialized = false;
  var textTaskCardCounter = 0;

  /* ─── API ─── */
  function getApi() {
    if (window.pywebview && window.pywebview.api) return window.pywebview.api;
    return null;
  }

  function escapeHtml(value) {
    return String(value === undefined || value === null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
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
    var container = $('toast-container');
    if (!container) return;
    var el = document.createElement('div');
    el.className = 'glass-toast ' + (type || 'info');
    el.textContent = msg;
    container.appendChild(el);
    while (container.children.length > 3) {
      container.removeChild(container.firstElementChild);
    }
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
      html += '<div class="drawer-entry ' + cls + '"><span class="ts">' +
        escapeHtml(e.time) + '</span>' + escapeHtml(e.op) +
        (e.detail ? ' — ' + escapeHtml(e.detail) : '') + '</div>';
    });

    var history = $('drawer-history');
    if (history) history.innerHTML = html || '暂无操作记录';

    var last = $('drawer-last-op');
    if (last) {
      var lastOk = opHistory.length > 0 ? opHistory[0].ok : null;
      last.textContent = op + (lastOk === true ? ' ✓' : lastOk === false ? ' ✗' : '');
    }
  }



  function safeLocalStorageGet(key) {
    try { return window.localStorage ? window.localStorage.getItem(key) : null; }
    catch (e) { return null; }
  }

  function safeLocalStorageSet(key, value) {
    try { if (window.localStorage) window.localStorage.setItem(key, value); }
    catch (e) { /* pywebview may block storage in some environments */ }
  }

  function isDrawerCollapsed() {
    return safeLocalStorageGet(DRAWER_STORAGE_KEY) === '1';
  }

  function applyDrawerState(collapsed) {
    var shell = $('app-shell');
    var drawerToggle = $('btn-drawer-collapse');
    var rail = $('drawer-rail');
    var expanded = !collapsed;

    if (shell) shell.classList.toggle('drawer-collapsed', collapsed);

    [drawerToggle, rail].forEach(function (btn) {
      if (!btn) return;
      btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    });

    if (drawerToggle) {
      drawerToggle.textContent = '收起';
      drawerToggle.title = '收起诊断栏';
    }
    if (rail) {
      rail.title = '展开诊断栏';
    }
  }

  function setDrawerCollapsed(collapsed) {
    safeLocalStorageSet(DRAWER_STORAGE_KEY, collapsed ? '1' : '0');
    applyDrawerState(collapsed);
  }

  function toggleDrawerCollapsed() {
    var shell = $('app-shell');
    var collapsed = shell ? shell.classList.contains('drawer-collapsed') : isDrawerCollapsed();
    setDrawerCollapsed(!collapsed);
  }

  function initDrawerControls() {
    ['btn-drawer-collapse', 'drawer-rail'].forEach(function (id) {
      var el = $(id);
      if (!el || el.dataset.drawerBound === '1') return;
      el.dataset.drawerBound = '1';
      el.addEventListener('click', function (e) {
        e.preventDefault();
        toggleDrawerCollapsed();
      });
    });
    applyDrawerState(isDrawerCollapsed());
  }

  function isSidebarCollapsed() {
    return safeLocalStorageGet(SIDEBAR_STORAGE_KEY) === '1';
  }

  function applySidebarCollapsedState(collapsed) {
    var btn = $('btn-sidebar-toggle');
    document.body.classList.toggle('sidebar-collapsed', !!collapsed);
    if (!btn) return;
    btn.setAttribute('aria-pressed', collapsed ? 'true' : 'false');
    btn.setAttribute('aria-label', collapsed ? '展开导航' : '收起导航');
    btn.title = collapsed ? '展开导航' : '收起导航';
    btn.textContent = collapsed ? '»' : '☰';
  }

  function setSidebarCollapsed(collapsed) {
    safeLocalStorageSet(SIDEBAR_STORAGE_KEY, collapsed ? '1' : '0');
    applySidebarCollapsedState(collapsed);
  }

  function toggleSidebarCollapsed() {
    setSidebarCollapsed(!document.body.classList.contains('sidebar-collapsed'));
  }

  function initSidebarControls() {
    var btn = $('btn-sidebar-toggle');
    if (btn && btn.dataset.sidebarBound !== '1') {
      btn.dataset.sidebarBound = '1';
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        toggleSidebarCollapsed();
      });
    }
    applySidebarCollapsedState(isSidebarCollapsed());
  }


  /* ─── Helpers ─── */
  function setVal(id, val) { var el = $(id); if (el) el.value = (val !== null && val !== undefined) ? val : ''; }
  function getVal(id) { var el = $(id); return el ? el.value : ''; }
  function setChecked(id, v) { var el = $(id); if (el) el.checked = !!v; }
  function getChecked(id) { var el = $(id); return el ? el.checked : false; }

  var S = {
    running: '运行中',
    stopped: '已停止',
    ready: '已就绪',
    unknown: '未知',
    error: '错误',
    loading: '加载中...',
    notDetected: '未检测到'
  };

  /* ─── Button feedback ─── */
  function setButtonLoading(btn, text, action) {
    if (!btn) return;
    activeAction = action || text;
    activeButton = btn;
    btn.disabled = true;
    btn.dataset.originalText = btn.dataset.originalText || btn.textContent;
    btn.textContent = text;
    btn.classList.add('is-loading');

    var last = $('drawer-last-op');
    if (last) last.textContent = text;
  }

  function restoreButton(btn, origText, action) {
    if (!btn) return;
    btn.textContent = origText || btn.dataset.originalText || btn.textContent;
    btn.classList.remove('is-loading');
    btn.disabled = false;
    if (!action || activeAction === action || activeButton === btn) {
      activeAction = null;
      activeButton = null;
    }
  }

  function getButtonText(action) {
    var map = {
      start: '启动小黄',
      stop: '停止小黄',
      restart: '重启小黄',
      refresh: '刷新状态',
      'open-text-chat': '文本对话',
      'save-config': '保存配置',
      'save-restart': '保存并重启'
    };
    return map[action] || action;
  }

  function getLoadingText(action) {
    var map = {
      start: '启动中...',
      stop: '停止中...',
      restart: '重启中...',
      refresh: '刷新中...',
      'save-config': '保存中...',
      'save-restart': '保存中...'
    };
    return map[action] || (action + '...');
  }

  /* ─── Bridge indicator ─── */
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
      enableControls(false);
    } else {
      el.textContent = '连接中...';
      el.className = 'drawer-value';
      enableControls(false);
    }
  }

  function enableControls(on) {
    ['btn-refresh', 'btn-top-refresh', 'btn-save-config', 'btn-save-restart'].forEach(function (id) {
      var el = $(id);
      if (el && el !== activeButton) el.disabled = !on;
    });

    if (!on) {
      ['btn-start', 'btn-stop', 'btn-restart'].forEach(function (id) {
        var el = $(id);
        if (el && el !== activeButton) el.disabled = true;
      });
      return;
    }

    var s = $('btn-start'); if (s && s !== activeButton) s.disabled = false;
    var t = $('btn-stop'); if (t && t !== activeButton) t.disabled = true;
    var r = $('btn-restart'); if (r && r !== activeButton) r.disabled = true;
  }

  /* ─── Render status ─── */
  function renderStatus(data) {
    var d = (data && data.ok && data.data) ? data.data : null;
    if (d) lastStatusData = d;
    if (!d) {
      setStatusBadge(S.loading, 'off');
      return;
    }

    var os = d.overall_status || 'UNKNOWN';
    var badgeCls = os === 'READY' ? '' : os === 'NOT_RUNNING' ? 'off' : os === 'ERROR' ? 'error' : 'warn';
    setStatusBadge(d.overall_message || os, badgeCls);
    setWakeBadge((d.wake_engine || 'stt_text'));

    setCard('card-stt', d.stt_running ? S.running : S.notDetected, d.stt_running ? 'ok' : 'err');
    setCard('card-overlay', d.overlay_running ? S.running : S.notDetected, d.overlay_running ? 'ok' : 'err');
    setCard('card-wake', d.wake_engine || 'stt_text', d.can_wake_now ? 'ok' : 'off');
    setCard('card-assistant', d.assistant_display_name || '小黄', 'ok');

    var running = d.stt_running || d.overlay_running;
    if (getApi() && !activeAction) {
      var s = $('btn-start'); if (s) s.disabled = running;
      var t = $('btn-stop'); if (t) t.disabled = !running;
      var r = $('btn-restart'); if (r) r.disabled = !running;
    }

    setVal('wake-engine', d.wake_engine || 'stt_text');
    setChecked('wake-fallback', d.wake_fallback_enabled !== false);
    setVal('wake-device', d.wake_device_index);
    setVal('wake-cooldown', d.wake_cooldown_seconds);
    setVal('wake-sensitivity', d.wake_sensitivity);

    setRows('runtime-detail', [
      ['STT 服务运行', d.stt_running],
      ['STT 就绪', d.stt_ready],
      ['模型已加载', d.stt_model_loaded],
      ['健康状态', d.stt_health_status],
      ['可唤醒', d.can_wake_now],
      ['TTS 启用', d.tts_enabled],
      ['LLM 提供方', d.llm_provider],
      ['配置文件路径', d.config_path],
      ['最近错误', d.last_error || '无']
    ]);

    setRows('wake-voice-detail', [
      ['引擎', d.wake_engine],
      ['兜底唤醒', d.wake_fallback_enabled],
      ['设备', d.wake_device_index],
      ['冷却时间', (d.wake_cooldown_seconds || 0) + 's'],
      ['灵敏度', d.wake_sensitivity],
      ['模型标签', d.wake_model_label || '--'],
      ['唤醒词', (d.wake_phrases || []).join(', ')]
    ]);

    setRows('events-list', [
      ['总体状态', d.overall_message || os],
      ['上次操作', d.last_operation || '无'],
      ['操作耗时', d.last_operation_elapsed_seconds ? d.last_operation_elapsed_seconds + 's' : '--']
    ]);

    var configPath = $('drawer-config-path');
    if (configPath) configPath.textContent = d.config_path || '--';

    var lastError = $('drawer-last-error');
    if (lastError) {
      lastError.textContent = d.last_error || '无';
      lastError.className = 'drawer-value' + (d.last_error ? ' err' : '');
    }
  }

  function setRows(id, rows) {
    var el = $(id);
    if (!el) return;
    el.innerHTML = rows.map(function (r) {
      return '<div class="event-row"><span class="event-label">' + escapeHtml(r[0]) +
        '</span><span class="event-val" title="' + escapeHtml(fmtVal(r[1])) + '">' +
        escapeHtml(fmtVal(r[1])) + '</span></div>';
    }).join('');
  }

  function fmtVal(v) {
    if (v === undefined || v === null || v === '') return '--';
    if (typeof v === 'boolean') return v ? '是' : '否';
    return String(v);
  }

  function setStatusBadge(text, cls) {
    var b = $('top-status');
    if (!b) return;
    b.textContent = text;
    b.className = 'status-badge' + (cls ? ' ' + cls : '');
  }

  function setWakeBadge(text) {
    var el = $('top-wake');
    if (el) el.textContent = text;
  }

  function setCard(id, text, cls) {
    var el = $(id);
    if (!el) return;
    el.textContent = text || '--';
    el.className = 'card-value' + (cls ? ' ' + cls : '');
  }

  /* ─── Sidebar ─── */
  function updateShellLayoutForSection(section) {
    var isHome = section === 'home';
    var isChat = section === 'chat';
    document.body.classList.toggle('home-page', isHome);
    document.body.classList.toggle('drawer-page', isHome);
    document.body.classList.toggle('non-home-page', !isHome);
    document.body.classList.toggle('no-drawer-page', !isHome);
    document.body.classList.toggle('chat-page', isChat);
  }

  function switchShell(shell) {
    var isText = shell === 'text-chat';
    currentShell = 'control';
    document.body.classList.toggle('mode-control', true);

    var controlShell = $('control-shell');
    if (controlShell) controlShell.classList.add('active');

    if (isText) {
      switchSection('chat');
      focusTextChatInput();
      drawerLog('切换对话页', true, '当前工作区');
    } else {
      drawerLog('返回控制中心', true, '当前窗口');
    }
  }

  function switchSection(sec) {
    var aliases = {
      overview: 'home',
      runtime: 'home',
      wake: 'settings',
      models: 'settings',
      logs: 'diagnostics',
      developer: 'settings',
      automation: 'tools',
      database: 'tools',
      'text-chat': 'chat'
    };
    currentSection = aliases[sec] || sec || 'home';
    updateShellLayoutForSection(currentSection);
    document.querySelectorAll('.sidebar-item').forEach(function (item) {
      item.classList.toggle('active', item.getAttribute('data-section') === currentSection);
    });
    document.querySelectorAll('.content-section').forEach(function (section) {
      section.classList.toggle('active', section.id === 'section-' + currentSection);
    });
  }

  function initNav() {
    document.querySelectorAll('.sidebar-item').forEach(function (item) {
      item.addEventListener('click', function () {
        var sec = item.getAttribute('data-section') || 'home';
        switchSection(sec);
        if (sec === 'chat') focusTextChatInput();
      });
    });
  }

  /* ─── Text chat ─── */
  function initTextChat() {
    if (textChatInitialized) return;
    textChatInitialized = true;
    resetTextChatMessages();

    var send = $('text-chat-send');
    var clear = $('text-chat-clear');
    var input = $('text-chat-input');
    var newChat = $('text-chat-new');
    if (send) send.addEventListener('click', sendTextChatMessage);
    if (clear) clear.addEventListener('click', clearTextChatSession);
    if (newChat) newChat.addEventListener('click', clearTextChatSession);
    var messages = $('text-chat-messages');
    if (messages) {
      messages.addEventListener('click', function (event) {
        var target = event.target.closest('[data-task-action]');
        if (!target) return;
        var taskId = target.getAttribute('data-task-id') || '';
        var action = target.getAttribute('data-task-action') || '';
        if (action === 'confirm') handlePendingTaskConfirm(taskId);
        if (action === 'cancel') handlePendingTaskCancel(taskId);
      });
    }
    if (input) {
      input.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          sendTextChatMessage();
        }
      });
    }
    document.querySelectorAll('[data-text-prompt]').forEach(function (button) {
      button.addEventListener('click', function () {
        fillTextChatPrompt(button.getAttribute('data-text-prompt') || '');
      });
    });
  }

  function focusTextChatInput() {
    var input = $('text-chat-input');
    if (!input) return;
    setTimeout(function () { input.focus(); }, 50);
  }

  function resetTextChatMessages() {
    textChatMessages = [];
    renderTextChatMessages();
    appendTextChatMessage(
      'assistant',
      '你好，我是小黄。直接输入消息，我会在这里回复。',
      { source: 'welcome' }
    );
  }

  function fillTextChatPrompt(text) {
    var input = $('text-chat-input');
    if (!input) return;
    input.value = text;
    input.focus();
  }

  function appendTextChatMessage(role, text, meta, pendingTask, executionResult) {
    var normalizedTask = normalizePendingTask(pendingTask);
    var normalizedResult = normalizeTextTaskExecutionResult(executionResult);
    textChatMessages.push({
      role: role,
      text: text,
      meta: meta || {},
      pendingTask: normalizedTask,
      executionResult: normalizedResult,
      taskUiStatus: normalizedTask ? (normalizedTask.allowed ? 'pending' : 'blocked') : '',
      ts: new Date().toLocaleTimeString()
    });
    renderTextChatMessages();
  }

  function scrollTextChatToBottom() {
    var messages = $('text-chat-messages');
    if (!messages) return;
    messages.scrollTop = messages.scrollHeight;
  }

  function normalizePendingTask(task) {
    if (!task || typeof task !== 'object') return null;
    var risk = String(task.risk_level || task.risk || 'medium').toLowerCase();
    if (risk !== 'low' && risk !== 'medium' && risk !== 'high') risk = 'medium';
    return {
      task_id: String(task.task_id || ('pending-task-' + (++textTaskCardCounter))),
      task_type: String(task.task_type || ''),
      title: String(task.title || '待确认任务'),
      summary: String(task.summary || ''),
      risk: risk,
      risk_level: risk,
      allowed: task.allowed !== false,
      reason: String(task.reason || ''),
      original_text: String(task.original_text || ''),
      registered: task.registered === true,
      registry_status: String(task.registry_status || ''),
      expires_at: task.expires_at,
      expires_in_seconds: task.expires_in_seconds,
      source: String(task.source || '')
    };
  }

  function renderTextChatMessages() {
    var el = $('text-chat-messages');
    if (!el) return;
    el.innerHTML = textChatMessages.map(function (msg, index) {
      var meta = msg.meta || {};
      var parts = [];
      if (meta.source) parts.push('source: ' + meta.source);
      if (meta.latency_ms !== undefined) parts.push(meta.latency_ms + 'ms');
      if (meta.llm_configured !== undefined) parts.push('llm configured: ' + (meta.llm_configured ? 'yes' : 'no'));
      if (meta.blocked_panel_command) parts.push('panel command blocked');
      var metaHtml = parts.length ? '<div class="text-chat-message-meta">' + escapeHtml(parts.join(' · ')) + '</div>' : '';
      var taskHtml = msg.pendingTask ? renderPendingTaskCard(msg, index) : '';
      var resultHtml = msg.executionResult ? renderTextTaskExecutionResultCard(msg.executionResult) : '';
      var bubbleHtml = msg.text ? '<div class="text-chat-bubble">' + escapeHtml(msg.text) + '</div>' : '';
      return '<article class="text-chat-message ' + escapeHtml(msg.role) + '">' +
        bubbleHtml +
        taskHtml +
        resultHtml +
        metaHtml +
        '</article>';
    }).join('');
    scrollTextChatToBottom();
  }

  function normalizeTextTaskExecutionResult(data) {
    if (!data || typeof data !== 'object') return null;
    var status = String(data.status || (data.ok ? 'completed' : 'failed')).toLowerCase();
    if (status !== 'completed' && status !== 'blocked' && status !== 'failed') {
      status = data.ok ? 'completed' : 'failed';
    }
    var risk = String(data.risk_level || data.risk || 'low').toLowerCase();
    if (risk !== 'low' && risk !== 'medium' && risk !== 'high') risk = 'medium';
    var readFiles = Array.isArray(data.read_files) ? data.read_files.map(function (item) {
      return String(item || '');
    }).filter(Boolean) : [];
    return {
      ok: data.ok === true,
      task_id: String(data.task_id || ''),
      task_type: String(data.task_type || ''),
      status: status,
      title: String(data.title || '只读任务结果'),
      summary: String(data.summary || ''),
      details: String(data.details || ''),
      risk_level: risk,
      read_files: readFiles,
      error: String(data.error || '')
    };
  }

  function renderTextTaskExecutionResultCard(result) {
    var statusClass = getExecutionStatusClass(result.status, result.ok);
    var details = splitExecutionDetails(result.details).join('\n');
    var detailsHtml = details
      ? '<div class="text-task-result-details"><div class="text-task-result-section-label">详情</div><pre>' + escapeHtml(details) + '</pre></div>'
      : '';
    var filesHtml = result.read_files.length
      ? '<div class="text-task-result-files"><div class="text-task-result-section-label">读取文件</div><ul>' + result.read_files.map(function (file) {
        return '<li>' + escapeHtml(file) + '</li>';
      }).join('') + '</ul></div>'
      : '';
    var errorHtml = result.error && !result.ok
      ? '<div class="text-task-result-error"><span>错误码</span><code>' + escapeHtml(result.error) + '</code></div>'
      : '';

    return '<section class="text-task-result-card ' + statusClass + '">' +
      '<div class="text-task-result-header">' +
        '<div>' +
          '<div class="text-task-result-title">' + escapeHtml(getExecutionStatusLabel(result.status, result.ok)) + '</div>' +
          '<div class="text-task-result-meta">' +
            '<span>' + escapeHtml(result.title || '只读任务结果') + '</span>' +
            '<span>' + escapeHtml(result.task_type || 'unknown') + '</span>' +
            '<span>' + escapeHtml(result.status) + '</span>' +
            '<span>风险：' + escapeHtml(result.risk_level) + '</span>' +
          '</div>' +
        '</div>' +
        '<span class="text-task-result-status ' + statusClass + '">' + escapeHtml(getExecutionStatusLabel(result.status, result.ok)) + '</span>' +
      '</div>' +
      '<div class="text-task-result-summary">' + escapeHtml(result.summary || '没有返回摘要。') + '</div>' +
      detailsHtml +
      filesHtml +
      errorHtml +
      '</section>';
  }

  function getExecutionStatusLabel(status, ok) {
    if (status === 'completed' || ok) return '任务执行完成';
    if (status === 'blocked') return '任务已拦截';
    return '任务执行失败';
  }

  function getExecutionStatusClass(status, ok) {
    if (status === 'completed' || ok) return 'completed';
    if (status === 'blocked') return 'blocked';
    return 'failed';
  }

  function splitExecutionDetails(details) {
    return String(details || '').split(/\r?\n/).filter(function (line) {
      return line.trim() !== '';
    });
  }

  function formatTaskExpiryLabel(task) {
    var expiresAt = Number(task.expires_at);
    var expiresIn = Number(task.expires_in_seconds);
    var now = Date.now() / 1000;
    var remaining;
    if (Number.isFinite(expiresAt) && expiresAt > 0) {
      remaining = Math.max(0, expiresAt - now);
    } else if (Number.isFinite(expiresIn) && expiresIn > 0) {
      remaining = expiresIn;
    } else {
      return '';
    }
    if (remaining >= 60) {
      return '约 ' + Math.round(remaining / 60) + ' 分钟内有效';
    }
    return Math.round(remaining) + ' 秒内有效';
  }

  function renderPendingTaskCard(msg, index) {
    var task = msg.pendingTask || {};
    var taskId = task.task_id || ('pending-task-' + index);
    var status = msg.taskUiStatus || (task.allowed ? 'pending' : 'blocked');
    var risk = (task.risk === 'low' || task.risk === 'high') ? task.risk : 'medium';
    var disabled = status !== 'pending';
    var cardClass = 'text-task-card ' + escapeHtml(status);
    var reason = task.reason ? '<div class="text-task-disabled-note">' + escapeHtml(task.reason) + '</div>' : '';
    var original = task.original_text
      ? '<div class="text-task-original"><span class="text-task-original-label">原始输入</span><span class="text-task-original-text">' + escapeHtml(task.original_text) + '</span></div>'
      : '';
    var source = task.source ? '<span>' + escapeHtml(task.source) + '</span>' : '';
    var type = task.task_type ? '<span>' + escapeHtml(task.task_type) + '</span>' : '';
    var registered = task.registered ? '<span>任务已注册</span>' : '';
    var expiresLabel = formatTaskExpiryLabel(task);
    var expires = expiresLabel ? '<span>' + escapeHtml(expiresLabel) + '</span>' : '';
    var confirmButton = task.allowed
      ? '<button type="button" class="text-task-confirm" data-task-action="confirm" data-task-id="' + escapeHtml(taskId) + '"' + (disabled ? ' disabled' : '') + '>' + escapeHtml(getTaskConfirmLabel(status)) + '</button>'
      : '<button type="button" class="text-task-confirm" disabled>确认执行</button>';
    var cancelLabel = task.allowed ? '取消' : '不处理';
    var cancelButton = '<button type="button" class="text-task-cancel" data-task-action="cancel" data-task-id="' + escapeHtml(taskId) + '"' + (disabled ? ' disabled' : '') + '>' + cancelLabel + '</button>';

    return '<section class="' + cardClass + '">' +
      '<div class="text-task-card-header">' +
        '<div>' +
          '<div class="text-task-title">' + escapeHtml(task.title || '待确认任务') + '</div>' +
          '<div class="text-task-meta">' + type + source + registered + expires + '<span>' + escapeHtml(getTaskStatusLabel(status, task.allowed)) + '</span></div>' +
        '</div>' +
        '<span class="text-task-risk ' + risk + '">' + escapeHtml(getTaskRiskLabel(risk)) + '</span>' +
      '</div>' +
      '<div class="text-task-summary">' + escapeHtml(task.summary || '需要你确认后才能继续。') + '</div>' +
      original +
      reason +
      '<div class="text-task-actions">' + confirmButton + cancelButton + '</div>' +
      '</section>';
  }

  function getTaskRiskLabel(risk) {
    if (risk === 'low') return '低风险';
    if (risk === 'high') return '高风险';
    return '中风险';
  }

  function getTaskStatusLabel(status, allowed) {
    if (!allowed || status === 'blocked') return '已拦截';
    if (status === 'executing') return '执行中';
    if (status === 'completed') return '已完成';
    if (status === 'failed') return '执行失败';
    if (status === 'confirmed') return '已确认';
    if (status === 'cancelled') return '已取消';
    return '等待确认';
  }

  function getTaskConfirmLabel(status) {
    if (status === 'executing') return '执行中';
    if (status === 'completed') return '已完成';
    if (status === 'blocked') return '已拦截';
    if (status === 'failed') return '执行失败';
    return '确认执行';
  }

  function findPendingTaskMessage(taskId) {
    for (var i = textChatMessages.length - 1; i >= 0; i -= 1) {
      var msg = textChatMessages[i];
      if (msg.pendingTask && msg.pendingTask.task_id === taskId) return msg;
    }
    return null;
  }

  function handlePendingTaskConfirm(taskId) {
    var msg = findPendingTaskMessage(taskId);
    if (!msg || !msg.pendingTask || !msg.pendingTask.allowed || msg.taskUiStatus !== 'pending') return;
    msg.taskUiStatus = 'executing';
    renderTextChatMessages();
    apiCall('confirm_text_task', { task_id: msg.pendingTask.task_id }).then(function (resp) {
      var data = resp && resp.data ? resp.data : {};
      if (resp && resp.ok && data.ok) {
        msg.taskUiStatus = 'completed';
        renderTextChatMessages();
        appendTextChatMessage('assistant', '', {
          source: 'text_task_execution',
          task_status: data.status || 'completed'
        }, null, data);
        return;
      }
      msg.taskUiStatus = data.status === 'blocked' ? 'blocked' : 'failed';
      renderTextChatMessages();
      if (!data.summary && resp && resp.error) data.summary = resp.error;
      if (!data.error) data.error = data.status === 'blocked' ? 'blocked_task' : 'execution_failed';
      appendTextChatMessage('assistant', '', {
        source: 'text_task_execution',
        task_status: data.status || 'failed'
      }, null, data);
    }).catch(function (e) {
      msg.taskUiStatus = 'failed';
      renderTextChatMessages();
      appendTextChatMessage('assistant', '', { source: 'text_task_execution' }, null, {
        ok: false,
        task_id: msg.pendingTask.task_id || '',
        task_type: msg.pendingTask.task_type || '',
        status: 'failed',
        title: msg.pendingTask.title || '只读任务执行失败',
        summary: '文本任务执行出错。',
        details: String(e),
        risk_level: msg.pendingTask.risk_level || msg.pendingTask.risk || 'medium',
        read_files: [],
        error: 'frontend_error'
      });
    }).finally(function () {
      focusTextChatInput();
    });
  }

  function handlePendingTaskCancel(taskId) {
    var msg = findPendingTaskMessage(taskId);
    if (!msg || !msg.pendingTask || msg.taskUiStatus !== 'pending') return;
    msg.taskUiStatus = 'cancelled';
    renderTextChatMessages();
    apiCall('cancel_text_task', { task_id: msg.pendingTask.task_id }).catch(function () {});
    appendTextChatMessage('assistant', '已取消该任务。', { source: 'frontend_confirmation' });
  }

  function setTextChatSending(on) {
    textChatSending = !!on;
    var input = $('text-chat-input');
    var send = $('text-chat-send');
    var status = $('text-chat-status');
    if (input) input.disabled = textChatSending;
    if (send) {
      send.disabled = textChatSending;
      send.textContent = textChatSending ? '发送中...' : '发送';
      send.classList.toggle('is-loading', textChatSending);
    }
    if (status) status.textContent = textChatSending ? '小黄正在思考...' : '本地文本入口';
  }

  function sendTextChatMessage() {
    var input = $('text-chat-input');
    var text = input ? input.value.trim() : '';
    if (!text || textChatSending) return;

    appendTextChatMessage('user', text);
    input.value = '';
    setTextChatSending(true);

    apiCall('send_text_message', {
      text: text,
      session_id: textChatSessionId
    }).then(function (resp) {
      if (!resp || !resp.ok) {
        appendTextChatMessage('assistant', (resp && resp.error) || '文本消息处理失败', { source: 'error' });
        return;
      }
      var data = resp.data || {};
      appendTextChatMessage('assistant', data.reply_text || data.error || '没有返回内容', {
        source: data.reply_source,
        latency_ms: data.latency_ms,
        blocked_panel_command: data.blocked_panel_command,
        llm_configured: data.llm_configured
      }, data.requires_confirmation ? data.pending_task : null);
    }).catch(function (e) {
      appendTextChatMessage('assistant', '文本消息处理出错：' + e, { source: 'js_error' });
    }).finally(function () {
      setTextChatSending(false);
      focusTextChatInput();
    });
  }

  function clearTextChatSession() {
    resetTextChatMessages();
    apiCall('clear_text_session', { session_id: textChatSessionId }).then(function (resp) {
      if (resp && resp.ok) {
        drawerLog('清空文本会话', true, resp.message || '');
      }
    }).catch(function () {});
    focusTextChatInput();
  }

  /* ─── Actions ─── */
  function refreshStatus() {
    updateBridgeIndicator();
    apiCall('get_status').then(renderStatus);
    apiCall('get_log_paths').then(function (r) {
      if (r && r.ok && r.data) lastLogPaths = r.data;
      var el = $('drawer-logs-path');
      if (el && r && r.ok && r.data) el.textContent = r.data.logs_directory || '--';
    });
    apiCall('get_runtime_events', 20).then(renderRuntimeEvents);
  }

  function handleButtonClick(action, btn) {
    if (!action) return;
    if (activeAction && btn !== activeButton) {
      toast('已有操作正在进行，请稍候。', 'info');
      return;
    }

    if (action === 'refresh') { doRefresh(btn); return; }
    if (action === 'start') { doStart(btn); return; }
    if (action === 'stop') { doStop(btn); return; }
    if (action === 'restart') { doRestart(btn); return; }
    if (action === 'open-text-chat') { doOpenTextChat(); return; }
    if (action === 'open-diagnostics') { doOpenDiagnostics(); return; }
    if (action === 'save-config') { doSaveConfig(btn); return; }
    if (action === 'save-restart') { doSaveAndRestart(btn); return; }
    if (action === 'export-diag') { doExportDiag(btn); return; }
    if (action === 'open-logs-folder') { doOpenLogsFolder(btn); return; }
    if (action === 'preflight-check') { doPreflightCheck(btn); return; }
    toast('未识别的操作: ' + action, 'err');
  }

  function doOpenTextChat() {
    switchShell('text-chat');
    focusTextChatInput();
    toast('已切换到对话页', 'info');
  }

  function doOpenDiagnostics() {
    switchShell('control');
    switchSection('diagnostics');
    toast('已切换到诊断页', 'info');
  }

  function doRefresh(btn) {
    btn = btn || document.querySelector('[data-action="refresh"]');
    setButtonLoading(btn, getLoadingText('refresh'), 'refresh');
    toast('正在刷新状态...', 'info');
    refreshStatus();
    setTimeout(function () { restoreButton(btn, getButtonText('refresh'), 'refresh'); }, 500);
  }

  function doStart(btn) {
    btn = btn || document.querySelector('[data-action="start"]');
    if (!btn || btn.disabled) return;
    setButtonLoading(btn, getLoadingText('start'), 'start');
    toast('正在启动小黄，请稍候...', 'info');
    drawerLog('启动小黄', null, '已发送启动请求');

    apiCall('start_xiaohuang').then(function (r) {
      if (r && r.ok) {
        lastStartupDiagnostic = null;
        toast(r.message || '启动成功', 'ok');
        drawerLog('启动小黄', true, r.message);
        setTimeout(refreshStatus, 3000);
      } else {
        var diag = (r && r.data && r.data.diagnostic) ? r.data.diagnostic : null;
        lastStartupDiagnostic = diag;
        showStartupDiagnostic(diag);
        var msg = (r && r.error) || '启动失败';
        if (diag && diag.summary) msg = diag.summary;
        toast(msg, 'err');
        drawerLog('启动小黄', false, msg);
        refreshStatus();
      }
    }).catch(function (e) {
      toast('启动出错: ' + e, 'err');
      drawerLog('启动小黄', false, String(e));
    }).finally(function () {
      restoreButton(btn, getButtonText('start'), 'start');
    });

    setTimeout(function () {
      if (activeAction === 'start') toast('启动仍在进行，请查看日志或稍后刷新状态', 'info');
    }, 8000);
  }

  function doStop(btn) {
    btn = btn || document.querySelector('[data-action="stop"]');
    if (!btn || btn.disabled) return;
    setButtonLoading(btn, getLoadingText('stop'), 'stop');
    toast('正在停止小黄...', 'info');

    apiCall('stop_xiaohuang').then(function (r) {
      if (r && r.ok) {
        toast('已停止', 'ok');
        drawerLog('停止小黄', true);
        setTimeout(refreshStatus, 2000);
      } else {
        toast((r && r.error) || '停止失败', 'err');
        drawerLog('停止小黄', false, (r && r.error));
        refreshStatus();
      }
    }).catch(function (e) {
      toast('停止出错: ' + e, 'err');
      drawerLog('停止小黄', false, String(e));
    }).finally(function () {
      restoreButton(btn, getButtonText('stop'), 'stop');
    });
  }

  function doRestart(btn) {
    btn = btn || document.querySelector('[data-action="restart"]');
    if (!btn || btn.disabled) return;
    setButtonLoading(btn, getLoadingText('restart'), 'restart');
    toast('正在重启小黄，请稍候...', 'info');

    apiCall('restart_xiaohuang').then(function (r) {
      if (r && r.ok) {
        lastStartupDiagnostic = null;
        toast('重启成功', 'ok');
        drawerLog('重启小黄', true);
        setTimeout(refreshStatus, 5000);
      } else {
        var diag = (r && r.data && r.data.diagnostic) ? r.data.diagnostic : null;
        lastStartupDiagnostic = diag;
        showStartupDiagnostic(diag);
        var msg = (r && r.error) || '重启失败';
        if (diag && diag.summary) msg = diag.summary;
        toast(msg, 'err');
        drawerLog('重启小黄', false, msg);
        refreshStatus();
      }
    }).catch(function (e) {
      toast('重启出错: ' + e, 'err');
      drawerLog('重启小黄', false, String(e));
    }).finally(function () {
      restoreButton(btn, getButtonText('restart'), 'restart');
    });
  }

  function renderRuntimeEvents(response) {
    var data = (response && response.ok && response.data) ? response.data : null;
    var events = (data && data.events) ? data.events : [];
    lastRuntimeEvents = events;
    var el = $('drawer-runtime-events');
    if (!el) return;
    if (!events.length) {
      el.innerHTML = '暂无运行事件';
      return;
    }
    el.innerHTML = events.slice(-15).map(function (evt) {
      var cls = evt.level === 'error' ? 'err' : evt.level === 'warning' ? 'warn' : '';
      return '<div class="drawer-entry ' + cls + '"><span class="ts">' +
        escapeHtml(evt.timestamp ? evt.timestamp.slice(-8) : '') + '</span>' +
        escapeHtml(evt.source + '/' + evt.event_type) +
        ' — ' + escapeHtml(evt.message || '') + '</div>';
    }).join('');
  }

  function collectDrawerText(id) {
    var el = $(id);
    return el ? (el.textContent || '').trim() : '';
  }

  function showStartupDiagnostic(diag) {
    var lastError = $('drawer-last-error');
    if (!lastError) return;
    if (!diag || !diag.summary) return;
    var text = '启动失败：' + escapeHtml(diag.summary);
    if (diag.suggestion) text += '\n建议：' + escapeHtml(diag.suggestion);
    if (diag.source_file) text += '\n来源：' + escapeHtml(diag.source_file);
    lastError.textContent = text;
    lastError.className = 'drawer-value err';
    lastError.style.whiteSpace = 'pre-wrap';
  }

  function doPreflightCheck(btn) {
    if (!btn || btn.disabled) return;
    setButtonLoading(btn, '检查中...', 'preflight-check');
    drawerLog('启动前检查', null, '已发送检查请求');

    apiCall('get_preflight_check').then(function (r) {
      if (r && r.ok && r.data) {
        lastPreflightCheck = r.data;
        renderPreflightCheck(r.data);
        var summary = r.data.summary || '检查完成';
        toast(summary, r.data.status === 'error' ? 'err' : r.data.status === 'warning' ? 'warn' : 'ok');
        drawerLog('启动前检查', true, summary);
      } else {
        lastPreflightCheck = null;
        toast((r && r.error) || '检查失败', 'err');
        drawerLog('启动前检查', false, (r && r.error));
      }
    }).catch(function (e) {
      toast('检查出错: ' + e, 'err');
      drawerLog('启动前检查', false, String(e));
    }).finally(function () {
      restoreButton(btn, '运行检查', 'preflight-check');
    });
  }

  function renderPreflightCheck(data) {
    var el = $('drawer-preflight');
    if (!el) return;
    if (!data || !data.items || !data.items.length) {
      el.innerHTML = '暂无检查结果';
      return;
    }
    var icon = { ok: '✅', warning: '⚠️', error: '❌' };
    var html = data.items.map(function (item) {
      var ico = icon[item.status] || '?';
      return '<div class="drawer-entry"><span class="ts">' + ico +
        '</span> ' + escapeHtml(item.label) + '：' + escapeHtml(item.message) +
        (item.suggestion ? '<div class="hint" style="margin-left:1.5em">→ ' + escapeHtml(item.suggestion) + '</div>' : '') +
        '</div>';
    }).join('');
    html += '<div style="margin-top:6px;font-weight:600">结论：' + escapeHtml(data.summary || '') + '</div>';
    el.innerHTML = html;
  }

  function doExportDiag(btn) {
    if (!btn || btn.disabled) return;
    setButtonLoading(btn, '导出中...', 'export-diag');
    toast('正在导出诊断信息...', 'info');
    drawerLog('导出诊断 TXT', null, '已发送导出请求');

    var payload = {
      exported_from: 'control_panel_web',
      bridge_ready: !!getApi(),
      status: lastStatusData || {},
      log_paths: lastLogPaths || {},
      drawer: {
        config_path: collectDrawerText('drawer-config-path'),
        logs_path: collectDrawerText('drawer-logs-path'),
        last_error: collectDrawerText('drawer-last-error'),
        last_operation: collectDrawerText('drawer-last-op')
      },
      history: opHistory,
      runtime_events: lastRuntimeEvents,
      startup_diagnostic: lastStartupDiagnostic || {},
      preflight_check: lastPreflightCheck || {}
    };

    apiCall('export_diagnostics_text', payload).then(function (r) {
      if (r && r.ok && r.data && r.data.path) {
        toast('诊断信息已导出: ' + (r.message || r.data.path), 'ok');
        drawerLog('导出诊断 TXT', true, r.data.path);
      } else {
        toast((r && r.error) || '导出失败', 'err');
        drawerLog('导出诊断 TXT', false, (r && r.error));
      }
    }).catch(function (e) {
      toast('导出出错: ' + e, 'err');
      drawerLog('导出诊断 TXT', false, String(e));
    }).finally(function () {
      restoreButton(btn, '导出 TXT', 'export-diag');
    });
  }

  function doOpenLogsFolder(btn) {
    if (!btn || btn.disabled) return;
    setButtonLoading(btn, '打开中...', 'open-logs-folder');
    drawerLog('打开日志目录', null, '已发送请求');
    apiCall('open_logs_folder').then(function (r) {
      if (r && r.ok) {
        toast('日志目录已打开', 'ok');
        drawerLog('打开日志目录', true, (r.data && r.data.path) || '');
      } else {
        toast((r && r.error) || '打开失败', 'err');
        drawerLog('打开日志目录', false, (r && r.error));
      }
    }).catch(function (e) {
      toast('打开出错: ' + e, 'err');
      drawerLog('打开日志目录', false, String(e));
    }).finally(function () {
      restoreButton(btn, '打开', 'open-logs-folder');
    });
  }

  function wakePayload() {
    return {
      engine: getVal('wake-engine'),
      fallback_enabled: getChecked('wake-fallback'),
      device_index: getVal('wake-device'),
      cooldown_seconds: getVal('wake-cooldown'),
      sensitivity: getVal('wake-sensitivity')
    };
  }

  function doSaveConfig(btn) {
    btn = btn || document.querySelector('[data-action="save-config"]');
    if (!btn || btn.disabled) return;
    setButtonLoading(btn, getLoadingText('save-config'), 'save-config');

    apiCall('save_wake_config', wakePayload()).then(function (r) {
      if (r && r.ok) {
        toast('配置已保存', 'ok');
        var hint = $('wake-hint');
        if (hint) hint.textContent = '已保存，需重启小黄生效。';
        drawerLog('保存配置', true);
        refreshStatus();
      } else {
        toast((r && r.error) || '保存失败', 'err');
        drawerLog('保存配置', false, (r && r.error));
      }
    }).catch(function (e) {
      toast('保存出错: ' + e, 'err');
      drawerLog('保存配置', false, String(e));
    }).finally(function () {
      restoreButton(btn, getButtonText('save-config'), 'save-config');
    });
  }

  function doSaveAndRestart(btn) {
    btn = btn || document.querySelector('[data-action="save-restart"]');
    if (!btn || btn.disabled) return;
    setButtonLoading(btn, getLoadingText('save-restart'), 'save-restart');

    apiCall('save_wake_config', wakePayload()).then(function (r) {
      if (!r || !r.ok) {
        toast((r && r.error) || '保存失败', 'err');
        drawerLog('保存并重启', false, (r && r.error));
        return Promise.resolve(null);
      }

      var hint = $('wake-hint');
      if (hint) hint.textContent = '';
      btn.textContent = '重启中...';
      drawerLog('保存配置', true, '准备重启');
      return apiCall('restart_xiaohuang').then(function (rr) {
        if (rr && rr.ok) {
          toast('保存并重启成功', 'ok');
          drawerLog('保存并重启', true);
          setTimeout(refreshStatus, 5000);
        } else {
          toast((rr && rr.error) || '重启失败', 'err');
          drawerLog('保存并重启', false, (rr && rr.error));
          refreshStatus();
        }
      });
    }).catch(function (e) {
      toast('保存并重启出错: ' + e, 'err');
      drawerLog('保存并重启', false, String(e));
    }).finally(function () {
      restoreButton(btn, getButtonText('save-restart'), 'save-restart');
    });
  }

  /* ─── Event Delegation ─── */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    e.preventDefault();
    var action = btn.getAttribute('data-action');
    if (action) handleButtonClick(action, btn);
  });

  /* ─── Init ─── */
  function doInit() {
    if (initDone) return;
    initDone = true;
    initNav();
    initSidebarControls();
    initDrawerControls();
    initTextChat();
    switchShell(currentShell);
    switchSection(currentSection);
    updateBridgeIndicator();
    refreshStatus();
    drawerLog('面板启动', true);
  }

  window.addEventListener('pywebviewready', function () {
    bridgeReady = true;
    doInit();
  });

  document.addEventListener('DOMContentLoaded', function () {
    initSidebarControls();
    initDrawerControls();
    updateBridgeIndicator();
    setTimeout(function () { if (!initDone) doInit(); }, 800);
  });
})();

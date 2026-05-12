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
  var taskHistoryItems = [];
  var taskHistoryLoading = false;
  var taskHistorySelectedId = null;

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

  function copyTextToClipboard(text) {
    var value = String(text || '');
    if (!value.trim()) return Promise.reject(new Error('empty clipboard text'));
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(value);
    }
    return new Promise(function (resolve, reject) {
      var area = document.createElement('textarea');
      area.value = value;
      area.setAttribute('readonly', 'readonly');
      area.style.position = 'fixed';
      area.style.left = '-9999px';
      document.body.appendChild(area);
      area.select();
      try {
        if (document.execCommand('copy')) resolve();
        else reject(new Error('copy command failed'));
      } catch (err) {
        reject(err);
      } finally {
        document.body.removeChild(area);
      }
    });
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
      'refresh-multica-status': '刷新 Multica 状态',
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
      'refresh-multica-status': '刷新中...',
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

  function renderMulticaStatus(resp) {
    var d = (resp && resp.ok && resp.data) ? resp.data : null;
    var error = resp && (resp.error || resp.message || resp.code);
    setMulticaText('multica-installed', d ? (d.installed ? '已安装' : '未找到') : '读取失败');
    setMulticaText('multica-version', d ? (d.version || '--') : '--');
    setMulticaText('multica-daemon', d ? ((d.daemon_running ? 'running' : 'stopped/unknown') + (d.daemon_summary ? ' · ' + d.daemon_summary : '')) : '--');
    setMulticaText('multica-agents', d ? ((d.agents || []).join(' / ') || '--') : '--');
    setMulticaText('multica-workspace', d ? (d.workspace_summary || '--') : '--');
    var warningEl = $('multica-warnings');
    if (warningEl) {
      var warnings = d && Array.isArray(d.warnings) ? d.warnings : [];
      warningEl.textContent = warnings.length ? ('警告：' + warnings.join('；')) : (d ? '只读状态读取完成。' : ('读取失败：' + (error || 'Multica 状态不可用')));
      warningEl.className = 'multica-status-warning' + (warnings.length || !d ? ' warn' : ' ok');
    }
  }

  function setMulticaText(id, value) {
    var el = $(id);
    if (el) el.textContent = fmtVal(value);
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
    if (currentSection === 'tasks') {
      loadTaskHistory();
    }
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
        var copyButton = event.target.closest('[data-handoff-copy]');
        if (copyButton) {
          event.preventDefault();
          handleAgentHandoffCopy(copyButton);
          return;
        }
        var terminalButton = event.target.closest('[data-handoff-terminal]');
        if (terminalButton) {
          event.preventDefault();
          handleAgentHandoffTerminal(terminalButton);
          return;
        }
        var draftButton = event.target.closest('[data-multica-draft]');
        if (draftButton) {
          event.preventDefault();
          handleMulticaIssueDraftAction(draftButton);
          return;
        }
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

  function getHealthStatusFromResult(result) {
    var text = ((result && result.summary) || '') + '\n' + ((result && result.details) || '');
    if (text.indexOf('有错误') >= 0) return 'error';
    if (text.indexOf('有警告') >= 0) return 'warning';
    if (text.indexOf('信息不足') >= 0) return 'unknown';
    if (text.indexOf('正常') >= 0) return 'healthy';
    return 'unknown';
  }

  function getHealthStatusLabel(status) {
    var map = { healthy: '正常', warning: '有警告', error: '有错误', unknown: '信息不足' };
    return map[status] || status;
  }

  function splitHealthReportSections(details) {
    var lines = String(details || '').split(/\r?\n/);
    var sections = [];
    var current = null;
    var headerRe = /^[一二三四五六七八九十]+、/;
    for (var i = 0; i < lines.length; i += 1) {
      var line = lines[i];
      var trimmed = line.trim();
      if (headerRe.test(trimmed)) {
        if (current) sections.push(current);
        current = { title: trimmed, body: '' };
      } else if (current) {
        current.body += (current.body ? '\n' : '') + line;
      }
    }
    if (current) sections.push(current);
    return sections;
  }

  function renderHealthReportResultCard(result) {
    var healthStatus = getHealthStatusFromResult(result);
    var healthLabel = getHealthStatusLabel(healthStatus);
    var sections = splitHealthReportSections(result.details || '');

    var sectionsHtml = sections.length
      ? sections.map(function (sec) {
          var lines = sec.body.split(/\r?\n/).filter(function (l) { return l.trim(); });
          return '<div class="health-report-section">' +
            '<div class="health-report-section-title">' + escapeHtml(sec.title) + '</div>' +
            '<div class="health-report-section-body">' +
              lines.map(function (l) { return '<div>' + escapeHtml(l) + '</div>'; }).join('') +
            '</div>' +
          '</div>';
        }).join('')
      : '<div class="health-report-section"><pre>' + escapeHtml(result.details || '') + '</pre></div>';

    return '<section class="text-task-result-card health-report-card">' +
      '<div class="health-report-head">' +
        '<span class="health-report-title">' + escapeHtml(result.title || '小黄健康检查报告') + '</span>' +
        '<span class="health-state-pill ' + healthStatus + '">' + escapeHtml(healthLabel) + '</span>' +
      '</div>' +
      '<div class="health-report-summary">' + escapeHtml(result.summary || '') + '</div>' +
      '<div class="health-report-sections">' + sectionsHtml + '</div>' +
      '</section>';
  }

  function renderTextTaskExecutionResultCard(result) {
    if (result.task_type === 'readonly_health_report') {
      return renderHealthReportResultCard(result);
    }
    if (result.task_type === 'agent_handoff_draft') {
      return renderAgentHandoffResultCard(result);
    }
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

  function renderAgentHandoffResultCard(result) {
    var statusClass = getExecutionStatusClass(result.status, result.ok);
    var handoff = parseAgentHandoffDetails(result.details || '');
    var details = splitExecutionDetails(result.details).join('\n');
    var terminalDisabled = !handoff.canOpenTerminal || !handoff.targetProjectPath;
    var terminalTitle = terminalDisabled ? (handoff.terminalHint || '目标项目路径不可用') : '打开目标项目终端';
    var terminalButton = '<button type="button" data-handoff-terminal data-target-project-path="' + escapeHtml(handoff.targetProjectPath) + '"' +
      (terminalDisabled ? ' disabled' : '') + ' title="' + escapeHtml(terminalTitle) + '">打开目标项目终端</button>';
    var actionsHtml = result.ok ? '<div class="agent-handoff-actions">' +
      '<button type="button" data-handoff-copy="full" data-handoff-path="' + escapeHtml(handoff.path) + '">复制完整提示词</button>' +
      terminalButton +
      '<button type="button" data-handoff-copy="path" data-handoff-path="' + escapeHtml(handoff.path) + '">复制文件路径</button>' +
      '<button type="button" data-handoff-copy="preview" data-handoff-preview="' + escapeHtml(handoff.preview) + '">复制预览</button>' +
      '<span class="agent-handoff-copy-status" aria-live="polite"></span>' +
      '</div>' : '';
    var targetMetaHtml = '<div class="agent-handoff-target-meta">' +
      '<div><span>目标项目路径</span><code>' + escapeHtml(handoff.targetProjectPath || '未指定') + '</code></div>' +
      '<div><span>目标项目类型</span><strong>' + escapeHtml(handoff.targetProjectKind || 'auto') + '</strong></div>' +
      '<div><span>项目关系</span><strong>' + escapeHtml(handoff.projectRelation || 'auto') + '</strong></div>' +
      (handoff.terminalHint ? '<div><span>终端状态</span><strong>' + escapeHtml(handoff.terminalHint) + '</strong></div>' : '') +
      '</div>';
    var pathHtml = handoff.path
      ? '<div class="agent-handoff-path"><span>文件</span><code>' + escapeHtml(handoff.path) + '</code></div>'
      : '';
    var previewHtml = handoff.preview
      ? '<div class="agent-handoff-preview"><div class="text-task-result-section-label">预览</div><pre>' + escapeHtml(handoff.preview) + '</pre></div>'
      : '';
    var multicaDraftHtml = result.ok ? renderMulticaIssueDraftPanel(result, handoff) : '';
    return '<section class="text-task-result-card agent-handoff-result-card ' + statusClass + '">' +
      '<div class="text-task-result-header">' +
        '<div>' +
          '<div class="text-task-result-title">' + escapeHtml(result.title || 'Agent Handoff 已生成') + '</div>' +
          '<div class="text-task-result-meta">' +
            '<span>' + escapeHtml(result.task_type || 'agent_handoff_draft') + '</span>' +
            '<span>' + escapeHtml(result.status) + '</span>' +
            '<span>风险：' + escapeHtml(result.risk_level) + '</span>' +
          '</div>' +
        '</div>' +
        '<span class="text-task-result-status ' + statusClass + '">' + escapeHtml(getExecutionStatusLabel(result.status, result.ok)) + '</span>' +
      '</div>' +
      '<div class="text-task-result-summary">' + escapeHtml(result.summary || 'Agent Handoff 已生成。') + '</div>' +
      actionsHtml +
      targetMetaHtml +
      multicaDraftHtml +
      pathHtml +
      previewHtml +
      '<div class="text-task-result-details agent-handoff-detail"><div class="text-task-result-section-label">详情</div><pre>' + escapeHtml(details) + '</pre></div>' +
      (result.error && !result.ok ? '<div class="text-task-result-error"><span>错误码</span><code>' + escapeHtml(result.error) + '</code></div>' : '') +
      '</section>';
  }

  function parseAgentHandoffDetails(details) {
    var text = String(details || '');
    var pathMatch = text.match(/(?:^|\n)文件：([^\n\r]+)/);
    var targetPathMatch = text.match(/(?:^|\n)目标项目路径：([^\n\r]+)/);
    var targetKindMatch = text.match(/(?:^|\n)目标项目类型：([^\n\r]+)/);
    var relationMatch = text.match(/(?:^|\n)与小黄项目关系：([^\n\r]+)/);
    var agentMatch = text.match(/(?:^|\n)目标 Agent：([^\n\r]+)/);
    var domainsMatch = text.match(/(?:^|\n)相关领域：([^\n\r]+)/);
    var databaseMatch = text.match(/(?:^|\n)数据库：([^\n\r]+)/);
    var canOpenMatch = text.match(/(?:^|\n)可打开终端：([^\n\r]+)/);
    var terminalHintMatch = text.match(/(?:^|\n)终端提示：([^\n\r]+)/);
    var marker = '\n预览：\n';
    var idx = text.indexOf(marker);
    return {
      path: pathMatch ? pathMatch[1].trim() : '',
      targetProjectPath: targetPathMatch ? targetPathMatch[1].trim() : '',
      targetProjectKind: targetKindMatch ? targetKindMatch[1].trim() : '',
      projectRelation: relationMatch ? relationMatch[1].trim() : '',
      targetAgent: agentMatch ? agentMatch[1].trim() : '',
      domains: domainsMatch ? domainsMatch[1].trim() : '',
      databaseStatus: databaseMatch ? databaseMatch[1].trim() : '',
      canOpenTerminal: canOpenMatch ? canOpenMatch[1].trim() === '是' : false,
      terminalHint: terminalHintMatch ? terminalHintMatch[1].trim() : '',
      preview: idx >= 0 ? text.slice(idx + marker.length).trim() : ''
    };
  }

  function renderMulticaIssueDraftPanel(result, handoff) {
    return '<div class="multica-draft-panel" data-multica-draft-panel>' +
      '<div class="multica-draft-head">' +
        '<div><div class="text-task-result-section-label">Multica Issue 草稿</div>' +
        '<p>仅草稿，未创建 issue，未分配 Agent。</p></div>' +
        '<button type="button" data-multica-draft="generate"' +
          ' data-handoff-title="' + escapeHtml(result.title || '') + '"' +
          ' data-handoff-path="' + escapeHtml(handoff.path) + '"' +
          ' data-target-project-path="' + escapeHtml(handoff.targetProjectPath) + '"' +
          ' data-target-project-kind="' + escapeHtml(handoff.targetProjectKind) + '"' +
          ' data-project-relation="' + escapeHtml(handoff.projectRelation) + '"' +
          ' data-database-status="' + escapeHtml(handoff.databaseStatus) + '"' +
          ' data-related-domains="' + escapeHtml(handoff.domains) + '"' +
          ' data-preferred-agent="' + escapeHtml(handoff.targetAgent) + '">生成 Issue 草稿</button>' +
      '</div>' +
      '<div class="multica-draft-summary" data-multica-draft-summary>尚未生成 Multica Issue 草稿。</div>' +
      '<div class="multica-draft-actions">' +
        '<button type="button" data-multica-draft="copy-title" disabled>复制 Issue 标题</button>' +
        '<button type="button" data-multica-draft="copy-description" disabled>复制 Issue 描述</button>' +
        '<button type="button" data-multica-draft="copy-command" disabled>复制命令草稿</button>' +
        '<button type="button" data-multica-draft="download-md" disabled>下载草稿 .md</button>' +
        '<button type="button" data-multica-draft="prepare-create" disabled>准备创建 Issue</button>' +
      '</div>' +
      '<div class="multica-create-confirm" data-multica-create-confirm hidden>' +
        '<p>将创建真实 Multica issue，但不会分配 Agent，也不会启动 Claude/Codex/opencode/OpenClaw。确认前请检查 title、description、target project 和 warnings。</p>' +
        '<label>确认短语 <code>CREATE_MULTICA_ISSUE</code>' +
          '<input type="text" data-multica-create-phrase autocomplete="off" spellcheck="false">' +
        '</label>' +
        '<div class="multica-create-actions">' +
          '<button type="button" data-multica-draft="confirm-create">确认创建 Issue</button>' +
          '<span data-multica-create-status></span>' +
        '</div>' +
      '</div>' +
      '<div class="multica-create-result" data-multica-create-result hidden></div>' +
      '<pre class="multica-draft-preview" data-multica-draft-preview></pre>' +
    '</div>';
  }

  function handleAgentHandoffCopy(btn) {
    var mode = btn.getAttribute('data-handoff-copy') || '';
    var status = btn.parentElement ? btn.parentElement.querySelector('.agent-handoff-copy-status') : null;
    var path = btn.getAttribute('data-handoff-path') || '';
    var preview = btn.getAttribute('data-handoff-preview') || '';
    var promise;
    if (mode === 'full') {
      promise = path ? apiCall('read_agent_handoff_file', { path: path }).then(function (resp) {
        if (!resp || !resp.ok || !resp.content) {
          throw new Error((resp && resp.error) || 'handoff file read failed');
        }
        return copyTextToClipboard(resp.content);
      }) : Promise.reject(new Error('missing handoff path'));
    } else if (mode === 'path') {
      promise = copyTextToClipboard(path);
    } else {
      promise = copyTextToClipboard(preview);
    }
    btn.disabled = true;
    return promise.then(function () {
      if (status) status.textContent = '已复制';
      toast(mode === 'full' ? '已复制完整提示词' : mode === 'path' ? '已复制文件路径' : '已复制预览', 'ok');
    }).catch(function () {
      if (status) status.textContent = '复制失败';
      toast('复制失败，请手动打开 handoff 文件', 'err');
    }).finally(function () {
      btn.disabled = false;
    });
  }

  function handleAgentHandoffTerminal(btn) {
    var status = btn.parentElement ? btn.parentElement.querySelector('.agent-handoff-copy-status') : null;
    var targetProjectPath = btn.getAttribute('data-target-project-path') || '';
    btn.disabled = true;
    if (status) status.textContent = '正在打开终端';
    return apiCall('open_agent_handoff_terminal', { target_project_path: targetProjectPath }).then(function (resp) {
      if (!resp || !resp.ok) {
        throw new Error((resp && (resp.error || resp.message || resp.code)) || 'open terminal failed');
      }
      if (status) status.textContent = '已请求打开';
      toast(resp.message || '已向系统请求打开目标项目终端', 'ok');
    }).catch(function (err) {
      if (status) status.textContent = '打开失败';
      toast((err && err.message) || '打开目标项目终端失败', 'err');
    }).finally(function () {
      btn.disabled = false;
    });
  }

  function handleMulticaIssueDraftAction(btn) {
    var action = btn.getAttribute('data-multica-draft') || '';
    var panel = btn.closest('[data-multica-draft-panel]');
    if (!panel) return Promise.resolve();
    if (action === 'generate') return generateMulticaIssueDraft(btn, panel);
    var draft = getPanelDraft(panel);
    if (!draft) {
      toast('请先生成 Issue 草稿', 'err');
      return Promise.resolve();
    }
    if (action === 'copy-title') return copyTextToClipboard(draft.title).then(function () { toast('已复制 Issue 标题', 'ok'); });
    if (action === 'copy-description') return copyTextToClipboard(draft.description).then(function () { toast('已复制 Issue 描述', 'ok'); });
    if (action === 'copy-command') return copyTextToClipboard(draft.create_command_preview).then(function () { toast('已复制命令草稿', 'ok'); });
    if (action === 'prepare-create') return prepareMulticaIssueCreate(panel);
    if (action === 'confirm-create') return confirmMulticaIssueCreate(btn, panel, draft);
    if (action === 'prepare-assign') return prepareMulticaIssueAssign(panel);
    if (action === 'confirm-assign') return confirmMulticaIssueAssign(btn, panel);
    if (action === 'download-md') {
      downloadTextFile(draft.markdown, buildDraftFilename(draft.title));
      toast('已下载草稿 .md', 'ok');
    }
    return Promise.resolve();
  }

  function generateMulticaIssueDraft(btn, panel) {
    var summary = panel.querySelector('[data-multica-draft-summary]');
    var preview = panel.querySelector('[data-multica-draft-preview]');
    var path = btn.getAttribute('data-handoff-path') || '';
    btn.disabled = true;
    if (summary) summary.textContent = '正在生成 Issue 草稿...';
    return apiCall('read_agent_handoff_file', { path: path }).then(function (fileResp) {
      if (!fileResp || !fileResp.ok || !fileResp.content) {
        throw new Error((fileResp && fileResp.error) || '无法读取完整 handoff prompt');
      }
      return apiCall('build_multica_issue_draft', {
        handoff_title: btn.getAttribute('data-handoff-title') || '',
        handoff_prompt: fileResp.content,
        target_project_path: btn.getAttribute('data-target-project-path') || '',
        target_project_kind: btn.getAttribute('data-target-project-kind') || 'auto',
        project_relation: btn.getAttribute('data-project-relation') || 'unknown',
        database_brief_status: btn.getAttribute('data-database-status') || '',
        related_domains: splitCommaList(btn.getAttribute('data-related-domains') || ''),
        preferred_agent: btn.getAttribute('data-preferred-agent') || ''
      });
    }).then(function (resp) {
      if (!resp || !resp.ok || !resp.data) {
        throw new Error((resp && (resp.error || resp.message || resp.code)) || 'Issue 草稿生成失败');
      }
      setPanelDraft(panel, resp.data);
      renderPanelDraft(panel, resp.data);
      toast('Multica Issue 草稿已生成', 'ok');
    }).catch(function (err) {
      if (summary) summary.textContent = 'Issue 草稿生成失败：' + ((err && err.message) || err);
      if (preview) preview.textContent = '';
      toast('Issue 草稿生成失败', 'err');
    }).finally(function () {
      btn.disabled = false;
    });
  }

  function setPanelDraft(panel, draft) {
    panel.dataset.issueDraftJson = JSON.stringify(draft || {});
    panel.dataset.issueCreateResultJson = '';
    panel.querySelectorAll('[data-multica-draft]').forEach(function (button) {
      var action = button.getAttribute('data-multica-draft') || '';
      if (action !== 'generate' && action !== 'confirm-create') button.disabled = false;
    });
    var confirmBox = panel.querySelector('[data-multica-create-confirm]');
    var resultBox = panel.querySelector('[data-multica-create-result]');
    var phrase = panel.querySelector('[data-multica-create-phrase]');
    var status = panel.querySelector('[data-multica-create-status]');
    if (confirmBox) confirmBox.hidden = true;
    if (resultBox) { resultBox.hidden = true; resultBox.innerHTML = ''; }
    if (phrase) phrase.value = '';
    if (status) status.textContent = '';
  }

  function getPanelDraft(panel) {
    try {
      return panel && panel.dataset.issueDraftJson ? JSON.parse(panel.dataset.issueDraftJson) : null;
    } catch (err) {
      return null;
    }
  }

  function getPanelCreateResult(panel) {
    try {
      return panel && panel.dataset.issueCreateResultJson ? JSON.parse(panel.dataset.issueCreateResultJson) : null;
    } catch (err) {
      return null;
    }
  }

  function renderPanelDraft(panel, draft) {
    var summary = panel.querySelector('[data-multica-draft-summary]');
    var preview = panel.querySelector('[data-multica-draft-preview]');
    var warnings = Array.isArray(draft.warnings) ? draft.warnings : [];
    if (summary) {
      summary.innerHTML = '<div><span>标题</span><strong>' + escapeHtml(draft.title || '--') + '</strong></div>' +
        '<div><span>建议 Agent</span><strong>' + escapeHtml((draft.suggested_assignees || []).join(' / ') || '--') + '</strong></div>' +
        '<div><span>默认建议</span><strong>' + escapeHtml(draft.default_assignee || '--') + '</strong></div>' +
        '<div><span>目标项目</span><code>' + escapeHtml(draft.target_project_path || '未指定') + '</code></div>' +
        '<div><span>安全状态</span><strong>仅草稿，未创建 issue，未分配 Agent</strong></div>' +
        (warnings.length ? '<p>' + escapeHtml(warnings.join('；')) + '</p>' : '');
    }
    if (preview) preview.textContent = draft.create_command_preview || '';
  }

  function prepareMulticaIssueCreate(panel) {
    var confirmBox = panel.querySelector('[data-multica-create-confirm]');
    var phrase = panel.querySelector('[data-multica-create-phrase]');
    var confirmButton = panel.querySelector('[data-multica-draft="confirm-create"]');
    var status = panel.querySelector('[data-multica-create-status]');
    if (confirmBox) confirmBox.hidden = false;
    if (phrase) {
      phrase.value = '';
      phrase.focus();
      phrase.oninput = function () {
        if (confirmButton) confirmButton.disabled = phrase.value.trim() !== 'CREATE_MULTICA_ISSUE';
      };
    }
    if (confirmButton) confirmButton.disabled = true;
    if (status) status.textContent = '输入确认短语后才能创建真实 issue。';
    toast('请检查草稿并输入确认短语', 'info');
    return Promise.resolve();
  }

  function confirmMulticaIssueCreate(btn, panel, draft) {
    var phrase = panel.querySelector('[data-multica-create-phrase]');
    var status = panel.querySelector('[data-multica-create-status]');
    var text = phrase ? phrase.value.trim() : '';
    if (text !== 'CREATE_MULTICA_ISSUE') {
      if (status) status.textContent = '确认短语不匹配。';
      toast('确认短语不匹配', 'err');
      return Promise.resolve();
    }
    btn.disabled = true;
    if (status) status.textContent = '正在创建 Multica issue...';
    return apiCall('create_multica_issue_from_draft', {
      title: draft.title || '',
      description: draft.description || '',
      confirmed: true,
      confirmation_text: text
    }).then(function (resp) {
      if (!resp || !resp.ok || !resp.data) {
        throw new Error((resp && (resp.error || resp.message || resp.code)) || '创建 Issue 失败');
      }
      panel.dataset.issueCreateResultJson = JSON.stringify(resp.data || {});
      renderMulticaIssueCreateResult(panel, resp.data);
      if (status) status.textContent = 'Multica issue 已创建。';
      toast('Multica issue 已创建', 'ok');
    }).catch(function (err) {
      if (status) status.textContent = '创建失败：' + ((err && err.message) || err);
      toast('创建 Multica issue 失败', 'err');
    }).finally(function () {
      btn.disabled = false;
    });
  }

  function renderMulticaIssueCreateResult(panel, result) {
    var box = panel.querySelector('[data-multica-create-result]');
    if (!box) return;
    var warnings = Array.isArray(result.warnings) ? result.warnings : [];
    box.hidden = false;
    box.innerHTML = '<strong>Multica issue 已创建</strong>' +
      '<div>Issue ID: <code>' + escapeHtml(result.issue_id || '未返回') + '</code></div>' +
      '<div>Identifier: <code>' + escapeHtml(result.identifier || '--') + '</code></div>' +
      '<div>标题: ' + escapeHtml(result.title || '--') + '</div>' +
      '<div>状态: ' + escapeHtml(result.status || '--') + '</div>' +
      '<div>未分配 Agent</div>' +
      '<div>下一步可在 C5F 中确认分配 Agent</div>' +
      (warnings.length ? '<p>' + escapeHtml(warnings.join('；')) + '</p>' : '') +
      renderMulticaIssueAssignPanel(result);
  }

  function renderMulticaIssueAssignPanel(result) {
    var issueId = result && result.issue_id ? String(result.issue_id) : '';
    var identifier = result && result.identifier ? String(result.identifier) : '';
    var suggestedIssueId = issueId || identifier;
    var fallbackHint = issueId ? '' :
      '<p>未自动返回 Issue ID。你可以手动输入已有 Multica issue id 或 identifier 后继续分配。</p>';
    return '<div class="multica-assign-panel" data-multica-assign-panel>' +
      fallbackHint +
      '<label>Issue ID / Identifier' +
        '<input type="text" data-multica-assign-issue-id autocomplete="off" spellcheck="false"' +
          ' placeholder="例如：78480e61 或 HHH-19" value="' + escapeHtml(suggestedIssueId) + '">' +
      '</label>' +
      '<label>Agent' +
        '<select data-multica-assign-agent>' +
          '<option value="claude">claude</option>' +
          '<option value="codex">codex</option>' +
          '<option value="opencode">opencode</option>' +
          '<option value="openclaw">openclaw</option>' +
        '</select>' +
      '</label>' +
      '<button type="button" data-multica-draft="prepare-assign">准备分配 Agent</button>' +
      '<div class="multica-assign-confirm" data-multica-assign-confirm hidden>' +
        '<p>将把真实 Multica issue 分配给所选 Agent。Multica 可能会让该 Agent 开始处理或进入工作队列。小黄不会额外启动本地 Agent，也不会读取 runs/run-messages。请确认 issue id 和 agent。</p>' +
        '<div>需要输入：<code data-multica-assign-expected></code></div>' +
        '<input type="text" data-multica-assign-phrase autocomplete="off" spellcheck="false">' +
        '<div class="multica-assign-actions">' +
          '<button type="button" data-multica-draft="confirm-assign" disabled>确认分配 Agent</button>' +
          '<span data-multica-assign-status></span>' +
        '</div>' +
      '</div>' +
      '<div class="multica-assign-result" data-multica-assign-result hidden></div>' +
    '</div>';
  }

  function prepareMulticaIssueAssign(panel) {
    var issueId = getAssignIssueId(panel);
    var issueInput = panel.querySelector('[data-multica-assign-issue-id]');
    var agentSelect = panel.querySelector('[data-multica-assign-agent]');
    var agent = agentSelect ? agentSelect.value : '';
    var confirmBox = panel.querySelector('[data-multica-assign-confirm]');
    var expectedEl = panel.querySelector('[data-multica-assign-expected]');
    var phrase = panel.querySelector('[data-multica-assign-phrase]');
    var confirmButton = panel.querySelector('[data-multica-draft="confirm-assign"]');
    var status = panel.querySelector('[data-multica-assign-status]');
    if (!issueId) {
      if (status) status.textContent = '请先输入已有 Multica issue id 或 identifier。';
      toast('请先输入 Issue ID / Identifier', 'err');
      return Promise.resolve();
    }
    var expected = buildAssignConfirmation(issueId, agent);
    if (confirmBox) confirmBox.hidden = false;
    if (expectedEl) expectedEl.textContent = expected;
    var resetExpected = function (reason) {
      issueId = getAssignIssueId(panel);
      expected = buildAssignConfirmation(issueId, agentSelect ? agentSelect.value : '');
      if (expectedEl) expectedEl.textContent = expected;
      if (phrase) phrase.value = '';
      if (confirmButton) confirmButton.disabled = true;
      if (status) status.textContent = reason || '请重新输入精确确认短语。';
    };
    if (agentSelect) agentSelect.onchange = function () { resetExpected('Agent 已变更，请重新输入精确确认短语。'); };
    if (issueInput) issueInput.oninput = function () { resetExpected('Issue ID / Identifier 已变更，请重新输入精确确认短语。'); };
    if (phrase) {
      phrase.value = '';
      phrase.focus();
      phrase.oninput = function () {
        if (confirmButton) confirmButton.disabled = !getAssignIssueId(panel) || phrase.value.trim() !== expected;
      };
    }
    if (confirmButton) confirmButton.disabled = true;
    if (status) status.textContent = '输入精确确认短语后才能分配真实 issue。';
    toast('请检查 issue id 和 agent 后输入确认短语', 'info');
    return Promise.resolve();
  }

  function confirmMulticaIssueAssign(btn, panel) {
    var issueId = getAssignIssueId(panel);
    var agentSelect = panel.querySelector('[data-multica-assign-agent]');
    var agent = agentSelect ? agentSelect.value : '';
    var phrase = panel.querySelector('[data-multica-assign-phrase]');
    var status = panel.querySelector('[data-multica-assign-status]');
    var expected = buildAssignConfirmation(issueId, agent);
    var text = phrase ? phrase.value.trim() : '';
    if (!issueId || text !== expected) {
      if (status) status.textContent = '确认短语不匹配。';
      toast('确认短语不匹配', 'err');
      return Promise.resolve();
    }
    btn.disabled = true;
    if (status) status.textContent = '正在分配 Multica issue...';
    return apiCall('assign_multica_issue_to_agent', {
      issue_id: issueId,
      agent: agent,
      confirmed: true,
      confirmation_text: text
    }).then(function (resp) {
      if (!resp || !resp.ok || !resp.data) {
        throw new Error((resp && (resp.error || resp.message || resp.code)) || '分配 Agent 失败');
      }
      renderMulticaIssueAssignResult(panel, resp.data);
      if (status) status.textContent = 'Multica issue 已分配。';
      toast('Multica issue 已分配给 ' + (resp.data.agent || agent), 'ok');
    }).catch(function (err) {
      if (status) status.textContent = '分配失败：' + ((err && err.message) || err);
      toast('分配 Multica issue 失败', 'err');
    }).finally(function () {
      btn.disabled = false;
    });
  }

  function renderMulticaIssueAssignResult(panel, result) {
    var box = panel.querySelector('[data-multica-assign-result]');
    if (!box) return;
    var warnings = Array.isArray(result.warnings) ? result.warnings : [];
    box.hidden = false;
    box.innerHTML = '<strong>Multica issue 已分配给 ' + escapeHtml(result.agent || '--') + '</strong>' +
      '<div>Issue ID: <code>' + escapeHtml(result.issue_id || '--') + '</code></div>' +
      '<div>状态: ' + escapeHtml(result.status || '--') + '</div>' +
      '<div>下一步 C6 可读取 runs / run-messages 做验收</div>' +
      (warnings.length ? '<p>' + escapeHtml(warnings.join('；')) + '</p>' : '');
  }

  function buildAssignConfirmation(issueId, agent) {
    return 'ASSIGN ' + String(issueId || '').trim() + ' TO ' + String(agent || '').trim();
  }

  function getAssignIssueId(panel) {
    var input = panel ? panel.querySelector('[data-multica-assign-issue-id]') : null;
    if (input) return String(input.value || '').trim();
    var created = getPanelCreateResult(panel);
    return created && created.issue_id ? String(created.issue_id).trim() : '';
  }

  /* ─── Standalone assign existing Multica issue ─── */
  function getStandaloneAssignPanel() {
    return document.querySelector('[data-multica-standalone-assign-panel]');
  }

  function getStandaloneIssueId() {
    var input = document.querySelector('[data-sa-issue-id]');
    return input ? String(input.value || '').trim() : '';
  }

  function getStandaloneAgent() {
    var select = document.querySelector('[data-sa-agent]');
    return select ? select.value : 'claude';
  }

  function prepareStandaloneAssign() {
    var issueId = getStandaloneIssueId();
    var agent = getStandaloneAgent();
    var confirmBox = document.querySelector('[data-sa-confirm]');
    var expectedEl = document.querySelector('[data-sa-expected]');
    var phrase = document.querySelector('[data-sa-phrase]');
    var confirmButton = document.querySelector('[data-sa-action="confirm"]');
    var status = document.querySelector('[data-sa-status]');
    if (!issueId) {
      if (status) status.textContent = '请先输入已有 Multica issue id 或 identifier。';
      toast('请先输入 Issue ID / Identifier', 'err');
      return;
    }
    var expected = buildAssignConfirmation(issueId, agent);
    if (confirmBox) confirmBox.hidden = false;
    if (expectedEl) expectedEl.textContent = expected;
    if (phrase) { phrase.value = ''; phrase.focus(); }
    if (confirmButton) confirmButton.disabled = true;
    if (status) status.textContent = '输入精确确认短语后才能分配真实 issue。';
    toast('请检查 issue id 和 agent 后输入确认短语', 'info');
  }

  function confirmStandaloneAssign(btn) {
    var issueId = getStandaloneIssueId();
    var agent = getStandaloneAgent();
    var phrase = document.querySelector('[data-sa-phrase]');
    var status = document.querySelector('[data-sa-status]');
    var confirmButton = document.querySelector('[data-sa-action="confirm"]');
    var expected = buildAssignConfirmation(issueId, agent);
    var text = phrase ? phrase.value.trim() : '';
    if (!issueId || text !== expected) {
      if (status) status.textContent = '确认短语不匹配。';
      toast('确认短语不匹配', 'err');
      return;
    }
    btn.disabled = true;
    if (confirmButton) confirmButton.disabled = true;
    if (status) status.textContent = '正在分配 Multica issue...';
    apiCall('assign_multica_issue_to_agent', {
      issue_id: issueId,
      agent: agent,
      confirmed: true,
      confirmation_text: text
    }).then(function (resp) {
      if (!resp || !resp.ok || !resp.data) {
        throw new Error((resp && (resp.error || resp.message || resp.code)) || '分配 Agent 失败');
      }
      renderStandaloneAssignResult(resp.data);
      if (status) status.textContent = 'Multica issue 已分配。';
      toast('Multica issue 已分配给 ' + (resp.data.agent || agent), 'ok');
    }).catch(function (err) {
      if (status) status.textContent = '分配失败：' + ((err && err.message) || err);
      toast('分配 Multica issue 失败', 'err');
    }).finally(function () {
      btn.disabled = false;
      if (confirmButton) confirmButton.disabled = false;
    });
  }

  function renderStandaloneAssignResult(result) {
    var box = document.querySelector('[data-sa-result]');
    if (!box) return;
    box.hidden = false;
    box.innerHTML = '<strong>Multica issue 已分配给 ' + escapeHtml(result.agent || '--') + '</strong>' +
      '<div>Issue ID: <code>' + escapeHtml(result.issue_id || '--') + '</code></div>' +
      '<div>状态: ' + escapeHtml(result.status || '--') + '</div>' +
      '<div>下一步 C6 可读取 runs / run-messages 做验收</div>';
  }

  function initStandaloneAssignListeners() {
    var block = $('multica-standalone-assign-block');
    if (!block || block.dataset.saBound === '1') return;
    block.dataset.saBound = '1';

    var toggleBtn = $('btn-toggle-sa');
    if (toggleBtn) {
      toggleBtn.addEventListener('click', function () {
        var panel = $('sa-panel');
        if (!panel) return;
        var visible = panel.style.display !== 'none';
        panel.style.display = visible ? 'none' : '';
        toggleBtn.textContent = visible ? '分配已有 Multica Issue' : '收起 Multica Issue 分配';
        var rrPanel = $('rr-panel');
        if (rrPanel) rrPanel.style.display = 'none';
        var rrToggle = $('btn-toggle-rr');
        if (rrToggle) rrToggle.textContent = '查看 Multica 运行记录';
      });
    }

    var rrToggleBtn = $('btn-toggle-rr');
    if (rrToggleBtn) {
      rrToggleBtn.addEventListener('click', function () {
        var panel = $('rr-panel');
        if (!panel) return;
        var visible = panel.style.display !== 'none';
        panel.style.display = visible ? 'none' : '';
        rrToggleBtn.textContent = visible ? '查看 Multica 运行记录' : '收起 Multica 运行记录';
        var saPanel = $('sa-panel');
        if (saPanel) saPanel.style.display = 'none';
        var saToggle = $('btn-toggle-sa');
        if (saToggle) saToggle.textContent = '分配已有 Multica Issue';
      });
    }

    block.addEventListener('click', function (event) {
      var btn = event.target.closest('[data-sa-action]');
      if (!btn) return;
      event.preventDefault();
      var action = btn.getAttribute('data-sa-action') || '';
      if (action === 'prepare') prepareStandaloneAssign();
      if (action === 'confirm') confirmStandaloneAssign(btn);
    });
    var phraseInput = block.querySelector('[data-sa-phrase]');
    if (phraseInput) {
      phraseInput.addEventListener('input', function () {
        var expected = buildAssignConfirmation(getStandaloneIssueId(), getStandaloneAgent());
        var confirmBtn = block.querySelector('[data-sa-action="confirm"]');
        if (confirmBtn) confirmBtn.disabled = phraseInput.value.trim() !== expected;
      });
    }

    /* run reader listeners */
    block.addEventListener('click', function (event) {
      var btn = event.target.closest('[data-rr-action]');
      if (!btn) return;
      event.preventDefault();
      var action = btn.getAttribute('data-rr-action') || '';
      if (action === 'read-runs') readRunsForPanel();
    });
    var rrPanel = $('rr-panel');
    if (rrPanel) {
      rrPanel.addEventListener('click', function (event) {
        var msgBtn = event.target.closest('[data-rr-read-msgs]');
        if (!msgBtn) return;
        event.preventDefault();
        var taskId = msgBtn.getAttribute('data-rr-read-msgs') || '';
        if (taskId) readRunMessagesForTask(taskId);
      });
    }
  }

  /* ─── Run reader helpers ─── */

  function getRunReaderIssueId() {
    var input = document.querySelector('[data-rr-issue-id]');
    return input ? String(input.value || '').trim() : '';
  }

  function readRunsForPanel() {
    var issueId = getRunReaderIssueId();
    var status = document.querySelector('[data-rr-status]');
    if (!issueId) {
      if (status) status.textContent = '请先输入 Issue ID / Identifier。';
      toast('请先输入 Issue ID / Identifier', 'err');
      return;
    }
    if (status) status.textContent = '正在读取 runs...';
    var runsDiv = document.querySelector('[data-rr-runs]');
    if (runsDiv) runsDiv.hidden = true;
    var msgsDiv = document.querySelector('[data-rr-messages]');
    if (msgsDiv) msgsDiv.hidden = true;

    apiCall('read_multica_issue_runs', { issue_id: issueId }).then(function (resp) {
      if (!resp || !resp.ok || !resp.data) {
        throw new Error((resp && (resp.error || resp.message)) || '读取 runs 失败');
      }
      renderRunsList(resp.data);
      if (status) status.textContent = resp.message || 'runs 读取完成';
    }).catch(function (err) {
      if (status) status.textContent = '读取失败：' + ((err && err.message) || err);
      toast('读取 Multica runs 失败', 'err');
    });
  }

  function renderRunsList(data) {
    var runs = (data && data.runs) ? data.runs : [];
    var runsDiv = document.querySelector('[data-rr-runs]');
    var list = document.querySelector('[data-rr-runs-list]');
    if (!runsDiv || !list) return;
    runsDiv.hidden = false;
    if (!runs.length) {
      list.innerHTML = '<p style="font-size:11px;color:var(--text-muted)">未找到运行记录。</p>';
      return;
    }
    var html = '';
    runs.forEach(function (run) {
      var taskId = run.task_id || run.run_id || '';
      var title = run.title || taskId || '--';
      html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--rim,rgba(255,255,255,0.06));gap:8px">' +
        '<div style="flex:1;min-width:0">' +
          '<div style="font-size:11px;font-weight:600;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escapeHtml(title) + '</div>' +
          '<div style="font-size:10px;color:var(--text-muted)">' +
            escapeHtml(run.task_id || '') + ' · ' + escapeHtml(run.status || '--') + ' · ' + escapeHtml(run.agent || '--') +
          '</div>' +
        '</div>' +
        (taskId ? '<button type="button" data-rr-read-msgs="' + escapeHtml(taskId) + '" class="glass-pill" style="font-size:10px;padding:3px 8px;flex-shrink:0">读取消息</button>' : '') +
      '</div>';
    });
    list.innerHTML = html;
  }

  function readRunMessagesForTask(taskId) {
    var status = document.querySelector('[data-rr-status]');
    if (status) status.textContent = '正在读取消息...';
    var msgsDiv = document.querySelector('[data-rr-messages]');
    if (msgsDiv) msgsDiv.hidden = true;

    apiCall('read_multica_run_messages', { task_id: taskId }).then(function (resp) {
      if (!resp || !resp.ok || !resp.data) {
        throw new Error((resp && (resp.error || resp.message)) || '读取 run-messages 失败');
      }
      renderRunMessages(resp.data);
      if (status) status.textContent = resp.message || 'run-messages 读取完成';
    }).catch(function (err) {
      if (status) status.textContent = '读取失败：' + ((err && err.message) || err);
      toast('读取 Multica run-messages 失败', 'err');
    });
  }

  function renderRunMessages(data) {
    var msgsDiv = document.querySelector('[data-rr-messages]');
    var list = document.querySelector('[data-rr-messages-list]');
    var review = document.querySelector('[data-rr-review]');
    if (!msgsDiv || !list) return;
    msgsDiv.hidden = false;
    var messages = (data && data.messages) ? data.messages : [];
    if (!messages.length) {
      list.innerHTML = '<p style="font-size:11px;color:var(--text-muted)">未找到运行消息。</p>';
    } else {
      var html = '';
      messages.forEach(function (m) {
        html += '<div style="padding:6px 8px;margin-bottom:4px;border-radius:6px;background:var(--fill-card-secondary,rgba(255,255,255,0.04));font-size:10px">' +
          '<div style="display:flex;gap:8px;margin-bottom:3px">' +
            '<span style="font-weight:600;color:var(--text-muted)">' + escapeHtml(m.role || m.author || '--') + '</span>' +
            '<span style="color:var(--text-muted)">' + escapeHtml(m.created_at || '') + '</span>' +
          '</div>' +
          '<div style="color:var(--text-secondary);line-height:1.45;white-space:pre-wrap;word-break:break-word">' + escapeHtml(m.content || '') + '</div>' +
        '</div>';
      });
      list.innerHTML = html;
    }
    if (review) review.textContent = data.review_summary || '';
  }

  function splitCommaList(text) {
    return String(text || '').split(',').map(function (item) { return item.trim(); }).filter(Boolean);
  }

  function downloadTextFile(text, filename) {
    var blob = new Blob([String(text || '')], { type: 'text/markdown;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename || 'multica-issue-draft.md';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function buildDraftFilename(title) {
    var safe = String(title || 'multica-issue-draft').replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, '-').slice(0, 64);
    return (safe || 'multica-issue-draft') + '.md';
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
    if (action === 'refresh-multica-status') { doRefreshMulticaStatus(btn); return; }
    if (action === 'save-config') { doSaveConfig(btn); return; }
    if (action === 'save-restart') { doSaveAndRestart(btn); return; }
    if (action === 'export-diag') { doExportDiag(btn); return; }
    if (action === 'open-logs-folder') { doOpenLogsFolder(btn); return; }
    if (action === 'preflight-check') { doPreflightCheck(btn); return; }
    if (action === 'clear-runtime-events') { handleClearRuntimeEvents(btn); return; }
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

  function doRefreshMulticaStatus(btn) {
    btn = btn || $('btn-multica-refresh');
    setButtonLoading(btn, getLoadingText('refresh-multica-status'), 'refresh-multica-status');
    renderMulticaStatus({ ok: true, data: { installed: true, version: '读取中...', daemon_running: false, daemon_summary: '读取中...', agents: [], workspace_summary: '读取中...', warnings: [] } });
    apiCall('get_multica_status').then(function (resp) {
      renderMulticaStatus(resp);
      if (resp && resp.ok) {
        toast('Multica 状态已刷新', 'ok');
      } else {
        toast((resp && resp.error) || 'Multica 状态读取失败', 'err');
      }
    }).catch(function (e) {
      renderMulticaStatus({ ok: false, error: String(e), code: 'JS_ERROR' });
      toast('Multica 状态读取出错', 'err');
    }).finally(function () {
      restoreButton(btn, getButtonText('refresh-multica-status'), 'refresh-multica-status');
    });
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

  function compactRuntimeEventText(text) {
    var s = String(text || '').replace(/\s+/g, ' ').trim();
    var idx = s.indexOf('Traceback');
    if (idx >= 0) {
      s = s.slice(0, idx).trim() || '出现异常';
    }
    return s.length > 110 ? s.slice(0, 110) + '…' : s;
  }

  function renderRuntimeEventEntries(events) {
    return events.slice(-15).map(function (evt) {
      var cls = evt.level === 'error' ? 'err' : evt.level === 'warning' ? 'warn' : '';
      var summary = compactRuntimeEventText(evt.message || '');
      return '<div class="drawer-entry ' + cls + '"><span class="ts">' +
        escapeHtml(evt.timestamp ? evt.timestamp.slice(-8) : '') + '</span>' +
        escapeHtml(evt.source + '/' + evt.event_type) +
        ' — ' + escapeHtml(summary) + '</div>';
    }).join('');
  }

  function renderRuntimeEvents(response) {
    var data = (response && response.ok && response.data) ? response.data : null;
    var events = (data && data.events) ? data.events : [];
    lastRuntimeEvents = events;
    var emptyHtml = '暂无运行事件';

    var drawerEl = $('drawer-runtime-events');
    if (drawerEl) {
      drawerEl.innerHTML = events.length ? renderRuntimeEventEntries(events) : emptyHtml;
    }

    var diagEl = $('diagnostics-events-list');
    if (diagEl) {
      diagEl.innerHTML = events.length ? renderRuntimeEventEntries(events) : emptyHtml;
    }
  }

  function handleClearRuntimeEvents(btn) {
    if (!btn || btn.disabled) return;
    var origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '清除中...';

    apiCall('clear_runtime_events').then(function (resp) {
      if (resp && resp.ok) {
        toast(resp.message || '最近事件已清空', 'ok');
        refreshRuntimeEvents();
      } else {
        toast((resp && resp.error) || '清空事件失败', 'err');
      }
    }).catch(function (e) {
      toast('清空事件出错: ' + e, 'err');
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = origText;
    });
  }

  function refreshRuntimeEvents() {
    apiCall('get_runtime_events', 20).then(renderRuntimeEvents);
  }

  /* ─── Task history ─── */
  function getHistorySignal(item) {
    var text = (item.summary || '') + ' ' + (item.safe_details_excerpt || '');
    if (text.indexOf('有错误') >= 0) return '有错误';
    if (text.indexOf('有警告') >= 0) return '有警告';
    if (text.indexOf('信息不足') >= 0) return '信息不足';
    if (text.indexOf('正常') >= 0) return '正常';
    if (item.status === 'failed' || item.ok === false) return '失败';
    return '完成';
  }

  function getHistorySignalClass(signal) {
    var map = {
      '正常': 'signal-ok',
      '完成': 'signal-ok',
      '有警告': 'signal-warn',
      '有错误': 'signal-err',
      '信息不足': 'signal-unknown',
      '失败': 'signal-err'
    };
    return map[signal] || '';
  }

  function formatHistoryTime(completedAt) {
    if (!completedAt) return '';
    var s = String(completedAt);
    if (s.length >= 16) s = s.slice(0, 16).replace('T', ' ');
    return s;
  }

  function getHistoryReadFilesCount(item) {
    if (!item || item.read_files_count === undefined || item.read_files_count === null) return '0';
    return String(item.read_files_count);
  }

  function formatHistoryRelativeTime(completedAt) {
    if (!completedAt) return '';
    try {
      var date = new Date(completedAt);
      var now = new Date();
      var diffMs = now - date;
      if (isNaN(diffMs) || diffMs < 0) return '';
      var diffMin = Math.floor(diffMs / 60000);
      if (diffMin < 1) return '刚刚';
      if (diffMin < 60) return diffMin + '分钟前';
      var diffHour = Math.floor(diffMin / 60);
      if (diffHour < 24) return diffHour + '小时前';
      var diffDay = Math.floor(diffHour / 24);
      return diffDay + '天前';
    } catch (e) {
      return '';
    }
  }

  function setTaskHistoryViewState(state) {
    var loading = $('tasks-history-loading');
    var error = $('tasks-history-error');
    var empty = $('tasks-history-empty');
    var grid = $('tasks-history-grid');
    if (loading) loading.style.display = state === 'loading' ? '' : 'none';
    if (error) error.style.display = state === 'error' ? '' : 'none';
    if (empty) empty.style.display = state === 'empty' ? '' : 'none';
    if (grid) grid.style.display = state === 'grid' ? '' : 'none';
  }

  function loadTaskHistory() {
    if (taskHistoryLoading) return;
    taskHistoryLoading = true;
    taskHistorySelectedId = null;
    setTaskHistoryViewState('loading');

    apiCall('get_recent_task_history', { limit: 20 }).then(function (resp) {
      if (resp && resp.ok && resp.data && Array.isArray(resp.data.items)) {
        taskHistoryItems = resp.data.items;
        renderTaskHistory();
        if (taskHistoryItems.length > 0) {
          setTaskHistoryViewState('grid');
          selectTaskHistoryItem(taskHistoryItems[0].history_id);
        } else {
          setTaskHistoryViewState('empty');
          renderTaskHistoryDetail(null);
        }
      } else {
        taskHistoryItems = [];
        renderTaskHistoryDetail(null);
        setTaskHistoryViewState('error');
      }
    }).catch(function () {
      taskHistoryItems = [];
      renderTaskHistoryDetail(null);
      setTaskHistoryViewState('error');
    }).finally(function () {
      taskHistoryLoading = false;
    });
  }

  function renderTaskHistory() {
    var list = $('tasks-history-list-scroll');

    if (!taskHistoryItems.length) {
      if (list) list.innerHTML = '';
      return;
    }

    var html = '';
    taskHistoryItems.forEach(function (item) {
      var signal = getHistorySignal(item);
      var signalCls = getHistorySignalClass(signal);
      var statusLabel = item.status === 'completed' ? '任务：完成' : '任务：失败';
      var statusCls = item.ok ? 'completed' : 'failed';
      var activeCls = taskHistorySelectedId === item.history_id ? ' active' : '';
      var timeDisplay = formatHistoryRelativeTime(item.completed_at) || formatHistoryTime(item.completed_at);
      var tags = (item.tags && item.tags.length) ? item.tags.map(escapeHtml).join(', ') : '';
      var metaParts = [timeDisplay, tags, getHistoryReadFilesCount(item) + ' files'].filter(function (p) { return p; });

      html += '<div class="task-history-card' + activeCls + '" data-history-id="' + escapeHtml(item.history_id) + '">' +
        '<div class="task-history-title-row">' +
          '<span class="task-history-title">' + escapeHtml(item.title || '任务') + '</span>' +
        '</div>' +
        '<div class="task-history-badge-row">' +
          '<span class="task-history-status ' + statusCls + '">' + escapeHtml(statusLabel) + '</span>' +
          '<span class="task-history-signal ' + signalCls + '">报告：' + escapeHtml(signal) + '</span>' +
        '</div>' +
        '<div class="task-history-summary">' + escapeHtml(item.summary || '') + '</div>' +
        '<div class="task-history-meta">' +
          '<span class="task-history-meta-text">' + escapeHtml(metaParts.join(' · ')) + '</span>' +
        '</div>' +
      '</div>';
    });

    if (list) list.innerHTML = html;
  }

  function parseHealthReportSections(text) {
    var clean = String(text || '').trim();
    if (!clean) return [];
    var markers = [
      { key: '总体状态', pattern: /总体状态[:：]/ },
      { key: '基础状态', pattern: /一、基础状态/ },
      { key: '配置状态', pattern: /二、配置状态/ },
      { key: '运行事件', pattern: /三、运行事件/ },
      { key: '历史日志', pattern: /四、最近错误(?:（历史日志）)?/ },
      { key: '代表性问题', pattern: /代表性问题[:：]/ },
      { key: '提醒', pattern: /提醒[:：]/ },
      { key: '建议', pattern: /六、建议/ }
    ];
    var positions = [];
    markers.forEach(function (m) {
      var match = clean.match(m.pattern);
      if (match) {
        positions.push({ key: m.key, index: match.index });
      }
    });
    positions.sort(function (a, b) { return a.index - b.index; });
    var sections = [];
    for (var i = 0; i < positions.length; i += 1) {
      var start = positions[i].index;
      var end = i + 1 < positions.length ? positions[i + 1].index : clean.length;
      var body = clean.slice(start, end).trim();
      if (body.length > 240) {
        body = body.slice(0, 240).trim() + '…';
      }
      sections.push({ title: positions[i].key, body: body });
    }
    if (!sections.length) {
      var body = clean;
      if (body.length > 240) body = body.slice(0, 240).trim() + '…';
      sections.push({ title: '安全详情', body: body });
    }
    return sections;
  }

  function buildHistoryInsightSections(item) {
    var text = item.safe_details_excerpt || item.summary || '';
    if (item.task_type === 'readonly_health_report') {
      return parseHealthReportSections(text);
    }
    return [
      { title: '摘要', body: item.summary || '暂无摘要' },
      { title: '安全详情', body: item.safe_details_excerpt || '暂无更多安全详情' }
    ];
  }

  function renderHistoryInsightBlocks(sections) {
    if (!sections || !sections.length) return '';
    return sections.map(function (sec) {
      var body = String(sec.body || '');
      if (body.length > 400) body = body.slice(0, 400).trim() + '…';
      return '<div class="tasks-history-detail-block">' +
        '<div class="tasks-history-detail-block-title">' + escapeHtml(sec.title) + '</div>' +
        '<div class="tasks-history-detail-block-body">' + escapeHtml(body) + '</div>' +
      '</div>';
    }).join('');
  }

  function selectTaskHistoryItem(historyId) {
    taskHistorySelectedId = historyId;
    renderTaskHistory();
    var item = taskHistoryItems.filter(function (it) { return it.history_id === historyId; })[0];
    renderTaskHistoryDetail(item || null);
  }

  function renderTaskHistoryDetail(item) {
    var detail = $('tasks-history-detail-scroll');
    if (!detail) return;

    if (!item) {
      detail.innerHTML = '<p class="tasks-history-detail-placeholder">选择一条任务查看安全详情</p>';
      return;
    }

    var signal = getHistorySignal(item);
    var signalCls = getHistorySignalClass(signal);
    var statusLabel = item.status === 'completed' ? '任务：完成' : '任务：失败';
    var statusCls = item.ok ? 'completed' : 'failed';
    var tags = (item.tags && item.tags.length) ? item.tags.map(function (t) {
      return '<span class="task-history-tag">' + escapeHtml(t) + '</span>';
    }).join('') : '';

    var sections = buildHistoryInsightSections(item);
    var insightHtml = renderHistoryInsightBlocks(sections);

    detail.innerHTML =
      '<div class="tasks-history-detail-section">' +
        '<div class="task-history-detail-head">' +
          '<span class="task-history-detail-title">' + escapeHtml(item.title || '任务') + '</span>' +
          '<div class="task-history-detail-badges">' +
            '<span class="task-history-status ' + statusCls + '">' + escapeHtml(statusLabel) + '</span>' +
            '<span class="task-history-signal ' + signalCls + '">报告：' + escapeHtml(signal) + '</span>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="tasks-history-detail-section tasks-history-detail-overview">' +
        '<div class="tasks-history-detail-block-title">状态概览</div>' +
        '<div class="tasks-history-detail-row"><span class="tasks-history-detail-label">任务类型</span><span>' + escapeHtml(item.task_type || '') + '</span></div>' +
        '<div class="tasks-history-detail-row"><span class="tasks-history-detail-label">风险等级</span><span>' + escapeHtml(item.risk_level || 'low') + '</span></div>' +
        '<div class="tasks-history-detail-row"><span class="tasks-history-detail-label">完成时间</span><span>' + escapeHtml(formatHistoryTime(item.completed_at)) + '</span></div>' +
        (item.read_files_count !== undefined && item.read_files_count !== null ? '<div class="tasks-history-detail-row"><span class="tasks-history-detail-label">读取文件</span><span>' + escapeHtml(getHistoryReadFilesCount(item)) + '</span></div>' : '') +
        (tags ? '<div class="tasks-history-detail-row"><span class="tasks-history-detail-label">标签</span><div class="tasks-history-detail-tags">' + tags + '</div></div>' : '') +
      '</div>' +
      insightHtml +
      '<div class="tasks-history-detail-section tasks-history-detail-raw">' +
        '<div class="tasks-history-detail-block-title">原始安全摘要</div>' +
        '<div class="tasks-history-detail-text tasks-history-detail-muted">' + escapeHtml(item.safe_details_excerpt || item.summary || '暂无') + '</div>' +
      '</div>' +
      '<div class="tasks-history-detail-section tasks-history-detail-id">' +
        '<span class="tasks-history-detail-label-id">ID: ' + escapeHtml(item.history_id || '') + '</span>' +
      '</div>';
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
  function initTaskHistory() {
    var list = $('tasks-history-list-scroll');
    if (list) {
      list.addEventListener('click', function (event) {
        var card = event.target.closest('.task-history-card');
        if (!card) return;
        var historyId = card.getAttribute('data-history-id');
        if (historyId) selectTaskHistoryItem(historyId);
      });
    }
    var refreshBtn = $('btn-tasks-refresh');
    if (refreshBtn && refreshBtn.dataset.tasksBound !== '1') {
      refreshBtn.dataset.tasksBound = '1';
      refreshBtn.addEventListener('click', function () {
        loadTaskHistory();
      });
    }
  }

  function doInit() {
    if (initDone) return;
    initDone = true;
    initNav();
    initSidebarControls();
    initDrawerControls();
    initTextChat();
    initTaskHistory();
    initStandaloneAssignListeners();
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

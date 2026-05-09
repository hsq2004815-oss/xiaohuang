(function () {
  'use strict';

  var currentSessionId = 'default';
  var messages = [];
  var sending = false;

  var $ = function (id) { return document.getElementById(id); };
  var messagesEl = $('messages');
  var input = $('message-input');
  var sendBtn = $('send-btn');
  var clearBtn = $('clear-btn');
  var newChatBtn = $('new-chat-btn');
  var bridgeStatus = $('bridge-status');

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

  function setBridgeStatus(text, cls) {
    if (!bridgeStatus) return;
    bridgeStatus.textContent = text;
    bridgeStatus.className = 'pill status-pill ' + (cls || '');
  }

  function updateBridge() {
    if (getApi()) {
      setBridgeStatus('本地文本入口', 'ok');
    } else {
      setBridgeStatus('等待桌面桥接', 'warn');
    }
  }

  function appendMessage(role, text, meta) {
    messages.push({
      role: role,
      text: text,
      meta: meta || {},
      ts: new Date().toLocaleTimeString()
    });
    renderMessages();
  }

  function renderMessages() {
    if (!messagesEl) return;
    messagesEl.innerHTML = messages.map(function (msg) {
      var meta = msg.meta || {};
      var metaParts = [];
      if (meta.source) metaParts.push('source: ' + meta.source);
      if (meta.latency_ms !== undefined) metaParts.push(meta.latency_ms + 'ms');
      if (meta.llm_configured !== undefined) metaParts.push('llm configured: ' + (meta.llm_configured ? 'yes' : 'no'));
      if (meta.blocked_panel_command) metaParts.push('panel command blocked');
      var metaHtml = metaParts.length ? '<div class="message-meta">' + escapeHtml(metaParts.join(' · ')) + '</div>' : '';
      return '<article class="message ' + escapeHtml(msg.role) + '">' +
        '<div class="bubble">' + escapeHtml(msg.text) + '</div>' +
        metaHtml +
        '</article>';
    }).join('');
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function setSending(on) {
    sending = !!on;
    if (sendBtn) {
      sendBtn.disabled = sending;
      sendBtn.textContent = sending ? '发送中...' : '发送';
    }
    if (input) input.disabled = sending;
  }

  function sendMessage() {
    var text = input ? input.value.trim() : '';
    if (!text || sending) return;

    appendMessage('user', text);
    input.value = '';
    setSending(true);

    var api = getApi();
    if (!api || typeof api.send_message !== 'function') {
      appendMessage('assistant', '桌面桥接未连接，暂时无法发送文本消息。', { source: 'bridge_error' });
      setSending(false);
      return;
    }

    Promise.resolve(api.send_message({
      text: text,
      session_id: currentSessionId
    })).then(function (resp) {
      if (!resp || !resp.ok) {
        appendMessage('assistant', (resp && resp.error) || '文本消息处理失败', { source: 'error' });
        return;
      }

      var data = resp.data || {};
      appendMessage('assistant', data.reply_text || data.error || '没有返回内容', {
        source: data.reply_source,
        latency_ms: data.latency_ms,
        has_llm_key: data.has_llm_key,
        llm_configured: data.llm_configured,
        blocked_panel_command: data.blocked_panel_command
      });
    }).catch(function (err) {
      appendMessage('assistant', '文本消息处理出错：' + err, { source: 'js_error' });
    }).finally(function () {
      setSending(false);
      if (input) input.focus();
    });
  }

  function clearSession() {
    messages = [];
    renderMessages();
    appendMessage('assistant', '你好，我是小黄。这里是文本交互界面，不需要唤醒词，也不会播放语音。你可以直接打字和我交流。', {
      source: 'welcome'
    });

    var api = getApi();
    if (api && typeof api.clear_session === 'function') {
      Promise.resolve(api.clear_session({ session_id: currentSessionId })).catch(function () {});
    }
  }

  function fillPrompt(text) {
    if (!input) return;
    input.value = text;
    input.focus();
  }

  function initEvents() {
    if (sendBtn) sendBtn.addEventListener('click', sendMessage);
    if (clearBtn) clearBtn.addEventListener('click', clearSession);
    if (newChatBtn) newChatBtn.addEventListener('click', clearSession);
    if (input) {
      input.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          sendMessage();
        }
      });
    }

    document.querySelectorAll('[data-prompt]').forEach(function (button) {
      button.addEventListener('click', function () {
        fillPrompt(button.getAttribute('data-prompt') || '');
      });
    });
  }

  window.addEventListener('pywebviewready', updateBridge);
  document.addEventListener('DOMContentLoaded', function () {
    initEvents();
    updateBridge();
    clearSession();
    setTimeout(updateBridge, 700);
  });
})();

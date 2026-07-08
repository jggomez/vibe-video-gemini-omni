/**
 * Gemini Omni Vibe Studio — Frontend Logic (Vanilla JS)
 * Handles WebSocket streaming, ADK agent telemetry, video playback,
 * turn history timeline, and Critic quality evaluation gauge.
 */

document.addEventListener('DOMContentLoaded', () => {
  const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  const wsUrl = isLocal
    ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/studio`
    : 'wss://vibe-video-studio-uk7bg6pcva-uc.a.run.app/ws/studio';
  let socket = null;
  let pingInterval = null;

  // Session state
  const userId = 'anonymous';
  let sessionId = sessionStorage.getItem('vibe_session_id');
  if (!sessionId) {
    sessionId = 'sess_' + Math.random().toString(36).substring(2, 10);
    sessionStorage.setItem('vibe_session_id', sessionId);
  }

  let currentTurn = 0;
  let isProcessing = false;
  let turnHistory = [];
  let currentTurnIterations = []; // tracks {iteration, directorReview} per loop pass
  let selectedDuration = '5s';
  let uploadedImagePath = '';

  // Mobile Tab Selector System
  const mobileTabBtns = document.querySelectorAll('.mobile-tab-btn');
  const studioWorkspace = document.getElementById('studio-workspace');
  const telemetryPanel = document.getElementById('telemetry-panel');
  const canvasPanel = document.getElementById('canvas-panel');
  const criticPanel = document.getElementById('critic-panel');

  function updateMobileTabVisibility(activeTab) {
    if (window.innerWidth >= 768) {
      // On desktop, remove hidden and restore flex for all panels
      if (telemetryPanel) {
        telemetryPanel.classList.remove('hidden');
        telemetryPanel.classList.add('flex');
      }
      if (canvasPanel) {
        canvasPanel.classList.remove('hidden');
        canvasPanel.classList.add('flex');
      }
      if (criticPanel) {
        criticPanel.classList.remove('hidden');
        criticPanel.classList.add('flex');
      }
      return;
    }

    // On mobile, show active as flex and hide the rest
    if (telemetryPanel) {
      if (activeTab === 'telemetry') {
        telemetryPanel.classList.remove('hidden');
        telemetryPanel.classList.add('flex');
        scrollToBottom();
      } else {
        telemetryPanel.classList.add('hidden');
        telemetryPanel.classList.remove('flex');
      }
    }

    if (canvasPanel) {
      if (activeTab === 'canvas') {
        canvasPanel.classList.remove('hidden');
        canvasPanel.classList.add('flex');
      } else {
        canvasPanel.classList.add('hidden');
        canvasPanel.classList.remove('flex');
      }
    }

    if (criticPanel) {
      if (activeTab === 'critic') {
        criticPanel.classList.remove('hidden');
        criticPanel.classList.add('flex');
      } else {
        criticPanel.classList.add('hidden');
        criticPanel.classList.remove('flex');
      }
    }
  }

  if (mobileTabBtns && studioWorkspace) {
    mobileTabBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        const tab = e.currentTarget.getAttribute('data-tab');
        
        // Remove active class from all tab buttons
        mobileTabBtns.forEach(b => b.classList.remove('active'));
        
        // Add active class to clicked tab button
        e.currentTarget.classList.add('active');
        
        // Update workspace attribute to toggle view panels
        studioWorkspace.setAttribute('data-active-tab', tab);
        
        updateMobileTabVisibility(tab);
      });
    });

    // Run visibility update on start and resize
    window.addEventListener('resize', () => {
      const activeTab = studioWorkspace.getAttribute('data-active-tab') || 'canvas';
      updateMobileTabVisibility(activeTab);
    });

    // Initialize visibility based on default active tab
    updateMobileTabVisibility('canvas');
  }

  // DOM Elements
  const btnNewSession = document.getElementById('btn-new-session');
  const btnToggleTips = document.getElementById('btn-toggle-tips');
  const btnCloseTips = document.getElementById('btn-close-tips');
  const proTipsCard = document.getElementById('pro-tips-card');
  const btnUploadImage = document.getElementById('btn-upload-image');
  const inputImageFile = document.getElementById('input-image-file');
  const referenceImageBadge = document.getElementById('reference-image-badge');
  const refImageName = document.getElementById('ref-image-name');
  const btnRemoveRefImage = document.getElementById('btn-remove-ref-image');

  const agentLogsContainer = document.getElementById('agent-logs-container');
  const agentWelcomeCard = document.getElementById('agent-welcome-card');
  const promptForm = document.getElementById('studio-prompt-form');
  const promptTextarea = document.getElementById('prompt-textarea');
  const btnSubmit = document.getElementById('btn-submit');
  const btnSubmitText = document.getElementById('btn-submit-text');
  const btnSubmitSpinner = document.getElementById('btn-submit-spinner');
  const btnSubmitIcon = document.getElementById('btn-submit-icon');
  const btnStop = document.getElementById('btn-stop');
  const turnBadge = document.getElementById('turn-badge');
  const videoPlayer = document.getElementById('studio-video-player');
  const canvasPlaceholder = document.getElementById('canvas-placeholder');
  const canvasBlocked = document.getElementById('canvas-blocked');
  const btnDownloadMain = document.getElementById('btn-download-main');
  const timelineTurns = document.getElementById('timeline-turns');
  const driftWarning = document.getElementById('drift-warning');
  const connStatus = document.getElementById('connection-status');
  const connText = document.getElementById('conn-text');
  const inputApiKey = document.getElementById('input-api-key');

  const analyticsInputTokens = document.getElementById('analytics-input-tokens');
  const analyticsInputCost = document.getElementById('analytics-input-cost');
  const analyticsOutputTokens = document.getElementById('analytics-output-tokens');
  const analyticsOutputCost = document.getElementById('analytics-output-cost');
  const analyticsVideoSeconds = document.getElementById('analytics-video-seconds');
  const analyticsVideoCost = document.getElementById('analytics-video-cost');
  const analyticsTotalCost = document.getElementById('analytics-total-cost');

  // Load and bind API Key from localStorage
  if (inputApiKey) {
    const savedKey = localStorage.getItem('gemini_api_key');
    if (savedKey) {
      inputApiKey.value = savedKey;
    }

    function updateApiKeyStatus() {
      const value = inputApiKey.value.trim();
      const container = inputApiKey.parentElement;
      const label = document.getElementById('label-api-key');
      const icon = container ? container.querySelector('svg') : null;

      if (!value) {
        inputApiKey.classList.add('border-amber-500/40');
        inputApiKey.classList.remove('border-emerald-500/40');
        if (label) {
          label.classList.add('text-amber-400');
          label.classList.remove('text-emerald-400');
          label.textContent = 'API Key (Required):';
        }
        if (icon) {
          icon.classList.add('text-amber-500/70');
          icon.classList.remove('text-emerald-500/70');
        }
      } else {
        inputApiKey.classList.remove('border-amber-500/40');
        inputApiKey.classList.add('border-emerald-500/40');
        if (label) {
          label.classList.remove('text-amber-400');
          label.classList.add('text-emerald-400');
          label.textContent = 'API Key (Configured):';
        }
        if (icon) {
          icon.classList.remove('text-amber-500/70');
          icon.classList.add('text-emerald-500/70');
        }
      }
    }

    inputApiKey.addEventListener('input', () => {
      localStorage.setItem('gemini_api_key', inputApiKey.value.trim());
      updateApiKeyStatus();
    });

    // Run once on initialization
    updateApiKeyStatus();
  }

  // Critic DOM Elements
  const criticIterationTabsContainer = document.getElementById('critic-iteration-tabs-container');
  const criticIterationTabs = document.getElementById('critic-iteration-tabs');
  const criticEmptyState = document.getElementById('critic-empty-state');
  const criticResults = document.getElementById('critic-results');
  const criticStatusBadge = document.getElementById('critic-status-badge');
  const criticSummaryText = document.getElementById('critic-summary-text');
  const criticScoreNum = document.getElementById('critic-score-num');
  const criticScoreCircle = document.getElementById('critic-score-circle');
  const criticFeedbackList = document.getElementById('critic-feedback-list');
  const criticRemixSuggestions = document.getElementById('critic-remix-suggestions');

  // Video controls DOM
  const btnPlayPause = document.getElementById('btn-play-pause');
  const iconPlay = document.getElementById('icon-play');
  const iconPause = document.getElementById('icon-pause');
  const btnMute = document.getElementById('btn-mute');
  const iconVolumeHigh = document.getElementById('icon-volume-high');
  const iconVolumeMuted = document.getElementById('icon-volume-muted');
  const sliderVolume = document.getElementById('slider-volume');
  const videoTimeDisplay = document.getElementById('video-time-display');
  const videoProgress = document.getElementById('video-progress');
  const videoProgressFill = document.getElementById('video-progress-fill');
  const videoControlsOverlay = document.querySelector('.video-controls-overlay');

  // Initialize WebSocket Connection
  function connectWebSocket() {
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log('Connected to ADK Agent Studio WebSocket');
      updateConnectionStatus('connected', 'Agents Online');
      if (pingInterval) clearInterval(pingInterval);
      pingInterval = setInterval(() => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ action: 'ping' }));
        }
      }, 25000);
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.step === 'pong') {
          // Heartbeat reply received, connection is warm and active
          return;
        }
        handleStreamEvent(data);
      } catch (err) {
        console.error('Error parsing WebSocket message:', err);
      }
    };

    socket.onclose = () => {
      updateConnectionStatus('disconnected', 'Disconnected');
      console.log('WebSocket closed. Reconnecting in 3 seconds...');
      if (pingInterval) {
        clearInterval(pingInterval);
        pingInterval = null;
      }
      if (isProcessing) {
        setProcessingState(false);
        removeThinkingCards();
        addErrorCard('Connection to the video studio was lost. Please verify your prompt or try again.');
      }
      setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
      console.error('WebSocket error:', err);
      updateConnectionStatus('disconnected', 'Connection Error');
      if (pingInterval) {
        clearInterval(pingInterval);
        pingInterval = null;
      }
      if (isProcessing) {
        setProcessingState(false);
        removeThinkingCards();
        addErrorCard('A network error occurred. Please check your internet connection.');
      }
    };
  }

  function updateConnectionStatus(state, text) {
    const dot = connStatus.querySelector('.conn-dot');
    if (dot) dot.className = `conn-dot ${state}`;
    if (connText) connText.textContent = text;
  }

  connectWebSocket();

  // New Project / New Session Modal Handler
  const modalNewProject = document.getElementById('modal-new-project');
  const modalBtnCancel = document.getElementById('modal-btn-cancel');
  const modalBtnConfirm = document.getElementById('modal-btn-confirm');

  function startNewSession() {
    sessionId = 'sess_' + Math.random().toString(36).substring(2, 10);
    sessionStorage.setItem('vibe_session_id', sessionId);
    currentTurn = 0;
    turnHistory = [];
    currentTurnIterations = [];

    // Reset UI
    agentLogsContainer.innerHTML = '';
    if (agentWelcomeCard) {
      agentLogsContainer.appendChild(agentWelcomeCard);
      agentWelcomeCard.style.display = 'block';
    }
    if (turnBadge) turnBadge.textContent = 'Turn —/4';
    if (driftWarning) driftWarning.classList.remove('visible');

    // Reset Video Player
    videoPlayer.pause();
    videoPlayer.removeAttribute('src');
    videoPlayer.load();
    videoPlayer.classList.add('hidden');
    if (videoControlsOverlay) videoControlsOverlay.classList.add('hidden');
    canvasPlaceholder.style.display = 'block';
    if (canvasBlocked) canvasBlocked.classList.add('hidden');
    btnDownloadMain.classList.add('hidden');
    if (videoProgressFill) videoProgressFill.style.width = '0%';
    if (videoTimeDisplay) videoTimeDisplay.textContent = '0:00 / 0:00';
    if (iconPlay) iconPlay.classList.add('hidden');
    if (iconPause) iconPause.classList.remove('hidden');
    timelineTurns.innerHTML = '<span class="text-xs text-slate-500 italic">No turns completed yet</span>';

    // Reset Critic
    criticResults.classList.add('hidden');
    criticEmptyState.classList.remove('hidden');
    criticStatusBadge.classList.add('hidden');
    if (criticIterationTabsContainer) criticIterationTabsContainer.classList.add('hidden');

    // Reset Analytics
    if (analyticsInputTokens) analyticsInputTokens.textContent = '0';
    if (analyticsInputCost) analyticsInputCost.textContent = '$0.0000';
    if (analyticsOutputTokens) analyticsOutputTokens.textContent = '0';
    if (analyticsOutputCost) analyticsOutputCost.textContent = '$0.0000';
    if (analyticsVideoSeconds) analyticsVideoSeconds.textContent = '0s';
    if (analyticsVideoCost) analyticsVideoCost.textContent = '$0.0000';
    if (analyticsTotalCost) analyticsTotalCost.textContent = '$0.000000';

    // Reset inputs
    promptTextarea.value = '';
    removeReferenceImage();
    console.log('Started new video session:', sessionId);
  }

  if (btnNewSession && modalNewProject) {
    btnNewSession.addEventListener('click', () => {
      modalNewProject.classList.add('active');
    });

    if (modalBtnCancel) {
      modalBtnCancel.addEventListener('click', () => {
        modalNewProject.classList.remove('active');
      });
    }

    if (modalBtnConfirm) {
      modalBtnConfirm.addEventListener('click', () => {
        modalNewProject.classList.remove('active');
        startNewSession();
      });
    }

    // Close on backdrop click
    modalNewProject.addEventListener('click', (e) => {
      if (e.target === modalNewProject) {
        modalNewProject.classList.remove('active');
      }
    });
  }

  // API Key Required Modal handlers
  const modalApiKeyRequired = document.getElementById('modal-api-key-required');
  const modalApiKeyBtnOk = document.getElementById('modal-api-key-btn-ok');

  function showApiKeyRequiredModal() {
    if (modalApiKeyRequired) {
      modalApiKeyRequired.classList.add('active');
    }
  }

  function hideApiKeyRequiredModal() {
    if (modalApiKeyRequired) {
      modalApiKeyRequired.classList.remove('active');
    }
    // Highlight input field after closing modal
    if (inputApiKey) {
      inputApiKey.focus();
      inputApiKey.classList.add('ring-2', 'ring-amber-500', 'border-amber-400');
      setTimeout(() => {
        inputApiKey.classList.remove('ring-2', 'ring-amber-500', 'border-amber-400');
      }, 1500);
    }
  }

  if (modalApiKeyBtnOk) {
    modalApiKeyBtnOk.addEventListener('click', hideApiKeyRequiredModal);
  }
  if (modalApiKeyRequired) {
    modalApiKeyRequired.addEventListener('click', (e) => {
      if (e.target === modalApiKeyRequired) {
        hideApiKeyRequiredModal();
      }
    });
  }

  // Toggle Pro Tips Card
  if (btnToggleTips) {
    btnToggleTips.addEventListener('click', () => {
      proTipsCard.classList.toggle('hidden');
    });
  }
  if (btnCloseTips) {
    btnCloseTips.addEventListener('click', () => {
      proTipsCard.classList.add('hidden');
    });
  }

  // Duration Chips Handler
  document.querySelectorAll('.duration-chip').forEach(chip => {
    chip.addEventListener('click', (e) => {
      e.preventDefault();
      document.querySelectorAll('.duration-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      selectedDuration = chip.getAttribute('data-duration') || '5s';
    });
  });

  // Reference Image Upload Handler
  if (btnUploadImage && inputImageFile) {
    btnUploadImage.addEventListener('click', () => inputImageFile.click());

    inputImageFile.addEventListener('change', async () => {
      const file = inputImageFile.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append('file', file);

      try {
        btnUploadImage.classList.add('animate-pulse');
        const resp = await fetch('/api/upload', { method: 'POST', body: formData });
        const resData = await resp.json();

        if (resData.status === 'success') {
          uploadedImagePath = resData.url;
          refImageName.textContent = resData.name;
          referenceImageBadge.classList.remove('hidden');
        } else {
          alert('Upload failed: ' + (resData.message || 'Unknown error'));
        }
      } catch (err) {
        console.error('Image upload failed:', err);
        alert('Could not upload reference image.');
      } finally {
        btnUploadImage.classList.remove('animate-pulse');
      }
    });
  }

  if (btnRemoveRefImage) {
    btnRemoveRefImage.addEventListener('click', removeReferenceImage);
  }

  function removeReferenceImage() {
    uploadedImagePath = '';
    if (inputImageFile) inputImageFile.value = '';
    if (referenceImageBadge) referenceImageBadge.classList.add('hidden');
  }

  // Prompt Form Submission
  promptForm.addEventListener('submit', (e) => {
    e.preventDefault();
    let rawPrompt = promptTextarea.value.trim();
    if (!rawPrompt || isProcessing) return;

    // Enforce mandatory Gemini API Key
    const apiKeyVal = inputApiKey ? inputApiKey.value.trim() : '';
    if (!apiKeyVal) {
      showApiKeyRequiredModal();
      return;
    }

    if (!socket || socket.readyState !== WebSocket.OPEN) {
      alert('WebSocket is connecting. Please wait a moment.');
      return;
    }

    // Attach duration constraint
    const promptText = `Target duration ${selectedDuration}: ${rawPrompt}`;

    // Increment local turn counter immediately so cards and timeline are correct
    currentTurn += 1;
    setProcessingState(true);
    currentTurnIterations = [];
    if (criticIterationTabsContainer) criticIterationTabsContainer.classList.add('hidden');

    if (agentWelcomeCard) agentWelcomeCard.style.display = 'none';

    // Show user turn card immediately
    addUserTurnLog(rawPrompt + ` (${selectedDuration})`, currentTurn);
    // Update turn badge proactively
    if (turnBadge) turnBadge.textContent = `Turn ${currentTurn}/4`;
    if (currentTurn >= 4 && driftWarning) driftWarning.classList.add('visible');

    socket.send(JSON.stringify({
      action: 'process_turn',
      prompt: promptText,
      session_id: sessionId,
      user_id: userId,
      uploaded_image_path: uploadedImagePath,
      api_key: inputApiKey ? inputApiKey.value.trim() : ''
    }));

    promptTextarea.value = '';
  });

  // Stop Agent Execution Button Handler
  if (btnStop) {
    btnStop.addEventListener('click', () => {
      if (!isProcessing) return;
      setProcessingState(false);
      removeThinkingCards();
      addErrorCard('Execution stopped by user.');
      if (socket) {
        socket.onclose = null; // disable auto 3-second reconnect timeout warning
        socket.close();
      }
      // Reconnect immediately so WS is ready for next prompt
      connectWebSocket();
    });
  }

  // Vibe Chips Handler
  document.querySelectorAll('.vibe-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const chipText = chip.textContent.trim();
      const currentVal = promptTextarea.value.trim();
      promptTextarea.value = currentVal ? `${currentVal} with ${chipText}` : chipText;
      promptTextarea.focus();
    });
  });

  // Stream Event Dispatcher — handles new protocol: agent_thinking / agent_done / turn_complete
  function handleStreamEvent(data) {
    const iter = data.iteration || 1;
    const turn = data.current_turn || currentTurn;

    if (data.token_metadata) {
      updateUsageAnalytics(data.token_metadata);
    }

    if (data.step === 'agent_thinking') {
      // Agent started computing — show animated thinking card
      showAgentThinking(data.agent || 'pipeline', iter);

    } else if (data.step === 'agent_done') {
      // Agent produced output — replace thinking card with result card
      removeThinkingCards();
      const agent = data.agent || 'pipeline';

      if (agent === 'creative_director' && data.creative_director_review) {
        addDirectorCard(data.creative_director_review, iter, turn);
        // Track this loop iteration for the right panel tabs
        const exists = currentTurnIterations.some(item => item.iteration === iter);
        if (!exists) {
          currentTurnIterations.push({ iteration: iter, directorReview: data.creative_director_review });
        }
        renderLoopIterationTabs(iter);

      } else if (agent === 'prompt_architect' && data.optimized_prompt) {
        addArchitectCard(data.optimized_prompt, iter, turn);

      } else if (agent === 'video_producer') {
        const artifact = (data.production_result && data.production_result.artifact_name)
          || data.artifact_name || 'video.mp4';
        addProducerCard(artifact, iter, turn);

      } else if (agent === 'critic' && data.critic_review) {
        addCriticLogCard(data.critic_review, iter, turn);
        renderCriticReviewPanel(data.critic_review);
      }

    } else if (data.step === 'turn_complete') {
      removeThinkingCards();
      // Fallback rendering of Creative Director and Architect results if missed during streaming
      if (data.creative_director_review && !agentLogsContainer.querySelector(`.director-card-turn-${turn}-iter-${iter}`)) {
        addDirectorCard(data.creative_director_review, iter, turn);
        const exists = currentTurnIterations.some(item => item.iteration === iter);
        if (!exists) {
          currentTurnIterations.push({ iteration: iter, directorReview: data.creative_director_review });
        }
        renderLoopIterationTabs(iter);
      }
      if (data.optimized_prompt && !agentLogsContainer.querySelector(`.architect-card-turn-${turn}-iter-${iter}`)) {
        addArchitectCard(data.optimized_prompt, iter, turn);
      }
      // Ensure critic panel shows if critic_review arrived
      if (data.critic_review) {
        renderCriticReviewPanel(data.critic_review);
      }
      finalizeTurn(data);

    } else if (data.step === 'error') {
      removeThinkingCards();
      addErrorCard(data.message || 'Pipeline execution failed');
      setProcessingState(false);
    }
  }

  function addUserTurnLog(promptText, turn) {
    const card = document.createElement('div');
    card.className = 'agent-card p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/30 text-xs space-y-1';
    card.innerHTML = `
      <div class="flex items-center justify-between font-bold text-indigo-400">
        <span>User Request (Turn #${turn})</span>
        <span class="text-[10px] text-slate-400 font-normal">Just now</span>
      </div>
      <p class="text-slate-200 font-medium leading-relaxed">"${escapeHtml(promptText)}"</p>
    `;
    agentLogsContainer.appendChild(card);
    scrollToBottom();
  }

  function showAgentThinking(agent, iter = 1) {
    removeThinkingCards();

    let color = 'indigo';
    let label = `Prompt Architect (Iter #${iter})`;
    let detail = 'Optimizing 6-dimension prompt vectors...';

    if (agent === 'creative_director') {
      color = 'amber';
      label = `Creative Director (Iter #${iter})`;
      detail = 'Establishing cinematic production concept...';
    } else if (agent === 'video_producer') {
      color = 'purple';
      label = `Video Producer (Iter #${iter})`;
      detail = 'Calling Google Omni via Interactions API...';
    } else if (agent === 'critic') {
      color = 'emerald';
      label = `Critic Agent (Iter #${iter})`;
      detail = 'Evaluating output quality & consistency...';
    }

    const card = document.createElement('div');
    card.id = 'thinking-card-active';
    card.className = `agent-card agent-${color} active p-3 rounded-xl border flex items-center justify-between text-xs`;
    card.innerHTML = `
      <div class="flex items-center gap-2.5">
        <span class="agent-status-dot ${color}"></span>
        <div>
          <strong class="text-slate-200 font-display">${label}</strong>
          <p class="text-[11px] text-slate-400">${detail}</p>
        </div>
      </div>
      <div class="thinking-dots dots-${color}">
        <span></span><span></span><span></span>
      </div>
    `;
    agentLogsContainer.appendChild(card);
    scrollToBottom();
  }

  function removeThinkingCards() {
    const active = document.getElementById('thinking-card-active');
    if (active) active.remove();
  }

  function addErrorCard(msg) {
    const card = document.createElement('div');
    card.className = 'agent-card p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-xs text-red-300 space-y-1';
    card.innerHTML = `
      <strong class="font-bold text-red-400 flex items-center gap-1">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        Pipeline Error
      </strong>
      <p>${escapeHtml(msg)}</p>
    `;
    agentLogsContainer.appendChild(card);
    scrollToBottom();
  }

  function finalizeTurn(data) {
    setProcessingState(false);

    const isBlocked = data.production_result && data.production_result.status === 'blocked';
    const iter = data.iteration || 1;
    const artifactName = data.artifact_name || 'video.mp4';
    const timestamp = Date.now();
    const videoUrl = `/api/videos/${artifactName}?session_id=${sessionId}&user_id=${userId}&t=${timestamp}`;

    if (isBlocked) {
      canvasPlaceholder.style.display = 'none';
      videoPlayer.classList.add('hidden');
      if (videoControlsOverlay) videoControlsOverlay.classList.add('hidden');
      if (canvasBlocked) canvasBlocked.classList.remove('hidden');
      btnDownloadMain.classList.add('hidden');
    } else {
      if (canvasBlocked) canvasBlocked.classList.add('hidden');
      canvasPlaceholder.style.display = 'none';
      videoPlayer.classList.remove('hidden');
      if (videoControlsOverlay) videoControlsOverlay.classList.remove('hidden');
      videoPlayer.src = videoUrl;
      videoPlayer.load();
      videoPlayer.play().catch(() => {});
      if (iconPlay) iconPlay.classList.add('hidden');
      if (iconPause) iconPause.classList.remove('hidden');

      // Export button
      btnDownloadMain.classList.remove('hidden');
      btnDownloadMain.onclick = () => {
        const a = document.createElement('a');
        a.href = videoPlayer.src || videoUrl;
        a.download = artifactName;
        a.click();
      };
    }

    // Update Critic Right Panel (final authoritative render)
    if (data.critic_review) {
      renderCriticReviewPanel(data.critic_review);
    }

    // Save to history — use server-authoritative turn number
    const serverTurn = data.current_turn || currentTurn;
    // Sync local currentTurn to server value (in case of any drift)
    currentTurn = serverTurn;

    // Avoid duplicate timeline entries for the same turn (in case of re-render)
    const alreadyInHistory = turnHistory.some(t => t.turn === serverTurn);
    if (!alreadyInHistory) {
      turnHistory.push({
        turn: serverTurn,
        artifactName,
        videoUrl,
        prompt: data.optimized_prompt || '',
        isBlocked: isBlocked
      });
    } else {
      // Update existing entry's videoUrl (video may have been regenerated)
      const entry = turnHistory.find(t => t.turn === serverTurn);
      if (entry) {
        entry.videoUrl = videoUrl;
        entry.artifactName = artifactName;
        entry.isBlocked = isBlocked;
      }
    }

    // Update Turn Badge & Drift Warning
    turnBadge.textContent = `Turn ${currentTurn}/4`;
    if (currentTurn >= 4) {
      driftWarning.classList.add('visible');
    } else {
      driftWarning.classList.remove('visible');
    }

    updateTimelineUI();
  }

  function addDirectorCard(review, iter = 1, turn = currentTurn) {
    const cardKey = `director-card-turn-${turn}-iter-${iter}`;
    if (agentLogsContainer.querySelector(`.${cardKey}`)) return;

    let reviewObj = {};
    try {
      reviewObj = typeof review === 'string' ? JSON.parse(review) : review;
    } catch (e) {
      console.error('Error parsing creative_director_review:', e, review);
      // Fallback in case raw text description is returned instead of JSON
      reviewObj = {
        production_concept: typeof review === 'string' ? review : JSON.stringify(review),
        director_approved: false,
        director_feedback: ''
      };
    }
    const approved = reviewObj.director_approved;
    const concept = reviewObj.production_concept || '';
    const feedback = reviewObj.director_feedback || '';

    const statusColor = approved
      ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30'
      : 'text-amber-400 bg-amber-500/10 border-amber-500/30';
    const statusLabel = approved ? '✓ Approved' : '⏳ Refining';

    const card = document.createElement('div');
    card.className = `agent-card ${cardKey} p-3 rounded-xl bg-[#0D1117] border border-amber-500/30 text-xs space-y-2`;
    card.innerHTML = `
      <div class="flex items-center justify-between font-display text-amber-400 font-semibold">
        <span class="flex items-center gap-1.5">
          <span class="agent-status-dot amber"></span>
          Creative Director (Iter #${iter})
        </span>
        <span class="text-[10px] px-1.5 py-0.5 rounded border ${statusColor} font-bold">${statusLabel}</span>
      </div>
      <div class="space-y-1.5">
        <p class="text-[10px] text-amber-300 font-semibold uppercase tracking-wide">Production Concept</p>
        <p class="text-[11px] text-slate-300 leading-relaxed bg-black/30 p-2 rounded border border-white/5">${escapeHtml(concept)}</p>
        ${feedback ? `
          <p class="text-[10px] text-amber-300 font-semibold uppercase tracking-wide mt-1">Director Feedback → Architect</p>
          <p class="text-[11px] text-amber-200/80 italic leading-relaxed bg-amber-500/5 p-2 rounded border border-amber-500/10">${escapeHtml(feedback)}</p>
        ` : ''}
      </div>
    `;
    agentLogsContainer.appendChild(card);
    scrollToBottom();
  }

  function addArchitectCard(promptStr, iter = 1, turn = currentTurn) {
    if (agentLogsContainer.querySelector(`.architect-card-turn-${turn}-iter-${iter}`)) return;
    const card = document.createElement('div');
    card.className = `agent-card architect-card-done architect-card-turn-${turn}-iter-${iter} p-3 rounded-xl bg-[#0D1117] border border-indigo-500/30 text-xs space-y-1.5`;
    card.innerHTML = `
      <div class="flex items-center justify-between font-display text-indigo-400 font-semibold">
        <span class="flex items-center gap-1.5">
          <span class="agent-status-dot indigo"></span>
          Architect Vector Output (Iter #${iter})
        </span>
        <span class="text-[10px] text-indigo-300 bg-indigo-500/20 px-1.5 py-0.5 rounded">6-Dim</span>
      </div>
      <p class="text-[11px] text-slate-300 font-mono leading-relaxed bg-black/40 p-2 rounded border border-white/5">${escapeHtml(promptStr)}</p>
    `;
    agentLogsContainer.appendChild(card);
    scrollToBottom();
  }

  function addProducerCard(artifactName, iter = 1, turn = currentTurn) {
    if (agentLogsContainer.querySelector(`.producer-card-turn-${turn}-iter-${iter}`)) return;
    const card = document.createElement('div');
    card.className = `agent-card producer-card-turn-${turn}-iter-${iter} p-3 rounded-xl bg-[#0D1117] border border-purple-500/30 text-xs space-y-1`;
    card.innerHTML = `
      <div class="flex items-center justify-between font-display text-purple-400 font-semibold">
        <span class="flex items-center gap-1.5">
          <span class="agent-status-dot purple"></span>
          Producer Execution (Iter #${iter})
        </span>
        <span class="text-[10px] text-emerald-400 font-bold">✓ Generated</span>
      </div>
      <p class="text-[11px] text-slate-400">Artifact: <code class="text-purple-300">${escapeHtml(artifactName)}</code></p>
    `;
    agentLogsContainer.appendChild(card);
    scrollToBottom();
  }

  function addCriticLogCard(review, iter = 1, turn = currentTurn) {
    if (agentLogsContainer.querySelector(`.critic-card-turn-${turn}-iter-${iter}`)) return;
    const isApproved = review.status === 'approved';
    const statusBg = isApproved ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300' : 'bg-amber-500/10 border-amber-500/40 text-amber-300';
    const badgeText = isApproved ? '✓ APPROVED' : '⚠️ REJECTED - NEEDS REFINEMENT';
    const badgeColor = isApproved ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40' : 'bg-amber-500/20 text-amber-400 border-amber-500/40';

    const card = document.createElement('div');
    card.className = `agent-card critic-card-turn-${turn}-iter-${iter} p-3 rounded-xl ${statusBg} border text-xs space-y-2 animate-fade-in`;
    card.innerHTML = `
      <div class="flex items-center justify-between font-bold">
        <span class="flex items-center gap-1.5">
          <span class="agent-status-dot ${isApproved ? 'emerald' : 'gold'}"></span>
          Critic Evaluation (Iter #${iter})
        </span>
        <span class="text-[10px] font-bold px-2 py-0.5 rounded-full border ${badgeColor}">${badgeText} (Score: ${review.score || 0}/100)</span>
      </div>
      <p class="text-[11px] text-slate-200 leading-relaxed font-medium">"${escapeHtml(review.summary || '')}"</p>
      ${review.feedback_points && review.feedback_points.length ? `
        <div class="space-y-1 bg-black/30 p-2 rounded-lg border border-white/5 text-[10px]">
          <strong class="text-slate-400 block uppercase tracking-wider">Critic Observations:</strong>
          <ul class="list-disc list-inside space-y-0.5 text-slate-300">
            ${review.feedback_points.map(pt => `<li>${escapeHtml(pt)}</li>`).join('')}
          </ul>
        </div>
      ` : ''}
    `;
    agentLogsContainer.appendChild(card);
    scrollToBottom();
  }

  // Renders the Loop Iterations tabs in the right panel header.
  // Tabs show each creative_director pass (Iter #1, #2, #3...).
  // Clicking a tab does nothing special — it's visual feedback for the alignment loop.
  function renderLoopIterationTabs(activeIteration = 1) {
    if (!criticIterationTabsContainer || !criticIterationTabs) return;
    if (currentTurnIterations.length === 0) return;

    criticIterationTabsContainer.classList.remove('hidden');
    criticIterationTabsContainer.classList.add('flex');

    criticIterationTabs.innerHTML = currentTurnIterations.map((item) => {
      const review = item.directorReview || {};
      const approved = typeof review === 'object' ? review.director_approved : false;
      const statusDot = approved ? '🟢' : '🔄';
      const activeClass = item.iteration === activeIteration
        ? 'bg-amber-600/80 text-white font-bold border-amber-400 shadow'
        : 'bg-slate-800/80 text-slate-400 hover:text-white border-slate-700';
      return `
        <button class="px-2.5 py-1 rounded-lg border text-[11px] transition-all flex items-center gap-1 ${activeClass}" data-iter="${item.iteration}" title="Alignment loop pass #${item.iteration}">
          <span>${statusDot} Iter #${item.iteration}</span>
        </button>
      `;
    }).join('');
  }

  // Renders the critic's quality review in the right panel (no tabs needed — critic runs once).
  function renderCriticReviewPanel(review) {
    if (!review) return;
    criticEmptyState.classList.add('hidden');
    criticResults.classList.remove('hidden');
    renderCriticReview(review);
  }

  function renderCriticReviewWithTabs(activeIteration = 1) {
    criticEmptyState.classList.add('hidden');
    criticResults.classList.remove('hidden');

    if (currentTurnIterations.length > 0 && criticIterationTabsContainer && criticIterationTabs) {
      criticIterationTabsContainer.classList.remove('hidden');
      criticIterationTabsContainer.classList.add('flex');
      criticIterationTabs.innerHTML = currentTurnIterations.map((item) => {
        const isApp = item.review.status === 'approved';
        const activeClass = item.iteration === activeIteration ? 'bg-indigo-600 text-white font-bold border-indigo-400 shadow' : 'bg-slate-800/80 text-slate-400 hover:text-white border-slate-700';
        const statusDot = isApp ? '🟢' : '🔴';
        return `
          <button class="px-2.5 py-1 rounded-lg border text-[11px] transition-all flex items-center gap-1 ${activeClass}" data-iter="${item.iteration}" title="Internal loop attempt #${item.iteration} for Turn ${currentTurn}">
            <span>${statusDot} Iter #${item.iteration}</span>
            <span class="text-[10px] opacity-80">(${item.review.score || 0}pt)</span>
          </button>
        `;
      }).join('');

      criticIterationTabs.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const iterNum = parseInt(e.currentTarget.getAttribute('data-iter'));
          renderCriticReviewWithTabs(iterNum);
        });
      });
    }

    const targetItem = currentTurnIterations.find(item => item.iteration === activeIteration) || currentTurnIterations[currentTurnIterations.length - 1];
    if (targetItem && targetItem.review) {
      renderCriticReview(targetItem.review);
    }
  }

  function renderCriticReview(review) {
    const score = review.score || 85;
    const isApproved = review.status === 'approved';

    // Badge
    criticStatusBadge.className = isApproved ? 'badge-approved' : 'badge-needs-refinement';
    criticStatusBadge.textContent = isApproved ? '✓ Approved' : '⚠️ Needs Refinement';
    criticStatusBadge.classList.remove('hidden');

    // Summary & Score
    criticSummaryText.textContent = review.summary || 'Video quality meets creative specifications.';
    criticScoreNum.textContent = score;

    // Animate circular gauge
    const circumference = 314;
    const offset = circumference - (score / 100) * circumference;
    criticScoreCircle.style.setProperty('--target-offset', `${offset}`);
    criticScoreCircle.style.strokeDashoffset = `${offset}`;

    // Feedback points
    criticFeedbackList.innerHTML = '';
    const points = review.feedback_points || ['Visual style matches prompt spec', 'Motion dynamics coherent'];
    points.forEach(pt => {
      const div = document.createElement('div');
      div.className = 'feedback-bullet';
      div.textContent = pt;
      criticFeedbackList.appendChild(div);
    });

    // Actionable Remix Suggestions
    criticRemixSuggestions.innerHTML = '';
    const suggestions = review.refinement_suggestions || ['Add sunset volumetric lighting', 'Shift camera to wide shot'];
    suggestions.forEach(sugg => {
      const btn = document.createElement('button');
      btn.className = 'remix-chip';
      btn.innerHTML = `<span>⚡</span> <span>${escapeHtml(sugg)}</span>`;
      btn.addEventListener('click', () => {
        promptTextarea.value = sugg;
        promptTextarea.focus();
      });
      criticRemixSuggestions.appendChild(btn);
    });
  }

  function updateTimelineUI() {
    timelineTurns.innerHTML = turnHistory.map((t, idx) => `
      <button class="timeline-chip ${t.turn === currentTurn ? 'active' : ''}" data-turn-idx="${idx}">
        <span>Turn ${t.turn}</span>
      </button>
    `).join('');

    timelineTurns.querySelectorAll('.timeline-chip').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const idx = parseInt(e.currentTarget.getAttribute('data-turn-idx'));
        const turnData = turnHistory[idx];
        if (turnData) {
          if (turnData.isBlocked) {
            canvasPlaceholder.style.display = 'none';
            videoPlayer.classList.add('hidden');
            if (videoControlsOverlay) videoControlsOverlay.classList.add('hidden');
            if (canvasBlocked) canvasBlocked.classList.remove('hidden');
            btnDownloadMain.classList.add('hidden');
          } else {
            if (canvasBlocked) canvasBlocked.classList.add('hidden');
            canvasPlaceholder.style.display = 'none';
            videoPlayer.classList.remove('hidden');
            if (videoControlsOverlay) videoControlsOverlay.classList.remove('hidden');
            videoPlayer.src = turnData.videoUrl;
            videoPlayer.load();
            videoPlayer.play().catch(() => {});
            if (iconPlay) iconPlay.classList.add('hidden');
            if (iconPause) iconPause.classList.remove('hidden');
            
            btnDownloadMain.classList.remove('hidden');
            btnDownloadMain.onclick = () => {
              const a = document.createElement('a');
              a.href = turnData.videoUrl;
              a.download = turnData.artifactName || 'video.mp4';
              a.click();
            };
          }

          timelineTurns.querySelectorAll('.timeline-chip').forEach(c => c.classList.remove('active'));
          e.currentTarget.classList.add('active');
        }
      });
    });
  }

  // Custom Video Player Controls
  if (videoPlayer) {
    videoPlayer.addEventListener('timeupdate', () => {
      if (videoPlayer.duration) {
        const pct = (videoPlayer.currentTime / videoPlayer.duration) * 100;
        videoProgressFill.style.width = `${pct}%`;
        const curSec = Math.floor(videoPlayer.currentTime);
        const durSec = Math.floor(videoPlayer.duration);
        videoTimeDisplay.textContent = `0:${curSec < 10 ? '0' : ''}${curSec} / 0:${durSec < 10 ? '0' : ''}${durSec}`;
      }
    });

    btnPlayPause.addEventListener('click', () => {
      if (videoPlayer.paused) {
        videoPlayer.play();
        if (iconPlay) iconPlay.classList.add('hidden');
        if (iconPause) iconPause.classList.remove('hidden');
      } else {
        videoPlayer.pause();
        if (iconPlay) iconPlay.classList.remove('hidden');
        if (iconPause) iconPause.classList.add('hidden');
      }
    });

    if (btnMute) {
      btnMute.addEventListener('click', () => {
        videoPlayer.muted = !videoPlayer.muted;
        if (videoPlayer.muted) {
          if (iconVolumeHigh) iconVolumeHigh.classList.add('hidden');
          if (iconVolumeMuted) iconVolumeMuted.classList.remove('hidden');
          if (sliderVolume) sliderVolume.value = 0;
        } else {
          if (iconVolumeHigh) iconVolumeHigh.classList.remove('hidden');
          if (iconVolumeMuted) iconVolumeMuted.classList.add('hidden');
          if (sliderVolume) sliderVolume.value = videoPlayer.volume || 1;
        }
      });
    }

    if (sliderVolume) {
      sliderVolume.addEventListener('input', (e) => {
        const val = parseFloat(e.target.value);
        videoPlayer.volume = val;
        if (val === 0) {
          videoPlayer.muted = true;
          if (iconVolumeHigh) iconVolumeHigh.classList.add('hidden');
          if (iconVolumeMuted) iconVolumeMuted.classList.remove('hidden');
        } else {
          videoPlayer.muted = false;
          if (iconVolumeHigh) iconVolumeHigh.classList.remove('hidden');
          if (iconVolumeMuted) iconVolumeMuted.classList.add('hidden');
        }
      });
    }

    videoProgress.addEventListener('click', (e) => {
      const rect = videoProgress.getBoundingClientRect();
      const pos = (e.clientX - rect.left) / rect.width;
      videoPlayer.currentTime = pos * videoPlayer.duration;
    });
  }

  // DevHack Academy Float Card Promotion
  const devhackPromoCard = document.getElementById('devhack-promo-card');
  const btnClosePromo = document.getElementById('btn-close-promo');

  if (devhackPromoCard && btnClosePromo) {
    if (localStorage.getItem('devhack_promo_dismissed') === 'true') {
      devhackPromoCard.style.display = 'none';
    }

    btnClosePromo.addEventListener('click', () => {
      devhackPromoCard.style.opacity = '0';
      devhackPromoCard.style.transform = 'scale(0.95)';
      setTimeout(() => {
        devhackPromoCard.style.display = 'none';
      }, 300);
      localStorage.setItem('devhack_promo_dismissed', 'true');
    });
  }

  function setProcessingState(processing) {
    isProcessing = processing;
    btnSubmit.disabled = processing;
    if (processing) {
      btnSubmitText.textContent = 'Synthesizing...';
      btnSubmitSpinner.classList.remove('hidden');
      btnSubmitIcon.classList.add('hidden');
      if (btnStop) btnStop.classList.remove('hidden');
    } else {
      btnSubmitText.textContent = 'Synthesize';
      btnSubmitSpinner.classList.add('hidden');
      btnSubmitIcon.classList.remove('hidden');
      if (btnStop) btnStop.classList.add('hidden');
    }
  }

  function scrollToBottom() {
    agentLogsContainer.scrollTop = agentLogsContainer.scrollHeight;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function updateUsageAnalytics(token_metadata) {
    if (!token_metadata) return;

    if (analyticsInputTokens) analyticsInputTokens.textContent = token_metadata.input_tokens.toLocaleString();
    if (analyticsInputCost) analyticsInputCost.textContent = `$${token_metadata.input_cost.toFixed(4)}`;

    if (analyticsOutputTokens) analyticsOutputTokens.textContent = token_metadata.text_output_tokens.toLocaleString();
    if (analyticsOutputCost) analyticsOutputCost.textContent = `$${token_metadata.text_output_cost.toFixed(4)}`;

    if (analyticsVideoSeconds) analyticsVideoSeconds.textContent = `${token_metadata.video_output_seconds}s`;
    if (analyticsVideoCost) analyticsVideoCost.textContent = `$${token_metadata.video_output_cost.toFixed(4)}`;

    if (analyticsTotalCost) analyticsTotalCost.textContent = `$${token_metadata.total_cost.toFixed(6)}`;
  }
});

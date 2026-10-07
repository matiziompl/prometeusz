import 'xterm/css/xterm.css';
import { createIcons, icons } from 'lucide';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { Terminal } from 'xterm';
import { FitAddon } from '@xterm/addon-fit';

marked.setOptions({
  gfm: true,
  breaks: true,
});

class PrometeuszApp {
  constructor() {
    this.sessions = [];
    this.folders = [];
    this.activeSessionId = null;
    this.activeRole = '';
    this.slashCommands = [];
    this.selectedSlashIndex = 0;
    this.terminal = null;
    this.fitAddon = null;
    this.ptySocket = null;
    this.metricsInterval = null;
    this.activeAbortController = null;
    this.isStreaming = false;
    this.userScrolledUp = false;
    this.currentFsPath = '/workspace';
    this.currentDiffMode = 'inline'; // 'inline' | 'side'
    this.attachedFiles = [];

    this.initElements();
    this.initIcons();
    this.initResizers();
    this.initEvents();
    this.initTerminal();
    this.initTheme();
    this.initFontSettings();
    this.initPinLock();
    this.loadSlashCommands();
    this.loadFolders();
    this.loadSessions();
    this.loadModels();
    this.loadAgents();
    this.startMetricsPoller();
    this.startSessionsPoller();
    this.requestNotificationPermission();
  }

  initIcons() {
    createIcons({ icons });
  }

  initElements() {
    // Left Sidebar
    this.sidebarLeft = document.getElementById('sidebar-left');
    this.resizerLeft = document.getElementById('resizer-left');
    this.mobileBackdrop = document.getElementById('mobile-backdrop');
    this.btnMobileSidebar = document.getElementById('btn-mobile-sidebar');
    this.btnCloseMobileSidebar = document.getElementById('btn-close-mobile-sidebar');
    this.sessionListEl = document.getElementById('session-list');
    this.pinnedSessionsListEl = document.getElementById('pinned-sessions-list');
    this.foldersContainer = document.getElementById('folders-container');
    this.sessionSearchInput = document.getElementById('session-search-input');
    this.btnClearSearch = document.getElementById('btn-clear-search');
    this.btnNewChat = document.getElementById('btn-new-chat');
    this.btnNewFolder = document.getElementById('btn-new-folder');
    this.btnPanic = document.getElementById('btn-panic');
    this.btnServerResources = document.getElementById('btn-server-resources');
    this.metricsPopover = document.getElementById('metrics-popover');

    // Middle Chat
    this.activeSessionTitle = document.getElementById('active-session-title');
    this.btnRenameSession = document.getElementById('btn-rename-session');
    this.activeModelBadge = document.getElementById('active-model-name');
    this.chatStream = document.getElementById('chat-stream');
    this.chatInput = document.getElementById('chat-input');
    this.btnSend = document.getElementById('btn-send-message');
    this.btnAbort = document.getElementById('btn-abort-message');
    this.bottomModelSelect = document.getElementById('bottom-model-select');
    this.bottomRoleSelect = document.getElementById('bottom-role-select');
    this.btnReloadConversationsMgmt = document.getElementById('btn-reload-conversations-mgmt');
    this.btnTriggerUpload = document.getElementById('btn-trigger-upload');
    this.fileUploadInput = document.getElementById('file-upload-input');
    this.chatDropzone = document.getElementById('chat-dropzone');
    this.slashAutocomplete = document.getElementById('slash-autocomplete');
    this.slashCommandsList = document.getElementById('slash-commands-list');
    this.promptAttachmentsBar = document.getElementById('prompt-attachments-bar');

    // Prompt bar + button & popover
    this.btnPlusAttach = document.getElementById('btn-plus-attach');
    this.plusPopover = document.getElementById('plus-popover');
    this.btnPopoverUpload = document.getElementById('btn-popover-upload');
    this.btnPopoverWorkspace = document.getElementById('btn-popover-workspace');
    this.workspaceFilesModal = document.getElementById('workspace-files-modal');
    this.btnCloseWorkspaceFiles = document.getElementById('btn-close-workspace-files');
    this.modalWorkspaceTree = document.getElementById('modal-workspace-tree');
    this.btnModalFsParent = document.getElementById('btn-modal-fs-parent');
    this.modalFsPath = document.getElementById('modal-fs-path');
    this.modalFsFilter = document.getElementById('modal-fs-filter');
    this.modalFsItems = [];
    this.modalFsCurrentPath = '/workspace';
    this.modalFsParentPath = null;
    this.currentArtifactText = '';
    this.currentArtifactName = '';
    this.settingFontSize = document.getElementById('setting-font-size');
    this.settingCodeFont = document.getElementById('setting-code-font');
    this.collapsedFolders = new Set(JSON.parse(localStorage.getItem('prometeusz_collapsed_folders') || '[]'));

    // Header buttons
    this.btnShortcutsHelp = document.getElementById('btn-shortcuts-help');
    this.btnOpenSettings = document.getElementById('btn-open-settings');
    this.btnExportChat = document.getElementById('btn-export-chat');
    this.btnToggleAuxiliary = document.getElementById('btn-toggle-auxiliary');

    // Auxiliary Panel
    this.sidebarRight = document.getElementById('sidebar-right');
    this.resizerRight = document.getElementById('resizer-right');
    this.btnCloseAuxiliary = document.getElementById('btn-close-auxiliary');

    // Modals
    this.settingsModal = document.getElementById('settings-modal');
    this.btnCloseSettings = document.getElementById('btn-close-settings');
    this.shortcutsModal = document.getElementById('shortcuts-modal');
    this.btnCloseShortcuts = document.getElementById('btn-close-shortcuts');
    this.newFolderModal = document.getElementById('new-folder-modal');
    this.newFolderInput = document.getElementById('new-folder-input');
    this.btnCloseNewFolderModal = document.getElementById('btn-close-new-folder-modal');
    this.btnCancelNewFolderModal = document.getElementById('btn-cancel-new-folder-modal');
    this.btnConfirmNewFolder = document.getElementById('btn-confirm-new-folder');
    this.pinLockOverlay = document.getElementById('pin-lock-overlay');
  }

  /* ────────────────── PRZESUWANE SEPARATORY (RESIZERS) ────────────────── */

  initResizers() {
    // Przywróć zapisane szerokości
    const savedLeftWidth = localStorage.getItem('prometeusz_left_sidebar_width');
    if (savedLeftWidth && this.sidebarLeft && window.innerWidth >= 768) {
      const parsed = parseInt(savedLeftWidth, 10);
      if (!isNaN(parsed)) {
        this.sidebarLeft.style.width = `${Math.max(220, Math.min(550, parsed))}px`;
      }
    }

    const savedRightWidth = localStorage.getItem('prometeusz_right_sidebar_width');
    if (savedRightWidth && this.sidebarRight) {
      const parsed = parseInt(savedRightWidth, 10);
      if (!isNaN(parsed)) {
        this.sidebarRight.style.width = `${Math.max(280, Math.min(750, parsed))}px`;
      }
    }

    // Lewy resizer
    if (this.resizerLeft && this.sidebarLeft) {
      let isDraggingLeft = false;
      let startX = 0;
      let startWidth = 0;

      const onPointerDownLeft = (e) => {
        isDraggingLeft = true;
        startX = e.clientX;
        startWidth = this.sidebarLeft.getBoundingClientRect().width;
        document.body.classList.add('is-resizing');
        window.addEventListener('pointermove', onPointerMoveLeft);
        window.addEventListener('pointerup', onPointerUpLeft);
      };

      const onPointerMoveLeft = (e) => {
        if (!isDraggingLeft) return;
        const delta = e.clientX - startX;
        const newWidth = Math.max(220, Math.min(550, Math.round(startWidth + delta)));
        this.sidebarLeft.style.width = `${newWidth}px`;
      };

      const onPointerUpLeft = () => {
        if (!isDraggingLeft) return;
        isDraggingLeft = false;
        document.body.classList.remove('is-resizing');
        window.removeEventListener('pointermove', onPointerMoveLeft);
        window.removeEventListener('pointerup', onPointerUpLeft);
        const finalWidth = Math.round(this.sidebarLeft.getBoundingClientRect().width);
        localStorage.setItem('prometeusz_left_sidebar_width', finalWidth);
      };

      this.resizerLeft.addEventListener('pointerdown', onPointerDownLeft);
    }

    // Prawy resizer
    if (this.resizerRight && this.sidebarRight) {
      let isDraggingRight = false;
      let startX = 0;
      let startWidth = 0;

      const onPointerDownRight = (e) => {
        isDraggingRight = true;
        startX = e.clientX;
        startWidth = this.sidebarRight.getBoundingClientRect().width;
        document.body.classList.add('is-resizing');
        window.addEventListener('pointermove', onPointerMoveRight);
        window.addEventListener('pointerup', onPointerUpRight);
      };

      const onPointerMoveRight = (e) => {
        if (!isDraggingRight) return;
        const delta = startX - e.clientX; // Przeciąganie w lewo powiększa prawy panel
        const newWidth = Math.max(280, Math.min(750, Math.round(startWidth + delta)));
        this.sidebarRight.style.width = `${newWidth}px`;
        this.fitAddon?.fit();
      };

      const onPointerUpRight = () => {
        if (!isDraggingRight) return;
        isDraggingRight = false;
        document.body.classList.remove('is-resizing');
        window.removeEventListener('pointermove', onPointerMoveRight);
        window.removeEventListener('pointerup', onPointerUpRight);
        const finalWidth = Math.round(this.sidebarRight.getBoundingClientRect().width);
        localStorage.setItem('prometeusz_right_sidebar_width', finalWidth);
        this.fitAddon?.fit();
      };

      this.resizerRight.addEventListener('pointerdown', onPointerDownRight);
    }
  }

  initEvents() {
    // Mobile Drawer
    this.btnMobileSidebar?.addEventListener('click', () => this.toggleMobileSidebar(true));
    this.btnCloseMobileSidebar?.addEventListener('click', () => this.toggleMobileSidebar(false));
    this.mobileBackdrop?.addEventListener('click', () => this.toggleMobileSidebar(false));

    // New Chat & Folder
    this.btnNewChat?.addEventListener('click', () => this.createNewSession());
    this.btnNewFolder?.addEventListener('click', () => this.openNewFolderModal());
    this.btnCloseNewFolderModal?.addEventListener('click', () => this.closeNewFolderModal());
    this.btnCancelNewFolderModal?.addEventListener('click', () => this.closeNewFolderModal());
    this.btnConfirmNewFolder?.addEventListener('click', () => this.submitNewFolder());
    this.newFolderInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        this.submitNewFolder();
      } else if (e.key === 'Escape') {
        this.closeNewFolderModal();
      }
    });
    this.newFolderModal?.addEventListener('click', (e) => {
      if (e.target === this.newFolderModal) {
        this.closeNewFolderModal();
      }
    });
    this.btnRenameSession?.addEventListener('click', () => this.promptRenameSession());
    this.activeSessionTitle?.addEventListener('dblclick', () => this.promptRenameSession());

    // Search
    this.sessionSearchInput?.addEventListener('input', (e) => this.handleSearch(e.target.value));
    this.btnClearSearch?.addEventListener('click', () => {
      if (this.sessionSearchInput) this.sessionSearchInput.value = '';
      this.btnClearSearch.classList.add('hidden');
      this.loadSessions();
    });

    // Panic Button
    this.btnPanic?.addEventListener('click', () => this.triggerPanic());

    // Server Resources Dock & Popover
    this.btnServerResources?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.metricsPopover?.classList.toggle('hidden');
      this.initIcons();
    });
    document.addEventListener('click', (e) => {
      if (!this.metricsPopover?.contains(e.target) && e.target !== this.btnServerResources && !this.btnServerResources?.contains(e.target)) {
        this.metricsPopover?.classList.add('hidden');
      }
    });

    // Header buttons
    this.btnShortcutsHelp?.addEventListener('click', () => this.toggleShortcutsModal(true));
    this.btnCloseShortcuts?.addEventListener('click', () => this.toggleShortcutsModal(false));
    this.btnOpenSettings?.addEventListener('click', () => this.openSettings());
    this.btnCloseSettings?.addEventListener('click', () => this.closeSettings());
    this.btnExportChat?.addEventListener('click', () => this.promptExport());
    this.btnToggleAuxiliary?.addEventListener('click', () => this.toggleAuxiliaryPanel());
    this.btnCloseAuxiliary?.addEventListener('click', () => this.toggleAuxiliaryPanel(false));

    // Chat actions
    this.btnSend?.addEventListener('click', () => this.handleSendMessage());
    this.btnAbort?.addEventListener('click', () => this.handleAbortMessage());
    this.chatInput?.addEventListener('keydown', (e) => this.handleInputKeydown(e));
    this.chatInput?.addEventListener('input', () => {
      this.chatInput.style.height = 'auto';
      this.chatInput.style.height = `${Math.min(this.chatInput.scrollHeight, 128)}px`;
      this.handleInputSlash();
    });

    // Bottom Role Select (Tokyo Night Krea Dropdown)
    this.bottomRoleSelect?.addEventListener('change', (e) => {
      this.activeRole = e.target.value || '';
    });

    // Odświeżanie zarządzania rozmowami w Ustawieniach
    this.btnReloadConversationsMgmt?.addEventListener('click', () => {
      this.loadConversationsManagement();
    });

    // Bottom Model Selector
    this.bottomModelSelect?.addEventListener('change', (e) => {
      this.selectModel(e.target.value);
    });

    // Prompt bar + button & popover (Gemini app pattern)
    this.btnPlusAttach?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.plusPopover?.classList.toggle('hidden');
      this.initIcons();
    });
    this.btnPopoverUpload?.addEventListener('click', () => {
      this.plusPopover?.classList.add('hidden');
      this.fileUploadInput?.click();
    });
    this.btnPopoverWorkspace?.addEventListener('click', () => {
      this.plusPopover?.classList.add('hidden');
      this.openWorkspaceFilesModal();
    });
    this.btnCloseWorkspaceFiles?.addEventListener('click', () => {
      this.workspaceFilesModal?.classList.add('hidden');
    });
    document.addEventListener('click', (e) => {
      if (!this.plusPopover?.contains(e.target) && e.target !== this.btnPlusAttach && !this.btnPlusAttach?.contains(e.target)) {
        this.plusPopover?.classList.add('hidden');
      }
    });

    // File Upload & Drag & Drop
    this.btnTriggerUpload?.addEventListener('click', () => this.fileUploadInput?.click());
    this.fileUploadInput?.addEventListener('change', (e) => this.handleFileSelect(e));
    this.setupDragAndDrop();

    // Sticky Auto-scroll tracking
    this.chatStream?.addEventListener('scroll', () => {
      const threshold = 80;
      const distanceFromBottom = this.chatStream.scrollHeight - this.chatStream.scrollTop - this.chatStream.clientHeight;
      this.userScrolledUp = distanceFromBottom > threshold;
    });

    // Auxiliary Tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.getAttribute('data-tab');
        this.switchAuxiliaryTab(tab);
      });
    });

    // Artifacts actions
    document.getElementById('btn-refresh-artifacts')?.addEventListener('click', () => this.loadArtifacts(this.activeSessionId));
    document.getElementById('btn-close-viewer')?.addEventListener('click', () => {
      document.getElementById('artifact-viewer')?.classList.add('hidden');
      document.getElementById('artifacts-list-container')?.classList.remove('hidden');
    });
    document.getElementById('btn-artifact-view-code')?.addEventListener('click', () => this.toggleArtifactView('code'));
    document.getElementById('btn-artifact-view-preview')?.addEventListener('click', () => this.toggleArtifactView('preview'));
    document.getElementById('btn-copy-artifact')?.addEventListener('click', () => this.copyArtifactContent());

    // Modal Workspace Files navigation & search filter
    document.getElementById('btn-modal-fs-parent')?.addEventListener('click', () => {
      if (this.modalFsParentPath) this.openWorkspaceFilesModal(this.modalFsParentPath);
    });
    document.getElementById('modal-fs-filter')?.addEventListener('input', (e) => {
      this.filterModalWorkspaceFiles(e.target.value);
    });

    // Changes diff toggle
    document.getElementById('btn-diff-inline')?.addEventListener('click', () => this.setDiffMode('inline'));
    document.getElementById('btn-diff-side')?.addEventListener('click', () => this.setDiffMode('side'));
    document.getElementById('btn-close-diff-viewer')?.addEventListener('click', () => {
      document.getElementById('diff-viewer')?.classList.add('hidden');
    });

    // Settings actions
    document.querySelectorAll('.settings-tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this.switchSettingsTab(btn.getAttribute('data-settings-tab'));
      });
    });
    document.querySelectorAll('.theme-card').forEach(card => {
      card.addEventListener('click', () => {
        const theme = card.getAttribute('data-theme');
        this.setTheme(theme);
      });
    });
    document.getElementById('btn-format-settings')?.addEventListener('click', () => this.formatSettingsJson());
    document.getElementById('btn-save-settings')?.addEventListener('click', () => this.saveSettingsJson());
    document.getElementById('skills-search-input')?.addEventListener('input', (e) => this.filterSkills(e.target.value));
    document.getElementById('btn-reload-skills')?.addEventListener('click', () => this.loadSkills());

    // PIN lock actions
    document.getElementById('btn-save-pin')?.addEventListener('click', () => this.savePinCode());
    document.getElementById('btn-remove-pin')?.addEventListener('click', () => this.removePinCode());
    document.getElementById('btn-unlock-pin')?.addEventListener('click', () => this.attemptUnlockPin());
    document.getElementById('unlock-pin-input')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.attemptUnlockPin();
    });

    // Global Shortcuts
    window.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'n') {
        e.preventDefault();
        this.createNewSession();
      } else if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault();
        this.openSettings();
      } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        this.toggleAuxiliaryPanel();
      } else if (e.key === '?' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        e.preventDefault();
        this.toggleShortcutsModal(true);
      } else if (e.key === 'Escape') {
        this.closeAllModals();
      }
    });
  }

  /* ────────────────── 6 MOTYWÓW & WYGLĄD ────────────────── */

  initTheme() {
    const saved = localStorage.getItem('prometeusz_theme') || 'tokyo-night';
    this.setTheme(saved);
  }

  setTheme(themeName) {
    document.documentElement.setAttribute('data-theme', themeName);
    document.body.setAttribute('data-theme', themeName);
    if (themeName === 'light-gray') {
      document.documentElement.classList.remove('dark');
    } else {
      document.documentElement.classList.add('dark');
    }
    localStorage.setItem('prometeusz_theme', themeName);

    document.querySelectorAll('.theme-card').forEach(c => {
      if (c.getAttribute('data-theme') === themeName) {
        c.classList.add('active');
      } else {
        c.classList.remove('active');
      }
    });
  }

  /* ────────────────── CZCIONKI & ROZMIARY ────────────────── */

  initFontSettings() {
    const savedFontSize = localStorage.getItem('prometeusz_font_size') || '14px';
    const savedCodeFont = localStorage.getItem('prometeusz_code_font') || "'JetBrains Mono', monospace";

    this.setFontSize(savedFontSize);
    this.setCodeFont(savedCodeFont);

    if (this.settingFontSize) {
      this.settingFontSize.value = savedFontSize;
      this.settingFontSize.addEventListener('change', (e) => {
        this.setFontSize(e.target.value);
      });
    }

    if (this.settingCodeFont) {
      this.settingCodeFont.value = savedCodeFont;
      this.settingCodeFont.addEventListener('change', (e) => {
        this.setCodeFont(e.target.value);
      });
    }
  }

  setFontSize(size) {
    document.documentElement.style.setProperty('--font-size-base', size);
    localStorage.setItem('prometeusz_font_size', size);
  }

  setCodeFont(fontFamily) {
    document.documentElement.style.setProperty('--font-family-mono', fontFamily);
    localStorage.setItem('prometeusz_code_font', fontFamily);
    if (this.term) {
      this.term.options.fontFamily = fontFamily;
    }
  }

  /* ────────────────── PIN LOCK HOMELAB ────────────────── */

  initPinLock() {
    const pin = localStorage.getItem('prometeusz_pin');
    if (pin && this.pinLockOverlay) {
      this.pinLockOverlay.classList.remove('hidden');
      setTimeout(() => document.getElementById('unlock-pin-input')?.focus(), 100);
    }
  }

  attemptUnlockPin() {
    const input = document.getElementById('unlock-pin-input');
    const err = document.getElementById('unlock-pin-error');
    const savedPin = localStorage.getItem('prometeusz_pin');
    if (input && input.value === savedPin) {
      this.pinLockOverlay?.classList.add('hidden');
      if (err) err.classList.add('hidden');
      input.value = '';
    } else {
      if (err) err.classList.remove('hidden');
      input?.focus();
    }
  }

  savePinCode() {
    const val = document.getElementById('setting-pin-input')?.value.trim();
    if (val && val.length >= 4) {
      localStorage.setItem('prometeusz_pin', val);
      const status = document.getElementById('pin-status-text');
      if (status) {
        status.textContent = '✓ Kod PIN został ustawiony i aktywowany.';
        status.classList.remove('hidden');
      }
    }
  }

  removePinCode() {
    localStorage.removeItem('prometeusz_pin');
    const status = document.getElementById('pin-status-text');
    if (status) {
      status.textContent = '✓ Blokada kodem PIN została wyłączona.';
      status.classList.remove('hidden');
    }
    const input = document.getElementById('setting-pin-input');
    if (input) input.value = '';
  }

  /* ────────────────── SESJE, FOLDERY, PRZYPINANIE, REORDER ────────────────── */

  async loadSessions() {
    try {
      const res = await fetch('/api/sessions');
      if (!res.ok) throw new Error();
      const raw = await res.json();
      this.sessions = raw.map(s => ({
        id: s.conversation_id,
        title: s.title || `Sesja ${s.conversation_id.slice(0, 8)}`,
        lastMessage: s.preview || 'Brak wiadomości',
        pinned: Boolean(s.pinned),
        folder: s.folder || '',
        updatedAt: s.last_modified ? new Date(s.last_modified).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Teraz'
      }));
    } catch {
      this.sessions = [];
    }
    this.renderSessions(this.sessions);
    if (this.sessions.length > 0 && !this.activeSessionId) {
      this.selectSession(this.sessions[0].id);
    } else if (this.sessions.length === 0 && !this.activeSessionId) {
      this.createNewSession();
    }
  }

  renderSessions(list) {
    if (!this.sessionListEl || !this.pinnedSessionsListEl) return;
    this.sessionListEl.innerHTML = '';
    this.pinnedSessionsListEl.innerHTML = '';

    const pinned = list.filter(s => s.pinned);
    const unpinned = list.filter(s => !s.pinned && !s.folder);

    // Pinned container visibility
    const pinnedCont = document.getElementById('pinned-container');
    if (pinnedCont) {
      pinnedCont.style.display = pinned.length > 0 ? 'block' : 'none';
    }

    pinned.forEach(s => this.pinnedSessionsListEl.appendChild(this.createSessionElement(s)));
    unpinned.forEach(s => this.sessionListEl.appendChild(this.createSessionElement(s)));
    this.renderFolderSessions(list);
    this.initIcons();
  }

  createSessionElement(sess) {
    const isActive = sess.id === this.activeSessionId;
    const item = document.createElement('div');
    item.className = `group flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer transition-all border ${
      isActive
        ? 'bg-[var(--bg-card)] border-[var(--accent-blue)]/50 text-[var(--text-main)]'
        : 'bg-transparent border-transparent hover:bg-[var(--bg-card)]/60 text-[var(--text-dim)] hover:text-[var(--text-main)]'
    }`;
    item.setAttribute('draggable', 'true');
    item.setAttribute('data-id', sess.id);

    item.innerHTML = `
      <div class="flex flex-col min-w-0 flex-1 mr-2">
        <div class="flex items-center gap-1.5">
          ${sess.pinned ? '<i data-lucide="pin" class="w-3 h-3 text-[var(--accent-blue)] flex-shrink-0"></i>' : ''}
          <span class="font-medium text-xs truncate">${this.escapeHtml(sess.title)}</span>
        </div>
        <p class="text-[10px] text-[var(--text-dim)] truncate mt-0.5">${this.escapeHtml(sess.lastMessage)}</p>
      </div>
      <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button class="btn-rename-session p-1 rounded hover:bg-[var(--border-color)] text-[var(--text-dim)] hover:text-[var(--accent-blue)]" title="Zmień nazwę">
          <i data-lucide="pencil" class="w-3 h-3"></i>
        </button>
        <button class="btn-pin-session p-1 rounded hover:bg-[var(--border-color)] text-[var(--text-dim)] hover:text-[var(--accent-blue)]" title="${sess.pinned ? 'Odepnij' : 'Przypnij'}">
          <i data-lucide="pin" class="w-3 h-3"></i>
        </button>
        <button class="btn-del-session p-1 rounded hover:bg-[var(--border-color)] text-[var(--text-dim)] hover:text-[#f7768e]" title="Usuń sesję">
          <i data-lucide="trash-2" class="w-3 h-3"></i>
        </button>
      </div>
    `;

    item.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      this.selectSession(sess.id);
    });

    item.querySelector('.btn-rename-session')?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.promptRenameSession(sess.id);
    });

    item.querySelector('.btn-pin-session')?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.togglePin(sess.id);
    });

    item.querySelector('.btn-del-session')?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.deleteSession(sess.id);
    });

    // Drag & drop sorting
    item.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', sess.id);
    });
    item.addEventListener('dragover', (e) => e.preventDefault());
    item.addEventListener('drop', (e) => {
      e.preventDefault();
      const draggedId = e.dataTransfer.getData('text/plain');
      this.reorderSessions(draggedId, sess.id);
    });

    return item;
  }

  async togglePin(sessionId) {
    try {
      await fetch(`/api/sessions/${sessionId}/pin`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      await this.loadSessions();
    } catch (_) {}
  }

  showConfirmModal({ title = 'Potwierdzenie', message = '', confirmText = 'Potwierdź', isDanger = true } = {}) {
    return new Promise((resolve) => {
      const modal = document.getElementById('custom-confirm-modal');
      const titleEl = document.getElementById('confirm-modal-title');
      const msgEl = document.getElementById('confirm-modal-message');
      const btnOk = document.getElementById('btn-ok-confirm-modal');
      const btnCancel = document.getElementById('btn-cancel-confirm-modal');
      const btnClose = document.getElementById('btn-close-confirm-modal');
      const iconCont = document.getElementById('confirm-modal-icon-container');

      if (!modal) {
        resolve(window.confirm(message));
        return;
      }

      if (titleEl) titleEl.textContent = title;
      if (msgEl) msgEl.textContent = message;
      if (btnOk) {
        btnOk.textContent = confirmText;
        if (isDanger) {
          btnOk.className = 'px-4 py-2 rounded-xl bg-[#f7768e] hover:brightness-110 text-[#121217] font-semibold text-xs transition-all shadow-md shadow-[#f7768e]/20 cursor-pointer';
          if (iconCont) {
            iconCont.className = 'p-2 rounded-xl bg-[#f7768e]/10 text-[#f7768e] border border-[#f7768e]/20';
            iconCont.innerHTML = '<i data-lucide="alert-triangle" class="w-4 h-4"></i>';
          }
        } else {
          btnOk.className = 'px-4 py-2 rounded-xl bg-[var(--accent-blue)] hover:brightness-110 text-[#121217] font-semibold text-xs transition-all shadow-md shadow-[#7aa2f7]/20 cursor-pointer';
          if (iconCont) {
            iconCont.className = 'p-2 rounded-xl bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/20';
            iconCont.innerHTML = '<i data-lucide="info" class="w-4 h-4"></i>';
          }
        }
      }

      this.initIcons();
      modal.classList.remove('hidden');

      const cleanup = (result) => {
        modal.classList.add('hidden');
        btnOk?.removeEventListener('click', onOk);
        btnCancel?.removeEventListener('click', onCancel);
        btnClose?.removeEventListener('click', onCancel);
        modal.removeEventListener('click', onBackdrop);
        window.removeEventListener('keydown', onKeyDown);
        resolve(result);
      };

      const onOk = () => cleanup(true);
      const onCancel = () => cleanup(false);
      const onBackdrop = (e) => {
        if (e.target === modal) cleanup(false);
      };
      const onKeyDown = (e) => {
        if (e.key === 'Escape') cleanup(false);
        else if (e.key === 'Enter') {
          e.preventDefault();
          cleanup(true);
        }
      };

      btnOk?.addEventListener('click', onOk);
      btnCancel?.addEventListener('click', onCancel);
      btnClose?.addEventListener('click', onCancel);
      modal.addEventListener('click', onBackdrop);
      window.addEventListener('keydown', onKeyDown);
    });
  }

  showPromptModal({ title = 'Wprowadź tekst', message = 'Wprowadź wartość:', defaultValue = '', confirmText = 'Zapisz' } = {}) {
    return new Promise((resolve) => {
      const modal = document.getElementById('custom-prompt-modal');
      const titleEl = document.getElementById('prompt-modal-title');
      const msgEl = document.getElementById('prompt-modal-message');
      const inputEl = document.getElementById('prompt-modal-input');
      const btnOk = document.getElementById('btn-ok-prompt-modal');
      const btnCancel = document.getElementById('btn-cancel-prompt-modal');
      const btnClose = document.getElementById('btn-close-prompt-modal');

      if (!modal) {
        resolve(window.prompt(message, defaultValue));
        return;
      }

      if (titleEl) titleEl.textContent = title;
      if (msgEl) msgEl.textContent = message;
      if (inputEl) inputEl.value = defaultValue;
      if (btnOk) btnOk.textContent = confirmText;

      this.initIcons();
      modal.classList.remove('hidden');
      setTimeout(() => {
        inputEl?.focus();
        inputEl?.select();
      }, 50);

      const cleanup = (result) => {
        modal.classList.add('hidden');
        btnOk?.removeEventListener('click', onOk);
        btnCancel?.removeEventListener('click', onCancel);
        btnClose?.removeEventListener('click', onCancel);
        modal.removeEventListener('click', onBackdrop);
        inputEl?.removeEventListener('keydown', onInputKey);
        window.removeEventListener('keydown', onKeyDown);
        resolve(result);
      };

      const onOk = () => cleanup(inputEl?.value ?? '');
      const onCancel = () => cleanup(null);
      const onBackdrop = (e) => {
        if (e.target === modal) cleanup(null);
      };
      const onInputKey = (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          onOk();
        } else if (e.key === 'Escape') {
          e.preventDefault();
          onCancel();
        }
      };
      const onKeyDown = (e) => {
        if (e.key === 'Escape') cleanup(null);
      };

      btnOk?.addEventListener('click', onOk);
      btnCancel?.addEventListener('click', onCancel);
      btnClose?.addEventListener('click', onCancel);
      modal.addEventListener('click', onBackdrop);
      inputEl?.addEventListener('keydown', onInputKey);
      window.addEventListener('keydown', onKeyDown);
    });
  }

  async deleteSession(sessionId) {
    const confirmed = await this.showConfirmModal({
      title: 'Usuń sesję',
      message: 'Czy na pewno chcesz bezpowrotnie usunąć tę sesję i jej transkrypt?',
      confirmText: 'Usuń',
      isDanger: true
    });
    if (!confirmed) return;
    try {
      await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
      if (this.activeSessionId === sessionId) {
        this.activeSessionId = null;
      }
      await this.loadSessions();
    } catch (_) {}
  }

  async promptRenameSession(targetId = null) {
    const sId = targetId || this.activeSessionId;
    if (!sId) return;
    const sess = this.sessions.find(s => s.id === sId);
    const current = sess ? sess.title : (this.activeSessionTitle?.textContent || '');
    const newName = await this.showPromptModal({
      title: 'Zmień nazwę sesji',
      message: 'Podaj nowy tytuł dla tej rozmowy:',
      defaultValue: current,
      confirmText: 'Zapisz'
    });
    if (newName && newName.trim() && newName.trim() !== current) {
      try {
        await fetch(`/api/sessions/${sId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: newName.trim() })
        });
        if (this.activeSessionTitle && sId === this.activeSessionId) {
          this.activeSessionTitle.textContent = newName.trim();
        }
        await this.loadSessions();
      } catch (_) {}
    }
  }

  async reorderSessions(draggedId, targetId) {
    if (draggedId === targetId) return;
    const ids = this.sessions.map(s => s.id);
    const fromIdx = ids.indexOf(draggedId);
    const toIdx = ids.indexOf(targetId);
    if (fromIdx !== -1 && toIdx !== -1) {
      ids.splice(fromIdx, 1);
      ids.splice(toIdx, 0, draggedId);
      try {
        await fetch('/api/sessions/order', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ order: ids })
        });
        await this.loadSessions();
      } catch (_) {}
    }
  }

  /* ────────────────── FOLDERY / PROJEKTY ────────────────── */

  async loadFolders() {
    try {
      const res = await fetch('/api/folders');
      if (res.ok) this.folders = await res.json();
    } catch (_) {
      this.folders = [];
    }
    this.renderFolders();
  }

  renderFolders() {
    if (!this.foldersContainer) return;
    this.foldersContainer.innerHTML = '';
    this.folders.forEach(f => {
      const isCollapsed = this.collapsedFolders?.has(f.id);
      const folderEl = document.createElement('div');
      folderEl.className = 'folder-group rounded-lg border border-[var(--border-color)]/60 bg-[var(--bg-base)]/40 p-1.5 space-y-1';
      folderEl.innerHTML = `
        <div class="folder-header flex items-center justify-between px-2 py-1 cursor-pointer select-none rounded hover:bg-[var(--bg-card)]/50 transition-colors">
          <div class="flex items-center gap-1.5 text-xs font-mono text-[var(--text-main)]">
            <i data-lucide="chevron-down" class="folder-arrow w-3.5 h-3.5 text-[var(--text-dim)] transition-transform duration-200 ${isCollapsed ? '-rotate-90' : ''}"></i>
            <i data-lucide="folder" class="w-3.5 h-3.5 text-[var(--accent-blue)]"></i>
            <span>${this.escapeHtml(f.name)}</span>
          </div>
          <button class="btn-del-folder text-[var(--text-dim)] hover:text-[#f7768e] p-0.5" title="Usuń folder">
            <i data-lucide="trash" class="w-3 h-3"></i>
          </button>
        </div>
        <div class="folder-items space-y-0.5 pl-2 transition-all duration-200 ${isCollapsed ? 'hidden' : ''}" data-folder-id="${f.id}"></div>
      `;

      const header = folderEl.querySelector('.folder-header');
      const items = folderEl.querySelector('.folder-items');
      const arrow = folderEl.querySelector('.folder-arrow');

      header?.addEventListener('click', (e) => {
        if (e.target.closest('.btn-del-folder')) return;
        const isHidden = items.classList.toggle('hidden');
        arrow?.classList.toggle('-rotate-90', isHidden);
        if (isHidden) {
          this.collapsedFolders.add(f.id);
        } else {
          this.collapsedFolders.delete(f.id);
        }
        localStorage.setItem('prometeusz_collapsed_folders', JSON.stringify(Array.from(this.collapsedFolders)));
      });

      folderEl.querySelector('.btn-del-folder')?.addEventListener('click', (e) => {
        e.stopPropagation();
        this.deleteFolder(f.id);
      });
      // Allow dropping sessions into folder
      folderEl.addEventListener('dragover', (e) => e.preventDefault());
      folderEl.addEventListener('drop', (e) => {
        e.preventDefault();
        const sessId = e.dataTransfer.getData('text/plain');
        this.assignSessionToFolder(sessId, f.id);
      });

      this.foldersContainer.appendChild(folderEl);
    });
    this.initIcons();
  }

  renderFolderSessions(list) {
    this.folders.forEach(f => {
      const container = document.querySelector(`.folder-items[data-folder-id="${f.id}"]`);
      if (container) {
        container.innerHTML = '';
        const inFolder = list.filter(s => s.folder === f.id);
        inFolder.forEach(s => container.appendChild(this.createSessionElement(s)));
      }
    });
  }

  openNewFolderModal() {
    if (!this.newFolderModal) return;
    this.newFolderModal.classList.remove('hidden');
    if (this.newFolderInput) {
      this.newFolderInput.value = '';
      setTimeout(() => this.newFolderInput?.focus(), 50);
    }
    this.initIcons();
  }

  closeNewFolderModal() {
    this.newFolderModal?.classList.add('hidden');
  }

  async submitNewFolder() {
    const name = this.newFolderInput?.value?.trim();
    if (!name) return;
    try {
      const res = await fetch('/api/folders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
      });
      if (res.ok) {
        await this.loadFolders();
        await this.loadSessions();
        this.closeNewFolderModal();
      }
    } catch (_) {}
  }

  async deleteFolder(folderId) {
    const confirmed = await this.showConfirmModal({
      title: 'Usuń folder',
      message: 'Czy na pewno chcesz usunąć ten folder? Sesje w folderze nie zostaną usunięte.',
      confirmText: 'Usuń folder',
      isDanger: true
    });
    if (!confirmed) return;
    try {
      await fetch(`/api/folders/${folderId}`, { method: 'DELETE' });
      await this.loadFolders();
      await this.loadSessions();
    } catch (_) {}
  }

  async assignSessionToFolder(sessionId, folderId) {
    try {
      await fetch(`/api/sessions/${sessionId}/folder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder: folderId })
      });
      await this.loadSessions();
    } catch (_) {}
  }

  /* ────────────────── FULL-TEXT SEARCH (FTS) ────────────────── */

  async handleSearch(query) {
    const q = query.trim();
    if (!q) {
      this.btnClearSearch?.classList.add('hidden');
      this.renderSessions(this.sessions);
      return;
    }
    this.btnClearSearch?.classList.remove('hidden');
    try {
      const res = await fetch(`/api/sessions/search?q=${encodeURIComponent(q)}`);
      if (res.ok) {
        const results = await res.json();
        const mapped = results.map(s => ({
          id: s.conversation_id,
          title: s.title || `Sesja ${s.conversation_id.slice(0, 8)}`,
          lastMessage: s.match_snippet || s.preview || 'Dopasowanie w treści',
          pinned: Boolean(s.pinned),
          folder: s.folder || '',
          updatedAt: 'Wynik'
        }));
        this.renderSessions(mapped);
      }
    } catch (_) {}
  }

  /* ────────────────── SELECT & LOAD SESSION ────────────────── */

  async selectSession(sessionId) {
    this.activeSessionId = sessionId;
    const session = this.sessions.find(s => s.id === sessionId);
    if (session && this.activeSessionTitle) {
      this.activeSessionTitle.textContent = session.title;
    }
    this.renderSessions(this.sessions);
    await this.loadMessages(sessionId);
    await this.loadArtifacts(sessionId);
    await this.loadChanges(sessionId);
    if (window.innerWidth < 768) {
      this.toggleMobileSidebar(false);
    }
  }

  async createNewSession() {
    const newSessionId = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : 'sess-' + Date.now() + '-' + Math.random().toString(36).substring(2, 9);

    this.activeSessionId = newSessionId;
    this.activeRole = '';
    if (this.bottomRoleSelect) this.bottomRoleSelect.value = '';
    if (this.activeSessionTitle) this.activeSessionTitle.textContent = 'Nowa konwersacja';
    if (this.chatStream) this.chatStream.innerHTML = '';
    this.renderSessions(this.sessions);
    await this.loadArtifacts(newSessionId);
    await this.loadChanges(newSessionId);

    this.renderAssistantTurn({
      thoughtText: 'Gotowy do obsługi nowego zadania. Silnik agy oraz podagenci są aktywni.',
      tools: [],
      markdown: 'Rozpocznij konwersację. Wybierz rolę lub model i wpisz prompt.'
    });
  }

  async loadMessages(sessionId) {
    if (!this.chatStream) return;
    this.chatStream.innerHTML = '';

    try {
      const res = await fetch(`/api/sessions/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        if (data.messages && data.messages.length > 0) {
          for (const msg of data.messages) {
            if (msg.role === 'user') {
              this.renderUserMessage(msg.content, msg.attachments || []);
            } else {
              const rawTools = msg.tool_calls || [];
              const tools = rawTools
                .filter(t => {
                  const name = t.toolSummary || t.name || '';
                  const cmd = t.toolAction || t.name || '';
                  const args = t.args || t.arguments || '';
                  const cmdStr = typeof args === 'string' ? args : (typeof args === 'object' ? (args.cmd || args.command || '') : '');
                  if (cmdStr.includes('agy -p') || cmdStr === 'agy --version' || cmd.includes('agy -p')) return false;
                  if (name === 'Bash Execution' && (cmdStr.includes('agy') || cmd.includes('agy'))) return false;
                  return true;
                })
                .map(t => {
                  const args = t.args || t.arguments;
                  const stdoutText = t.output || (typeof args === 'object' ? JSON.stringify(args, null, 2) : (args || 'ok'));
                  return {
                    name: t.toolSummary || t.name || 'Wywołanie narzędzia',
                    icon: 'terminal',
                    badge: 'completed',
                    command: t.toolAction || t.name || 'run_command',
                    stdout: stdoutText
                  };
                });
              this.renderAssistantTurn({
                thoughtTime: '1.8s',
                thoughtText: msg.thinking || 'Przetwarzanie zapytania i analiza kontekstu.',
                tools: tools,
                markdown: msg.content || ''
              });
            }
          }
          return;
        }
      }
    } catch (_) {}

    // Default welcome
    this.renderAssistantTurn({
      thoughtTime: '0.8s',
      thoughtText: 'Panel Prometeusz połączony z silnikiem agy.',
      tools: [],
      markdown: 'Wpisz dowolne pytanie lub polecenie (np. `ile to 2+2`), aby uruchomić pełne wnioskowanie modelu.'
    });
  }

  /* ────────────────── RENDERING CZATU & KODU ────────────────── */

  parseMarkdown(text) {
    if (!text) return '';
    const raw = marked.parse(text);
    const clean = DOMPurify.sanitize(raw, { FORBID_ATTR: ['id'] });

    // Wrap pre/code blocks with language badge and Copy button
    const parser = new DOMParser();
    const doc = parser.parseFromString(`<div>${clean}</div>`, 'text/html');
    doc.querySelectorAll('pre code').forEach(codeBlock => {
      const pre = codeBlock.parentElement;
      const langClass = Array.from(codeBlock.classList).find(c => c.startsWith('language-'));
      const lang = langClass ? langClass.replace('language-', '') : 'text';

      const wrapper = doc.createElement('div');
      wrapper.className = 'code-block-wrapper';
      wrapper.innerHTML = `
        <div class="code-block-header">
          <span>${lang}</span>
          <button class="code-block-copy-btn">
            <i data-lucide="copy" class="w-3 h-3"></i>
            <span>Kopiuj</span>
          </button>
        </div>
      `;
      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(pre);
    });

    return doc.body.firstElementChild.innerHTML;
  }

  renderUserMessage(text, attachments = []) {
    if (!this.chatStream) return;
    const msg = document.createElement('div');
    msg.className = 'flex justify-end user-bubble';

    let attachmentsHtml = '';
    if (attachments && attachments.length > 0) {
      attachmentsHtml = `
        <div class="flex flex-wrap gap-2 mb-2.5 justify-end">
          ${attachments.map(att => {
            const fileName = att.name || (att.path ? att.path.split('/').pop() : 'Plik');
            const ext = (fileName.includes('.') ? fileName.split('.').pop() : 'FILE').toUpperCase().slice(0, 5);
            const dispName = this.formatAttachmentName ? this.formatAttachmentName(fileName) : fileName;
            return `
              <div class="flex items-center gap-2 px-2.5 py-1 rounded-xl bg-[#2a2b3d] border border-[#3f415c]/60 text-xs shadow-sm" title="${this.escapeHtml(att.path || fileName)}">
                <span class="bg-[#1d1e2c] text-[#7aa2f7] border border-[#3b3e5a] uppercase font-mono text-[9px] font-bold px-1 py-0.5 rounded">${this.escapeHtml(ext)}</span>
                <span class="text-[var(--text-main)] font-medium truncate max-w-[180px]">${this.escapeHtml(dispName)}</span>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    msg.innerHTML = `
      <div class="relative max-w-2xl px-4 py-3 rounded-2xl bg-[var(--bg-card)] border border-[var(--border-color)] text-[var(--text-main)] shadow-lg group">
        ${attachmentsHtml}
        ${text ? `<p class="whitespace-pre-wrap">${this.escapeHtml(text)}</p>` : ''}
        <button class="btn-edit-prompt absolute top-2 right-2 p-1 rounded bg-[var(--bg-base)] text-[var(--text-dim)] hover:text-[var(--accent-blue)] opacity-0 group-hover:opacity-100 transition-opacity" title="Edytuj i ponów">
          <i data-lucide="pencil" class="w-3 h-3"></i>
        </button>
      </div>
    `;

    msg.querySelector('.btn-edit-prompt')?.addEventListener('click', () => {
      if (this.chatInput) {
        this.chatInput.value = text;
        this.chatInput.focus();
      }
    });

    this.chatStream.appendChild(msg);
    this.initIcons();
    this.scrollToBottom();
  }

  renderAssistantTurn(data) {
    if (!this.chatStream) return null;
    const turn = document.createElement('div');
    turn.className = 'assistant-turn flex flex-col space-y-3 max-w-3xl';

    // Thought block
    const thought = document.createElement('div');
    thought.className = `thought-block ${data.thoughtText ? '' : 'hidden'}`;
    thought.innerHTML = `
      <div class="thought-header">
        <div class="flex items-center gap-2">
          <i data-lucide="brain" class="w-3.5 h-3.5 text-[var(--accent-blue)]"></i>
          <span class="thought-title">Thought for ${data.thoughtTime || '1.0s'}</span>
        </div>
        <i data-lucide="chevron-down" class="w-3.5 h-3.5 transition-transform duration-200"></i>
      </div>
      <div class="thought-content hidden">${this.escapeHtml(data.thoughtText || '')}</div>
    `;
    const header = thought.querySelector('.thought-header');
    const content = thought.querySelector('.thought-content');
    const chevron = thought.querySelector('[data-lucide="chevron-down"]');
    header.addEventListener('click', () => {
      content.classList.toggle('hidden');
      chevron.classList.toggle('rotate-180');
    });
    turn.appendChild(thought);

    // Tool cards
    if (data.tools && data.tools.length > 0) {
      data.tools.forEach(tool => {
        const toolName = tool.name || '';
        const toolCmd = tool.command || '';
        if (toolCmd.includes('agy -p') || toolCmd === 'agy --version' || toolCmd.startsWith('agy ')) {
          return;
        }
        if (toolName === 'Bash Execution' && (toolCmd.includes('agy') || !toolCmd)) {
          return;
        }
        const card = document.createElement('div');
        card.className = 'tool-card';
        card.innerHTML = `
          <div class="tool-card-header">
            <div class="flex items-center gap-2">
              <i data-lucide="${tool.icon || 'terminal'}" class="w-3.5 h-3.5 text-[var(--accent-blue)]"></i>
              <span class="font-semibold text-[var(--text-main)]">${this.escapeHtml(tool.name || 'Wywołanie narzędzia')}</span>
              <span class="text-[10px] text-[var(--text-dim)] truncate max-w-xs">${this.escapeHtml(tool.command || '')}</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="px-1.5 py-0.5 rounded text-[10px] bg-[#9ece6a]/10 text-[#9ece6a] border border-[#9ece6a]/20">${this.escapeHtml(tool.badge || 'completed')}</span>
              <button class="btn-copy-out p-1 rounded hover:bg-[var(--bg-base)] text-[var(--text-dim)] hover:text-[var(--text-main)] transition-all" title="Kopiuj stdout">
                <i data-lucide="copy" class="w-3 h-3"></i>
              </button>
            </div>
          </div>
          <div class="tool-stdout-container custom-scroll">
            <pre><code class="language-bash">${this.escapeHtml(tool.stdout || '')}</code></pre>
          </div>
        `;
        const copyBtn = card.querySelector('.btn-copy-out');
        copyBtn?.addEventListener('click', () => {
          navigator.clipboard.writeText(tool.stdout || '');
          copyBtn.innerHTML = '<i data-lucide="check" class="w-3 h-3 text-[#9ece6a]"></i>';
          this.initIcons();
          setTimeout(() => {
            copyBtn.innerHTML = '<i data-lucide="copy" class="w-3 h-3"></i>';
            this.initIcons();
          }, 1500);
        });
        turn.appendChild(card);
      });
    }

    // Markdown container
    const mdEl = document.createElement('div');
    mdEl.className = 'markdown-body px-1';
    if (data.markdown) {
      mdEl.innerHTML = this.parseMarkdown(data.markdown);
    }
    turn.appendChild(mdEl);

    // Attach copy button handlers on generated code blocks
    turn.querySelectorAll('.code-block-copy-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const codeText = btn.closest('.code-block-wrapper').querySelector('pre code').innerText;
        navigator.clipboard.writeText(codeText);
        btn.innerHTML = '<i data-lucide="check" class="w-3 h-3 text-[#9ece6a]"></i> <span>Skopiowano</span>';
        this.initIcons();
        setTimeout(() => {
          btn.innerHTML = '<i data-lucide="copy" class="w-3 h-3"></i> <span>Kopiuj</span>';
          this.initIcons();
        }, 1500);
      });
    });

    this.chatStream.appendChild(turn);
    this.initIcons();
    this.scrollToBottom();

    return { turn, thought, mdEl, content };
  }

  scrollToBottom(force = false) {
    if (!this.chatStream) return;
    if (force || !this.userScrolledUp) {
      this.chatStream.scrollTop = this.chatStream.scrollHeight;
    }
  }

  /* ────────────────── STRUMIENIOWANIE AGY & STOP/ABORT ────────────────── */

  async handleSendMessage() {
    if (!this.chatInput || this.isStreaming) return;
    const text = this.chatInput.value.trim();
    if (!text && this.attachedFiles.length === 0) return;

    const sentAttachments = [...this.attachedFiles];
    this.chatInput.value = '';
    this.chatInput.style.height = 'auto';
    this.renderUserMessage(text, sentAttachments);
    this.clearAttachments();

    // Toggle Send -> Stop/Abort button
    this.setStreamingState(true);
    const taskId = `task-${Date.now()}`;
    this.activeAbortController = new AbortController();

    const turnObj = this.renderAssistantTurn({
      thoughtTime: 'w toku...',
      thoughtText: 'Generowanie wnioskowania w silniku agy...',
      tools: [],
      markdown: ''
    });

    if (turnObj?.thought) {
      turnObj.thought.classList.remove('hidden');
    }

    try {
      const selectedModel = this.bottomModelSelect?.value || 'Gemini 3.8 Flash (High)';
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/x-ndjson, text/event-stream;q=0.9'
        },
        signal: this.activeAbortController.signal,
        body: JSON.stringify({
          prompt: text,
          conversation_id: this.activeSessionId,
          model: selectedModel,
          agent: this.activeRole,
          task_id: taskId,
          attachments: sentAttachments
        })
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let accumulatedMarkdown = '';
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          let raw = line.trim();
          if (!raw) continue;
          if (raw.startsWith('data:')) {
            raw = raw.slice(5).trim();
          }
          if (!raw || raw === '[DONE]') continue;
          try {
            const data = JSON.parse(raw);
            if (data.type === 'init' && data.conversation_id) {
              this.activeSessionId = data.conversation_id;
            } else if (data.type === 'thought') {
              if (turnObj?.content) turnObj.content.textContent = data.text;
              if (turnObj?.thought) turnObj.thought.classList.remove('hidden');
            } else if (data.type === 'tool_update') {
              if (data.tool_name === 'Bash Execution' || (data.tool_name && data.tool_name.startsWith('agy'))) {
                continue;
              }
              const toolCard = turnObj?.turn?.querySelector('.tool-card');
              if (toolCard) {
                const nameEl = toolCard.querySelector('.tool-card-header span.font-semibold');
                if (nameEl && data.tool_name) nameEl.textContent = data.tool_name;
                const badgeEl = toolCard.querySelector('.tool-card-header span[class*="rounded"]');
                if (badgeEl) {
                  const state = data.state || 'running';
                  badgeEl.textContent = state;
                  if (state === 'DONE' || state === 'ready') {
                    badgeEl.className = 'px-1.5 py-0.5 rounded text-[10px] bg-[#9ece6a]/10 text-[#9ece6a] border border-[#9ece6a]/20';
                  } else {
                    badgeEl.className = 'px-1.5 py-0.5 rounded text-[10px] bg-[#7aa2f7]/10 text-[#7aa2f7] border border-[#7aa2f7]/20';
                  }
                }
                if (data.tool_info?.output) {
                  const codeEl = toolCard.querySelector('.tool-stdout-container pre code');
                  if (codeEl) codeEl.textContent = data.tool_info.output;
                }
              }
            } else if (data.type === 'text_delta') {
              accumulatedMarkdown += data.delta;
              if (turnObj?.mdEl) {
                turnObj.mdEl.innerHTML = this.parseMarkdown(accumulatedMarkdown);
              }
              this.scrollToBottom();
            } else if (data.type === 'done') {
              const finalResp = data.response || accumulatedMarkdown;
              if (turnObj?.mdEl && finalResp) {
                turnObj.mdEl.innerHTML = this.parseMarkdown(finalResp);
              }
              const thoughtTitle = turnObj?.thought?.querySelector('.thought-title');
              if (thoughtTitle && data.duration) {
                thoughtTitle.textContent = `Thought for ${Number(data.duration).toFixed(1)}s`;
              }
              const badges = turnObj?.turn?.querySelectorAll('.tool-card span');
              badges?.forEach(b => {
                if (b.textContent === 'running' || b.textContent === 'ACTIVE') {
                  b.textContent = 'ready';
                  b.className = 'px-1.5 py-0.5 rounded text-[10px] bg-[#9ece6a]/10 text-[#9ece6a] border border-[#9ece6a]/20';
                }
              });
              await this.loadSessions();
              this.notifyCompletion(finalResp || 'Zadanie ukończone.');
            } else if (data.type === 'error') {
              if (turnObj?.mdEl) {
                turnObj.mdEl.innerHTML = `<span class="text-[#f7768e] font-mono">Błąd: ${this.escapeHtml(data.message)}</span>`;
              }
              const badges = turnObj?.turn?.querySelectorAll('.tool-card span');
              badges?.forEach(b => {
                if (b.textContent === 'running' || b.textContent === 'ACTIVE') {
                  b.textContent = 'error';
                  b.className = 'px-1.5 py-0.5 rounded text-[10px] bg-[#f7768e]/10 text-[#f7768e] border border-[#f7768e]/20';
                }
              });
            }
          } catch (_) {}
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        if (turnObj?.mdEl) {
          turnObj.mdEl.innerHTML += `\n\n<span class="text-[#f7768e] font-mono text-xs">⏹ Przerwano przez użytkownika.</span>`;
        }
      } else if (turnObj?.mdEl) {
        turnObj.mdEl.innerHTML = `<span class="text-[#f7768e] font-mono">Błąd połączenia z agy: ${this.escapeHtml(e.message)}</span>`;
      }
    } finally {
      const badges = turnObj?.turn?.querySelectorAll('.tool-card span');
      badges?.forEach(b => {
        if (b.textContent === 'running') {
          b.textContent = 'ready';
          b.className = 'px-1.5 py-0.5 rounded text-[10px] bg-[#9ece6a]/10 text-[#9ece6a] border border-[#9ece6a]/20';
        }
      });
      this.setStreamingState(false);
      this.scrollToBottom(true);
    }
  }

  async handleAbortMessage() {
    if (this.activeAbortController) {
      this.activeAbortController.abort();
    }
    try {
      await fetch('/api/chat/abort', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: this.activeSessionId })
      });
    } catch (_) {}
    this.setStreamingState(false);
  }

  setStreamingState(isStreaming) {
    this.isStreaming = isStreaming;
    if (isStreaming) {
      this.btnSend?.classList.add('hidden');
      this.btnAbort?.classList.remove('hidden');
    } else {
      this.btnAbort?.classList.add('hidden');
      this.btnSend?.classList.remove('hidden');
    }
  }

  /* ────────────────── GEMINI-STYLE ATTACHMENTS ────────────────── */

  formatAttachmentName(name) {
    if (!name) return '';
    if (name.length > 16) {
      return name.slice(0, 14) + '...';
    }
    return name;
  }

  addAttachment(fileObj) {
    if (!fileObj || !fileObj.name) return;
    const exists = this.attachedFiles.some(f => (f.path && fileObj.path && f.path === fileObj.path) || f.name === fileObj.name);
    if (!exists) {
      this.attachedFiles.push(fileObj);
      this.renderAttachments();
    }
  }

  removeAttachment(index) {
    if (index >= 0 && index < this.attachedFiles.length) {
      this.attachedFiles.splice(index, 1);
      this.renderAttachments();
    }
  }

  clearAttachments() {
    this.attachedFiles = [];
    this.renderAttachments();
  }

  renderAttachments() {
    if (!this.promptAttachmentsBar) return;
    if (this.attachedFiles.length === 0) {
      this.promptAttachmentsBar.classList.add('hidden');
      this.promptAttachmentsBar.innerHTML = '';
      return;
    }

    this.promptAttachmentsBar.classList.remove('hidden');
    this.promptAttachmentsBar.innerHTML = '';

    this.attachedFiles.forEach((file, index) => {
      const ext = (file.name && file.name.includes('.') ? file.name.split('.').pop() : 'FILE').toUpperCase().slice(0, 5);
      const dispName = this.formatAttachmentName(file.name);
      const card = document.createElement('div');
      card.className = 'w-32 h-[72px] flex-shrink-0 p-2.5 rounded-xl bg-[#2a2b3d] border border-[#3f415c]/60 flex flex-col justify-between shadow-sm relative group hover:border-[#5a5e80] transition-colors';
      card.innerHTML = `
        <div class="flex items-center justify-between">
          <span class="bg-[#1d1e2c] text-[#7aa2f7] border border-[#3b3e5a] uppercase font-mono text-[10px] font-bold px-1.5 py-0.5 rounded select-none">${this.escapeHtml(ext)}</span>
          <button type="button" class="btn-remove-attachment w-5 h-5 rounded-full bg-[#1d1e2c]/80 hover:bg-[#434768] text-[var(--text-dim)] hover:text-white flex items-center justify-center transition-colors cursor-pointer" title="Odłącz plik" data-index="${index}">
            <i data-lucide="x" class="w-3 h-3"></i>
          </button>
        </div>
        <div class="truncate text-xs font-medium text-[var(--text-main)] select-none" title="${this.escapeHtml(file.name)}">
          ${this.escapeHtml(dispName)}
        </div>
      `;

      card.querySelector('.btn-remove-attachment')?.addEventListener('click', (e) => {
        e.stopPropagation();
        this.removeAttachment(index);
      });

      this.promptAttachmentsBar.appendChild(card);
    });

    this.initIcons();
  }

  /* ────────────────── DRAG & DROP & UPLOAD ────────────────── */

  setupDragAndDrop() {
    const dropzone = this.chatDropzone;
    if (!dropzone) return;

    ['dragenter', 'dragover'].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        dropzone.classList.add('drag-over-active');
      });
    });

    ['dragleave', 'drop'].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        dropzone.classList.remove('drag-over-active');
      });
    });

    dropzone.addEventListener('drop', (e) => {
      const files = e.dataTransfer.files;
      if (files && files.length > 0) {
        this.uploadFiles(files);
      }
    });
  }

  handleFileSelect(e) {
    const files = e.target.files;
    if (files && files.length > 0) {
      this.uploadFiles(files);
    }
  }

  async uploadFiles(files) {
    for (const file of files) {
      try {
        const res = await fetch('/api/upload', {
          method: 'POST',
          headers: {
            'X-Filename': file.name,
            'Content-Type': file.type || 'application/octet-stream'
          },
          body: file
        });
        if (res.ok) {
          const data = await res.json();
          this.addAttachment({
            name: data.filename || file.name,
            path: data.path,
            size: data.size,
            type: file.type
          });
          await this.loadUploads();
        }
      } catch (_) {}
    }
  }

  async loadUploads() {
    const listEl = document.getElementById('uploads-list');
    if (!listEl) return;
    listEl.innerHTML = '';

    try {
      const res = await fetch('/api/uploads');
      if (!res.ok) throw new Error();
      const files = await res.json();

      if (files.length === 0) {
        listEl.innerHTML = '<p class="text-xs font-mono text-[var(--text-dim)] p-2">Brak wgranych plików.</p>';
        return;
      }

      files.forEach(f => {
        const item = document.createElement('div');
        item.className = 'flex items-center justify-between p-2 rounded-lg bg-[var(--bg-card)] border border-[var(--border-color)] text-xs font-mono';
        item.innerHTML = `
          <div class="flex items-center gap-2 min-w-0 flex-1">
            <i data-lucide="file" class="w-3.5 h-3.5 text-[var(--accent-blue)] flex-shrink-0"></i>
            <span class="truncate text-[var(--text-main)]">${this.escapeHtml(f.filename)}</span>
            <span class="text-[10px] text-[var(--text-dim)]">${(f.size / 1024).toFixed(1)} KB</span>
          </div>
          <div class="flex items-center gap-1">
            <button class="btn-insert-upload p-1 rounded hover:bg-[var(--border-color)] text-[var(--text-dim)] hover:text-[var(--accent-blue)]" title="Wstaw do promptu">
              <i data-lucide="link" class="w-3 h-3"></i>
            </button>
            <button class="btn-delete-upload p-1 rounded hover:bg-[var(--border-color)] text-[var(--text-dim)] hover:text-[#f7768e]" title="Usuń plik">
              <i data-lucide="trash-2" class="w-3 h-3"></i>
            </button>
          </div>
        `;
        item.querySelector('.btn-insert-upload')?.addEventListener('click', () => {
          this.addAttachment({
            name: f.filename,
            path: f.path,
            size: f.size
          });
        });
        item.querySelector('.btn-delete-upload')?.addEventListener('click', async () => {
          const confirmed = await this.showConfirmModal({
            title: 'Usuń plik',
            message: `Czy na pewno chcesz usunąć ${f.filename}?`,
            confirmText: 'Usuń',
            isDanger: true
          });
          if (confirmed) {
            await fetch(`/api/uploads/${f.filename}`, { method: 'DELETE' });
            await this.loadUploads();
          }
        });
        listEl.appendChild(item);
      });
      this.initIcons();
    } catch (_) {}
  }

  /* ────────────────── PRZEGLĄDARKA PLIKÓW NA MASZYNIE (FILES) ────────────────── */

  async loadFs(dirPath) {
    this.currentFsPath = dirPath || '/workspace';
    const pathEl = document.getElementById('fs-current-path');
    const listEl = document.getElementById('fs-file-list');
    if (pathEl) pathEl.textContent = this.currentFsPath;
    if (!listEl) return;
    listEl.innerHTML = '';

    try {
      const res = await fetch(`/api/fs/list?path=${encodeURIComponent(this.currentFsPath)}`);
      if (!res.ok) throw new Error();
      const data = await res.json();

      data.items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'flex items-center justify-between p-2 rounded-lg hover:bg-[var(--bg-card)] cursor-pointer text-xs font-mono transition-all';
        row.innerHTML = `
          <div class="flex items-center gap-2 min-w-0 flex-1">
            <i data-lucide="${item.is_dir ? 'folder' : 'file-code'}" class="w-3.5 h-3.5 ${item.is_dir ? 'text-[var(--accent-blue)]' : 'text-[var(--text-dim)]'} flex-shrink-0"></i>
            <span class="truncate text-[var(--text-main)]">${this.escapeHtml(item.name)}</span>
          </div>
          ${item.size ? `<span class="text-[10px] text-[var(--text-dim)]">${(item.size / 1024).toFixed(1)} KB</span>` : ''}
        `;
        row.addEventListener('click', () => {
          if (item.is_dir) {
            this.loadFs(item.path);
          } else {
            this.previewFsFile(item.path);
          }
        });
        listEl.appendChild(row);
      });
      this.initIcons();
    } catch (_) {}
  }

  navigateFsParent() {
    if (this.currentFsPath === '/' || this.currentFsPath === '') return;
    const parts = this.currentFsPath.split('/').filter(Boolean);
    parts.pop();
    const parent = '/' + parts.join('/');
    this.loadFs(parent || '/');
  }

  async previewFsFile(filePath) {
    const panel = document.getElementById('fs-preview-panel');
    const nameEl = document.getElementById('fs-preview-name');
    const codeEl = document.getElementById('fs-preview-content');
    if (!panel || !nameEl || !codeEl) return;

    try {
      const res = await fetch(`/api/fs/read?path=${encodeURIComponent(filePath)}`);
      if (res.ok) {
        const data = await res.json();
        nameEl.textContent = data.filename;
        nameEl.setAttribute('data-full-path', data.path);
        codeEl.textContent = data.content;
        panel.classList.remove('hidden');
      }
    } catch (_) {}
  }

  /* ────────────────── ZAKŁADKA CHANGES & DIFF MODE ────────────────── */

  async loadChanges(sessionId) {
    const listEl = document.getElementById('changes-list');
    const badge = document.getElementById('changes-count-badge');
    if (!listEl) return;
    listEl.innerHTML = '';

    if (!sessionId) {
      if (badge) badge.textContent = '0 zmian';
      return;
    }

    try {
      const res = await fetch(`/api/sessions/${sessionId}/changes`);
      if (!res.ok) throw new Error();
      const changes = await res.json();
      if (badge) badge.textContent = `${changes.length} zmian`;

      if (changes.length === 0) {
        listEl.innerHTML = '<p class="text-xs font-mono text-[var(--text-dim)] p-2">Brak zmodyfikowanych plików w tej sesji.</p>';
        return;
      }

      changes.forEach(c => {
        const item = document.createElement('div');
        item.className = 'flex items-center justify-between p-2 rounded-lg bg-[var(--bg-card)] border border-[var(--border-color)] text-xs font-mono cursor-pointer hover:border-[var(--accent-blue)]';
        item.innerHTML = `
          <div class="flex items-center gap-2 min-w-0 flex-1">
            <i data-lucide="file-diff" class="w-3.5 h-3.5 text-[var(--accent-green)] flex-shrink-0"></i>
            <span class="truncate text-[var(--text-main)]">${this.escapeHtml(c.filename)}</span>
          </div>
          <span class="text-[10px] text-[var(--text-dim)]">${c.lines_count} linii</span>
        `;
        item.addEventListener('click', () => this.viewDiff(sessionId, c.path));
        listEl.appendChild(item);
      });
      this.initIcons();
    } catch (_) {}
  }

  async viewDiff(sessionId, filePath) {
    const viewer = document.getElementById('diff-viewer');
    const nameEl = document.getElementById('diff-viewer-filename');
    const bodyEl = document.getElementById('diff-viewer-body');
    if (!viewer || !nameEl || !bodyEl) return;

    try {
      const res = await fetch(`/api/sessions/${sessionId}/changes/diff?file=${encodeURIComponent(filePath)}`);
      if (res.ok) {
        const data = await res.json();
        nameEl.textContent = data.filename;
        bodyEl.innerHTML = '';

        if (this.currentDiffMode === 'inline') {
          data.lines.forEach(l => {
            const div = document.createElement('div');
            div.className = 'diff-line flex';
            div.innerHTML = `<span class="w-8 text-[var(--text-dim)] select-none">${l.num}</span><span>${this.escapeHtml(l.text)}</span>`;
            bodyEl.appendChild(div);
          });
        } else {
          // Side-by-side
          const container = document.createElement('div');
          container.className = 'diff-container flex gap-2';
          const leftCol = document.createElement('div');
          leftCol.className = 'diff-col flex-1';
          const rightCol = document.createElement('div');
          rightCol.className = 'diff-col flex-1';

          data.lines.forEach(l => {
            const leftLine = document.createElement('div');
            leftLine.className = 'diff-line';
            leftLine.textContent = l.text;
            leftCol.appendChild(leftLine);

            const rightLine = document.createElement('div');
            rightLine.className = 'diff-line';
            rightLine.textContent = l.text;
            rightCol.appendChild(rightLine);
          });
          container.appendChild(leftCol);
          container.appendChild(rightCol);
          bodyEl.appendChild(container);
        }
        viewer.classList.remove('hidden');
      }
    } catch (_) {}
  }

  setDiffMode(mode) {
    this.currentDiffMode = mode;
    const btnInline = document.getElementById('btn-diff-inline');
    const btnSide = document.getElementById('btn-diff-side');
    if (mode === 'inline') {
      btnInline?.classList.add('bg-[var(--bg-card)]', 'text-[var(--accent-blue)]');
      btnSide?.classList.remove('bg-[var(--bg-card)]', 'text-[var(--accent-blue)]');
    } else {
      btnSide?.classList.add('bg-[var(--bg-card)]', 'text-[var(--accent-blue)]');
      btnInline?.classList.remove('bg-[var(--bg-card)]', 'text-[var(--accent-blue)]');
    }
  }

  /* ────────────────── ARTIFACTS Z CZYTELNYM PODGLĄDEM I MARKDOWN ────────────────── */

  async loadArtifacts(sessionId) {
    const listEl = document.getElementById('artifacts-list');
    const containerEl = document.getElementById('artifacts-list-container');
    const viewerEl = document.getElementById('artifact-viewer');
    if (!listEl) return;
    listEl.innerHTML = '';
    containerEl?.classList.remove('hidden');
    viewerEl?.classList.add('hidden');
    if (!sessionId) return;

    try {
      const res = await fetch(`/api/sessions/${sessionId}/artifacts`);
      if (!res.ok) throw new Error();
      const artifacts = await res.json();

      if (artifacts.length === 0) {
        listEl.innerHTML = '<p class="text-xs font-mono text-[var(--text-dim)] p-3 text-center">Brak wygenerowanych artefaktów w tej sesji.</p>';
        return;
      }

      artifacts.forEach(art => {
        const item = document.createElement('div');
        item.className = 'flex items-center justify-between p-2.5 rounded-lg bg-[var(--bg-card)] border border-[var(--border-color)] text-xs font-mono cursor-pointer hover:border-[var(--accent-blue)] transition-all group';
        const isMd = art.name.toLowerCase().endsWith('.md');
        const isHtml = art.name.toLowerCase().endsWith('.html') || art.name.toLowerCase().endsWith('.htm') || art.name.toLowerCase().endsWith('.svg');
        const iconName = isHtml ? 'layout' : (isMd ? 'file-text' : 'file-code');
        
        item.innerHTML = `
          <div class="flex items-center gap-2.5 min-w-0 flex-1">
            <div class="p-1 rounded bg-[var(--bg-base)] text-[var(--accent-blue)] flex-shrink-0">
              <i data-lucide="${iconName}" class="w-3.5 h-3.5"></i>
            </div>
            <div class="flex flex-col min-w-0 flex-1">
              <span class="truncate font-medium text-[var(--text-main)] group-hover:text-[var(--accent-blue)] transition-colors">${this.escapeHtml(art.name)}</span>
              <span class="text-[10px] text-[var(--text-dim)] font-mono">${(art.size / 1024).toFixed(1)} KB</span>
            </div>
          </div>
          <button class="p-1 text-[var(--text-dim)] group-hover:text-[var(--accent-blue)] transition-colors" title="Otwórz podgląd">
            <i data-lucide="chevron-right" class="w-4 h-4"></i>
          </button>
        `;
        item.addEventListener('click', () => this.viewArtifact(sessionId, art.name, art.is_live_render));
        listEl.appendChild(item);
      });
      this.initIcons();
    } catch (_) {}
  }

  async viewArtifact(sessionId, filename, isLive) {
    const listContainer = document.getElementById('artifacts-list-container');
    const viewer = document.getElementById('artifact-viewer');
    const nameEl = document.getElementById('artifact-viewer-filename');
    const mdEl = document.getElementById('artifact-markdown-preview');
    const iframe = document.getElementById('artifact-iframe-preview');
    const codeEl = document.getElementById('artifact-viewer-code-container');
    if (!viewer || !nameEl) return;

    try {
      const res = await fetch(`/api/sessions/${sessionId}/artifacts/${filename}`);
      if (res.ok) {
        const text = await res.text();
        this.currentArtifactText = text;
        this.currentArtifactName = filename;
        nameEl.textContent = filename;

        const isMd = filename.toLowerCase().endsWith('.md');
        const isHtml = filename.toLowerCase().endsWith('.html') || filename.toLowerCase().endsWith('.htm') || filename.toLowerCase().endsWith('.svg');

        // Kod źródłowy
        if (codeEl) {
          codeEl.innerHTML = `<pre class="font-mono text-xs p-3 rounded-lg bg-[var(--bg-panel)] border border-[var(--border-color)] overflow-x-auto whitespace-pre leading-relaxed text-[var(--text-main)]"><code>${this.escapeHtml(text)}</code></pre>`;
        }

        // Podgląd Markdown / Tekst
        if (mdEl) {
          if (isMd) {
            mdEl.innerHTML = DOMPurify.sanitize(marked.parse(text));
          } else {
            mdEl.innerHTML = `<pre class="font-mono text-xs whitespace-pre-wrap">${this.escapeHtml(text)}</pre>`;
          }
        }

        // Podgląd iframe dla HTML/SVG
        if (iframe && isHtml) {
          iframe.srcdoc = text;
        }

        listContainer?.classList.add('hidden');
        viewer.classList.remove('hidden');

        // Domyślny tryb: podgląd dla md i html, kod dla pozostałych
        const defaultMode = (isMd || isHtml || isLive) ? 'preview' : 'code';
        this.toggleArtifactView(defaultMode);
        this.initIcons();
      }
    } catch (_) {}
  }

  toggleArtifactView(mode) {
    const mdEl = document.getElementById('artifact-markdown-preview');
    const iframe = document.getElementById('artifact-iframe-preview');
    const codeEl = document.getElementById('artifact-viewer-code-container');
    const btnCode = document.getElementById('btn-artifact-view-code');
    const btnPreview = document.getElementById('btn-artifact-view-preview');

    const isHtml = (this.currentArtifactName || '').toLowerCase().endsWith('.html') ||
                   (this.currentArtifactName || '').toLowerCase().endsWith('.htm') ||
                   (this.currentArtifactName || '').toLowerCase().endsWith('.svg');

    if (mode === 'preview') {
      codeEl?.classList.add('hidden');
      if (isHtml) {
        mdEl?.classList.add('hidden');
        iframe?.classList.remove('hidden');
      } else {
        iframe?.classList.add('hidden');
        mdEl?.classList.remove('hidden');
      }
      btnPreview?.classList.add('bg-[var(--bg-card)]', 'text-[var(--accent-blue)]');
      btnCode?.classList.remove('bg-[var(--bg-card)]', 'text-[var(--accent-blue)]');
    } else {
      mdEl?.classList.add('hidden');
      iframe?.classList.add('hidden');
      codeEl?.classList.remove('hidden');
      btnCode?.classList.add('bg-[var(--bg-card)]', 'text-[var(--accent-blue)]');
      btnPreview?.classList.remove('bg-[var(--bg-card)]', 'text-[var(--accent-blue)]');
    }
  }

  copyArtifactContent() {
    if (!this.currentArtifactText) return;
    navigator.clipboard.writeText(this.currentArtifactText).then(() => {
      const btn = document.getElementById('btn-copy-artifact');
      if (btn) {
        btn.innerHTML = '<i data-lucide="check" class="w-3.5 h-3.5 text-[#9ece6a]"></i>';
        this.initIcons();
        setTimeout(() => {
          btn.innerHTML = '<i data-lucide="copy" class="w-3.5 h-3.5"></i>';
          this.initIcons();
        }, 1500);
      }
    });
  }

  /* ────────────────── TERMINAL (xterm.js) ────────────────── */

  initTerminal() {
    const container = document.getElementById('xterm-container');
    if (!container) return;

    this.terminal = new Terminal({
      theme: {
        background: '#121217',
        foreground: '#c0caf5',
        cursor: '#7aa2f7',
        black: '#15161e',
        red: '#f7768e',
        green: '#9ece6a',
        yellow: '#e0af68',
        blue: '#7aa2f7',
        magenta: '#bb9af7',
        cyan: '#7dcfff',
        white: '#a9b1d6',
      },
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: 12,
      lineHeight: 1.2,
      cursorBlink: true,
    });

    this.fitAddon = new FitAddon();
    this.terminal.loadAddon(this.fitAddon);
    this.terminal.open(container);
    this.fitAddon.fit();

    window.addEventListener('resize', () => this.fitAddon?.fit());
    document.getElementById('btn-terminal-clear')?.addEventListener('click', () => this.terminal?.clear());
    document.getElementById('btn-terminal-reconnect')?.addEventListener('click', () => this.connectPty());
    this.connectPty();
  }

  connectPty() {
    const dot = document.getElementById('pty-status-dot');
    const text = document.getElementById('pty-status-text');
    if (this.ptySocket) {
      try { this.ptySocket.close(); } catch (_) {}
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/pty`;

    this.terminal?.writeln('\x1b[34m[Prometeusz PTY]\x1b[0m Łączenie z /ws/pty...');

    try {
      this.ptySocket = new WebSocket(wsUrl);

      this.ptySocket.onopen = () => {
        if (dot) dot.className = 'w-2 h-2 rounded-full bg-[#9ece6a]';
        if (text) text.textContent = '/ws/pty online';
        this.terminal?.writeln('\x1b[32m[Prometeusz PTY]\x1b[0m Połączono z konsolą silnika agy.\r\n');
        if (this.terminal) {
          this.ptySocket.send(JSON.stringify({
            type: 'resize',
            rows: this.terminal.rows || 24,
            cols: this.terminal.cols || 80
          }));
        }
      };

      this.ptySocket.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          if (parsed.type === 'stdout' && parsed.data) {
            this.terminal?.write(parsed.data);
          }
        } catch (_) {
          this.terminal?.write(event.data);
        }
      };

      this.ptySocket.onclose = () => {
        if (dot) dot.className = 'w-2 h-2 rounded-full bg-[#ff9e64]';
        if (text) text.textContent = 'Rozłączono';
      };

      this.terminal?.onData((data) => {
        if (this.ptySocket && this.ptySocket.readyState === WebSocket.OPEN) {
          this.ptySocket.send(JSON.stringify({ type: 'stdin', data }));
        }
      });
    } catch {
      this.terminal?.writeln('\x1b[31m[Prometeusz PTY]\x1b[0m Błąd połączenia.');
    }
  }

  /* ────────────────── METRYKI & PANIC ────────────────── */

  startSessionsPoller() {
    this.sessionsInterval = setInterval(() => {
      if (!this.sessionSearchInput || !this.sessionSearchInput.value.trim()) {
        this.loadSessions();
      }
    }, 2000);
  }

  startMetricsPoller() {
    this.pollMetrics();
    this.metricsInterval = setInterval(() => this.pollMetrics(), 3000);
  }

  async pollMetrics() {
    try {
      const res = await fetch('/api/metrics');
      if (!res.ok) return;
      const data = await res.json();
      const cpuVal = document.getElementById('cpu-value');
      const cpuBar = document.getElementById('cpu-bar');
      const ramVal = document.getElementById('ram-value');
      const ramBar = document.getElementById('ram-bar');
      const diskVal = document.getElementById('disk-value');
      const diskBar = document.getElementById('disk-bar');

      const rawUsed = data.ram_used_gb ?? data.memory_used_gb ?? (data.memory_used ? (data.memory_used / (1024**3)) : 0);
      const rawTotal = data.ram_total_gb ?? data.memory_total_gb ?? (data.memory_total ? (data.memory_total / (1024**3)) : 0);
      const usedGb = Number(rawUsed).toFixed(1);
      const totalGb = Number(rawTotal).toFixed(1);
      if (cpuVal) cpuVal.textContent = `${data.cpu_percent}%`;
      if (cpuBar) cpuBar.style.width = `${Math.max(data.cpu_percent, 2)}%`;
      if (ramVal) ramVal.textContent = `${usedGb} / ${totalGb} GB`;
      if (ramBar) ramBar.style.width = `${Math.max(data.memory_percent, 2)}%`;
      if (diskVal) diskVal.textContent = `${data.disk_percent}%`;
      if (diskBar) diskBar.style.width = `${Math.max(data.disk_percent, 2)}%`;
    } catch (_) {}
  }

  async triggerPanic() {
    const confirmed = await this.showConfirmModal({
      title: 'Panic — Zabij procesy',
      message: 'Czy na pewno chcesz natychmiast ubić wszystkie wiszące procesy w piaskownicy?',
      confirmText: 'Zabij procesy',
      isDanger: true
    });
    if (!confirmed) return;
    try {
      const res = await fetch('/api/panic', { method: 'POST' });
      const data = await res.json();
      await this.showConfirmModal({
        title: 'Sukces Panic',
        message: `Zabito ${data.processes_killed ?? 0} procesów.`,
        confirmText: 'OK',
        isDanger: false
      });
      this.connectPty();
    } catch (_) {}
  }

  /* ────────────────── AGENCI, MODELE & EKSPORT ────────────────── */

  async loadAgents() {
    try {
      const res = await fetch('/api/agents');
      if (res.ok) {
        const agents = await res.json();
        if (this.bottomRoleSelect && Array.isArray(agents)) {
          const currentVal = this.bottomRoleSelect.value || '';
          this.bottomRoleSelect.innerHTML = `
            <option value="" class="bg-[#1f2335] text-[#c0caf5]" ${!currentVal ? 'selected' : ''}>Domyślna</option>
            ${agents.map(a => {
              const val = a.id || a.name;
              const label = `@${a.name || a.id}`;
              const isSelected = currentVal === val || currentVal === label;
              const title = a.description ? this.escapeHtml(a.description) : '';
              return `<option value="${val}" class="bg-[#1f2335] text-[#c0caf5]" ${isSelected ? 'selected' : ''} title="${title}">${label}</option>`;
            }).join('')}
          `;
        }
      }
    } catch (_) {}
  }

  async loadModels() {
    try {
      const res = await fetch('/api/models');
      if (res.ok) {
        const data = await res.json();
        if (this.bottomModelSelect && data.available_models) {
          this.bottomModelSelect.innerHTML = data.available_models.map(m =>
            `<option value="${m}" class="bg-[#1f2335] text-[#c0caf5]" ${m === data.active_model ? 'selected' : ''}>${m}</option>`
          ).join('');
        }
        if (this.activeModelBadge && data.active_model) {
          this.activeModelBadge.textContent = data.active_model;
        }
      }
    } catch (_) {}
  }

  async selectModel(modelName) {
    try {
      await fetch('/api/models/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelName })
      });
      if (this.activeModelBadge) this.activeModelBadge.textContent = modelName;
    } catch (_) {}
  }

  async promptExport() {
    if (!this.activeSessionId) return;
    const isMd = await this.showConfirmModal({
      title: 'Eksport rozmowy',
      message: 'Wybierz format eksportu sesji: Kliknij Markdown, lub Anuluj aby pobrać JSON.',
      confirmText: 'Pobierz Markdown (.md)',
      isDanger: false
    });
    const format = isMd ? 'markdown' : 'json';
    window.open(`/api/sessions/${this.activeSessionId}/export?format=${format}`, '_blank');
  }

  async exportMarkdownDirect() {
    if (!this.activeSessionId) {
      await this.showConfirmModal({
        title: 'Brak aktywnej sesji',
        message: 'Wybierz lub rozpocznij konwersację przed eksportem.',
        confirmText: 'OK',
        isDanger: false
      });
      return;
    }
    const a = document.createElement('a');
    a.href = `/api/sessions/${this.activeSessionId}/export?format=markdown`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  /* ────────────────── POMOCNICZE / MODALE / NOTYFIKACJE ────────────────── */

  toggleMobileSidebar(show) {
    if (show) {
      this.sidebarLeft?.classList.remove('-translate-x-full');
      this.mobileBackdrop?.classList.remove('hidden');
    } else {
      this.sidebarLeft?.classList.add('-translate-x-full');
      this.mobileBackdrop?.classList.add('hidden');
    }
  }

  toggleAuxiliaryPanel(forceState) {
    if (!this.sidebarRight) return;
    const isHidden = this.sidebarRight.classList.contains('hidden');
    const newState = forceState !== undefined ? forceState : isHidden;
    if (newState) {
      this.sidebarRight.classList.remove('hidden');
      this.resizerRight?.classList.remove('hidden');
      this.fitAddon?.fit();
    } else {
      this.sidebarRight.classList.add('hidden');
      this.resizerRight?.classList.add('hidden');
    }
  }

  switchAuxiliaryTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tabName);
    });
    document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
    document.getElementById(`tab-content-${tabName}`)?.classList.remove('hidden');

    if (tabName === 'terminal') {
      setTimeout(() => this.fitAddon?.fit(), 50);
    } else if (tabName === 'artifacts') {
      this.loadArtifacts(this.activeSessionId);
    } else if (tabName === 'changes') {
      this.loadChanges(this.activeSessionId);
    }
  }

  openSettings() {
    this.settingsModal?.classList.remove('hidden');
    this.loadSettingsJson();
    this.loadSkills();
    this.loadConversationsManagement();
    this.initIcons();
  }

  closeSettings() {
    this.settingsModal?.classList.add('hidden');
  }

  switchSettingsTab(tabName) {
    document.querySelectorAll('.settings-tab-btn').forEach(b => {
      const isActive = b.getAttribute('data-settings-tab') === tabName;
      b.classList.toggle('active', isActive);
      if (isActive) {
        b.classList.add('border-[var(--accent-blue)]', 'text-[var(--accent-blue)]');
        b.classList.remove('border-transparent', 'text-[var(--text-dim)]');
      } else {
        b.classList.remove('border-[var(--accent-blue)]', 'text-[var(--accent-blue)]');
        b.classList.add('border-transparent', 'text-[var(--text-dim)]');
      }
    });
    document.querySelectorAll('.settings-tab-content').forEach(c => c.classList.add('hidden'));
    document.getElementById(`settings-tab-${tabName}`)?.classList.remove('hidden');

    if (tabName === 'conversations') {
      this.loadConversationsManagement();
    }
    this.initIcons();
  }

  async loadSettingsJson() {
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        const editor = document.getElementById('settings-json-editor');
        if (editor) editor.value = JSON.stringify(data, null, 2);
      }
    } catch (_) {}
  }

  async saveSettingsJson() {
    const editor = document.getElementById('settings-json-editor');
    if (!editor) return;
    try {
      const parsed = JSON.parse(editor.value);
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsed)
      });
      if (res.ok) {
        const status = document.getElementById('settings-save-status');
        if (status) {
          status.classList.remove('hidden');
          setTimeout(() => status.classList.add('hidden'), 2000);
        }
      }
    } catch (e) {
      alert(`Błąd JSON: ${e.message}`);
    }
  }

  formatSettingsJson() {
    const editor = document.getElementById('settings-json-editor');
    if (editor) {
      try {
        editor.value = JSON.stringify(JSON.parse(editor.value), null, 2);
      } catch (_) {}
    }
  }

  async loadSkills() {
    const grid = document.getElementById('skills-grid');
    if (!grid) return;
    grid.innerHTML = '';
    try {
      const res = await fetch('/api/skills');
      if (res.ok) {
        const skills = await res.json();
        skills.forEach(s => {
          const card = document.createElement('div');
          card.className = 'p-3 rounded-xl bg-[var(--bg-base)] border border-[var(--border-color)] text-xs font-mono space-y-1';
          card.innerHTML = `
            <div class="font-bold text-[var(--accent-blue)]">${this.escapeHtml(s.name)}</div>
            <p class="text-[10px] text-[var(--text-dim)]">${this.escapeHtml(s.description || 'Brak opisu')}</p>
          `;
          grid.appendChild(card);
        });
      }
    } catch (_) {}
  }

  /* ────────────────── ZARZĄDZANIE ROZMOWAMI (SETTINGS) ────────────────── */

  async loadConversationsManagement() {
    const listContainer = document.getElementById('conversations-mgmt-list');
    const countBadge = document.getElementById('conversations-mgmt-count');
    if (!listContainer) return;

    listContainer.innerHTML = `
      <div class="py-12 flex flex-col items-center justify-center gap-2 text-xs text-[var(--text-dim)] font-mono">
        <i data-lucide="loader" class="w-5 h-5 animate-spin text-[var(--accent-blue)]"></i>
        <span>Ładowanie listy rozmów...</span>
      </div>
    `;
    this.initIcons();

    try {
      const res = await fetch('/api/sessions');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const sessions = await res.json();

      if (countBadge) {
        countBadge.textContent = Array.isArray(sessions) ? String(sessions.length) : '0';
      }

      if (!Array.isArray(sessions) || sessions.length === 0) {
        listContainer.innerHTML = `
          <div class="py-12 flex flex-col items-center justify-center gap-2 text-xs text-[var(--text-dim)] border border-dashed border-[var(--border-color)] rounded-xl">
            <i data-lucide="message-square-off" class="w-6 h-6 text-[var(--text-muted)]"></i>
            <span class="font-medium text-[var(--text-main)]">Brak zapisanych rozmów</span>
            <span class="text-[11px] text-[var(--text-muted)]">Rozpocznij nową konwersację w panelu głównym.</span>
          </div>
        `;
        this.initIcons();
        return;
      }

      listContainer.innerHTML = '';

      sessions.forEach(s => {
        const sessionId = s.conversation_id;
        const title = s.title || `Sesja ${sessionId.slice(0, 8)}`;
        const preview = s.preview || s.last_message || 'Brak wiadomości w sesji';

        let formattedDate = 'Niedawno';
        if (s.last_modified || s.updated_at) {
          const d = new Date(s.last_modified || s.updated_at);
          if (!isNaN(d.getTime())) {
            const day = String(d.getDate()).padStart(2, '0');
            const month = String(d.getMonth() + 1).padStart(2, '0');
            const year = d.getFullYear();
            const hours = String(d.getHours()).padStart(2, '0');
            const minutes = String(d.getMinutes()).padStart(2, '0');
            formattedDate = `${day}.${month}.${year}, ${hours}:${minutes}`;
          }
        }

        const count = s.message_count ?? s.messages_count ?? (Array.isArray(s.messages) ? s.messages.length : (s.step_count ?? s.steps_count));
        let messagesLabel = '';
        if (count != null) {
          const n = Number(count);
          if (n === 1) messagesLabel = '1 wiadomość';
          else if (n >= 2 && n <= 4) messagesLabel = `${n} wiadomości`;
          else messagesLabel = `${n} wiadomości`;
        }

        const isActive = sessionId === this.activeSessionId;

        const row = document.createElement('div');
        row.className = `group flex items-center justify-between p-3.5 rounded-xl border transition-all cursor-pointer ${
          isActive
            ? 'bg-[var(--bg-card)] border-[var(--accent-blue)]/50 shadow-sm'
            : 'bg-[var(--bg-base)]/50 hover:bg-[var(--bg-card)] border-[var(--border-color)] hover:border-[var(--accent-blue)]/40'
        }`;

        row.innerHTML = `
          <div class="flex flex-col min-w-0 flex-1 mr-3 space-y-1">
            <div class="flex items-center gap-2.5 flex-wrap">
              <span class="font-semibold text-xs text-[var(--text-main)] group-hover:text-[var(--accent-blue)] transition-colors truncate max-w-sm">${this.escapeHtml(title)}</span>
              <span class="text-[11px] font-mono text-[var(--text-dim)] flex items-center gap-1">
                <i data-lucide="calendar" class="w-3 h-3 text-[var(--text-muted)]"></i>
                <span>${formattedDate}</span>
              </span>
              ${messagesLabel ? `<span class="px-2 py-0.5 rounded-full bg-[var(--bg-panel)] border border-[var(--border-color)] text-[10px] font-mono text-[var(--accent-blue)]">${messagesLabel}</span>` : ''}
              ${s.pinned ? '<span class="px-1.5 py-0.5 rounded bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] text-[10px] font-mono flex items-center gap-1"><i data-lucide="pin" class="w-2.5 h-2.5"></i>Przypięta</span>' : ''}
            </div>
            <p class="text-[11px] text-[var(--text-dim)] truncate leading-relaxed">${this.escapeHtml(preview)}</p>
          </div>

          <div class="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1.5 flex-shrink-0">
            <button type="button" class="btn-fork-session px-2.5 py-1.5 rounded-lg bg-[var(--bg-panel)] hover:bg-[var(--accent-blue)] hover:text-[#121217] border border-[var(--border-color)] hover:border-transparent text-xs font-medium text-[var(--text-main)] transition-all flex items-center gap-1.5 cursor-pointer shadow-sm" title="Sforkuj rozmowę (utwórz kopię z nowym ID)">
              <i data-lucide="git-fork" class="w-3.5 h-3.5"></i>
              <span>Sforkuj</span>
            </button>
            <button type="button" class="btn-export-session px-2.5 py-1.5 rounded-lg bg-[var(--bg-panel)] hover:bg-[var(--accent-blue)] hover:text-[#121217] border border-[var(--border-color)] hover:border-transparent text-xs font-medium text-[var(--text-main)] transition-all flex items-center gap-1.5 cursor-pointer shadow-sm" title="Pobierz sformatowany plik .md">
              <i data-lucide="download" class="w-3.5 h-3.5"></i>
              <span>Eksportuj</span>
            </button>
          </div>
        `;

        row.addEventListener('click', (e) => {
          if (e.target.closest('button')) return;
          this.selectSession(sessionId);
          this.closeSettings();
        });

        const btnFork = row.querySelector('.btn-fork-session');
        btnFork?.addEventListener('click', async (e) => {
          e.stopPropagation();
          try {
            btnFork.disabled = true;
            const forkRes = await fetch(`/api/sessions/${sessionId}/fork`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' }
            });
            if (!forkRes.ok) throw new Error(`HTTP ${forkRes.status}`);
            const forkData = await forkRes.json();
            const newSessionId = forkData.conversation_id || forkData.session_id || forkData.id;
            await this.loadSessions();
            await this.loadConversationsManagement();
            if (newSessionId) {
              await this.selectSession(newSessionId);
            }
            this.closeSettings();
          } catch (err) {
            console.error('Błąd podczas forkowania sesji:', err);
          } finally {
            btnFork.disabled = false;
          }
        });

        const btnExport = row.querySelector('.btn-export-session');
        btnExport?.addEventListener('click', (e) => {
          e.stopPropagation();
          const a = document.createElement('a');
          a.href = `/api/sessions/${sessionId}/export?format=markdown`;
          a.download = '';
          document.body.appendChild(a);
          a.click();
          a.remove();
        });

        listContainer.appendChild(row);
      });

      this.initIcons();
    } catch (_) {
      listContainer.innerHTML = `
        <div class="py-8 text-center text-xs text-[#f7768e] border border-dashed border-[#f7768e]/30 rounded-xl">
          Nie udało się pobrać listy rozmów z serwera.
        </div>
      `;
      this.initIcons();
    }
  }

  toggleShortcutsModal(show) {
    if (show) {
      this.shortcutsModal?.classList.remove('hidden');
      this.initIcons();
    } else {
      this.shortcutsModal?.classList.add('hidden');
    }
  }

  closeAllModals() {
    this.closeSettings();
    this.toggleShortcutsModal(false);
    this.closeNewFolderModal();
    this.workspaceFilesModal?.classList.add('hidden');
    this.plusPopover?.classList.add('hidden');
    this.metricsPopover?.classList.add('hidden');
    document.getElementById('custom-confirm-modal')?.classList.add('hidden');
    document.getElementById('custom-prompt-modal')?.classList.add('hidden');
  }

  async openWorkspaceFilesModal(dirPath = '/workspace') {
    if (!this.workspaceFilesModal || !this.modalWorkspaceTree) return;
    this.workspaceFilesModal.classList.remove('hidden');
    this.modalWorkspaceTree.innerHTML = '<div class="text-[var(--text-dim)] p-2">Ładowanie plików...</div>';

    try {
      const res = await fetch(`/api/fs/list?path=${encodeURIComponent(dirPath)}`);
      if (!res.ok) throw new Error();
      const data = await res.json();

      this.modalFsCurrentPath = data.current_path || dirPath;
      this.modalFsParentPath = data.parent_path;
      this.modalFsItems = Array.isArray(data) ? data : (data.items || []);

      const pathDisplay = document.getElementById('modal-fs-path');
      if (pathDisplay) {
        pathDisplay.textContent = this.modalFsCurrentPath;
      }

      const btnParent = document.getElementById('btn-modal-fs-parent');
      if (btnParent) {
        const canGoUp = Boolean(this.modalFsParentPath && this.modalFsCurrentPath !== '/workspace');
        btnParent.disabled = !canGoUp;
      }

      const filterInput = document.getElementById('modal-fs-filter');
      if (filterInput) {
        filterInput.value = '';
      }

      this.renderModalWorkspaceFiles(this.modalFsItems);
    } catch (_) {
      this.modalWorkspaceTree.innerHTML = '<div class="text-[#f7768e] p-2">Nie udało się załadować listy plików.</div>';
    }
  }

  renderModalWorkspaceFiles(items) {
    if (!this.modalWorkspaceTree) return;
    this.modalWorkspaceTree.innerHTML = '';

    if (!items || items.length === 0) {
      this.modalWorkspaceTree.innerHTML = '<div class="text-[var(--text-dim)] p-3 text-center">Brak plików w tym katalogu.</div>';
      return;
    }

    const sorted = [...items].sort((a, b) => {
      if (a.is_dir === b.is_dir) {
        return a.name.localeCompare(b.name);
      }
      return a.is_dir ? -1 : 1;
    });

    sorted.forEach(item => {
      const row = document.createElement('div');
      row.className = 'flex items-center justify-between p-2 rounded-lg hover:bg-[var(--bg-card)] cursor-pointer text-xs transition-colors group';

      const isDir = Boolean(item.is_dir);
      const iconName = isDir ? 'folder' : 'file-text';
      const iconColor = isDir ? 'text-[var(--accent-blue)]' : 'text-[var(--text-dim)]';
      const nameColor = isDir ? 'font-semibold text-[var(--text-main)] group-hover:text-[var(--accent-blue)]' : 'text-[var(--text-main)]';
      const sizeText = isDir ? 'Folder' : (item.size != null ? (item.size > 0 ? (item.size / 1024).toFixed(1) + ' KB' : '0 B') : '');

      row.innerHTML = `
        <div class="flex items-center gap-2.5 min-w-0 flex-1">
          <i data-lucide="${iconName}" class="w-3.5 h-3.5 ${iconColor} flex-shrink-0"></i>
          <span class="truncate ${nameColor}">${this.escapeHtml(item.name)}</span>
        </div>
        <span class="text-[10px] text-[var(--text-dim)] flex-shrink-0 font-mono">${sizeText}</span>
      `;

      row.addEventListener('click', () => {
        if (isDir) {
          this.openWorkspaceFilesModal(item.path);
        } else {
          this.addAttachment({
            name: item.name,
            path: item.path,
            size: item.size
          });
          this.workspaceFilesModal?.classList.add('hidden');
        }
      });

      this.modalWorkspaceTree.appendChild(row);
    });

    this.initIcons();
  }

  filterModalWorkspaceFiles(query) {
    if (!this.modalFsItems) return;
    const q = (query || '').trim().toLowerCase();
    if (!q) {
      this.renderModalWorkspaceFiles(this.modalFsItems);
      return;
    }
    const filtered = this.modalFsItems.filter(item => item.name.toLowerCase().includes(q));
    this.renderModalWorkspaceFiles(filtered);
  }

  requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }

  notifyCompletion(message) {
    if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
      new Notification('Prometeusz — Odpowiedź gotowa', {
        body: message.slice(0, 100),
        icon: '/favicon.ico'
      });
    }
  }

  escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  handleInputKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      this.handleSendMessage();
    }
  }

  handleInputSlash() {
    const val = this.chatInput?.value || '';
    if (val.startsWith('/') && !val.includes(' ')) {
      this.filterSlashCommands(val);
    } else {
      this.slashAutocomplete?.classList.add('hidden');
    }
  }

  async loadSlashCommands() {
    try {
      const res = await fetch('/api/slash-commands');
      if (res.ok) this.slashCommands = await res.json();
    } catch (_) {}
  }

  filterSlashCommands(query) {
    const list = this.slashCommandsList;
    if (!list) return;
    list.innerHTML = '';
    const filtered = this.slashCommands.filter(c => c.command.startsWith(query));
    if (filtered.length === 0) {
      this.slashAutocomplete?.classList.add('hidden');
      return;
    }
    filtered.forEach(c => {
      const item = document.createElement('div');
      item.className = 'flex items-center justify-between px-3 py-1.5 rounded-lg hover:bg-[var(--bg-card)] cursor-pointer text-xs font-mono';
      item.innerHTML = `
        <span class="text-[var(--accent-blue)] font-bold">${this.escapeHtml(c.command)}</span>
        <span class="text-[10px] text-[var(--text-dim)]">${this.escapeHtml(c.description)}</span>
      `;
      item.addEventListener('click', () => {
        if (this.chatInput) {
          this.chatInput.value = `${c.command} `;
          this.chatInput.focus();
        }
        this.slashAutocomplete?.classList.add('hidden');
      });
      list.appendChild(item);
    });
    this.slashAutocomplete?.classList.remove('hidden');
  }
}

window.addEventListener('DOMContentLoaded', () => {
  window.app = new PrometeuszApp();
});

/**
 * EnterpriseERP — Main JavaScript
 * Sidebar, Dark Mode, Notifications, Global Search, Kanban, Utilities
 */

'use strict';

/* ─── ERP App Namespace ──────────────────────────────────────────────────── */
const ERP = {
  version: '2.0.0',
  csrfToken: document.querySelector('meta[name="csrf-token"]')?.content || '',

  // ── Init ──────────────────────────────────────────────────────────────────
  init() {
    this.Sidebar.init();
    this.Theme.init();
    this.Notifications.init();
    this.GlobalSearch.init();
    this.DataTables.init();
    this.Forms.init();
    this.Messages.init();
    this.Shortcuts.init();
    console.info(`EnterpriseERP v${this.version} initialized`);
  },

  // ── Helpers ───────────────────────────────────────────────────────────────
  request(url, options = {}) {
    const defaults = {
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.csrfToken,
      },
    };
    return fetch(url, { ...defaults, ...options, headers: { ...defaults.headers, ...(options.headers || {}) } })
      .then(r => r.json());
  },

  toast(message, type = 'success', duration = 3500) {
    Swal.fire({
      toast: true,
      position: 'top-end',
      showConfirmButton: false,
      timer: duration,
      timerProgressBar: true,
      icon: type,
      title: message,
      customClass: { popup: 'swal-toast' },
    });
  },

  confirm(message, title = 'Are you sure?') {
    return Swal.fire({
      title,
      text: message,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#e63946',
      cancelButtonColor: '#6c757d',
      confirmButtonText: 'Yes, proceed',
      cancelButtonText: 'Cancel',
    }).then(r => r.isConfirmed);
  },

  formatCurrency(amount, currency = 'USD', locale = 'en-US') {
    return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(amount);
  },

  formatDate(date, format = 'medium') {
    return new Intl.DateTimeFormat('en-US', { dateStyle: format }).format(new Date(date));
  },
};

/* ─── Sidebar ────────────────────────────────────────────────────────────── */
ERP.Sidebar = {
  sidebar: null,
  mainWrapper: null,
  isCollapsed: false,
  isMobile: false,

  init() {
    this.sidebar = document.getElementById('sidebar');
    this.mainWrapper = document.getElementById('mainWrapper');
    if (!this.sidebar) return;

    this.isMobile = window.innerWidth <= 768;
    this.isCollapsed = localStorage.getItem('sidebarCollapsed') === 'true' && !this.isMobile;

    if (this.isCollapsed) this.sidebar.classList.add('collapsed');

    // Toggle buttons
    document.getElementById('sidebarToggle')?.addEventListener('click', () => this.toggle());
    document.getElementById('sidebarToggleBtn')?.addEventListener('click', () => this.toggle());

    // Sub-nav accordion
    document.querySelectorAll('.nav-parent').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const parent = link.closest('.nav-has-children');
        const isOpen = parent.classList.contains('open');
        // Close others
        document.querySelectorAll('.nav-has-children.open').forEach(el => el.classList.remove('open'));
        if (!isOpen) parent.classList.add('open');
      });
    });

    // Auto-open active parent
    const activeChild = document.querySelector('.nav-child.active');
    if (activeChild) activeChild.closest('.nav-has-children')?.classList.add('open');

    // Module search
    document.getElementById('moduleSearch')?.addEventListener('input', (e) => this.filterNav(e.target.value));

    // Mobile overlay
    if (this.isMobile) {
      const overlay = document.createElement('div');
      overlay.className = 'sidebar-overlay';
      overlay.style.cssText = 'display:none;position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:99;';
      overlay.addEventListener('click', () => this.closeMobile());
      document.body.appendChild(overlay);
      this.overlay = overlay;
    }

    window.addEventListener('resize', () => this.handleResize());
  },

  toggle() {
    if (window.innerWidth <= 768) {
      this.sidebar.classList.toggle('mobile-open');
      if (this.overlay) this.overlay.style.display = this.sidebar.classList.contains('mobile-open') ? 'block' : 'none';
    } else {
      this.isCollapsed = !this.isCollapsed;
      this.sidebar.classList.toggle('collapsed', this.isCollapsed);
      localStorage.setItem('sidebarCollapsed', this.isCollapsed);
    }
  },

  closeMobile() {
    this.sidebar.classList.remove('mobile-open');
    if (this.overlay) this.overlay.style.display = 'none';
  },

  handleResize() {
    const wasMobile = this.isMobile;
    this.isMobile = window.innerWidth <= 768;
    if (wasMobile !== this.isMobile) {
      this.sidebar.classList.remove('mobile-open', 'collapsed');
      if (!this.isMobile && this.isCollapsed) this.sidebar.classList.add('collapsed');
      if (this.overlay) this.overlay.style.display = 'none';
    }
  },

  filterNav(query) {
    const q = query.toLowerCase();
    document.querySelectorAll('.nav-item').forEach(item => {
      const text = item.textContent.toLowerCase();
      item.style.display = (!q || text.includes(q)) ? '' : 'none';
    });
    document.querySelectorAll('.nav-section-title').forEach(t => {
      t.style.display = q ? 'none' : '';
    });
  },
};

/* ─── Theme (Dark / Light) ───────────────────────────────────────────────── */
ERP.Theme = {
  init() {
    const btn = document.getElementById('themeToggle');
    if (!btn) return;
    btn.addEventListener('click', () => this.toggle());
  },

  toggle() {
    const html = document.documentElement;
    const current = html.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);

    const icon = document.querySelector('#themeToggle i');
    if (icon) { icon.className = `fas fa-${next === 'dark' ? 'sun' : 'moon'}`; }

    // Persist via API
    ERP.request('/api/v1/auth/users/me/', {
      method: 'PATCH',
      body: JSON.stringify({ theme: next }),
    }).catch(() => {});
  },
};

/* ─── Notifications ──────────────────────────────────────────────────────── */
ERP.Notifications = {
  loaded: false,

  init() {
    const btn = document.getElementById('notificationBtn');
    if (!btn) return;

    btn.addEventListener('click', () => {
      if (!this.loaded) this.load();
    });

    document.getElementById('markAllRead')?.addEventListener('click', (e) => {
      e.preventDefault();
      this.markAllRead();
    });

    // Poll every 30s for new notifications
    setInterval(() => this.checkNew(), 30000);
  },

  load() {
    this.loaded = true;
    ERP.request('/api/v1/notifications/notifications/?is_read=false&page_size=15')
      .then(data => this.render(data.results || []))
      .catch(() => this.renderError());
  },

  render(notifications) {
    const list = document.getElementById('notificationList');
    if (!list) return;

    if (!notifications.length) {
      list.innerHTML = '<div style="padding:32px;text-align:center;color:var(--text-muted)"><i class="fas fa-bell-slash fa-2x"></i><p style="margin-top:12px">No new notifications</p></div>';
      return;
    }

    list.innerHTML = notifications.map(n => `
      <div class="notification-item unread" data-id="${n.id}" onclick="ERP.Notifications.markRead('${n.id}', '${n.action_url}')">
        <div class="notification-item-icon" style="background:${this.typeColor(n.notification_type)}20;color:${this.typeColor(n.notification_type)}">
          <i class="fas fa-${this.typeIcon(n.notification_type)}"></i>
        </div>
        <div style="flex:1;min-width:0">
          <div style="font-weight:600;font-size:13px;margin-bottom:2px">${n.title}</div>
          <div style="font-size:12px;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${n.message}</div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px">${this.timeAgo(n.created_at)}</div>
        </div>
      </div>
    `).join('');
  },

  renderError() {
    const list = document.getElementById('notificationList');
    if (list) list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted)">Failed to load notifications</div>';
  },

  markRead(id, url) {
    ERP.request(`/api/v1/notifications/notifications/${id}/mark_read/`, { method: 'POST' })
      .then(() => {
        if (url) window.location.href = url;
        else this.load();
        this.updateBadge(-1);
      });
  },

  markAllRead() {
    ERP.request('/api/v1/notifications/notifications/mark_all_read/', { method: 'POST' })
      .then(() => {
        this.load();
        const badge = document.querySelector('.notification-badge');
        if (badge) badge.style.display = 'none';
      });
  },

  checkNew() {
    ERP.request('/api/v1/notifications/notifications/?is_read=false&page_size=1')
      .then(data => {
        const count = data.count || 0;
        const badge = document.querySelector('.notification-badge');
        if (badge) {
          badge.textContent = count > 0 ? count : '';
          badge.style.display = count > 0 ? 'flex' : 'none';
        }
      }).catch(() => {});
  },

  updateBadge(delta) {
    const badge = document.querySelector('.notification-badge');
    if (!badge) return;
    const current = parseInt(badge.textContent) || 0;
    const next = Math.max(0, current + delta);
    badge.textContent = next || '';
    badge.style.display = next > 0 ? 'flex' : 'none';
  },

  typeIcon(type) {
    const map = { info: 'info-circle', success: 'check-circle', warning: 'exclamation-triangle', error: 'times-circle', approval: 'check-double', reminder: 'clock', alert: 'bell' };
    return map[type] || 'bell';
  },

  typeColor(type) {
    const map = { info: '#4895ef', success: '#2dc653', warning: '#f8a200', error: '#e63946', approval: '#4361ee', reminder: '#9b5de5', alert: '#f15bb5' };
    return map[type] || '#4361ee';
  },

  timeAgo(dateStr) {
    const diff = (Date.now() - new Date(dateStr)) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
    return `${Math.floor(diff/86400)}d ago`;
  },
};

/* ─── Global Search ──────────────────────────────────────────────────────── */
ERP.GlobalSearch = {
  input: null,
  results: null,
  debounceTimer: null,

  init() {
    this.input = document.getElementById('globalSearch');
    this.results = document.getElementById('searchResults');
    if (!this.input) return;

    this.input.addEventListener('input', () => {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = setTimeout(() => this.search(), 300);
    });

    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this.close();
    });

    document.addEventListener('click', (e) => {
      if (!this.input.contains(e.target) && !this.results.contains(e.target)) this.close();
    });
  },

  search() {
    const q = this.input.value.trim();
    if (q.length < 2) { this.close(); return; }

    ERP.request(`/api/v1/dashboard/search/?q=${encodeURIComponent(q)}`)
      .then(data => this.render(data))
      .catch(() => {});
  },

  render(data) {
    if (!data.results?.length) { this.results.innerHTML = ''; this.results.style.display = 'none'; return; }

    this.results.style.display = 'block';
    this.results.style.cssText = 'position:absolute;top:calc(100% + 8px);left:0;right:0;background:var(--bg-card);border:1px solid var(--border-color);border-radius:var(--radius-lg);box-shadow:var(--shadow-xl);z-index:999;max-height:380px;overflow-y:auto;';
    this.results.innerHTML = data.results.map(r => `
      <a href="${r.url}" style="display:flex;align-items:center;gap:12px;padding:10px 14px;color:var(--text-primary);border-bottom:1px solid var(--border-color);">
        <div style="width:32px;height:32px;border-radius:8px;background:rgba(67,97,238,0.1);display:flex;align-items:center;justify-content:center;color:var(--brand-primary)">
          <i class="fas fa-${r.icon || 'search'}"></i>
        </div>
        <div>
          <div style="font-weight:600;font-size:13px">${r.title}</div>
          <div style="font-size:11px;color:var(--text-muted)">${r.module} · ${r.subtitle || ''}</div>
        </div>
      </a>
    `).join('');
  },

  close() {
    if (this.results) { this.results.innerHTML = ''; this.results.style.display = 'none'; }
  },
};

/* ─── DataTables ─────────────────────────────────────────────────────────── */
ERP.DataTables = {
  instances: {},

  init() {
    document.querySelectorAll('[data-datatable]').forEach(table => {
      const id = table.id || `dt-${Date.now()}`;
      const options = JSON.parse(table.dataset.datatableOptions || '{}');
      this.instances[id] = $(table).DataTable({
        responsive: true,
        pageLength: 25,
        language: {
          search: '',
          searchPlaceholder: 'Search...',
          lengthMenu: 'Show _MENU_ entries',
          info: 'Showing _START_–_END_ of _TOTAL_ records',
          emptyTable: 'No records found',
          zeroRecords: 'No matching records',
        },
        dom: '<"dt-toolbar d-flex align-items-center gap-2 mb-3"<"dt-search"f><"ms-auto"l>>rt<"dt-footer d-flex align-items-center justify-content-between mt-3"ip>',
        ...options,
      });
    });
  },

  get(id) { return this.instances[id]; },
};

/* ─── Forms ──────────────────────────────────────────────────────────────── */
ERP.Forms = {
  init() {
    // Delete confirmation
    document.querySelectorAll('[data-confirm-delete]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        const msg = btn.dataset.confirmDelete || 'This action cannot be undone.';
        const confirmed = await ERP.confirm(msg, 'Delete this record?');
        if (confirmed) {
          const form = btn.closest('form');
          if (form) form.submit();
          else if (btn.href) window.location.href = btn.href;
        }
      });
    });

    // Loading state on form submit
    document.querySelectorAll('form[data-loading]').forEach(form => {
      form.addEventListener('submit', () => {
        const btn = form.querySelector('[type="submit"]');
        if (btn) {
          btn.disabled = true;
          const label = btn.dataset.loadingText || 'Processing...';
          btn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i>${label}`;
        }
      });
    });

    // Float label effect
    document.querySelectorAll('.form-floating input, .form-floating textarea').forEach(el => {
      el.addEventListener('focus', () => el.closest('.form-floating').classList.add('focused'));
      el.addEventListener('blur', () => el.closest('.form-floating').classList.remove('focused'));
    });
  },
};

/* ─── Flash Messages ─────────────────────────────────────────────────────── */
ERP.Messages = {
  init() {
    setTimeout(() => {
      document.querySelectorAll('#messagesContainer .alert').forEach(el => {
        el.style.transition = 'opacity 0.5s';
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 500);
      });
    }, 5000);
  },
};

/* ─── Keyboard Shortcuts ─────────────────────────────────────────────────── */
ERP.Shortcuts = {
  init() {
    document.addEventListener('keydown', (e) => {
      // Ctrl+K → Focus global search
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        document.getElementById('globalSearch')?.focus();
      }
      // Ctrl+B → Toggle sidebar
      if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault();
        ERP.Sidebar.toggle();
      }
    });
  },
};

/* ─── Kanban Board ───────────────────────────────────────────────────────── */
ERP.Kanban = {
  init(boardEl, onDrop) {
    if (!boardEl) return;
    let dragging = null;

    boardEl.querySelectorAll('.kanban-card').forEach(card => {
      card.draggable = true;
      card.addEventListener('dragstart', () => {
        dragging = card;
        card.classList.add('dragging');
        setTimeout(() => card.style.opacity = '0.4', 0);
      });
      card.addEventListener('dragend', () => {
        dragging = null;
        card.classList.remove('dragging');
        card.style.opacity = '';
      });
    });

    boardEl.querySelectorAll('.kanban-cards').forEach(zone => {
      zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        const after = this.getDragAfterEl(zone, e.clientY);
        if (after === null) zone.appendChild(dragging);
        else zone.insertBefore(dragging, after);
      });

      zone.addEventListener('drop', (e) => {
        e.preventDefault();
        const columnStatus = zone.closest('.kanban-column').dataset.status;
        const taskId = dragging?.dataset.taskId;
        if (taskId && columnStatus && onDrop) onDrop(taskId, columnStatus);
      });
    });
  },

  getDragAfterEl(container, y) {
    const draggables = [...container.querySelectorAll('.kanban-card:not(.dragging)')];
    return draggables.reduce((closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) return { offset, element: child };
      return closest;
    }, { offset: Number.NEGATIVE_INFINITY }).element || null;
  },
};

/* ─── Charts Factory ─────────────────────────────────────────────────────── */
ERP.Charts = {
  defaults() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return {
      color: isDark ? '#e6edf3' : '#1a1a2e',
      gridColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
    };
  },

  line(canvasId, labels, datasets, options = {}) {
    const d = this.defaults();
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: d.color } }, ...options.plugins },
        scales: {
          x: { ticks: { color: d.color }, grid: { color: d.gridColor } },
          y: { ticks: { color: d.color }, grid: { color: d.gridColor } },
          ...options.scales,
        },
        ...options,
      },
    });
  },

  bar(canvasId, labels, datasets, options = {}) {
    const d = this.defaults();
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: d.color } } },
        scales: {
          x: { ticks: { color: d.color }, grid: { color: d.gridColor } },
          y: { ticks: { color: d.color }, grid: { color: d.gridColor } },
          ...options.scales,
        },
        ...options,
      },
    });
  },

  doughnut(canvasId, labels, data, colors, options = {}) {
    const ctx = document.getElementById(canvasId)?.getContext('2d');
    if (!ctx) return null;
    return new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{ data, backgroundColor: colors, borderWidth: 0 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '70%',
        plugins: { legend: { position: 'bottom', labels: { color: this.defaults().color, padding: 16 } } },
        ...options,
      },
    });
  },
};

/* ─── Boot ───────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => ERP.init());

document.addEventListener('DOMContentLoaded', function() {
    // Initialize Bootstrap Toasts
    var toastElList = [].slice.call(document.querySelectorAll('.toast'))
    var toastList = toastElList.map(function(toastEl) {
        return new bootstrap.Toast(toastEl, {
            autohide: true,
            delay: 5000
        });
    });
    toastList.forEach(toast => toast.show());
});

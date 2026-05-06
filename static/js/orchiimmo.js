/**
 * ORCHIIMMO — Premium Interactive JS
 * 3D Tilt · Scroll Animations · Counters · Particles · Navbar
 */

document.addEventListener('DOMContentLoaded', () => {

  // ════════════════════════════════════════════════════════════
  // 0. THÈME CLAIR / SOMBRE
  // ════════════════════════════════════════════════════════════
  const themeBtn  = document.getElementById('theme-toggle');
  const iconLight = document.getElementById('theme-icon-light');
  const iconDark  = document.getElementById('theme-icon-dark');

  function applyTheme(theme) {
    if (theme === 'light') {
      document.body.classList.add('light-mode');
      iconLight?.classList.add('d-none');
      iconDark?.classList.remove('d-none');
      themeBtn?.setAttribute('title', 'Mode sombre / الوضع الداكن');
    } else {
      document.body.classList.remove('light-mode');
      iconLight?.classList.remove('d-none');
      iconDark?.classList.add('d-none');
      themeBtn?.setAttribute('title', 'Mode clair / الوضع الفاتح');
    }
    localStorage.setItem('orchiimmo-theme', theme);
  }

  // Charger la préférence sauvegardée
  const savedTheme = localStorage.getItem('orchiimmo-theme') || 'dark';
  applyTheme(savedTheme);

  themeBtn?.addEventListener('click', () => {
    const current = localStorage.getItem('orchiimmo-theme') || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
  });

  // ════════════════════════════════════════════════════════════
  // 0b. LANGUE FR / AR (Darija)
  // ════════════════════════════════════════════════════════════
  const langBtn   = document.getElementById('lang-toggle');
  const langLabel = document.getElementById('lang-label');

  // Textes de traduction pour les éléments communs
  const TRANSLATIONS = {
    fr: {
      pageTitle:   document.title,  // garder le titre original
      searchPlaceholder: 'Rechercher une ville…',
    },
    ar: {
      searchPlaceholder: 'ابحث عن مدينة…',
    }
  };

  function applyLang(lang) {
    if (lang === 'ar') {
      document.body.classList.add('lang-ar');
      document.documentElement.setAttribute('dir', 'rtl');
      document.documentElement.setAttribute('lang', 'ar');
      langLabel && (langLabel.textContent = 'FR');
      langBtn?.setAttribute('title', 'Français');
    } else {
      document.body.classList.remove('lang-ar');
      document.documentElement.setAttribute('dir', 'ltr');
      document.documentElement.setAttribute('lang', 'fr');
      langLabel && (langLabel.textContent = 'AR');
      langBtn?.setAttribute('title', 'العربية / الدارجة');
    }
    // ── Mettre à jour le texte des <option> dans les <select> bilingues ──
    document.querySelectorAll('option[data-fr]').forEach(opt => {
      opt.textContent = (lang === 'ar') ? (opt.dataset.ar || opt.dataset.fr) : opt.dataset.fr;
    });
    localStorage.setItem('orchiimmo-lang', lang);
  }

  const savedLang = localStorage.getItem('orchiimmo-lang') || 'fr';
  applyLang(savedLang);

  langBtn?.addEventListener('click', () => {
    const current = localStorage.getItem('orchiimmo-lang') || 'fr';
    applyLang(current === 'fr' ? 'ar' : 'fr');
  });

  // ── 1. Navbar scroll effect ─────────────────────────────────
  const navbar = document.querySelector('.navbar');
  if (navbar) {
    window.addEventListener('scroll', () => {
      navbar.classList.toggle('scrolled', window.scrollY > 30);
    }, { passive: true });
  }

  // ── 2. 3D Card Tilt Effect ──────────────────────────────────
  function applyTilt(selector, maxTilt = 12, scale = 1.03) {
    document.querySelectorAll(selector).forEach(card => {
      card.addEventListener('mousemove', e => {
        const rect   = card.getBoundingClientRect();
        const cx     = rect.left + rect.width  / 2;
        const cy     = rect.top  + rect.height / 2;
        const dx     = (e.clientX - cx) / (rect.width  / 2);
        const dy     = (e.clientY - cy) / (rect.height / 2);
        const rotateX = -dy * maxTilt;
        const rotateY =  dx * maxTilt;
        card.style.transform =
          `perspective(800px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(${scale})`;
        card.style.transition = 'transform 0.05s ease';

        // Effet de lumière dynamique
        const lightX = ((e.clientX - rect.left) / rect.width)  * 100;
        const lightY = ((e.clientY - rect.top)  / rect.height) * 100;
        card.style.setProperty('--light-x', lightX + '%');
        card.style.setProperty('--light-y', lightY + '%');
      });

      card.addEventListener('mouseleave', () => {
        card.style.transform = 'perspective(800px) rotateX(0) rotateY(0) scale(1)';
        card.style.transition = 'transform 0.4s cubic-bezier(0.4,0,0.2,1)';
      });
    });
  }

  applyTilt('.property-card', 8, 1.03);
  applyTilt('.kpi-card',      6, 1.04);
  applyTilt('.feature-card',  5, 1.02);

  // ── 3. Scroll Animation (Intersection Observer) ─────────────
  const observerOptions = {
    threshold: 0.12,
    rootMargin: '0px 0px -50px 0px'
  };

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry, i) => {
      if (entry.isIntersecting) {
        setTimeout(() => {
          entry.target.classList.add('visible');
        }, i * 80);
        observer.unobserve(entry.target);
      }
    });
  }, observerOptions);

  document.querySelectorAll('.animate-on-scroll').forEach(el => observer.observe(el));

  // Ajouter la classe à tous les éléments importants s'ils ne l'ont pas
  const autoAnimate = document.querySelectorAll(
    '.card:not(.animate-on-scroll), h2:not(.animate-on-scroll), h3:not(.animate-on-scroll)'
  );
  // (on n'auto-ajoute pas pour éviter les conflits avec les animations CSS existantes)

  // ── 4. Animated Counters ────────────────────────────────────
  function animateCounter(el, end, duration = 1800, prefix = '', suffix = '') {
    const start     = 0;
    const startTime = performance.now();

    function update(currentTime) {
      const elapsed  = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Easing out cubic
      const eased    = 1 - Math.pow(1 - progress, 3);
      const current  = Math.floor(eased * end);
      el.textContent = prefix + current.toLocaleString('fr-MA') + suffix;
      if (progress < 1) requestAnimationFrame(update);
      else el.textContent = prefix + end.toLocaleString('fr-MA') + suffix;
    }
    requestAnimationFrame(update);
  }

  // Observer pour les KPIs
  const counterObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const el  = entry.target;
        const raw = el.dataset.target;
        if (raw) {
          animateCounter(el, parseInt(raw), 1500);
          counterObserver.unobserve(el);
        }
      }
    });
  }, { threshold: 0.5 });

  document.querySelectorAll('[data-counter]').forEach(el => counterObserver.observe(el));

  // ── 5. Ripple Effect sur les boutons ─────────────────────────
  document.querySelectorAll('.btn').forEach(btn => {
    btn.addEventListener('click', function(e) {
      const ripple    = document.createElement('span');
      const rect      = this.getBoundingClientRect();
      const size      = Math.max(rect.width, rect.height);
      const x         = e.clientX - rect.left - size / 2;
      const y         = e.clientY - rect.top  - size / 2;

      ripple.style.cssText = `
        position: absolute;
        width: ${size}px; height: ${size}px;
        left: ${x}px; top: ${y}px;
        background: rgba(255,255,255,0.2);
        border-radius: 50%;
        transform: scale(0);
        animation: ripple-anim 0.5s ease-out;
        pointer-events: none;
      `;
      this.style.position = 'relative';
      this.style.overflow = 'hidden';
      this.appendChild(ripple);
      setTimeout(() => ripple.remove(), 600);
    });
  });

  // Ajouter keyframe ripple dynamiquement
  const styleSheet = document.createElement('style');
  styleSheet.textContent = `
    @keyframes ripple-anim {
      to { transform: scale(3); opacity: 0; }
    }
  `;
  document.head.appendChild(styleSheet);

  // ── 6. Particles flottantes (hero section) ───────────────────
  const hero = document.querySelector('.hero-section');
  if (hero) {
    createParticles(hero, 18);
  }

  function createParticles(container, count) {
    for (let i = 0; i < count; i++) {
      const p = document.createElement('div');
      const size  = Math.random() * 4 + 1;
      const delay = Math.random() * 8;
      const dur   = Math.random() * 10 + 10;
      const left  = Math.random() * 100;
      const opacity = Math.random() * 0.4 + 0.1;

      p.style.cssText = `
        position: absolute;
        width: ${size}px; height: ${size}px;
        background: rgba(72,149,239,${opacity});
        border-radius: 50%;
        left: ${left}%;
        bottom: -10px;
        animation: particle-rise ${dur}s ${delay}s ease-in-out infinite;
        pointer-events: none;
        z-index: 0;
      `;
      container.appendChild(p);
    }
    // Keyframe particles
    if (!document.querySelector('#particle-style')) {
      const ps = document.createElement('style');
      ps.id = 'particle-style';
      ps.textContent = `
        @keyframes particle-rise {
          0%   { transform: translateY(0) translateX(0)   scale(1);   opacity: 0; }
          10%  { opacity: 1; }
          50%  { transform: translateY(-40vh) translateX(20px)  scale(1.2); }
          90%  { opacity: 0.5; }
          100% { transform: translateY(-80vh) translateX(-10px) scale(0.5); opacity: 0; }
        }
      `;
      document.head.appendChild(ps);
    }
  }

  // ── 7. Tooltips Bootstrap ───────────────────────────────────
  const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
  tooltipTriggerList.forEach(el => {
    new bootstrap.Tooltip(el, { trigger: 'hover focus' });
  });

  // ── 8. Auto-dismiss alerts ──────────────────────────────────
  document.querySelectorAll('.alert:not(.alert-permanent)').forEach(alert => {
    setTimeout(() => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) bsAlert.close();
    }, 5000);
  });

  // ── 9. Filtres formulaire — auto-submit sur changement ──────
  const filterForm = document.getElementById('filter-form');
  if (filterForm) {
    filterForm.querySelectorAll('select').forEach(sel => {
      sel.addEventListener('change', () => filterForm.submit());
    });
    filterForm.querySelector('input[name="opportunity"]')?.addEventListener('change', () => {
      filterForm.submit();
    });
  }

  // ── 10. Smooth scroll to top ────────────────────────────────
  const scrollBtn = document.getElementById('scroll-top');
  if (scrollBtn) {
    window.addEventListener('scroll', () => {
      scrollBtn.style.opacity = window.scrollY > 300 ? '1' : '0';
      scrollBtn.style.pointerEvents = window.scrollY > 300 ? 'auto' : 'none';
    }, { passive: true });
    scrollBtn.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // ── 11. Loading state sur le form de prédiction ─────────────
  const predictForm = document.getElementById('predict-form');
  const submitBtn   = document.getElementById('submit-btn');
  if (predictForm && submitBtn) {
    predictForm.addEventListener('submit', () => {
      submitBtn.disabled = true;
      submitBtn.innerHTML =
        '<span class="spinner-border spinner-border-sm me-2"></span>Calcul IA en cours…';
    });
  }

  console.log('%c🏠 ORCHIIMMO — Maroc MAD', 'color:#4895EF;font-size:16px;font-weight:bold;');
  console.log('%cPlateforme PFE 2026 — Immobilier Maroc', 'color:#94A3B8;');
});

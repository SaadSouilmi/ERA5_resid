(() => {
  const nav = document.getElementById("article-toc");
  const list = nav.querySelector("ol");
  const headings = [...document.querySelectorAll("article h1, article h2")];
  const used = new Set([...document.querySelectorAll("[id]")].map(el => el.id));
  const entries = headings.map(heading => {
    if (!heading.id) {
      const base = heading.textContent.trim().toLowerCase().normalize("NFKD")
        .replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "") || "section";
      let id = base, suffix = 2;
      while (used.has(id)) id = base + "-" + suffix++;
      heading.id = id;
      used.add(id);
    }
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = "#" + heading.id;
    link.textContent = heading.textContent.trim();
    item.append(link);
    list.append(item);
    return { heading, item, link };
  });
  if (!entries.length) return;
  nav.hidden = false;
  let scrollFrame = 0;
  let scrollToken = 0;
  const cancelScroll = () => {
    scrollToken++;
    if (scrollFrame) cancelAnimationFrame(scrollFrame);
    scrollFrame = 0;
  };
  const interruptScroll = () => cancelScroll();
  for (const type of ["wheel", "touchstart"]) {
    window.addEventListener(type, interruptScroll, { passive: true });
  }
  window.addEventListener("keydown", event => {
    if (["ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End", " ", "Tab", "Escape"].includes(event.key)) interruptScroll();
  });
  window.addEventListener("popstate", interruptScroll);
  nav.addEventListener("click", event => {
    const link = event.target.closest("a[href^='#']");
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const entry = entries.find(candidate => candidate.link === link);
    if (!entry) return;
    event.preventDefault();
    cancelScroll();
    try { if (location.hash !== link.hash) history.pushState(null, "", link.hash); } catch {}
    const start = window.scrollY;
    const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    const target = Math.min(maxScroll, Math.max(0, start + entry.heading.getBoundingClientRect().top - 24));
    const distance = target - start;
    const duration = Math.min(1000, 650 + Math.abs(distance) * .08);
    const began = performance.now();
    const token = scrollToken;
    const arrive = () => {
      if (!entry.heading.hasAttribute("tabindex")) {
        entry.heading.setAttribute("tabindex", "-1");
        entry.heading.addEventListener("blur", () => entry.heading.removeAttribute("tabindex"), { once: true });
      }
      entry.heading.focus({ preventScroll: true });
    };
    if (Math.abs(distance) < 1) {
      window.scrollTo({ top: target, behavior: "instant" });
      arrive();
      return;
    }
    const step = now => {
      if (token !== scrollToken) return;
      const progress = Math.min(1, (now - began) / duration);
      const eased = progress < .5 ? 4 * progress ** 3 : 1 - ((-2 * progress + 2) ** 3) / 2;
      window.scrollTo({ top: start + distance * eased, behavior: "instant" });
      if (progress < 1) scrollFrame = requestAnimationFrame(step);
      else {
        scrollFrame = 0;
        arrive();
      }
    };
    scrollFrame = requestAnimationFrame(step);
  });
  let frame = 0;
  const update = () => {
    frame = 0;
    let active = entries[0];
    const nearBottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
    if (nearBottom) active = entries[entries.length - 1];
    else for (const entry of entries) {
      if (entry.heading.getBoundingClientRect().top <= Math.min(160, window.innerHeight * .22)) active = entry;
      else break;
    }
    for (const entry of entries) {
      if (entry === active) {
        entry.item.classList.add("is-current");
        entry.link.setAttribute("aria-current", "location");
      } else {
        entry.item.classList.remove("is-current");
        entry.link.removeAttribute("aria-current");
      }
    }
  };
  const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule, { passive: true });
  window.addEventListener("load", schedule, { once: true });
  window.addEventListener("hashchange", schedule);
  document.fonts?.ready.then(schedule);
  if ("ResizeObserver" in window) new ResizeObserver(schedule).observe(document.querySelector("article"));
  update();
})();

/* TAG social layer: reviews, share, Let's Go, collections. Plain JS, no deps. */
(function () {
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const J = { "Content-Type": "application/json" };
  const api = async (url, opts) => {
    try {
      const r = await fetch(url, opts);
      let d = null;
      try { d = await r.json(); } catch (e) {}
      if (r.status === 401 || (r.redirected && /login/.test(r.url))) { location.href = "/login"; return { error: "auth" }; }
      if (!r.ok) return { error: (d && d.error) || "Ошибка " + r.status };
      return d || {};
    } catch (e) { return { error: "Нет соединения" }; }
  };
  const post = (url, body, method) => api(url, { method: method || "POST", headers: J, body: JSON.stringify(body || {}) });

  function toast(t) {
    const el = document.createElement("div");
    el.className = "sx-toast"; el.textContent = t;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2600);
  }

  function sheet(html) {
    const ov = document.createElement("div");
    ov.className = "sx-overlay";
    ov.innerHTML = '<div class="sx-sheet">' + html + "</div>";
    ov.addEventListener("click", (e) => { if (e.target === ov) ov.remove(); });
    document.body.appendChild(ov);
    return ov;
  }

  /* ---------- place identity ---------- */
  function cityOf(place) {
    if (place._city) return place._city;
    try {
      for (const c in placesData) {
        if (Array.isArray(placesData[c]) && placesData[c].indexOf(place) !== -1) return c;
      }
      for (const c in placesData) {
        if (Array.isArray(placesData[c]) && placesData[c].some((p) => p.title === place.title)) return c;
      }
    } catch (e) {}
    return "";
  }
  function photoOf(place) {
    const ph = Array.isArray(place.photos) && place.photos.length ? place.photos[0] : place.img || "";
    return typeof ph === "string" ? ph : (ph && ph.url) || "";
  }
  function info(place) {
    const c = place.coords || (place.locations && place.locations[0] && place.locations[0].coords) || [];
    const desc = String(place.desc || "").replace(/\s+/g, " ").slice(0, 300);
    const city = cityOf(place);
    return { key: city + "::" + place.title, city, title: place.title, desc, photo: photoOf(place), lat: c[0], lon: c[1] };
  }

  /* ---------- stars ---------- */
  function starsHtml(n, small) {
    let s = '<span class="sx-stars' + (small ? " sm" : "") + '">';
    for (let i = 1; i <= 10; i++) s += '<span class="sx-star' + (i <= n ? " on" : "") + '" data-v="' + i + '">★</span>';
    return s + "</span>";
  }
  function bindStarInput(root, onChange) {
    let val = 0;
    const stars = root.querySelectorAll(".sx-star");
    const paint = (n) => stars.forEach((s) => s.classList.toggle("on", +s.dataset.v <= n));
    stars.forEach((s) => {
      s.addEventListener("click", () => { val = +s.dataset.v; paint(val); onChange(val); });
      s.addEventListener("mouseenter", () => paint(+s.dataset.v));
    });
    root.addEventListener("mouseleave", () => paint(val));
    return { set(n) { val = n; paint(n); onChange(n); }, get: () => val };
  }

  /* ---------- reviews ---------- */
  async function renderReviews(container, place) {
    const p = info(place);
    container.innerHTML = '<div class="sx-section"><h3>Отзывы</h3><div class="sx-muted">Загрузка…</div></div>';
    const data = await api("/api/reviews?place_key=" + encodeURIComponent(p.key));
    if (container._place !== place) return; // modal switched
    const me = Number(document.body.dataset.userId) || null;
    const list = data.reviews || [];
    const mine = list.find((r) => r.mine);
    let html = '<div class="sx-section"><h3>Отзывы';
    if (data.count) html += ' <span class="sx-rating-num">★ ' + data.avg + '</span> <span class="sx-muted">(' + data.count + ")</span>";
    html += "</h3>";
    if (me) {
      html += '<div class="sx-form" id="sxForm"><div>' + starsHtml(mine ? mine.rating : 0) + '<span class="sx-rating-num" id="sxNum">' + (mine ? mine.rating + "/10" : "") + "</span></div>" +
        '<textarea id="sxText" placeholder="Расскажите, как вам это место…" maxlength="2000"></textarea>' +
        '<div class="sx-thumbs" id="sxThumbs"></div>' +
        '<div class="sx-actions" style="margin:0"><label class="sx-btn ghost">📷 Фото / видео<input type="file" id="sxFiles" accept="image/*,video/*" multiple hidden></label>' +
        '<button class="sx-btn primary" id="sxSend">' + (mine ? "Обновить отзыв" : "Опубликовать") + "</button></div></div>";
    } else {
      html += '<p class="sx-muted"><a href="/login" style="color:var(--neon)">Войдите</a>, чтобы оставить отзыв.</p>';
    }
    html += '<div id="sxList" style="margin-top:14px">' + (list.length ? "" : '<p class="sx-muted">Отзывов пока нет — будьте первым.</p>') + "</div></div>";
    container.innerHTML = html;

    const listEl = container.querySelector("#sxList");
    list.forEach((r) => {
      const el = document.createElement("div");
      el.className = "sx-review";
      const ava = r.user.avatar ? '<img class="sx-ava" src="' + esc(r.user.avatar) + '">' : '<span class="sx-ava">' + esc((r.user.nickname || "?")[0]) + "</span>";
      el.innerHTML = '<div class="sx-rv-head">' + ava + "<b>" + esc(r.user.nickname) + "</b>" + starsHtml(r.rating, true) + '<span class="sx-rating-num">' + r.rating + "</span>" +
        (r.mine ? '<button class="sx-del" title="Удалить">🗑</button>' : "") + "</div>" +
        (r.text ? '<div class="sx-rv-text">' + esc(r.text) + "</div>" : "") +
        (r.media && r.media.length ? '<div class="sx-rv-media">' + r.media.map((m) => m.type === "video"
          ? '<video src="' + esc(m.url) + '" controls preload="metadata"></video>'
          : '<a href="' + esc(m.url) + '" target="_blank"><img src="' + esc(m.url) + '" loading="lazy"></a>').join("") + "</div>" : "");
      const del = el.querySelector(".sx-del");
      if (del) del.onclick = async () => { if (confirm("Удалить отзыв?")) { await api("/api/reviews/" + r.id, { method: "DELETE" }); renderReviews(container, place); } };
      listEl.appendChild(el);
    });

    if (!me) return;
    const form = container.querySelector("#sxForm");
    const num = form.querySelector("#sxNum");
    const stars = bindStarInput(form, (n) => (num.textContent = n + "/10"));
    if (mine) { stars.set(mine.rating); container.querySelector("#sxText").value = mine.text || ""; }
    const files = form.querySelector("#sxFiles");
    const thumbs = form.querySelector("#sxThumbs");
    files.onchange = () => {
      thumbs.innerHTML = "";
      Array.from(files.files).slice(0, 4).forEach((f) => {
        const url = URL.createObjectURL(f);
        thumbs.insertAdjacentHTML("beforeend", f.type.startsWith("video") ? '<video src="' + url + '" muted></video>' : '<img src="' + url + '">');
      });
    };
    const send = form.querySelector("#sxSend");
    send.onclick = async () => {
      if (!stars.get()) return toast("Поставьте оценку от 1 до 10");
      const fd = new FormData();
      fd.append("place_key", p.key); fd.append("rating", stars.get());
      fd.append("text", container.querySelector("#sxText").value);
      Array.from(files.files).slice(0, 4).forEach((f) => fd.append("media", f));
      send.disabled = true; send.textContent = "Отправка…";
      const r = await api("/api/reviews", { method: "POST", body: fd });
      if (r.error) { toast(r.error); send.disabled = false; send.textContent = "Опубликовать"; return; }
      toast("Отзыв сохранён ✨");
      renderReviews(container, place);
    };
  }

  /* ---------- people picker ---------- */
  async function pickPeople(title, subtitle, confirmLabel) {
    const d = await api("/api/friends");
    return new Promise((resolve) => {
      if (d.error) return resolve(null);
      const ov = sheet('<h3>' + esc(title) + '</h3><div class="sx-muted" style="margin-bottom:8px">' + esc(subtitle || "") + '</div><div id="sxPeople"></div><div class="sx-actions"><button class="sx-btn ghost" id="sxCancel">Отмена</button><button class="sx-btn primary" id="sxOk">' + esc(confirmLabel || "Отправить") + "</button></div>");
      const box = ov.querySelector("#sxPeople");
      const friends = d.friends || [];
      if (!friends.length) box.innerHTML = '<p class="sx-muted">У вас пока нет друзей. Найдите людей через «Search users» и добавьте в друзья.</p>';
      friends.forEach((f) => {
        const row = document.createElement("label");
        row.className = "sx-person";
        row.innerHTML = '<input type="checkbox" value="' + f.id + '">' + (f.avatar ? '<img class="sx-ava" src="' + esc(f.avatar) + '">' : '<span class="sx-ava">' + esc((f.nickname || "?")[0]) + "</span>") + "<span>" + esc(f.nickname) + "</span>";
        box.appendChild(row);
      });
      ov.querySelector("#sxCancel").onclick = () => { ov.remove(); resolve(null); };
      ov.addEventListener("click", (e) => { if (e.target === ov) resolve(null); });
      ov.querySelector("#sxOk").onclick = () => {
        const ids = Array.from(box.querySelectorAll("input:checked")).map((i) => +i.value);
        if (!ids.length) return toast("Выберите хотя бы одного друга");
        ov.remove(); resolve(ids);
      };
    });
  }

  /* ---------- share place to chat (↗) ---------- */
  async function sharePlace(place) {
    const p = info(place);
    const ids = await pickPeople("Отправить место", p.title, "Отправить");
    if (!ids) return;
    let ok = 0, err = "";
    for (const id of ids) {
      const r = await post("/api/send_message", { receiver_id: id, kind: "place", place: p });
      if (r.error) err = r.error; else ok++;
    }
    toast(ok ? "Отправлено в чат ✓" : err || "Не удалось отправить");
  }

  /* ---------- Let's Go ---------- */
  async function letsGo(place) {
    const p = info(place);
    const d = await api("/api/friends");
    if (d.error) return;
    const ov = sheet("<h3>Let's Go 🚀</h3><div class='sx-muted' style='margin-bottom:8px'>" + esc(p.title) + "</div>" +
      '<input class="sx-input" id="sxWhen" placeholder="Когда? (например, в субботу в 15:00)" maxlength="40" style="margin-bottom:8px">' +
      '<input class="sx-input" id="sxNote" placeholder="Комментарий (необязательно)" maxlength="300" style="margin-bottom:10px">' +
      '<div id="sxPeople"></div><div class="sx-actions"><button class="sx-btn ghost" id="sxCancel">Отмена</button><button class="sx-btn primary" id="sxOk">Предложить</button></div>');
    const box = ov.querySelector("#sxPeople");
    if (!(d.friends || []).length) box.innerHTML = '<p class="sx-muted">Сначала добавьте друзей через «Search users».</p>';
    (d.friends || []).forEach((f) => {
      const row = document.createElement("label");
      row.className = "sx-person";
      row.innerHTML = '<input type="checkbox" value="' + f.id + '">' + (f.avatar ? '<img class="sx-ava" src="' + esc(f.avatar) + '">' : '<span class="sx-ava">' + esc((f.nickname || "?")[0]) + "</span>") + "<span>" + esc(f.nickname) + "</span>";
      box.appendChild(row);
    });
    ov.querySelector("#sxCancel").onclick = () => ov.remove();
    ov.querySelector("#sxOk").onclick = async () => {
      const ids = Array.from(box.querySelectorAll("input:checked")).map((i) => +i.value);
      if (!ids.length) return toast("Выберите друзей");
      const r = await post("/api/letsgo", { place: p, friend_ids: ids, when: ov.querySelector("#sxWhen").value, note: ov.querySelector("#sxNote").value });
      if (r.error) return toast(r.error);
      ov.remove(); toast("Приглашение отправлено ✓");
    };
  }

  /* ---------- collections ---------- */
  let savedKeys = new Set(), savedTitles = new Set();
  async function loadSaved() {
    const d = await api("/api/collections/saved");
    if (d && d.keys) { savedKeys = new Set(d.keys); savedTitles = new Set(d.titles || []); }
    return d;
  }
  function isSaved(place) { return savedKeys.has(info(place).key) || savedTitles.has(place.title); }

  async function pickCollection(place, onChange) {
    const p = info(place);
    const d = await api("/api/collections?place_key=" + encodeURIComponent(p.key));
    if (d.error) return;
    const all = (d.mine || []).concat((d.joined || []).filter((c) => c.can_edit));
    let changed = false;
    const DEFAULT_TITLE = "Избранное";
    const addToDefault = async () => {
      let def = (d.mine || []).find((c) => c.title === DEFAULT_TITLE);
      if (!def) {
        const r = await post("/api/collections", { title: DEFAULT_TITLE, description: "Несортированные места", privacy: "private" });
        if (r.error) return toast(r.error);
        def = r.collection;
      }
      const a = await post("/api/collections/" + def.id + "/items", { place: p });
      if (a.error) return toast(a.error);
      await loadSaved(); onChange && onChange();
      toast("Добавлено в коллекцию «" + DEFAULT_TITLE + "»");
    };
    const finish = async (ov) => {
      ov.remove();
      if (!changed && !isSaved(place)) await addToDefault();
    };
    const ov = sheet("<h3>⭐ Выберите коллекцию</h3><div class='sx-muted' style='margin-bottom:8px'>" + esc(p.title) + '</div><div id="sxCols"></div>' +
      '<div class="sx-section"><div class="sx-form"><input class="sx-input" id="sxNew" placeholder="Новая коллекция, например «Кофейни для работы»" maxlength="120">' +
      '<select class="sx-input" id="sxPriv"><option value="private">🔒 Приватная</option><option value="friends">👥 Только друзья</option><option value="public">🌍 Публичная</option></select>' +
      '<button class="sx-btn primary" id="sxCreate">Создать и добавить</button></div></div>' +
      '<div class="sx-actions"><a class="sx-btn ghost" href="/collections" style="text-decoration:none;color:inherit">Все коллекции</a><button class="sx-btn ghost" id="sxClose">Готово</button></div>');
    const box = ov.querySelector("#sxCols");
    const draw = () => {
      box.innerHTML = all.length ? "" : '<p class="sx-muted">Коллекций пока нет — создайте первую ниже.</p>';
      const priv = { public: "🌍", friends: "👥", private: "🔒" };
      all.forEach((c) => {
        const row = document.createElement("div");
        row.className = "sx-col-row";
        row.innerHTML = '<span style="font-size:22px;color:' + (c.has ? "var(--neon)" : "rgba(255,255,255,.3)") + '">' + (c.has ? "★" : "☆") + '</span><div class="t"><b>' + esc(c.title) + '</b><span class="sx-muted">' + priv[c.privacy] + " · " + c.count + " мест</span></div>";
        row.onclick = async () => {
          const r = c.has ? await post("/api/collections/" + c.id + "/items", { place_key: p.key }, "DELETE") : await post("/api/collections/" + c.id + "/items", { place: p });
          if (r.error) return toast(r.error);
          c.has = !c.has; c.count = r.count; changed = true;
          await loadSaved(); draw(); onChange && onChange();
          toast(c.has ? "Добавлено в коллекцию «" + c.title + "»" : "Убрано из «" + c.title + "»");
        };
        box.appendChild(row);
      });
    };
    draw();
    ov.querySelector("#sxClose").onclick = () => finish(ov);
    ov.addEventListener("click", (e) => { if (e.target === ov) finish(ov); });
    ov.querySelector("#sxCreate").onclick = async () => {
      const title = ov.querySelector("#sxNew").value.trim();
      if (!title) return toast("Введите название");
      const r = await post("/api/collections", { title, privacy: ov.querySelector("#sxPriv").value });
      if (r.error) return toast(r.error);
      const a = await post("/api/collections/" + r.collection.id + "/items", { place: p });
      if (a.error) return toast(a.error);
      changed = true;
      await loadSaved(); onChange && onChange(); ov.remove(); toast("Добавлено в коллекцию «" + title + "»");
    };
  }

  /* One-time migration of old favorites into a "Избранное" collection */
  async function migrateFavorites() {
    try {
      if (localStorage.getItem("tagFavMigrated")) return;
      const fav = await api("/api/favorite_locations");
      if (!Array.isArray(fav)) return;
      if (fav.length) {
        const c = await post("/api/collections", { title: "Избранное", privacy: "private" });
        if (c.collection) {
          for (const title of fav) {
            let place = null;
            try { for (const k in placesData) { place = (placesData[k] || []).find((x) => x.title === title); if (place) { place = Object.assign({}, place, { _city: k }); break; } } } catch (e) {}
            if (place) await post("/api/collections/" + c.collection.id + "/items", { place: info(place) });
          }
        }
      }
      localStorage.setItem("tagFavMigrated", "1");
    } catch (e) {}
  }

  async function shareCollection(c) {
    const ids = await pickPeople("Отправить коллекцию", c.title, "Отправить");
    if (!ids) return;
    const r = await post("/api/collections/" + c.id + "/send", { receiver_ids: ids });
    toast(r.error || "Коллекция отправлена ✓");
  }

  window.SOCIAL = { esc, api, post, toast, sheet, info, starsHtml, renderReviews, sharePlace, letsGo, pickCollection, pickPeople, loadSaved, isSaved, migrateFavorites, shareCollection };
})();

/* Generic list+create panel. Keeps every module page short:
   each page just declares its endpoint, table columns, and form fields. */

async function loadOptions(select, endpoint, labelField, valueField = "id") {
  try {
    const data = await apiGet(endpoint);
    const items = data.results || data;
    items.forEach(item => {
      select.appendChild(el("option", { value: item[valueField] }, String(item[labelField])));
    });
  } catch (e) { /* endpoint may be role-restricted; ignore */ }
}

/** Builds a flat form from a field-list. Returns `ready`, a promise that
 *  resolves once every select's optionsEndpoint has loaded -- callers that
 *  need to pre-fill values (e.g. an edit modal) should await it before
 *  setting selections, since option population is otherwise fire-and-forget. */
function buildForm(fields) {
  const form = el("div", { class: "form-inline" });
  const inputs = {};
  const pending = [];
  fields.forEach(f => {
    const row = el("div", { class: "form-row" });
    row.appendChild(el("label", {}, f.label));
    let input;
    if (f.type === "select" || f.type === "multiselect") {
      input = el("select", { "data-name": f.name });
      if (f.type === "multiselect") input.setAttribute("multiple", "multiple");
      else input.appendChild(el("option", { value: "" }, "--"));
      if (f.optionsEndpoint) pending.push(loadOptions(input, f.optionsEndpoint, f.optionsLabel || "name"));
      if (f.choices) f.choices.forEach(c => input.appendChild(el("option", { value: c }, c)));
    } else if (f.type === "textarea") {
      input = el("textarea", { "data-name": f.name, rows: "2" });
    } else if (f.type === "checkbox") {
      input = el("input", { type: "checkbox", "data-name": f.name });
    } else {
      input = el("input", { type: f.type || "text", "data-name": f.name, step: f.step || "",
        ...(f.type === "date" && f.allowPast ? { class: "allow-past" } : {}) });
    }
    inputs[f.name] = input;
    row.appendChild(input);
    form.appendChild(row);
  });
  return { form, inputs, ready: Promise.all(pending) };
}

function readForm(inputs, fields) {
  const body = {};
  fields.forEach(f => {
    const input = inputs[f.name];
    if (f.type === "multiselect") {
      const selected = Array.from(input.selectedOptions).map(o => o.value).filter(Boolean);
      if (selected.length === 0 && !f.required) return;
      body[f.name] = selected.map(Number);
      return;
    }
    let val = f.type === "checkbox" ? input.checked : input.value;
    if (val === "" ) { if (!f.required) return; }
    if (f.type === "number") val = val === "" ? null : Number(val);
    body[f.name] = val;
  });
  return body;
}

/** Pre-fills a built form's inputs from an existing record, for editing. */
function fillForm(inputs, fields, item) {
  fields.forEach(f => {
    const input = inputs[f.name];
    if (f.type === "multiselect") {
      const values = (item[f.name] || []).map(String);
      Array.from(input.options).forEach(o => { o.selected = values.includes(o.value); });
    } else if (f.type === "checkbox") {
      input.checked = !!item[f.name];
    } else {
      input.value = item[f.name] ?? "";
    }
  });
}

/* ---- shared modal, used by crudPanel's View/Edit dialogs ---- */
let _crudModalKeyHandler = null;
function closeCrudModal() {
  document.getElementById("modal-overlay")?.remove();
  if (_crudModalKeyHandler) { document.removeEventListener("keydown", _crudModalKeyHandler); _crudModalKeyHandler = null; }
}
/** `opts.wide` renders a roomier modal (660px) for detail/summary views
 *  (party profile, order/PO breakdowns) -- plain forms stay the default,
 *  compact width. Press Esc (or click the backdrop) to close. */
function showCrudModal(titleText, bodyNodes, footerNodes, opts = {}) {
  closeCrudModal();
  document.body.appendChild(el("div", { class: "modal-overlay", id: "modal-overlay", onclick: e => { if (e.target.id === "modal-overlay") closeCrudModal(); } }, [
    el("div", { class: `modal-card${opts.wide ? " modal-wide" : ""}` }, [
      el("h3", {}, titleText),
      ...bodyNodes,
      el("div", { class: "form-inline", style: "margin-top:1rem;" }, footerNodes),
    ]),
  ]));
  // Esc closes the popup — attach once per open, removed on close.
  _crudModalKeyHandler = (e) => { if (e.key === "Escape") closeCrudModal(); };
  document.addEventListener("keydown", _crudModalKeyHandler);
}

/** Generic "create a missing master-data record without leaving the page"
 *  modal. `cfg` = { title, endpoint, fields:[{name,label,type,step,required}], hint? }.
 *  `onCreated(record)` is called with the API response on success -- the
 *  caller decides what to do with it (push into a cache, select it, etc). */
function openQuickAddModal(cfg, onCreated) {
  const inputs = {};
  const errorBox = el("div", { class: "error-msg", style: "display:none;" });
  const rows = cfg.fields.map(f => {
    const input = el("input", { type: f.type || "text", ...(f.step ? { step: f.step } : {}) });
    inputs[f.name] = input;
    return field(f.label + (f.required ? " *" : ""), input);
  });
  const submit = async () => {
    const body = {};
    for (const f of cfg.fields) {
      const raw = inputs[f.name].value;
      if (f.required && !raw) { errorBox.textContent = `${f.label} is required.`; errorBox.style.display = "block"; return; }
      if (raw === "") continue;
      body[f.name] = f.type === "number" ? Number(raw) : raw;
    }
    try {
      const created = await apiPost(cfg.endpoint, body);
      closeCrudModal();
      onCreated(created);
    } catch (e) { errorBox.textContent = e.message; errorBox.style.display = "block"; }
  };
  showCrudModal(cfg.title, [
    cfg.hint ? el("p", { class: "muted", style: "margin-top:-0.5rem;" }, cfg.hint) : null,
    errorBox, ...rows,
  ], [
    el("button", { type: "button", onclick: submit }, "Create"),
    el("button", { class: "secondary", type: "button", onclick: closeCrudModal }, "Cancel"),
  ]);
  inputs[cfg.fields[0].name].focus();
}

/** Wraps a <select> with a compact "+" button that opens a quick-add
 *  modal. `leading` is an optional extra element (e.g. a color swatch)
 *  placed before the select. */
function selectWithAdd(selectNode, addTitle, onClickAdd, leading) {
  const addBtn = el("button", { class: "icon-btn", type: "button", title: addTitle, onclick: onClickAdd }, "+");
  return el("div", { class: "select-with-add" }, leading ? [leading, selectNode, addBtn] : [selectNode, addBtn]);
}

/** Best-effort singular form of a panel title, for button/modal labels
 *  ("Parties" -> "Party", "Accessories" -> "Accessory", "Colors" -> "Color"). */
function singularize(word) {
  const w = String(word || "").trim();
  if (/ies$/i.test(w)) return w.replace(/ies$/i, "y");
  if (/(ss|us|is)$/i.test(w)) return w;
  if (/(ch|sh|x|s|z)es$/i.test(w)) return w.replace(/es$/i, "");
  if (/s$/i.test(w)) return w.replace(/s$/i, "");
  return w;
}

/**
 * Renders a card with a create-form and a live table for one REST resource.
 * @param {HTMLElement} container
 * @param {object} opts { title, endpoint, columns:[{key,label,render?}], fields:[{name,label,type,choices?,optionsEndpoint?}],
 *   editable?: bool -- adds a View/Edit actions column,
 *   onView?: (item, close) => void -- custom detail view; defaults to a
 *     generic dump of `columns` when omitted }
 */
function crudPanel(container, opts) {
  const card = el("div", { class: "card" });
  const noun = opts.addLabel || singularize(opts.title);

  // The create form is no longer always on screen — it opens in a popup
  // when the user clicks "Add", keeping each panel clean and scannable.
  const addBtn = el("button", { type: "button", class: "btn-add", onclick: () => openCreate() }, [
    el("span", { class: "btn-add-plus" }, "+"), `Add ${noun}`,
  ]);
  card.appendChild(el("div", { class: "crud-header" }, [el("h3", {}, opts.title), addBtn]));

  const tableWrap = el("div", { style: "overflow-x:auto;" });
  card.appendChild(tableWrap);
  container.appendChild(card);

  function openCreate() {
    const { form: createForm, inputs: createInputs, ready } = buildForm(opts.fields);
    const errorBox = el("div", { class: "error-msg", style: "display:none;" });
    const saveBtn = el("button", {
      type: "button",
      onclick: async () => {
        try {
          const body = readForm(createInputs, opts.fields);
          await apiPost(opts.endpoint, body);
          closeCrudModal();
          notify.success(`${noun} added.`);
          await refresh();
        } catch (e) { errorBox.textContent = e.message; errorBox.style.display = "block"; }
      },
    }, `Add ${noun}`);
    const cancelBtn = el("button", { class: "secondary", type: "button", onclick: closeCrudModal }, "Cancel");
    showCrudModal(`Add ${noun}`, [errorBox, createForm], [saveBtn, cancelBtn]);
    ready.then(() => { const first = createForm.querySelector("input, select, textarea"); if (first) first.focus(); });
  }

  function openEdit(item) {
    const { form: editForm, inputs: editInputs, ready } = buildForm(opts.fields);
    ready.then(() => fillForm(editInputs, opts.fields, item));
    const errorBox = el("div", { class: "error-msg", style: "display:none;" });
    const saveBtn = el("button", {
      type: "button",
      onclick: async () => {
        try {
          const body = readForm(editInputs, opts.fields);
          await apiPatch(`${opts.endpoint}${item.id}/`, body);
          closeCrudModal();
          notify.success(`${noun} updated.`);
          await refresh();
        } catch (e) { errorBox.textContent = e.message; errorBox.style.display = "block"; }
      },
    }, "Save Changes");
    const cancelBtn = el("button", { class: "secondary", type: "button", onclick: closeCrudModal }, "Cancel");
    showCrudModal(`Edit ${opts.title}`, [errorBox, editForm], [saveBtn, cancelBtn]);
  }

  function openView(item) {
    if (opts.onView) { opts.onView(item, closeCrudModal); return; }
    const pairs = opts.columns.map(c => {
      const val = c.render ? c.render(item) : item[c.key];
      return [c.label || c.key, val instanceof HTMLElement ? val : String(val ?? "—")];
    });
    const closeBtn = el("button", { class: "secondary", type: "button", onclick: closeCrudModal }, "Close");
    showCrudModal(`${opts.title} Details`, [detailGrid(pairs)], [closeBtn], { wide: true });
  }

  async function refresh() {
    tableWrap.innerHTML = "Loading...";
    try {
      // Load every row (walk pagination) so the built-in table can search,
      // sort and paginate client-side across the whole dataset.
      const items = await fetchAll(opts.endpoint);
      const columns = opts.columns.map(c => ({
        label: c.label || c.key, key: c.key,
        render: c.render ? (row => c.render(row)) : undefined,
        value: c.key ? (row => row[c.key]) : undefined,
      }));
      if (opts.editable) {
        columns.push({
          label: "Actions", sortable: false,
          render: item => el("div", { class: "form-inline" }, [
            el("button", { class: "secondary", type: "button", onclick: () => openView(item) }, "View"),
            el("button", { type: "button", onclick: () => openEdit(item) }, "Edit"),
          ]),
        });
      }
      tableWrap.innerHTML = "";
      dataTable(tableWrap, {
        columns, rows: items, pageSize: opts.pageSize || 10,
        searchPlaceholder: `Search ${opts.title.toLowerCase()}…`, emptyText: "No records yet.",
      });
    } catch (e) {
      tableWrap.innerHTML = `<p class="error-msg">Could not load: ${e.message}</p>`;
    }
  }
  refresh();
  return { refresh };
}

/* Shared building blocks for Store's 3 purchase-creation pages
   (Order-Specific, Bulk, Customer-Supplied): one item-row renderer with a
   Material Type (Fabric/Accessory) toggle, quick-add modals for Fabric
   Type/Color/Accessory/Vendor/Party, and payload/validation helpers.
   Reuses el()/field()/selectEl()/numberInput()/removeIconBtn()/colorDot()
   (api.js) and showCrudModal()/openQuickAddModal()/selectWithAdd() (crud.js)
   -- no new modal/DOM-builder primitives invented here. */

// A roll is a physical package, never a unit -- fabric is measured in m/kg,
// accessories in pieces/cones/etc. "No. of rolls" is captured separately.
const FABRIC_UNITS = ["METERS", "YARDS", "KILOGRAMS", "GRAMS"];
const ACCESSORY_UNITS = ["PIECES", "METERS", "YARDS", "KILOGRAMS", "CONES", "DOZEN"];
const ACCESSORY_SPEC_LABEL = {
  ZIPPER: "Length (e.g. 20mm)", BUTTON: "Size (e.g. 18L)", THREAD: "Count (e.g. 40/2)",
  ELASTIC: "Width (e.g. 25mm)", LABEL: "Size / Type", OTHER: "Specification",
};
const ACCESSORY_TYPE_LABEL = t => t.charAt(0) + t.slice(1).toLowerCase();

const PURCHASE_QUICK_ADD = {
  vendor: { title: "New Vendor", endpoint: "/master/vendors/", fields: [
    { name: "company_name", label: "Company Name", required: true },
    { name: "contact_person", label: "Contact Person" },
    { name: "phone", label: "Phone", required: true },
    { name: "email", label: "Email" },
  ]},
  party: { title: "New Party / Customer", endpoint: "/master/parties/", fields: [
    { name: "name", label: "Name", required: true },
    { name: "phone", label: "Phone" },
  ]},
  fabricType: { title: "New Fabric Type", endpoint: "/master/fabric-types/", fields: [
    { name: "name", label: "Name", required: true },
    { name: "gsm", label: "GSM", type: "number", step: "0.01" },
    { name: "composition", label: "Composition (e.g. 100% Cotton)" },
  ]},
  color: { title: "New Color", endpoint: "/master/colors/", fields: [
    { name: "name", label: "Name", required: true },
    { name: "hex_code", label: "Hex Code (optional)" },
  ], hint: "Leave hex code blank to auto-generate one from the name." },
};

/** Small "nothing to pick yet" hint, styled like the Order Builder's roll
 *  warnings -- red when the list is empty everywhere, muted when it's just
 *  empty for the current filter. */
function emptyListHint(text, severe) {
  return el("div", { class: "muted", style: `margin-top:0.3rem;${severe ? "color:var(--danger);" : ""}` }, text);
}

/** Accessory quick-add is bespoke (not the generic openQuickAddModal shape)
 *  because the size_spec field's label swaps live per accessory_type.
 *  `defaultType` pre-selects the type the user was already filtering by. */
function openAccessoryQuickAdd(defaultType, onCreated) {
  const typeInput = el("select", {}, Object.keys(ACCESSORY_SPEC_LABEL).map(t => el("option", { value: t }, ACCESSORY_TYPE_LABEL(t))));
  if (defaultType) typeInput.value = defaultType;
  const nameInput = el("input", { type: "text" });
  const specLabelText = el("span", {}, ACCESSORY_SPEC_LABEL[typeInput.value]);
  const specInput = el("input", { type: "text" });
  const unitInput = el("select", {}, ACCESSORY_UNITS.map(u => el("option", { value: u }, u)));
  typeInput.onchange = () => { specLabelText.textContent = ACCESSORY_SPEC_LABEL[typeInput.value]; };
  const errorBox = el("div", { class: "error-msg", style: "display:none;" });

  const submit = async () => {
    if (!nameInput.value) { errorBox.textContent = "Name is required."; errorBox.style.display = "block"; return; }
    try {
      const created = await apiPost("/master/accessories/", {
        accessory_type: typeInput.value, name: nameInput.value, size_spec: specInput.value, unit: unitInput.value,
      });
      closeCrudModal();
      onCreated(created);
    } catch (e) { errorBox.textContent = e.message; errorBox.style.display = "block"; }
  };
  showCrudModal("New Accessory", [
    errorBox,
    field("Type", typeInput),
    field("Name *", nameInput),
    field(specLabelText, specInput),
    field("Unit", unitInput),
  ], [
    el("button", { type: "button", onclick: submit }, "Create"),
    el("button", { class: "secondary", type: "button", onclick: closeCrudModal }, "Cancel"),
  ]);
  nameInput.focus();
}

function blankPurchaseItem(nextId) {
  return { cid: nextId, material_type: "FABRIC", fabric_type: "", color: "", accessory: "", accessoryType: "", quantity: "", no_of_rolls: "1", unit: "" };
}

/** Renders one purchase-item row (Fabric or Accessory). `master` =
 *  {fabricTypes, colors, accessories}. `callbacks` = { onRerender,
 *  onRemove, removeDisabled }. */
function renderPurchaseItemRow(item, idx, master, callbacks) {
  const { onRerender, onRemove, removeDisabled } = callbacks;
  const isFabric = item.material_type === "FABRIC";

  const typeSelect = selectEl({ onchange: e => {
    item.material_type = e.target.value; item.fabric_type = ""; item.color = ""; item.accessory = ""; item.accessoryType = ""; item.unit = ""; onRerender();
  } }, [
    { value: "FABRIC", label: "Fabric" },
    { value: "ACCESSORY", label: "Accessory" },
  ], item.material_type);

  let materialFields, materialHint;

  if (isFabric) {
    materialFields = [
      field("Fabric Type", selectWithAdd(
        selectEl({ onchange: e => { item.fabric_type = e.target.value; onRerender(); } },
          master.fabricTypes.map(f => ({ value: f.id, label: f.gsm ? `${f.name} · ${f.gsm} GSM` : f.name })), item.fabric_type, "Select fabric type"),
        "Add Fabric Type",
        () => openQuickAddModal(PURCHASE_QUICK_ADD.fabricType, created => { master.fabricTypes.push(created); item.fabric_type = created.id; onRerender(); }),
      )),
      field("Color", selectWithAdd(
        selectEl({ onchange: e => { item.color = e.target.value; onRerender(); } },
          master.colors.map(c => ({ value: c.id, label: c.hex_code ? `${c.name} (${c.hex_code})` : c.name })), item.color, "Select color"),
        "Add Color",
        () => openQuickAddModal(PURCHASE_QUICK_ADD.color, created => { master.colors.push(created); item.color = created.id; onRerender(); }),
        colorDot((master.colors.find(c => String(c.id) === String(item.color)) || {}).hex_code),
      )),
      field("Unit", selectEl({ onchange: e => { item.unit = e.target.value; } }, FABRIC_UNITS.map(u => ({ value: u, label: u })), item.unit, "Select unit")),
    ];
    if (master.fabricTypes.length === 0 || master.colors.length === 0) {
      materialHint = emptyListHint("No fabric types/colors exist yet — click the + button next to a field to add one.", true);
    }
  } else {
    const filteredAccessories = item.accessoryType
      ? master.accessories.filter(a => a.accessory_type === item.accessoryType)
      : master.accessories;

    materialFields = [
      field("Accessory Type", selectEl({ onchange: e => { item.accessoryType = e.target.value; item.accessory = ""; onRerender(); } },
        Object.keys(ACCESSORY_SPEC_LABEL).map(t => ({ value: t, label: ACCESSORY_TYPE_LABEL(t) })), item.accessoryType, "All types")),
      field("Accessory", selectWithAdd(
        selectEl({ onchange: e => { item.accessory = e.target.value; onRerender(); } },
          filteredAccessories.map(a => ({ value: a.id, label: `${ACCESSORY_TYPE_LABEL(a.accessory_type)} — ${a.name}${a.size_spec ? ` (${a.size_spec})` : ""}` })),
          item.accessory, "Select accessory"),
        "Add Accessory",
        () => openAccessoryQuickAdd(item.accessoryType, created => {
          master.accessories.push(created); item.accessory = created.id; item.accessoryType = created.accessory_type; onRerender();
        }),
      )),
      field("Unit", selectEl({ onchange: e => { item.unit = e.target.value; } }, ACCESSORY_UNITS.map(u => ({ value: u, label: u })), item.unit, "Select unit")),
    ];
    if (master.accessories.length === 0) {
      materialHint = emptyListHint("No accessories exist yet — click the + button to add your first one.", true);
    } else if (filteredAccessories.length === 0) {
      materialHint = emptyListHint(`No ${ACCESSORY_TYPE_LABEL(item.accessoryType)} accessories yet — click + to add one, or clear the type filter.`, false);
    }
  }

  const quantityLabel = (isFabric && callbacks.showRolls) ? "Total Quantity (m / kg)" : "Quantity";
  // The roll hint updates LIVE via this element — typing the quantity/rolls
  // must NOT rebuild the form (that stole focus after every digit).
  const rollHint = el("div", { class: "muted", style: "margin-top:0.3rem;" });
  function updateRollHint() {
    const n = Number(item.no_of_rolls) || 1, q = Number(item.quantity) || 0;
    rollHint.textContent = (isFabric && callbacks.showRolls && n > 1 && q > 0)
      ? `Will create ${n} stock rolls ≈ ${(q / n).toFixed(2)} each.` : "";
  }
  const rowFields = [
    field("Material", typeSelect),
    ...materialFields,
    field(quantityLabel, numberInput(item.quantity, v => { item.quantity = v; updateRollHint(); }, { min: "0.01", step: "0.01" })),
  ];
  if (isFabric && callbacks.showRolls) {
    rowFields.push(field("No. of rolls", numberInput(item.no_of_rolls, v => { item.no_of_rolls = v; updateRollHint(); }, { min: "1", step: "1" })));
  }
  updateRollHint();
  const fields = el("div", { class: "form-inline" }, rowFields);

  return el("div", { class: "subcard level-color" }, [
    el("div", { class: "subcard-header" }, [
      el("span", { class: "subcard-title" }, `Item ${idx + 1}`),
      removeIconBtn("Remove item", removeDisabled, onRemove),
    ]),
    fields, rollHint, materialHint,
  ]);
}

/** Client-side validation mirroring PurchaseOrderSerializer.validate(). */
function validatePurchaseItems(items) {
  const errors = [];
  if (!items.length) errors.push("Add at least one item.");
  items.forEach((item, i) => {
    if (item.material_type === "FABRIC") {
      if (!item.fabric_type || !item.color) errors.push(`Item ${i + 1}: select a fabric type and color.`);
    } else if (!item.accessory) {
      errors.push(`Item ${i + 1}: select an accessory.`);
    }
    if (!item.quantity || Number(item.quantity) <= 0) errors.push(`Item ${i + 1}: enter a positive quantity.`);
  });
  return [...new Set(errors)];
}

function buildPurchaseItemsPayload(items) {
  return items.map(item => ({
    material_type: item.material_type,
    fabric_type: item.material_type === "FABRIC" ? Number(item.fabric_type) : null,
    color: item.material_type === "FABRIC" ? Number(item.color) : null,
    accessory: item.material_type === "ACCESSORY" ? Number(item.accessory) : null,
    quantity: Number(item.quantity),
    no_of_rolls: item.material_type === "FABRIC" ? (Number(item.no_of_rolls) || 1) : 1,
    unit: item.unit || "",
  }));
}

import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
import json
import re


# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="Factory AI - Factory Control",
    page_icon="🏭",
    layout="wide"
)


# =========================================================
# PASSWORD GATE
# =========================================================

def get_app_password():
    try:
        return st.secrets["APP_PASSWORD"]
    except Exception:
        return None


def check_password():
    expected = get_app_password()
    if not expected:
        return True
    if st.session_state.get("authenticated"):
        return True

    st.title("🔐 Factory AI — Trial Access")
    st.caption("Enter the access code shared with you for the 7-day trial.")

    with st.form("trial_login"):
        pwd = st.text_input("Access Code", type="password")
        submitted = st.form_submit_button("Enter", type="primary")

    if submitted:
        if pwd == expected:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect access code. Please try again.")

    return False


if not check_password():
    st.stop()


# =========================================================
# 7-DAY TRIAL
# =========================================================

TRIAL_FILE = Path(__file__).with_name("factory_trial.json")
TRIAL_DAYS = 7


def load_trial_start():
    if not TRIAL_FILE.exists():
        today = date.today().isoformat()
        try:
            TRIAL_FILE.write_text(json.dumps({"start_date": today}), encoding="utf-8")
        except Exception:
            pass
        return date.today()
    try:
        data = json.loads(TRIAL_FILE.read_text(encoding="utf-8"))
        return date.fromisoformat(data["start_date"])
    except Exception:
        return date.today()


trial_start = load_trial_start()
trial_end = trial_start + timedelta(days=TRIAL_DAYS)

if date.today() > trial_end:
    st.error("Your 7-day Factory AI demo has expired.")
    st.stop()

days_left = max(0, (trial_end - date.today()).days)


# =========================================================
# PERSISTENCE
# =========================================================

DATA_FILE = Path(__file__).with_name("factory_data.json")

PERSIST_KEYS = [
    "orders", "raw_receipts", "material_consumption", "production_jobs",
    "dispatch_records", "store_verifications", "order_closures", "labour_entries",
    "factory_lines", "factory_teams", "factory_products",
    "production_manager_phone", "store_manager_phone", "dispatch_manager_phone",
    "next_order",
]


def save_data():
    try:
        data = {k: st.session_state[k] for k in PERSIST_KEYS}
        DATA_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        print(f"[save_data] {e}")


def load_data():
    if not DATA_FILE.exists():
        return
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        for k, v in data.items():
            if k in PERSIST_KEYS:
                st.session_state[k] = v
    except Exception as e:
        print(f"[load_data] {e}")


# =========================================================
# SESSION DEFAULTS
# =========================================================

DEFAULTS = {
    "orders": [], "raw_receipts": [], "material_consumption": [],
    "production_jobs": [], "dispatch_records": [], "store_verifications": [],
    "order_closures": [], "labour_entries": [],
    "factory_lines": ["Line 1", "Line 2", "Line 3", "Cutting Line", "Rolling Line", "Finishing Line"],
    "factory_teams": ["Team A", "Team B", "Team C", "Shift 1", "Shift 2", "Shift 3"],
    "factory_products": ["Flat Bar", "Round Bar", "Angle", "Channel", "Square Bar"],
    "production_manager_phone": "", "store_manager_phone": "", "dispatch_manager_phone": "",
    "next_order": 1001,
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v.copy() if isinstance(v, list) else v

if "data_loaded" not in st.session_state:
    load_data()
    st.session_state["data_loaded"] = True


# =========================================================
# HELPERS
# =========================================================

def product_key(product, size):
    return f"{product} | {size}"


def line_items(order):
    items = order.get("items")
    if not items:
        items = [{"product": order.get("product", ""), "size": order.get("size", ""),
                  "quantity": float(order.get("quantity", 0)), "rate": float(order.get("rate", 0))}]
        order["items"] = items
    return [(f"{order['id']}-{i + 1}", item) for i, item in enumerate(items)]


def order_quantity(order):
    return sum(float(item["quantity"]) for _, item in line_items(order))


def dispatched_for_line(line_id):
    return sum(float(x.get("quantity", 0)) for x in st.session_state.dispatch_records if x.get("line_id") == line_id)


def line_balance(item, line_id):
    return max(0, float(item["quantity"]) - dispatched_for_line(line_id))


def order_balance(order):
    return sum(line_balance(item, lid) for lid, item in line_items(order))


def get_job(line_id):
    jobs = [j for j in st.session_state.production_jobs if j.get("line_id") == line_id]
    return jobs[-1] if jobs else None


def line_status(item, line_id):
    if line_balance(item, line_id) <= 0:
        return "COMPLETED"
    job = get_job(line_id)
    if not job:
        return "PENDING PRODUCTION"
    if job.get("status") == "READY FOR STORE VERIFICATION":
        return "STORE VERIFICATION"
    if job.get("status") == "IN PRODUCTION":
        return "IN PRODUCTION"
    return job.get("status", "PENDING")


def raw_materials():
    return sorted({r["material"] for r in st.session_state.raw_receipts})


def raw_received(m):
    return sum(float(x.get("quantity", 0)) for x in st.session_state.raw_receipts if x.get("material") == m)


def raw_consumed(m):
    return sum(float(x.get("raw_input", 0)) for x in st.session_state.material_consumption if x.get("material") == m)


def raw_available(m):
    return max(0, raw_received(m) - raw_consumed(m))


def verified_finished_stock(p, s):
    k = product_key(p, s)
    return sum(float(x.get("quantity", 0)) for x in st.session_state.store_verifications if x.get("product_key") == k)


def dispatched_for_product(p, s):
    k = product_key(p, s)
    return sum(float(x.get("quantity", 0)) for x in st.session_state.dispatch_records if x.get("product_key") == k)


def available_finished_stock(p, s):
    return max(0, verified_finished_stock(p, s) - dispatched_for_product(p, s))


def production_jobs_waiting_store():
    return [j for j in st.session_state.production_jobs if j.get("status") == "READY FOR STORE VERIFICATION"]


def dispatch_queue():
    result = []
    for order in st.session_state.orders:
        for line_id, item in line_items(order):
            ready = available_finished_stock(item["product"], item["size"])
            bal = line_balance(item, line_id)
            if ready > 0 and bal > 0:
                result.append({"order": order, "item": item, "line_id": line_id, "ready": min(ready, bal)})
    return result


def pending_production_items():
    pending = []
    for order in st.session_state.orders:
        for idx, (line_id, item) in enumerate(line_items(order), start=1):
            bal = line_balance(item, line_id)
            if bal <= 0:
                continue
            avail = available_finished_stock(item["product"], item["size"])
            required = max(0, bal - avail)
            if required <= 0:
                continue
            job = get_job(line_id)
            pending.append({
                "line_id": line_id, "order": order, "item": item, "item_num": idx,
                "balance": bal, "available": avail, "production_required": required,
                "has_job": job is not None, "job_status": job.get("status", "-") if job else "-",
            })
    return pending


def clear_all_demo_data():
    for k in ["orders", "raw_receipts", "material_consumption", "production_jobs",
              "dispatch_records", "store_verifications", "order_closures", "labour_entries"]:
        st.session_state[k] = []
    st.session_state.next_order = 1001
    for k in ["new_order_items_df", "new_order_items_editor", "last_created_order",
              "dp_order_df", "dp_order_sig", "dp_extra_df"]:
        st.session_state.pop(k, None)
    try:
        if DATA_FILE.exists():
            DATA_FILE.unlink()
    except Exception:
        pass


# =========================================================
# WHATSAPP
# =========================================================

def clean_phone(p):
    return re.sub(r"\D", "", p or "")


def wa_link(phone, message):
    return f"https://wa.me/{clean_phone(phone)}?text={quote(message)}"


def order_wa_text(order):
    lines = ["🏭 NEW PRODUCTION ORDER", "",
             f"Order: {order['id']}", f"Customer: {order['customer']}",
             f"Priority: {order.get('priority', 'Normal')}",
             f"Delivery: {order.get('pickup_date', '-')}", "", "ITEMS TO PRODUCE:"]
    for i, it in enumerate(order.get("items", []), 1):
        lines.append(f"{i}. {it['product']} | {it['size']} | {it['quantity']:,.2f} KG")
    if order.get("remarks"):
        lines += ["", f"Remarks: {order['remarks']}"]
    lines += ["", "Please confirm production line and team."]
    return "\n".join(lines)


def store_wa_text(order):
    lines = ["📦 NEW ORDER — STORE / MATERIAL CHECK", "",
             f"Order: {order['id']}", f"Customer: {order['customer']}",
             f"Delivery: {order.get('pickup_date', '-')}", "", "ITEMS:"]
    for i, it in enumerate(order.get("items", []), 1):
        lines.append(f"{i}. {it['product']} | {it['size']} | {it['quantity']:,.2f} KG")
    lines += ["", "Please confirm material and space."]
    return "\n".join(lines)


def dispatch_wa_text(order):
    lines = ["🚚 NEW ORDER — DISPATCH PLANNING", "",
             f"Order: {order['id']}", f"Customer: {order['customer']}",
             f"Priority: {order.get('priority', 'Normal')}",
             f"Delivery: {order.get('pickup_date', '-')}", "", "ITEMS:"]
    for i, it in enumerate(order.get("items", []), 1):
        ready = available_finished_stock(it["product"], it["size"])
        lines.append(f"{i}. {it['product']} | {it['size']} | Qty {it['quantity']:,.2f} KG | Verified: {ready:,.2f} KG")
    lines += ["", "Dispatch only verified stock."]
    return "\n".join(lines)


# =========================================================
# HEADER + SIDEBAR
# =========================================================

st.title("🏭 Factory AI")
st.caption("Factory Control System • Orders • Production • Material • Labour • Dispatch • AI Report")
st.info(f"Demo Mode | {days_left} day(s) remaining | No sample factory data is loaded.")

st.sidebar.title("🏭 Factory AI")

menu = st.sidebar.radio("Navigation", [
    "Owner Dashboard", "Factory Setup", "New Customer Order",
    "📤 Send to Production", "📤 Send to Store", "📤 Send to Dispatch",
    "Material Receiving", "Raw Material Stock",
    "🏭 Daily Production", "Production Line",
    "Store Verification", "Loading & Dispatch",
    "Order Balance & Closure", "Daily Factory Report", "Bills & Documents",
])

st.sidebar.divider()

if st.sidebar.button("🗑️ Reset Demo Data"):
    clear_all_demo_data()
    st.success("All demo data cleared.")
    st.rerun()

if get_app_password() and st.sidebar.button("🚪 Log Out"):
    st.session_state["authenticated"] = False
    st.rerun()


# =========================================================
# OWNER DASHBOARD
# =========================================================

if menu == "Owner Dashboard":
    st.header("📊 Owner Dashboard")

    active_jobs = [j for j in st.session_state.production_jobs if j.get("status") == "IN PRODUCTION"]
    produced = sum(float(j.get("finished", 0)) for j in st.session_state.production_jobs)
    total_balance = sum(order_balance(o) for o in st.session_state.orders)
    raw_stock = sum(raw_available(m) for m in raw_materials())
    store_pending = len(production_jobs_waiting_store())
    loading_ready = sum(x["ready"] for x in dispatch_queue())
    dispatched = sum(float(x.get("quantity", 0)) for x in st.session_state.dispatch_records)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Customer Orders", len(st.session_state.orders))
    c2.metric("Production Lines Active", len(active_jobs))
    c3.metric("Produced KG", f"{produced:,.2f}")
    c4.metric("Order Balance KG", f"{total_balance:,.2f}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Raw Material Stock", f"{raw_stock:,.2f} KG")
    c6.metric("Store Pending", store_pending)
    c7.metric("Loading Ready", f"{loading_ready:,.2f} KG")
    c8.metric("Dispatched", f"{dispatched:,.2f} KG")

    st.divider()
    st.subheader("📋 Current Orders")

    if not st.session_state.orders:
        st.info("No customer orders yet.")
    else:
        rows = []
        for order in st.session_state.orders:
            for idx, (line_id, item) in enumerate(line_items(order), 1):
                job = get_job(line_id)
                rows.append({
                    "Order": order["id"], "Item #": idx,
                    "Customer": order["customer"],
                    "Product": item["product"], "Size": item["size"],
                    "Order KG": item["quantity"],
                    "Balance KG": line_balance(item, line_id),
                    "Line": job.get("line", "-") if job else "-",
                    "Team": job.get("team", "-") if job else "-",
                    "Status": line_status(item, line_id),
                    "Priority": order.get("priority", "Normal"),
                })
        st.dataframe(rows, use_container_width=True, hide_index=True)


# =========================================================
# FACTORY SETUP
# =========================================================

elif menu == "Factory Setup":
    st.header("⚙️ Factory Setup")

    st.subheader("📱 WhatsApp Contacts")
    st.caption("With country code. Example: 919876543210")

    c1, c2, c3 = st.columns(3)
    st.session_state.production_manager_phone = c1.text_input(
        "Production Manager", value=st.session_state.production_manager_phone, placeholder="919876543210")
    st.session_state.store_manager_phone = c2.text_input(
        "Store Manager", value=st.session_state.store_manager_phone, placeholder="919876543210")
    st.session_state.dispatch_manager_phone = c3.text_input(
        "Dispatch Manager", value=st.session_state.dispatch_manager_phone, placeholder="919876543210")

    st.divider()
    lines_text = st.text_area("Production Lines", value="\n".join(st.session_state.factory_lines), height=150)
    teams_text = st.text_area("Production Teams", value="\n".join(st.session_state.factory_teams), height=150)
    products_text = st.text_area("Products", value="\n".join(st.session_state.factory_products), height=150)

    if st.button("💾 Save Factory Setup", type="primary"):
        st.session_state.factory_lines = [x.strip() for x in lines_text.splitlines() if x.strip()]
        st.session_state.factory_teams = [x.strip() for x in teams_text.splitlines() if x.strip()]
        st.session_state.factory_products = [x.strip() for x in products_text.splitlines() if x.strip()]
        save_data()
        st.success("Saved.")


# =========================================================
# NEW CUSTOMER ORDER
# =========================================================

elif menu == "New Customer Order":
    st.header("📝 New Customer Order")

    last = st.session_state.get("last_created_order")
    if last:
        st.success(f"✅ Order {last['id']} created for {last['customer']}.")

        pm = st.session_state.get("production_manager_phone", "").strip()
        sm = st.session_state.get("store_manager_phone", "").strip()
        dm = st.session_state.get("dispatch_manager_phone", "").strip()

        if pm:
            st.link_button("📱 Send to Production Manager", wa_link(pm, order_wa_text(last)), type="primary")
        if sm:
            st.link_button("📦 Send to Store Manager", wa_link(sm, store_wa_text(last)))
        if dm:
            st.link_button("🚚 Send to Dispatch Manager", wa_link(dm, dispatch_wa_text(last)))

        if st.button("✖ Close and create another"):
            st.session_state.pop("last_created_order", None)
            st.rerun()
        st.divider()

    c1, c2 = st.columns(2)
    customer = c1.text_input("Customer / Company Name")
    contact = c2.text_input("Customer Contact")

    c3, c4 = st.columns(2)
    priority = c3.selectbox("Priority", ["Normal", "High", "Urgent"])
    pickup_date = c4.date_input("Required / Pickup Date", value=date.today())
    remarks = st.text_area("Order Remarks")

    st.subheader("📦 Order Items")
    st.caption("Add as many products/sizes as needed. Click ➕ at the bottom of the table.")

    if "new_order_items_df" not in st.session_state:
        st.session_state.new_order_items_df = pd.DataFrame([
            {"product": st.session_state.factory_products[0], "size": "", "quantity": 0.0, "rate": 0.0}
        ])

    edited = st.data_editor(
        st.session_state.new_order_items_df,
        num_rows="dynamic", use_container_width=True,
        column_config={
            "product": st.column_config.SelectboxColumn("Product", options=st.session_state.factory_products, required=True),
            "size": st.column_config.TextColumn("Size / Spec", required=True),
            "quantity": st.column_config.NumberColumn("Qty KG", min_value=0.0, format="%.2f"),
            "rate": st.column_config.NumberColumn("Rate ₹/KG", min_value=0.0, format="%.2f"),
        },
        key="new_order_items_editor",
    )
    st.session_state.new_order_items_df = edited

    if st.button("✅ Create Customer Order", type="primary"):
        valid = []
        for _, row in edited.iterrows():
            p = str(row.get("product") or "").strip()
            s = str(row.get("size") or "").strip()
            try:
                q = float(row.get("quantity") or 0)
                r = float(row.get("rate") or 0)
            except (TypeError, ValueError):
                q, r = 0.0, 0.0
            if p and s and q > 0:
                valid.append({"product": p, "size": s, "quantity": q, "rate": r})

        if not customer.strip():
            st.error("Customer name is required.")
        elif not valid:
            st.error("At least one valid item required.")
        else:
            oid = f"ORD-{st.session_state.next_order}"
            order = {
                "id": oid, "customer": customer.strip(), "contact": contact.strip(),
                "priority": priority, "pickup_date": str(pickup_date),
                "remarks": remarks.strip(),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "items": valid,
            }
            st.session_state.orders.append(order)
            st.session_state.next_order += 1
            st.session_state.new_order_items_df = pd.DataFrame([
                {"product": st.session_state.factory_products[0], "size": "", "quantity": 0.0, "rate": 0.0}
            ])
            st.session_state.pop("new_order_items_editor", None)
            st.session_state.last_created_order = order
            save_data()
            st.rerun()


# =========================================================
# SEND TO PRODUCTION / STORE / DISPATCH
# =========================================================

elif menu == "📤 Send to Production":
    st.header("📤 Send Orders to Production Manager")
    phone = st.session_state.get("production_manager_phone", "").strip()

    if not phone:
        st.warning("Set the Production Manager WhatsApp number in Factory Setup.")
    elif not st.session_state.orders:
        st.info("No orders yet.")
    else:
        for order in reversed(st.session_state.orders):
            with st.expander(f"{order['id']} | {order['customer']}"):
                preview = order_wa_text(order)
                st.code(preview, language="text")
                st.link_button("📱 Open WhatsApp", wa_link(phone, preview), type="primary")


elif menu == "📤 Send to Store":
    st.header("📦 Send Orders to Store Manager")
    phone = st.session_state.get("store_manager_phone", "").strip()

    if not phone:
        st.warning("Set the Store Manager WhatsApp number in Factory Setup.")
    elif not st.session_state.orders:
        st.info("No orders yet.")
    else:
        for order in reversed(st.session_state.orders):
            with st.expander(f"{order['id']} | {order['customer']}"):
                preview = store_wa_text(order)
                st.code(preview, language="text")
                st.link_button("📦 Open WhatsApp", wa_link(phone, preview), type="primary")


elif menu == "📤 Send to Dispatch":
    st.header("🚚 Send Orders to Dispatch Manager")
    phone = st.session_state.get("dispatch_manager_phone", "").strip()

    if not phone:
        st.warning("Set the Dispatch Manager WhatsApp number in Factory Setup.")
    elif not st.session_state.orders:
        st.info("No orders yet.")
    else:
        for order in reversed(st.session_state.orders):
            with st.expander(f"{order['id']} | {order['customer']}"):
                preview = dispatch_wa_text(order)
                st.code(preview, language="text")
                st.link_button("🚚 Open WhatsApp", wa_link(phone, preview), type="primary")


# =========================================================
# MATERIAL RECEIVING
# =========================================================

elif menu == "Material Receiving":
    st.header("📥 Raw Material Receiving")

    with st.form("mat_recv"):
        c1, c2 = st.columns(2)
        supplier = c1.text_input("Supplier")
        material = c2.text_input("Material / Grade", placeholder="MS Billet")

        c3, c4 = st.columns(2)
        grn = c3.text_input("GRN / Receipt No")
        vehicle = c4.text_input("Vehicle No")

        c5, c6, c7 = st.columns(3)
        qty = c5.number_input("Quantity KG", min_value=0.0, step=100.0)
        rate = c6.number_input("Rate ₹/KG", min_value=0.0, step=1.0)
        rdate = c7.date_input("Date", value=date.today())

        received_by = st.text_input("Received By")
        location = st.text_input("Location")
        remarks = st.text_area("Remarks")
        ok = st.form_submit_button("📥 Receive Material")

    if ok:
        if not material.strip():
            st.error("Material required.")
        elif qty <= 0:
            st.error("Quantity must be > 0.")
        else:
            st.session_state.raw_receipts.append({
                "supplier": supplier.strip(), "material": material.strip(),
                "grn": grn.strip(), "vehicle": vehicle.strip(),
                "quantity": qty, "rate": rate, "value": qty * rate,
                "date": str(rdate), "received_by": received_by.strip(),
                "location": location.strip(), "remarks": remarks.strip(),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            save_data()
            st.success(f"{qty:,.2f} KG received.")


# =========================================================
# RAW MATERIAL STOCK
# =========================================================

elif menu == "Raw Material Stock":
    st.header("📦 Raw Material Stock")
    ms = raw_materials()

    if not ms:
        st.info("No raw material yet.")
    else:
        rows = [{"Material": m, "Received KG": raw_received(m),
                 "Consumed KG": raw_consumed(m), "Available KG": raw_available(m)} for m in ms]
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.subheader("Receiving History")
        st.dataframe(st.session_state.raw_receipts, use_container_width=True, hide_index=True)


# =========================================================
# DAILY PRODUCTION
# =========================================================

elif menu == "🏭 Daily Production":
    st.header("🏭 Daily Production Plan")
    today_str = date.today().strftime("%d %b %Y")
    st.caption(f"Today: **{today_str}** — plan production and send to Production Manager.")

    pending = pending_production_items()

    # ---- Section A: from customer orders ----
    st.subheader("📋 A. From Customer Orders")
    st.caption("Edit **Make Today KG** to produce more or less than the required balance. "
               "Untick items you don't want to produce today.")

    if not pending:
        st.info("No pending order items. Use Section B below to plan stock production.")
        order_selected = pd.DataFrame()
    else:
        sig = tuple(sorted((p["line_id"], p["has_job"]) for p in pending))
        if st.session_state.get("dp_order_sig") != sig or "dp_order_df" not in st.session_state:
            rows = []
            for p in pending:
                rows.append({
                    "Include": not p["has_job"],
                    "Product": p["item"]["product"],
                    "Size": p["item"]["size"],
                    "Order": p["order"]["id"],
                    "Customer": p["order"]["customer"],
                    "Priority": p["order"].get("priority", "Normal"),
                    "Required KG": float(p["production_required"]),
                    "Make Today KG": float(p["production_required"]),
                    "Status": "🆕 No Job" if not p["has_job"] else f"⚙️ {p['job_status']}",
                    "_line_id": p["line_id"],
                })
            st.session_state.dp_order_df = pd.DataFrame(rows)
            st.session_state.dp_order_sig = sig

        order_ed = st.data_editor(
            st.session_state.dp_order_df,
            hide_index=True, use_container_width=True,
            disabled=["Product", "Size", "Order", "Customer", "Priority", "Required KG", "Status", "_line_id"],
            column_config={
                "Include": st.column_config.CheckboxColumn("Include", default=True),
                "Required KG": st.column_config.NumberColumn(format="%.2f"),
                "Make Today KG": st.column_config.NumberColumn("Make Today KG", min_value=0.0, format="%.2f"),
                "_line_id": st.column_config.TextColumn("Line ID"),
            },
            key="dp_order_editor",
        )
        st.session_state.dp_order_df = order_ed
        order_selected = order_ed[(order_ed["Include"] == True) & (order_ed["Make Today KG"] > 0)].copy()

    st.divider()

    # ---- Section B: extra stock production ----
    st.subheader("➕ B. Extra Production (for Stock)")
    st.caption("Add any sizes not linked to customer orders. These go in the WhatsApp plan only "
               "(no tracked jobs created).")

    if "dp_extra_df" not in st.session_state:
        st.session_state.dp_extra_df = pd.DataFrame([
            {"Product": st.session_state.factory_products[0], "Size": "", "Qty KG": 0.0}
        ])

    extra_ed = st.data_editor(
        st.session_state.dp_extra_df,
        num_rows="dynamic", use_container_width=True,
        column_config={
            "Product": st.column_config.SelectboxColumn("Product", options=st.session_state.factory_products),
            "Size": st.column_config.TextColumn("Size"),
            "Qty KG": st.column_config.NumberColumn("Qty KG", min_value=0.0, format="%.2f"),
        },
        key="dp_extra_editor",
    )
    st.session_state.dp_extra_df = extra_ed
    extra_selected = extra_ed[extra_ed["Qty KG"] > 0].copy()

    st.divider()

    # ---- Preview + actions ----
    if order_selected.empty and extra_selected.empty:
        st.info("👆 Tick items in Section A or add quantities in Section B to build the plan.")
    else:
        lines = ["🏭 DAILY PRODUCTION PLAN", f"Date: {today_str}", ""]
        total = 0.0

        if not order_selected.empty:
            lines.append("FROM CUSTOMER ORDERS:")
            for _, r in order_selected.iterrows():
                lines.append(f"• {r['Product']} | {r['Size']} | {r['Make Today KG']:,.2f} KG | {r['Order']} ({r['Customer']}) | {r['Priority']}")
                total += float(r["Make Today KG"])
            lines.append("")

        if not extra_selected.empty:
            lines.append("EXTRA STOCK PRODUCTION:")
            for _, r in extra_selected.iterrows():
                lines.append(f"• {r['Product']} | {r['Size']} | {r['Qty KG']:,.2f} KG")
                total += float(r["Qty KG"])
            lines.append("")

        lines += [f"Total: {total:,.2f} KG", "", "Please confirm line and team."]
        preview = "\n".join(lines)

        st.subheader(f"📱 Preview — Total {total:,.2f} KG")
        st.code(preview, language="text")

        c1, c2 = st.columns(2)

        with c1:
            if not order_selected.empty:
                if st.button("⚙️ Create Production Jobs (Order Items)", type="primary", use_container_width=True):
                    created = skipped = 0
                    for _, r in order_selected.iterrows():
                        lid = r["_line_id"]
                        if not lid:
                            continue
                        if get_job(lid):
                            skipped += 1
                            continue
                        st.session_state.production_jobs.append({
                            "line_id": lid, "order_id": r["Order"],
                            "product": r["Product"], "size": r["Size"],
                            "required": float(r["Make Today KG"]),
                            "finished": 0.0, "wastage": 0.0, "damage": 0.0, "scrap": 0.0,
                            "line": "", "team": "", "status": "PLANNED",
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })
                        created += 1
                    save_data()
                    st.success(f"Created {created} job(s). Skipped {skipped}. Go to Production Line.")
                    st.rerun()
            else:
                st.info("Tracked jobs are created only for order items.")

        with c2:
            pm = st.session_state.get("production_manager_phone", "").strip()
            if pm:
                st.link_button("📱 Send Plan via WhatsApp", wa_link(pm, preview), type="primary", use_container_width=True)
            else:
                st.warning("Set Production Manager WhatsApp in Factory Setup.")


# =========================================================
# PRODUCTION LINE
# =========================================================

elif menu == "Production Line":
    st.header("🏭 Production Line Control")

    if not st.session_state.production_jobs:
        st.info("No jobs yet. Create from Daily Production.")
    else:
        for i, job in enumerate(st.session_state.production_jobs):
            order = next((o for o in st.session_state.orders if o["id"] == job["order_id"]), None)
            if not order:
                continue

            with st.expander(f"{job['line_id']} | {order['customer']} | {job['product']} | {job['status']}"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Required", f"{job['required']:,.2f} KG")
                c2.metric("Produced", f"{job['finished']:,.2f} KG")
                c3.metric("Wastage", f"{job['wastage']:,.2f} KG")
                c4.metric("Damage", f"{job['damage']:,.2f} KG")

                line = st.selectbox("Line", st.session_state.factory_lines, key=f"line_{i}")
                team = st.selectbox("Team", st.session_state.factory_teams, key=f"team_{i}")

                if not raw_materials():
                    st.warning("Receive raw material first.")
                    continue

                material = st.selectbox("Raw Material", raw_materials(), key=f"mat_{i}")
                avail = raw_available(material)
                st.caption(f"Available: {avail:,.2f} KG")

                c5, c6 = st.columns(2)
                raw_in = c5.number_input("Raw Input KG", min_value=0.0, max_value=max(avail, 0.0), step=100.0, key=f"raw_{i}")
                finished = c6.number_input("Finished KG", min_value=0.0, step=100.0, key=f"fin_{i}")

                c7, c8, c9 = st.columns(3)
                waste = c7.number_input("Wastage KG", min_value=0.0, step=1.0, key=f"wst_{i}")
                damage = c8.number_input("Damage KG", min_value=0.0, step=1.0, key=f"dmg_{i}")
                scrap = c9.number_input("Scrap KG", min_value=0.0, step=1.0, key=f"scr_{i}")

                mat_rate = st.number_input("Material ₹/KG", min_value=0.0, step=1.0, key=f"mrt_{i}")

                if st.button("▶️ Record Production", key=f"rec_{i}"):
                    if finished <= 0:
                        st.error("Finished must be > 0.")
                    elif raw_in <= 0:
                        st.error("Raw input must be > 0.")
                    elif raw_in > avail:
                        st.error("Insufficient raw material.")
                    elif finished + waste + damage + scrap > raw_in + 0.0001:
                        st.error("Output sum > raw input.")
                    else:
                        rem = max(0, job["required"] - job["finished"])
                        if finished > rem:
                            st.error(f"Max {rem:,.2f} KG remaining.")
                        else:
                            job["line"] = line
                            job["team"] = team
                            job["finished"] += finished
                            job["wastage"] += waste
                            job["damage"] += damage
                            job["scrap"] += scrap
                            job["status"] = "READY FOR STORE VERIFICATION" if job["finished"] >= job["required"] else "IN PRODUCTION"

                            st.session_state.material_consumption.append({
                                "line_id": job["line_id"], "order_id": job["order_id"],
                                "product": job["product"], "size": job["size"],
                                "material": material, "raw_input": raw_in, "finished": finished,
                                "wastage": waste, "damage": damage, "scrap": scrap,
                                "material_rate": mat_rate, "material_cost": raw_in * mat_rate,
                                "line": line, "team": team, "date": str(date.today()),
                                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            })
                            save_data()
                            st.success(f"{finished:,.2f} KG recorded.")
                            st.rerun()

                st.divider()
                st.subheader("👷 Labour")

                c10, c11, c12 = st.columns(3)
                worker = c10.text_input("Worker", key=f"w_{i}")
                hours = c11.number_input("Hours", min_value=0.0, step=1.0, key=f"h_{i}")
                hourly = c12.number_input("₹/Hour", min_value=0.0, step=10.0, key=f"hr_{i}")

                if st.button("👷 Add Labour", key=f"lb_{i}"):
                    if worker.strip() and hours > 0:
                        st.session_state.labour_entries.append({
                            "line_id": job["line_id"], "order_id": job["order_id"],
                            "worker": worker.strip(), "hours": hours, "rate": hourly,
                            "cost": hours * hourly, "date": str(date.today()),
                        })
                        save_data()
                        st.success("Labour added.")
                    else:
                        st.error("Worker + hours required.")


# =========================================================
# STORE VERIFICATION
# =========================================================

elif menu == "Store Verification":
    st.header("📦 Store Verification")
    st.caption("⚠️ **Production Ready ≠ Dispatch Ready.** Only verified quantity is dispatchable.")

    jobs = production_jobs_waiting_store()

    if not jobs:
        st.info("No production waiting for verification.")
    else:
        for i, job in enumerate(jobs):
            with st.expander(f"{job['line_id']} | {job['product']} | {job['size']} | {job['finished']:,.2f} KG"):
                qty = st.number_input("Physical Verified KG", min_value=0.0,
                                      max_value=float(job["finished"]),
                                      value=float(job["finished"]), key=f"vq_{i}")
                loc = st.text_input("Location", key=f"vl_{i}")
                ver = st.text_input("Verified By", key=f"vb_{i}")
                notes = st.text_area("Notes", key=f"vn_{i}")

                if st.button("✅ Verify & Move to Finished Stock", key=f"v_{i}"):
                    if qty <= 0:
                        st.error("Quantity must be > 0.")
                    else:
                        shortfall = job["finished"] - qty
                        st.session_state.store_verifications.append({
                            "line_id": job["line_id"], "order_id": job["order_id"],
                            "product": job["product"], "size": job["size"],
                            "product_key": product_key(job["product"], job["size"]),
                            "quantity": qty, "location": loc.strip(),
                            "verifier": ver.strip(), "notes": notes.strip(),
                            "date": str(date.today()),
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })
                        job["status"] = "VERIFIED" if qty >= job["finished"] else "PARTIALLY VERIFIED"
                        save_data()

                        if shortfall > 0:
                            st.warning(f"⚠️ Verified {qty:,.2f} KG vs claimed {job['finished']:,.2f} KG. "
                                       f"Shortfall of {shortfall:,.2f} KG.")
                        else:
                            st.success(f"{qty:,.2f} KG verified.")
                        st.rerun()


# =========================================================
# LOADING & DISPATCH
# =========================================================

elif menu == "Loading & Dispatch":
    st.header("🚚 Loading & Dispatch")

    queue = dispatch_queue()

    if not queue:
        st.info("No verified stock ready for dispatch.")
    else:
        for i, entry in enumerate(queue):
            order, item, lid, ready = entry["order"], entry["item"], entry["line_id"], entry["ready"]
            with st.expander(f"{lid} | {order['customer']} | {item['product']} | {item['size']} | Ready {ready:,.2f} KG"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Balance", f"{line_balance(item, lid):,.2f} KG")
                c2.metric("Verified Ready", f"{ready:,.2f} KG")
                c3.metric("Rate", f"₹{item['rate']:,.2f}")
                c4.metric("Priority", order.get("priority", "Normal"))

                c5, c6 = st.columns(2)
                truck = c5.text_input("Truck No", key=f"t_{i}")
                driver = c6.text_input("Driver", key=f"d_{i}")

                load_qty = st.number_input("Loading KG", min_value=0.0,
                                           max_value=float(ready), value=float(ready), step=100.0, key=f"lq_{i}")
                d_rate = st.number_input("Rate ₹/KG", min_value=0.0, value=float(item["rate"]), step=1.0, key=f"dr_{i}")
                d_notes = st.text_area("Remarks", key=f"dn_{i}")

                if st.button("🚚 Confirm Dispatch", key=f"disp_{i}"):
                    if load_qty <= 0:
                        st.error("Quantity must be > 0.")
                    else:
                        st.session_state.dispatch_records.append({
                            "line_id": lid, "order_id": order["id"],
                            "customer": order["customer"],
                            "product": item["product"], "size": item["size"],
                            "product_key": product_key(item["product"], item["size"]),
                            "quantity": load_qty, "rate": d_rate, "value": load_qty * d_rate,
                            "truck": truck.strip(), "driver": driver.strip(),
                            "remarks": d_notes.strip(), "date": str(date.today()),
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })
                        save_data()
                        st.success(f"{load_qty:,.2f} KG dispatched.")
                        st.rerun()


# =========================================================
# ORDER BALANCE
# =========================================================

elif menu == "Order Balance & Closure":
    st.header("📌 Order Balance & Closure")

    if not st.session_state.orders:
        st.info("No orders.")
    else:
        for i, order in enumerate(st.session_state.orders):
            bal = order_balance(order)
            qty = order_quantity(order)
            with st.expander(f"{order['id']} | {order['customer']} | Balance {bal:,.2f} KG"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Order Qty", f"{qty:,.2f} KG")
                c2.metric("Dispatched", f"{qty - bal:,.2f} KG")
                c3.metric("Balance", f"{bal:,.2f} KG")

                st.subheader("Line Items")
                rows = []
                for idx, (lid, item) in enumerate(line_items(order), 1):
                    lb = line_balance(item, lid)
                    rows.append({"Item #": idx, "Line ID": lid, "Product": item["product"],
                                 "Size": item["size"], "Qty KG": item["quantity"],
                                 "Dispatched KG": item["quantity"] - lb, "Balance KG": lb,
                                 "Status": line_status(item, lid)})
                st.dataframe(rows, use_container_width=True, hide_index=True)

                note = st.text_area("Closure Note", key=f"cl_{i}")
                if st.button("🔒 Close Order", key=f"c_{i}"):
                    st.session_state.order_closures.append({
                        "order_id": order["id"], "date": str(date.today()),
                        "balance_at_closure": bal, "note": note.strip(),
                    })
                    save_data()
                    st.success(f"{order['id']} closed.")


# =========================================================
# DAILY FACTORY REPORT
# =========================================================

elif menu == "Daily Factory Report":
    st.header("🤖 Daily Factory AI Report")

    rd = st.date_input("Report Date", value=date.today())
    rds = str(rd)

    raw_recv = sum(float(x.get("quantity", 0)) for x in st.session_state.raw_receipts if x.get("date") == rds)
    raw_cons = sum(float(x.get("raw_input", 0)) for x in st.session_state.material_consumption if x.get("date") == rds)
    mat_cost = sum(float(x.get("material_cost", 0)) for x in st.session_state.material_consumption if x.get("date") == rds)
    finished = sum(float(x.get("finished", 0)) for x in st.session_state.material_consumption if x.get("date") == rds)
    wastage = sum(float(x.get("wastage", 0)) for x in st.session_state.material_consumption if x.get("date") == rds)
    damage = sum(float(x.get("damage", 0)) for x in st.session_state.material_consumption if x.get("date") == rds)
    scrap = sum(float(x.get("scrap", 0)) for x in st.session_state.material_consumption if x.get("date") == rds)
    labour = sum(float(x.get("cost", 0)) for x in st.session_state.labour_entries if x.get("date") == rds)
    verified = sum(float(x.get("quantity", 0)) for x in st.session_state.store_verifications if x.get("date") == rds)
    dispatched = sum(float(x.get("quantity", 0)) for x in st.session_state.dispatch_records if x.get("date") == rds)
    disp_value = sum(float(x.get("value", 0)) for x in st.session_state.dispatch_records if x.get("date") == rds)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Raw Received", f"{raw_recv:,.2f} KG")
    c2.metric("Raw Consumed", f"{raw_cons:,.2f} KG")
    c3.metric("Finished", f"{finished:,.2f} KG")
    c4.metric("Dispatched", f"{dispatched:,.2f} KG")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Wastage", f"{wastage:,.2f} KG")
    c6.metric("Damage", f"{damage:,.2f} KG")
    c7.metric("Labour Cost", f"₹{labour:,.2f}")
    c8.metric("Dispatch Value", f"₹{disp_value:,.2f}")

    active_jobs = len([j for j in st.session_state.production_jobs if j.get("status") == "IN PRODUCTION"])
    store_pending = len(production_jobs_waiting_store())
    loading_ready = sum(x["ready"] for x in dispatch_queue())

    st.divider()
    st.subheader("📱 WhatsApp-Ready Daily Report")

    report = f"""
🏭 FACTORY AI — DAILY REPORT

Date: {rds}

PRODUCTION
Finished: {finished:,.2f} KG

MATERIAL
Raw Received: {raw_recv:,.2f} KG
Raw Consumed: {raw_cons:,.2f} KG
Wastage: {wastage:,.2f} KG
Damage: {damage:,.2f} KG
Scrap: {scrap:,.2f} KG

COST
Material: ₹{mat_cost:,.2f}
Labour: ₹{labour:,.2f}

STORE
Verified: {verified:,.2f} KG

DISPATCH
Dispatched: {dispatched:,.2f} KG
Value: ₹{disp_value:,.2f}

STATUS
Active Jobs: {active_jobs}
Store Pending: {store_pending}
Loading Ready: {loading_ready:,.2f} KG
"""
    st.code(report, language="text")
    st.download_button("📥 Download", report, file_name=f"report_{rds}.txt")


# =========================================================
# BILLS
# =========================================================

elif menu == "Bills & Documents":
    st.header("📄 Bills & Documents")

    if not st.session_state.dispatch_records:
        st.info("No dispatch records.")
    else:
        st.dataframe(st.session_state.dispatch_records, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("🧾 Dispatch Bill")
        oids = list(dict.fromkeys(x["order_id"] for x in st.session_state.dispatch_records))
        sel = st.selectbox("Order", oids)
        for r in [x for x in st.session_state.dispatch_records if x["order_id"] == sel]:
            st.markdown(f"""
**{r['order_id']}** — {r.get('customer', '-')}  
{r['product']} | {r['size']} | {r['quantity']:,.2f} KG @ ₹{r['rate']:,.2f} = **₹{r['value']:,.2f}**  
Truck: {r['truck']} | Driver: {r['driver']} | {r['date']}
""")


# =========================================================
# FOOTER
# =========================================================

save_data()

st.divider()
st.caption("Factory AI • Production & Dispatch Control • Designed for manufacturing operations")
import os
import random
from datetime import datetime

import pandas as pd
import streamlit as st

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Smart School Communication System", layout="wide")

DATA_FILE = "updated_student_dataset.csv"
USERS_FILE = "users.csv"
ATTENDANCE_FILE = "attendance_updates.csv"
MESSAGE_LOG_FILE = "message_log.csv"
STATUS_LOG_FILE = "status_update_log.csv"

REQUIRED_STUDENT_COLS = ["roll_no", "name", "mobile_number", "class", "section", "student_status"]
REQUIRED_USER_COLS = ["username", "password", "role", "name", "mobile_number"]
REQUIRED_ATTENDANCE_COLS = ["roll_no", "student_status", "date"]


# =========================
# HELPERS
# =========================
def normalize_roll(series):
    return series.astype(str).str.strip().str.replace(".0", "", regex=False)

def normalize_mobile(value):
    value = str(value).strip().replace(" ", "")
    if value.startswith("+91"):
        return value
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 10:
        digits = digits[-10:]
        return "+91" + digits
    return value

def ensure_base_files():
    if not os.path.exists(MESSAGE_LOG_FILE):
        pd.DataFrame(columns=[
            "date_time", "teacher_name", "teacher_username", "teacher_role",
            "teacher_id", "roll_no", "student_name", "class", "section",
            "student_status", "message_type", "message_text", "delivery_status"
        ]).to_csv(MESSAGE_LOG_FILE, index=False)

    if not os.path.exists(STATUS_LOG_FILE):
        pd.DataFrame(columns=[
            "date_time", "updated_by_name", "updated_by_username", "updated_by_role",
            "roll_no", "student_name", "old_status", "new_status", "source"
        ]).to_csv(STATUS_LOG_FILE, index=False)

def validate_required_file(path, required_cols, label):
    if not os.path.exists(path):
        st.error(f"{label} file not found: {path}")
        st.stop()

    try:
        df = pd.read_csv(path)
    except Exception as e:
        st.error(f"Could not read {label}: {e}")
        st.stop()

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        st.error(f"{label} missing columns: {missing}")
        st.stop()

    return df

@st.cache_data
def load_students():
    df = pd.read_csv(DATA_FILE)
    df["roll_no"] = normalize_roll(df["roll_no"])
    for col in ["name", "mobile_number", "class", "section", "student_status"]:
        df[col] = df[col].astype(str).str.strip()
    df["mobile_number"] = df["mobile_number"].apply(normalize_mobile)
    return df

@st.cache_data
def load_users():
    df = pd.read_csv(USERS_FILE)
    for col in ["username", "password", "role", "name", "mobile_number"]:
        df[col] = df[col].astype(str).str.strip()
    df["mobile_number"] = df["mobile_number"].apply(normalize_mobile)
    return df

def save_students(df):
    df.to_csv(DATA_FILE, index=False)
    st.cache_data.clear()

def append_csv_row(file_path, new_df):
    if os.path.exists(file_path):
        try:
            old = pd.read_csv(file_path)
            combined = pd.concat([old, new_df], ignore_index=True)
        except Exception:
            combined = new_df
    else:
        combined = new_df
    combined.to_csv(file_path, index=False)

def login_user(username, password, mobile_number, users_df):
    mobile_number = normalize_mobile(mobile_number)
    match = users_df[
        (users_df["username"] == username.strip()) &
        (users_df["password"] == password.strip()) &
        (users_df["mobile_number"] == mobile_number)
    ]
    if len(match) == 1:
        row = match.iloc[0]
        return {
            "username": row["username"],
            "role": row["role"],
            "name": row["name"],
            "mobile_number": row["mobile_number"]
        }
    return None

def run_attendance_sync(current_user):
    if not os.path.exists(ATTENDANCE_FILE):
        return 0, 0, "Attendance file not found"

    try:
        attendance_df = pd.read_csv(ATTENDANCE_FILE)
    except Exception as e:
        return 0, 0, f"Attendance file read error: {e}"

    missing = [c for c in REQUIRED_ATTENDANCE_COLS if c not in attendance_df.columns]
    if missing:
        return 0, 0, f"Attendance file missing columns: {missing}"

    students_df = load_students().copy()
    students_df["roll_no"] = normalize_roll(students_df["roll_no"])

    attendance_df["roll_no"] = normalize_roll(attendance_df["roll_no"])
    attendance_df["student_status"] = attendance_df["student_status"].astype(str).str.strip()
    attendance_df["date"] = attendance_df["date"].astype(str).str.strip()

    updated_count = 0
    invalid_count = 0
    log_rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    latest_attendance = attendance_df.drop_duplicates(subset=["roll_no"], keep="last")

    for _, row in latest_attendance.iterrows():
        roll = row["roll_no"]
        new_status = row["student_status"]

        mask = students_df["roll_no"] == roll
        if mask.any():
            old_status = str(students_df.loc[mask, "student_status"].values[0])
            student_name = str(students_df.loc[mask, "name"].values[0])

            if old_status != new_status:
                students_df.loc[mask, "student_status"] = new_status
                updated_count += 1

                log_rows.append({
                    "date_time": now,
                    "updated_by_name": current_user["name"],
                    "updated_by_username": current_user["username"],
                    "updated_by_role": current_user["role"],
                    "roll_no": roll,
                    "student_name": student_name,
                    "old_status": old_status,
                    "new_status": new_status,
                    "source": "attendance_csv_sync"
                })
        else:
            invalid_count += 1

    save_students(students_df)

    if log_rows:
        append_csv_row(STATUS_LOG_FILE, pd.DataFrame(log_rows))

    return updated_count, invalid_count, "Attendance sync completed"

def build_sidebar_filters(df):
    st.sidebar.header("🔍 Filter Students")

    class_options = ["All"] + sorted(df["class"].dropna().unique().tolist())
    section_options = ["All"] + sorted(df["section"].dropna().unique().tolist())
    status_options = ["All"] + sorted(df["student_status"].dropna().unique().tolist())

    selected_class = st.sidebar.selectbox("Select Class", class_options)
    selected_section = st.sidebar.selectbox("Select Section", section_options)
    selected_status = st.sidebar.selectbox("Select Student Status", status_options)
    roll_search = st.sidebar.text_input("Enter Roll No (optional)")

    filtered_df = df.copy()

    if selected_class != "All":
        filtered_df = filtered_df[filtered_df["class"] == selected_class]

    if selected_section != "All":
        filtered_df = filtered_df[filtered_df["section"] == selected_section]

    if selected_status != "All":
        filtered_df = filtered_df[filtered_df["student_status"] == selected_status]

    if roll_search.strip():
        filtered_df = filtered_df[
            filtered_df["roll_no"].str.contains(roll_search.strip().replace(".0", ""), case=False, na=False)
        ]

    return filtered_df

def show_export_buttons():
    st.subheader("⬇️ Export Logs")

    col1, col2 = st.columns(2)

    with col1:
        if os.path.exists(MESSAGE_LOG_FILE):
            with open(MESSAGE_LOG_FILE, "rb") as f:
                st.download_button(
                    "Download Message Logs CSV",
                    data=f,
                    file_name="message_log.csv",
                    mime="text/csv"
                )

    with col2:
        if os.path.exists(STATUS_LOG_FILE):
            with open(STATUS_LOG_FILE, "rb") as f:
                st.download_button(
                    "Download Status Logs CSV",
                    data=f,
                    file_name="status_update_log.csv",
                    mime="text/csv"
                )


# =========================
# INIT
# =========================
ensure_base_files()
validate_required_file(DATA_FILE, REQUIRED_STUDENT_COLS, "Student dataset")
validate_required_file(USERS_FILE, REQUIRED_USER_COLS, "Users file")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "user" not in st.session_state:
    st.session_state.user = None

if "attendance_sync_done" not in st.session_state:
    st.session_state.attendance_sync_done = False

if "recent_message" not in st.session_state:
    st.session_state.recent_message = None

if "otp_sent" not in st.session_state:
    st.session_state.otp_sent = False

if "generated_otp" not in st.session_state:
    st.session_state.generated_otp = None

if "verified_user" not in st.session_state:
    st.session_state.verified_user = None


# =========================
# LOGIN PAGE WITH DEMO OTP
# =========================
if not st.session_state.logged_in:
    st.title("🔐 Smart School Communication System")
    st.subheader("Authorized Staff Login with Demo OTP")

    users_df = load_users()

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    mobile_number = st.text_input("Mobile Number")
    otp_input = st.text_input("Enter OTP", max_chars=6)

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Generate OTP"):
            user = login_user(username, password, mobile_number, users_df)
            if user:
                otp = str(random.randint(100000, 999999))
                st.session_state.generated_otp = otp
                st.session_state.otp_sent = True
                st.session_state.verified_user = user

                st.success("Demo OTP generated successfully.")
                st.info(f"Your Demo OTP is: {otp}")
            else:
                st.error("Invalid username, password, or mobile number.")

    with col2:
        if st.button("Verify OTP & Login"):
            if not st.session_state.otp_sent:
                st.warning("First generate OTP.")
            elif otp_input.strip() == "":
                st.warning("Enter OTP.")
            elif otp_input.strip() == str(st.session_state.generated_otp):
                st.session_state.logged_in = True
                st.session_state.user = st.session_state.verified_user
                st.session_state.attendance_sync_done = False
                st.session_state.recent_message = None
                st.session_state.otp_sent = False
                st.session_state.generated_otp = None
                st.session_state.verified_user = None
                st.success("Login successful.")
                st.rerun()
            else:
                st.error("Invalid OTP.")

    st.caption("Demo OTP system: Project demonstration purpose only.")
    st.stop()


# =========================
# MAIN APP
# =========================
current_user = st.session_state.user
students_df = load_students()

if not st.session_state.attendance_sync_done:
    updated_count, invalid_count, msg = run_attendance_sync(current_user)
    st.session_state.attendance_sync_done = True
    if "completed" in msg.lower():
        if updated_count > 0 or invalid_count > 0:
            st.success(f"{msg} | Updated: {updated_count} | Invalid Roll Nos: {invalid_count}")
        else:
            st.info("Attendance sync checked. No status changes found.")
    else:
        st.warning(msg)

st.title("📘 Smart School Communication System")
st.write(f"Welcome, **{current_user['name']}** ({current_user['role'].capitalize()})")

top1, top2 = st.columns([6, 1])
with top2:
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.session_state.attendance_sync_done = False
        st.session_state.recent_message = None
        st.session_state.otp_sent = False
        st.session_state.generated_otp = None
        st.session_state.verified_user = None
        st.rerun()

filtered_df = build_sidebar_filters(students_df)

# Dashboard
st.subheader("📊 Dashboard")
d1, d2, d3, d4 = st.columns(4)
d1.metric("Total Students", len(students_df))
d2.metric("Present", int((students_df["student_status"].str.lower() == "present").sum()))
d3.metric("Absent", int((students_df["student_status"].str.lower() == "absent").sum()))
d4.metric("Leave", int((students_df["student_status"].str.lower() == "leave").sum()))

# Student list
st.subheader("🎯 Filtered Student List")
display_df = filtered_df[["roll_no", "name", "class", "section", "student_status"]].copy()
st.dataframe(display_df, width="stretch")
st.info(f"Total filtered students: {len(filtered_df)}")
st.caption("📌 Mobile numbers are hidden for privacy.")

# Admin controls
if current_user["role"] == "admin":
    st.subheader("⚙️ Admin Controls")
    c1, c2 = st.columns(2)

    with c1:
        if st.button("Run Attendance Sync Now"):
            updated_count, invalid_count, msg = run_attendance_sync(current_user)
            if "completed" in msg.lower():
                st.success(f"{msg} | Updated: {updated_count} | Invalid Roll Nos: {invalid_count}")
                st.rerun()
            else:
                st.warning(msg)

    with c2:
        st.write("Admin has full access to logs and attendance sync.")

# Send Message
st.subheader("✉️ Send Message")

teacher_id = st.text_input("Teacher ID / Subject")
message_type = st.selectbox(
    "Message Type",
    ["Homework", "Holiday Notice", "Exam Reminder", "General Announcement"]
)
message_text = st.text_area("Enter Message")

st.caption("✅ Present students-ku mattum message anuppuvom. Absent / Leave students-ku message pogathu.")

if st.button("Send Message"):
    if teacher_id.strip() == "":
        st.warning("Teacher ID / Subject enter pannunga.")
    elif message_text.strip() == "":
        st.warning("Message enter pannunga.")
    else:
        send_df = filtered_df[
            filtered_df["student_status"].str.lower() == "present"
        ].copy()

        if len(send_df) == 0:
            st.warning("Present students yaarum illa. So message send aagala.")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_rows = []

            for _, row in send_df.iterrows():
                log_rows.append({
                    "date_time": now,
                    "teacher_name": current_user["name"],
                    "teacher_username": current_user["username"],
                    "teacher_role": current_user["role"],
                    "teacher_id": teacher_id,
                    "roll_no": row["roll_no"],
                    "student_name": row["name"],
                    "class": row["class"],
                    "section": row["section"],
                    "student_status": row["student_status"],
                    "message_type": message_type,
                    "message_text": message_text,
                    "delivery_status": "Sent"
                })

            append_csv_row(MESSAGE_LOG_FILE, pd.DataFrame(log_rows))

            st.session_state.recent_message = {
                "date_time": now,
                "teacher_name": current_user["name"],
                "teacher_id": teacher_id,
                "message_type": message_type,
                "message_text": message_text,
                "sent_count": len(send_df)
            }

            excluded_count = len(filtered_df) - len(send_df)

            st.success(f"✅ Message sent successfully to {len(send_df)} Present students.")
            if excluded_count > 0:
                st.warning(f"Absent/Leave students {excluded_count} per-ku message anuppala.")

# Recent Message
st.subheader("📨 Recent Message")

if st.session_state.recent_message is not None:
    recent = st.session_state.recent_message

    st.write(f"**Date & Time:** {recent['date_time']}")
    st.write(f"**Teacher Name:** {recent['teacher_name']}")
    st.write(f"**Teacher ID / Subject:** {recent['teacher_id']}")
    st.write(f"**Message Type:** {recent['message_type']}")
    st.write(f"**Message Text:** {recent['message_text']}")
    st.write(f"**Sent Count:** {recent['sent_count']}")
else:
    st.info("No recent message available.")

# Full Message Logs
st.subheader("📂 Message Logs")
if os.path.exists(MESSAGE_LOG_FILE):
    try:
        msg_logs = pd.read_csv(MESSAGE_LOG_FILE)
        st.dataframe(msg_logs, width="stretch")
    except Exception as e:
        st.error(f"Could not load message logs: {e}")
else:
    st.info("No message logs available yet.")

# Status Logs
st.subheader("📋 Status Update Logs")
if os.path.exists(STATUS_LOG_FILE):
    try:
        status_logs = pd.read_csv(STATUS_LOG_FILE)
        st.dataframe(status_logs, width="stretch")
    except Exception as e:
        st.error(f"Could not load status logs: {e}")
else:
    st.info("No status update logs available yet.")

# Export
show_export_buttons()

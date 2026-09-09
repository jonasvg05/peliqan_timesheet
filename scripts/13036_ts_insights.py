if 'RUN_CONTEXT' in globals():  # Running on Peliqan
    RUN_ENV = 'peliqan'
else:  # Running outside of Peliqan
    RUN_ENV = 'local'
    from peliqan import Peliqan
    import streamlit as st
    import os
    api_key = os.getenv("PELIQAN_API_KEY")
    if not api_key:
        st.error("PELIQAN_API_KEY environment variable is not set.")
        st.stop()
    interface_id = os.getenv("PELIQAN_INTERFACE_ID", 0)
    pq = Peliqan(api_key)
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is not None:
            RUN_CONTEXT = "interactive"
    except Exception:
        RUN_CONTEXT = "background"

import streamlit as st
import plotly.graph_objects as go

# =====================================================
# Config
# =====================================================

DW_NAME = "dw_3202"
SCHEMA = "ts_prod"

CLIENTS_TABLE = "clients"
USERS_TABLE = "users"
PROJECTS_TABLE = "projects"
TASKS_TABLE = "tasks"

TASK_STATUSES = ["done", "todo", "in_progress"]

# Client 43 ("Internal Support") is not a real client - it's a bucket. Projects
# under it are named after the real client they were support work for, so
# those hours belong to that client too (matched by project name == client name).
INTERNAL_SUPPORT_CLIENT_ID = 43

st.set_page_config(page_title="Insights", layout="wide")

# =====================================================
# Data loading
# =====================================================

@st.cache_data(ttl=300)
def load_clients():
    dbconn = pq.dbconnect(DW_NAME)
    return sorted(
        dbconn.fetch(DW_NAME, SCHEMA, CLIENTS_TABLE) or [],
        key=lambda c: (c.get("name") or "").lower()
    )


@st.cache_data(ttl=300)
def load_projects():
    dbconn = pq.dbconnect(DW_NAME)
    return dbconn.fetch(DW_NAME, SCHEMA, PROJECTS_TABLE) or []


@st.cache_data(ttl=300)
def load_tasks():
    dbconn = pq.dbconnect(DW_NAME)
    return dbconn.fetch(DW_NAME, SCHEMA, TASKS_TABLE) or []


@st.cache_data(ttl=300)
def load_hours_by_user_for_project(project_id):
    dbconn = pq.dbconnect(DW_NAME)
    sql = f"""
        SELECT
            u.name AS user_name,
            SUM(t.duration) AS total_minutes
        FROM ts_prod.timetable t
        JOIN ts_prod.tasks tk ON tk.id = t.task_id
        JOIN ts_prod.users u ON u.id::text = t.user_id
        WHERE tk.project_id = {int(project_id)}
        GROUP BY u.name
        ORDER BY total_minutes DESC
    """
    return dbconn.fetch(DW_NAME, query=sql, df=True)


@st.cache_data(ttl=300)
def load_users():
    dbconn = pq.dbconnect(DW_NAME)
    return sorted(
        dbconn.fetch(DW_NAME, SCHEMA, USERS_TABLE) or [],
        key=lambda u: (u.get("name") or "").lower()
    )


@st.cache_data(ttl=300)
def load_hours_by_project_for_user(user_id):
    dbconn = pq.dbconnect(DW_NAME)
    sql = f"""
        SELECT
            p.name AS project_name,
            SUM(t.duration) AS total_minutes
        FROM ts_prod.timetable t
        JOIN ts_prod.tasks tk ON tk.id = t.task_id
        JOIN ts_prod.projects p ON p.id = tk.project_id
        WHERE t.user_id::text = '{int(user_id)}'
        GROUP BY p.name
        ORDER BY total_minutes DESC
    """
    return dbconn.fetch(DW_NAME, query=sql, df=True)


@st.cache_data(ttl=300)
def load_task_ids_for_user(user_id):
    dbconn = pq.dbconnect(DW_NAME)
    sql = f"""
        SELECT DISTINCT task_id
        FROM ts_prod.timetable
        WHERE user_id::text = '{int(user_id)}'
    """
    df = dbconn.fetch(DW_NAME, query=sql, df=True)
    return set(df["task_id"].tolist()) if not df.empty else set()


def is_truthy(value):
    """dbconn.fetch(schema, table) returns booleans as the strings "true"/"false",
    not Python bools, so a plain truthiness check on the raw value is always True."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def pie_chart(labels, values, title):
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.4))
    fig.update_layout(title=title, margin=dict(t=40, b=0, l=0, r=0), height=320)
    return fig


st.title("Insights")

tab_clients, tab_users = st.tabs(["Clients", "Users"])

with tab_clients:
    clients = load_clients()

    if not clients:
        st.info("No clients found.")
    else:
        client_options = {c["id"]: c["name"] for c in clients}

        header_col, select_col = st.columns([4, 1])

        with select_col:
            selected_client_id = st.selectbox(
                "Client",
                options=list(client_options.keys()),
                format_func=lambda cid: client_options[cid],
                key="clients_tab_selected_client_id",
                label_visibility="collapsed",
            )

        selected_client = next(c for c in clients if c["id"] == selected_client_id)

        with header_col:
            st.header(selected_client["name"])
            meta = " · ".join(
                str(v) for v in (selected_client.get("status"), selected_client.get("category"))
                if v
            )
            if meta:
                st.caption(meta)

        client_projects = sorted(
            (
                p for p in load_projects()
                if p.get("client_id") == selected_client_id
                or (p.get("client_id") == INTERNAL_SUPPORT_CLIENT_ID and p.get("name") == selected_client["name"])
            ),
            key=lambda p: (p.get("name") or "").lower()
        )

        if not client_projects:
            st.info("No projects found for this client.")
        else:
            project_options = {p["id"]: p["name"] for p in client_projects}

            proj_select_col, _ = st.columns([1, 3])
            with proj_select_col:
                selected_project_id = st.selectbox(
                    "Project",
                    options=list(project_options.keys()),
                    format_func=lambda pid: project_options[pid],
                    key="clients_tab_selected_project_id",
                )

            st.subheader("Most hours logged")
            hours_by_user = load_hours_by_user_for_project(selected_project_id)

            if hours_by_user.empty:
                st.info("No hours logged for this project yet.")
            else:
                hours_by_user["hours"] = (hours_by_user["total_minutes"] / 60.0).round(1)
                st.dataframe(
                    hours_by_user[["user_name", "hours"]],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "user_name": "User",
                        "hours": "Hours",
                    },
                )

            project_tasks = [t for t in load_tasks() if t.get("project_id") == selected_project_id]

            if not project_tasks:
                st.info("No tasks found for this project.")
            else:
                pie_col1, pie_col2 = st.columns(2)

                with pie_col1:
                    billable_count = sum(1 for t in project_tasks if is_truthy(t.get("billable")))
                    non_billable_count = len(project_tasks) - billable_count
                    st.plotly_chart(
                        pie_chart(
                            ["Billable", "Non-billable"],
                            [billable_count, non_billable_count],
                            "Tasks by billable",
                        ),
                        use_container_width=True,
                    )

                with pie_col2:
                    status_counts = {
                        status: sum(1 for t in project_tasks if t.get("status") == status)
                        for status in TASK_STATUSES
                    }
                    st.plotly_chart(
                        pie_chart(
                            list(status_counts.keys()),
                            list(status_counts.values()),
                            "Tasks by status",
                        ),
                        use_container_width=True,
                    )

with tab_users:
    users = load_users()

    if not users:
        st.info("No users found.")
    else:
        user_options = {u["id"]: u["name"] for u in users}

        header_col, select_col = st.columns([4, 1])

        with select_col:
            selected_user_id = st.selectbox(
                "User",
                options=list(user_options.keys()),
                format_func=lambda uid: user_options[uid],
                key="users_tab_selected_user_id",
                label_visibility="collapsed",
            )

        selected_user = next(u for u in users if u["id"] == selected_user_id)

        with header_col:
            st.header(selected_user["name"])
            if selected_user.get("email"):
                st.caption(selected_user["email"])

        st.subheader("Most hours logged")
        hours_by_project = load_hours_by_project_for_user(selected_user_id)

        if hours_by_project.empty:
            st.info("No hours logged by this user yet.")
        else:
            hours_by_project["hours"] = (hours_by_project["total_minutes"] / 60.0).round(1)
            st.dataframe(
                hours_by_project[["project_name", "hours"]],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "project_name": "Project",
                    "hours": "Hours",
                },
            )

        user_task_ids = load_task_ids_for_user(selected_user_id)
        user_tasks = [t for t in load_tasks() if t.get("id") in user_task_ids]

        if not user_tasks:
            st.info("No tasks found for this user.")
        else:
            pie_col, _ = st.columns(2)

            with pie_col:
                billable_count = sum(1 for t in user_tasks if is_truthy(t.get("billable")))
                non_billable_count = len(user_tasks) - billable_count
                st.plotly_chart(
                    pie_chart(
                        ["Billable", "Non-billable"],
                        [billable_count, non_billable_count],
                        "Tasks by billable",
                    ),
                    use_container_width=True,
                )

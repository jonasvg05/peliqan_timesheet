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
import pandas as pd
from datetime import date, timedelta

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


def sql_int_list(ids):
    return ",".join(str(int(i)) for i in ids)


def sql_text_list(ids):
    return ",".join(f"'{int(i)}'" for i in ids)


@st.cache_data(ttl=300)
def load_hours_by_user_for_project(project_ids, start_date, end_date):
    if not project_ids:
        return pd.DataFrame(columns=["user_name", "total_minutes"])
    dbconn = pq.dbconnect(DW_NAME)
    sql = f"""
        SELECT
            u.name AS user_name,
            SUM(t.duration) AS total_minutes
        FROM ts_prod.timetable t
        JOIN ts_prod.tasks tk ON tk.id = t.task_id
        JOIN ts_prod.users u ON u.id::text = t.user_id
        WHERE tk.project_id IN ({sql_int_list(project_ids)})
          AND t.date::date BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
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
def load_hours_by_project_for_user(user_ids, start_date, end_date):
    if not user_ids:
        return pd.DataFrame(columns=["project_name", "total_minutes"])
    dbconn = pq.dbconnect(DW_NAME)
    sql = f"""
        SELECT
            p.name AS project_name,
            SUM(t.duration) AS total_minutes
        FROM ts_prod.timetable t
        JOIN ts_prod.tasks tk ON tk.id = t.task_id
        JOIN ts_prod.projects p ON p.id = tk.project_id
        WHERE t.user_id::text IN ({sql_text_list(user_ids)})
          AND t.date::date BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        GROUP BY p.name
        ORDER BY total_minutes DESC
    """
    return dbconn.fetch(DW_NAME, query=sql, df=True)


@st.cache_data(ttl=300)
def load_task_ids_for_user(user_ids, start_date, end_date):
    if not user_ids:
        return set()
    dbconn = pq.dbconnect(DW_NAME)
    sql = f"""
        SELECT DISTINCT task_id
        FROM ts_prod.timetable
        WHERE user_id::text IN ({sql_text_list(user_ids)})
          AND date::date BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
    """
    df = dbconn.fetch(DW_NAME, query=sql, df=True)
    return set(df["task_id"].tolist()) if not df.empty else set()


@st.cache_data(ttl=300)
def load_support_hours_by_client(start_date, end_date):
    dbconn = pq.dbconnect(DW_NAME)
    sql = f"""
        SELECT
            p.name AS client_name,
            SUM(t.duration) AS total_minutes
        FROM ts_prod.timetable t
        JOIN ts_prod.tasks tk ON tk.id = t.task_id
        JOIN ts_prod.projects p ON p.id = tk.project_id
        WHERE p.client_id = {INTERNAL_SUPPORT_CLIENT_ID}
          AND t.date::date BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        GROUP BY p.name
        ORDER BY total_minutes DESC
    """
    return dbconn.fetch(DW_NAME, query=sql, df=True)


@st.cache_data(ttl=300)
def load_support_hours_over_time(start_date, end_date, granularity):
    dbconn = pq.dbconnect(DW_NAME)
    sql = f"""
        SELECT
            date_trunc('{granularity}', t.date::date) AS period,
            SUM(t.duration) AS total_minutes
        FROM ts_prod.timetable t
        JOIN ts_prod.tasks tk ON tk.id = t.task_id
        JOIN ts_prod.projects p ON p.id = tk.project_id
        WHERE p.client_id = {INTERNAL_SUPPORT_CLIENT_ID}
          AND t.date::date BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        GROUP BY period
        ORDER BY period
    """
    return dbconn.fetch(DW_NAME, query=sql, df=True)


def hours_granularity(start_date, end_date):
    return "week" if (end_date - start_date).days > 60 else "day"


@st.cache_data(ttl=300)
def load_hours_over_time_for_user(user_ids, start_date, end_date, granularity):
    if not user_ids:
        return pd.DataFrame(columns=["period", "total_minutes"])
    dbconn = pq.dbconnect(DW_NAME)
    sql = f"""
        SELECT
            date_trunc('{granularity}', date::date) AS period,
            SUM(duration) AS total_minutes
        FROM ts_prod.timetable
        WHERE user_id::text IN ({sql_text_list(user_ids)})
          AND date::date BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        GROUP BY period
        ORDER BY period
    """
    return dbconn.fetch(DW_NAME, query=sql, df=True)


def multiselect_with_controls(label, key, all_ids, id_to_label):
    """Multiselect with "Select all" / "Clear filters" buttons. An empty
    selection is treated by callers as "no filter" (i.e. everything), so
    "Clear filters" empties the box but still shows unfiltered data."""
    all_ids = list(all_ids)

    existing = st.session_state.get(key)
    if existing is not None:
        sanitized = [i for i in existing if i in all_ids]
        if sanitized != existing:
            st.session_state[key] = sanitized

    def select_all():
        st.session_state[key] = list(all_ids)

    def clear_filters():
        st.session_state[key] = []

    ms_col, all_col, clear_col = st.columns([6, 1, 1])
    with ms_col:
        selected = st.multiselect(
            label,
            options=all_ids,
            default=all_ids,
            format_func=lambda i: id_to_label[i],
            key=key,
            label_visibility="collapsed",
        )
    with all_col:
        st.button("Select all", key=f"{key}_select_all_btn", on_click=select_all, use_container_width=True)
    with clear_col:
        st.button("Clear filters", key=f"{key}_clear_btn", on_click=clear_filters, use_container_width=True)

    return selected if selected else list(all_ids)


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


def hours_line_chart(x, y, x_title, y_title):
    fig = go.Figure(go.Scatter(x=x, y=y, mode="lines+markers"))
    fig.update_layout(
        xaxis_title=x_title,
        yaxis_title=y_title,
        xaxis=dict(tickformat="%d-%m-%Y", tickfont=dict(size=16)),
        yaxis=dict(tickfont=dict(size=16)),
        font=dict(size=16),
        margin=dict(t=20, b=0, l=0, r=0),
        height=350,
    )
    return fig


st.title("Insights")

period_col, _ = st.columns([1, 3])
with period_col:
    date_range = st.date_input(
        "Period",
        value=(date.today() - timedelta(days=90), date.today()),
        key="global_date_range",
    )

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = date.today() - timedelta(days=90), date.today()

tab_clients, tab_users, tab_support = st.tabs(["Clients", "Users", "Support"])

with tab_clients:
    clients = load_clients()

    if not clients:
        st.info("No clients found.")
    else:
        st.subheader("Clients")
        client_options = {c["id"]: c["name"] for c in clients}
        selected_client_ids = multiselect_with_controls(
            "Client", "clients_tab_selected_client_ids", client_options.keys(), client_options
        )
        selected_clients = [c for c in clients if c["id"] in selected_client_ids]
        selected_client_names = {c["name"] for c in selected_clients}
        st.caption(f"{len(selected_clients)} of {len(clients)} clients selected")

        client_projects = sorted(
            (
                p for p in load_projects()
                if p.get("client_id") in selected_client_ids
                or (p.get("client_id") == INTERNAL_SUPPORT_CLIENT_ID and p.get("name") in selected_client_names)
            ),
            key=lambda p: (p.get("name") or "").lower()
        )

        if not client_projects:
            st.info("No projects found for the selected clients.")
        else:
            st.subheader("Projects")
            project_options = {p["id"]: p["name"] for p in client_projects}
            selected_project_ids = multiselect_with_controls(
                "Project", "clients_tab_selected_project_ids", project_options.keys(), project_options
            )
            st.caption(f"{len(selected_project_ids)} of {len(client_projects)} projects selected")

            st.subheader("Most hours logged")
            hours_by_user = load_hours_by_user_for_project(selected_project_ids, start_date, end_date)

            if hours_by_user.empty:
                st.info("No hours logged for the selected projects yet.")
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

            project_tasks = [t for t in load_tasks() if t.get("project_id") in selected_project_ids]

            if not project_tasks:
                st.info("No tasks found for the selected projects.")
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
        st.subheader("Users")
        user_options = {u["id"]: u["name"] for u in users}
        selected_user_ids = multiselect_with_controls(
            "User", "users_tab_selected_user_ids", user_options.keys(), user_options
        )
        st.caption(f"{len(selected_user_ids)} of {len(users)} users selected")

        st.subheader("Most hours logged")
        hours_by_project = load_hours_by_project_for_user(selected_user_ids, start_date, end_date)

        if hours_by_project.empty:
            st.info("No hours logged by the selected users yet.")
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

        st.subheader("Hours over time")
        granularity = hours_granularity(start_date, end_date)
        hours_over_time = load_hours_over_time_for_user(selected_user_ids, start_date, end_date, granularity)

        if hours_over_time.empty:
            st.info("No hours logged by the selected users in the selected period.")
        else:
            hours_over_time["hours"] = hours_over_time["total_minutes"] / 60.0
            st.plotly_chart(
                hours_line_chart(
                    hours_over_time["period"],
                    hours_over_time["hours"],
                    granularity.capitalize(),
                    "Hours",
                ),
                use_container_width=True,
            )


        user_task_ids = load_task_ids_for_user(selected_user_ids, start_date, end_date)
        user_tasks = [t for t in load_tasks() if t.get("id") in user_task_ids]

        if not user_tasks:
            st.info("No tasks found for the selected users.")
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

with tab_support:
    st.header("Internal Support")
    st.caption(
        "Support work is logged under the Internal Support bucket, with one project "
        "per client. This gives an overview across all clients' support hours."
    )

    hours_by_client = load_support_hours_by_client(start_date, end_date)

    if hours_by_client.empty:
        st.info("No support hours logged in the selected period.")
    else:
        hours_by_client["hours"] = (hours_by_client["total_minutes"] / 60.0).round(1)

        kpi1, kpi2 = st.columns(2)
        kpi1.metric("Total support hours", f"{hours_by_client['hours'].sum():,.1f}")
        kpi2.metric("Clients with support hours", len(hours_by_client))

        st.subheader("Hours by client")
        st.dataframe(
            hours_by_client[["client_name", "hours"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "client_name": "Client",
                "hours": "Hours",
            },
        )

        st.subheader("Hours over time")
        granularity = hours_granularity(start_date, end_date)
        support_hours_over_time = load_support_hours_over_time(start_date, end_date, granularity)

        if support_hours_over_time.empty:
            st.info("No support hours logged in the selected period.")
        else:
            support_hours_over_time["hours"] = support_hours_over_time["total_minutes"] / 60.0
            st.plotly_chart(
                hours_line_chart(
                    support_hours_over_time["period"],
                    support_hours_over_time["hours"],
                    granularity.capitalize(),
                    "Hours",
                ),
                use_container_width=True,
            )

    support_project_ids = {
        p["id"] for p in load_projects()
        if p.get("client_id") == INTERNAL_SUPPORT_CLIENT_ID
    }
    support_tasks = [t for t in load_tasks() if t.get("project_id") in support_project_ids]

    if support_tasks:
        st.subheader("Support tasks")
        pie_col, _ = st.columns(2)

        with pie_col:
            billable_count = sum(1 for t in support_tasks if is_truthy(t.get("billable")))
            non_billable_count = len(support_tasks) - billable_count
            st.plotly_chart(
                pie_chart(
                    ["Billable", "Non-billable"],
                    [billable_count, non_billable_count],
                    "Support tasks by billable",
                ),
                use_container_width=True,
            )

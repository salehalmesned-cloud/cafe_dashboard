"""
Streamlit dashboard for managing cafe expenses and sales.

This application connects to a PostgreSQL database (e.g. Supabase)
using environment variables for connection details. It allows the
user to:

* View, filter and search expense records
* Add new companies, expenses and monthly sales
* See aggregated statistics (total spent, outstanding)
* Download filtered data or summaries as CSV/Excel
* Visualise monthly expenses versus sales and top companies

To run locally, install streamlit and psycopg2:
    pip install streamlit pandas psycopg2-binary

Ensure the following environment variables are set:
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, SSLMODE

Then run:
    streamlit run streamlit_app_interactive.py

"""

import os
import datetime
import pandas as pd
import numpy as np
import psycopg2
import psycopg2.extras
import streamlit as st
import matplotlib.pyplot as plt


def get_connection():
    """Return a new database connection using environment vars."""
    host = os.environ.get("PGHOST")
    port = os.environ.get("PGPORT", 5432)
    database = os.environ.get("PGDATABASE")
    user = os.environ.get("PGUSER")
    password = os.environ.get("PGPASSWORD")
    sslmode = os.environ.get("SSLMODE", "require")
    conn = psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        sslmode=sslmode,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    return conn


@st.cache_data(ttl=300)
def load_data():
    """Load expenses, companies and sales data from the database."""
    conn = get_connection()
    dfs = {}
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM companies ORDER BY name;")
        dfs['companies'] = pd.DataFrame(cur.fetchall())
        cur.execute("SELECT * FROM expenses ORDER BY id;")
        expenses = pd.DataFrame(cur.fetchall())
        if not expenses.empty:
            expenses['amount'] = pd.to_numeric(expenses['amount'], errors='coerce')
        dfs['expenses'] = expenses
        cur.execute("SELECT * FROM sales ORDER BY year, month;")
        dfs['sales'] = pd.DataFrame(cur.fetchall())
    conn.close()
    return dfs


def insert_company(name: str) -> None:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies (name) VALUES (%s) ON CONFLICT (name) DO NOTHING;", (name,))
        conn.commit()
    conn.close()


def insert_expense(expense_number: str, amount: float, amount_raw: str, company_id: int, status: str, date: datetime.date) -> None:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO expenses (expense_number, amount, amount_raw, company_id, status, expense_date, month, year)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (
                expense_number,
                amount,
                amount_raw,
                company_id,
                status,
                date,
                date.month,
                date.year,
            ),
        )
        conn.commit()
    conn.close()


def upsert_sales(month: int, year: int, amount: float) -> None:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sales (month, year, amount)
            VALUES (%s, %s, %s)
            ON CONFLICT (month, year) DO UPDATE SET amount = EXCLUDED.amount;
            """,
            (month, year, amount),
        )
        conn.commit()
    conn.close()


def main():
    st.set_page_config(page_title="لوحة تحكم المقهي", layout="wide")
    st.title("لوحة تحكم المصروفات والمبيعات للمقهي")

    # Sidebar for adding records
    st.sidebar.header("إضافة بيانات جديدة")

    with st.sidebar.expander("إضافة شركة"):
        new_company_name = st.text_input("اسم الشركة الجديدة")
        if st.button("إضافة الشركة") and new_company_name.strip():
            insert_company(new_company_name.strip())
            st.success("تم إضافة الشركة بنجاح")
            st.cache_data.clear()

    with st.sidebar.expander("إضافة مصروف"):
        dfs = load_data()
        company_names = dfs['companies']
        expense_number = st.text_input("رقم الصرف")
        amount_raw = st.text_input("المبلغ")
        amount_val = st.number_input("المبلغ (رقمي)", min_value=0.0, step=0.1)
        company_options = company_names['name'].tolist() if not company_names.empty else []
        company_name = st.selectbox("الشركة", options=company_options)
        status_options = sorted(dfs['expenses']['status'].dropna().unique()) if not dfs['expenses'].empty else []
        status_value = st.selectbox("الحالة", options=status_options + ["تم الصرف", "لم يتم"])
        date_value = st.date_input("التاريخ", value=datetime.date.today())
        if st.button("إضافة المصروف") and expense_number and company_name:
            # fetch company id
            company_id = None
            if not company_names.empty:
                rec = company_names.loc[company_names['name'] == company_name]
                if not rec.empty:
                    company_id = rec.iloc[0]['id']
            insert_expense(expense_number, amount_val, amount_raw, company_id, status_value, date_value)
            st.success("تم إضافة المصروف بنجاح")
            st.cache_data.clear()

    with st.sidebar.expander("إضافة مبيعات شهرية"):
        month_names = {1:"يناير",2:"فبراير",3:"مارس",4:"أبريل",5:"مايو",6:"يونيو",7:"يوليو",8:"أغسطس",9:"سبتمبر",10:"أكتوبر",11:"نوفمبر",12:"ديسمبر"}
        month_num = st.selectbox("الشهر", options=list(month_names.keys()), format_func=lambda x: month_names[x])
        year_num = st.number_input("السنة", value=datetime.date.today().year, step=1)
        sales_amount = st.number_input("قيمة المبيعات", min_value=0.0, step=0.1)
        if st.button("تسجيل المبيعات"):
            upsert_sales(month_num, int(year_num), sales_amount)
            st.success("تم تسجيل المبيعات")
            st.cache_data.clear()

    # Main content
    dfs = load_data()
    expenses = dfs['expenses']
    companies = dfs['companies']
    sales = dfs['sales']

    # Filters
    st.subheader("عرض البيانات")
    if not expenses.empty:
        # Search and filters
        cols = st.columns(3)
        search_term = cols[0].text_input("بحث عن رقم الصرف أو المبلغ أو الشركة")
        company_filter = cols[1].selectbox("تصفية بحسب الشركة", options=["الكل"] + companies['name'].tolist()) if not companies.empty else "الكل"
        status_filter = cols[2].selectbox("تصفية بحسب الحالة", options=["الكل"] + sorted(expenses['status'].dropna().unique()))
        # Date range
        date_col1, date_col2 = st.columns(2)
        min_date = expenses['expense_date'].min().date() if not expenses['expense_date'].isna().all() else datetime.date.today()
        max_date = expenses['expense_date'].max().date() if not expenses['expense_date'].isna().all() else datetime.date.today()
        start_date = date_col1.date_input("من تاريخ", value=min_date)
        end_date = date_col2.date_input("إلى تاريخ", value=max_date)

        filtered = expenses.copy()
        # apply date filter
        filtered = filtered[(filtered['expense_date'] >= pd.Timestamp(start_date)) & (filtered['expense_date'] <= pd.Timestamp(end_date))]
        # apply search
        if search_term:
            mask = (
                filtered['expense_number'].astype(str).str.contains(search_term, case=False, na=False) |
                filtered['amount_raw'].astype(str).str.contains(search_term, case=False, na=False) |
                filtered['amount'].astype(str).str.contains(search_term, case=False, na=False)
            )
            filtered = filtered[mask]
        # apply company filter
        if company_filter != "الكل":
            cid = companies.loc[companies['name'] == company_filter, 'id'].iloc[0]
            filtered = filtered[filtered['company_id'] == cid]
        # apply status filter
        if status_filter != "الكل":
            filtered = filtered[filtered['status'] == status_filter]

        # Display table
        st.dataframe(
            filtered[["id", "expense_number", "amount", "company_id", "status", "expense_date"]]
            .rename(columns={
                "expense_number": "رقم الصرف",
                "amount": "المبلغ",
                "company_id": "الشركة",
                "status": "الحالة",
                "expense_date": "التاريخ",
            })
        )

        # Aggregations
        total_spent = filtered['amount'].sum()
        unpaid_total = filtered.loc[filtered['status'] != 'تم الصرف', 'amount'].sum()
        kpi1, kpi2 = st.columns(2)
        kpi1.metric("إجمالي المصروفات", f"{total_spent:,.2f}")
        kpi2.metric("إجمالي غير مدفوع", f"{unpaid_total:,.2f}")

        # Summaries
        summary_month = filtered.groupby(['year','month'])['amount'].sum().reset_index()
        summary_month['period'] = summary_month['year'].astype(str) + '-' + summary_month['month'].astype(str).str.zfill(2)
        summary_company = filtered.groupby('company_id')['amount'].sum().reset_index()
        if not summary_company.empty:
            summary_company = summary_company.merge(companies[['id','name']], left_on='company_id', right_on='id', how='left')
        summary_company = summary_company.sort_values('amount', ascending=False)

        # Charts
        chart_tab1, chart_tab2 = st.tabs(["المصروفات مقابل المبيعات", "أعلى الشركات صرفًا"])
        with chart_tab1:
            # merge with sales
            if not summary_month.empty:
                sales_summary = sales.copy()
                if not sales_summary.empty:
                    sales_summary['period'] = sales_summary['year'].astype(str) + '-' + sales_summary['month'].astype(str).str.zfill(2)
                merged = summary_month.merge(sales_summary[['period','amount']], on='period', how='left', suffixes=("_expenses", "_sales"))
                fig, ax = plt.subplots()
                ax.plot(merged['period'], merged['amount_expenses'], label='المصروفات')
                if not merged['amount_sales'].isna().all():
                    ax.plot(merged['period'], merged['amount_sales'], label='المبيعات')
                ax.set_title("المصروفات مقابل المبيعات")
                ax.set_xlabel("الفترة (سنة-شهر)")
                ax.set_ylabel("القيمة")
                ax.legend()
                plt.xticks(rotation=45, ha='right')
                st.pyplot(fig)
            else:
                st.write("لا توجد بيانات لعرض الرسم")

        with chart_tab2:
            if not summary_company.empty:
                top_n = summary_company.head(10)
                fig, ax = plt.subplots()
                ax.bar(top_n['name'], top_n['amount'])
                ax.set_title("أعلى الشركات صرفًا")
                ax.set_xlabel("الشركة")
                ax.set_ylabel("المبلغ")
                plt.xticks(rotation=45, ha='right')
                st.pyplot(fig)
            else:
                st.write("لا توجد بيانات للعرض")

        # Download buttons
        st.subheader("تحميل البيانات")
        csv = filtered.to_csv(index=False)
        st.download_button(
            label="تحميل البيانات المحددة (CSV)",
            data=csv,
            file_name="expenses_filtered.csv",
            mime="text/csv",
        )
        # Monthly summary and company summary downloads
        sm_csv = summary_month.to_csv(index=False)
        st.download_button("تحميل ملخص شهري (CSV)", sm_csv, "summary_month.csv", mime="text/csv")
        sc_csv = summary_company[['name','amount']].to_csv(index=False) if not summary_company.empty else ""
        if sc_csv:
            st.download_button("تحميل ملخص الشركات (CSV)", sc_csv, "summary_company.csv", mime="text/csv")
    else:
        st.info("لا توجد سجلات مصروفات حتى الآن. يرجى إضافة مصروفات لعرض البيانات.")


if __name__ == "__main__":
    main()

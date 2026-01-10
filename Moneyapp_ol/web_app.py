import streamlit as st
import pandas as pd
from github import Github
from io import StringIO
import datetime
import plotly.express as px

# ==========================================
# 1. 配置区域
# ==========================================
st.set_page_config(page_title="Allen的云账本 Pro", page_icon="💰", layout="wide")

try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO_NAME = st.secrets["REPO_NAME"]
except:
    st.error("请在 Streamlit 后台配置 Secrets！")
    st.stop()


def get_repo():
    g = Github(GITHUB_TOKEN)
    return g.get_repo(REPO_NAME)


# ==========================================
# 2. 侧边栏：登录 & 工具箱
# ==========================================
with st.sidebar:
    st.title("💰 智能云账本")

    # --- 登录模块 ---
    if 'user' not in st.session_state:
        st.session_state.user = ""

    if not st.session_state.user:
        user_input = st.text_input("请输入名字登录:")
        if st.button("🚀 进入系统"):
            if user_input.strip():
                st.session_state.user = user_input.strip()
                st.rerun()
        st.stop()
    else:
        st.success(f"当前用户: {st.session_state.user}")
        if st.button("退出"):
            st.session_state.user = ""
            st.rerun()

    st.markdown("---")

    # --- 汇率换算小工具 (适合你关注美股/港股) ---
    st.subheader("💱 简易汇率估算")
    amount_ex = st.number_input("金额", value=100.0)
    currency_type = st.selectbox("币种", ["USD to CNY", "HKD to CNY", "CNY to USD"])

    # 这里用固定汇率做演示，之后可以接API
    rates = {"USD to CNY": 7.25, "HKD to CNY": 0.93, "CNY to USD": 0.14}
    result = amount_ex * rates[currency_type]
    st.metric("估算结果", f"{result:.2f}")

# ==========================================
# 3. 数据处理核心
# ==========================================
current_user = st.session_state.user
file_name = f"data_{current_user}.csv"
repo = get_repo()
file_exists = False
existing_sha = None

# 定义标准表头
COLUMNS = ["日期", "类型", "分类", "金额", "备注"]

try:
    file_content = repo.get_contents(file_name)
    csv_data = file_content.decoded_content.decode("utf-8")
    df = pd.read_csv(StringIO(csv_data))
    # 确保日期列是时间格式，方便后续按月筛选
    df["日期"] = pd.to_datetime(df["日期"]).dt.date
    existing_sha = file_content.sha
    file_exists = True
except:
    # 新用户初始化
    df = pd.DataFrame(columns=COLUMNS)
    file_exists = False

# ==========================================
# 4. 主界面：多Tab布局
# ==========================================
st.title(f"👋 {current_user} 的财务中心")

# 使用 Tabs 分隔功能，界面更清爽
tab1, tab2, tab3 = st.tabs(["📊 财务看板", "✍️ 记一笔", "📋 详细流水"])

# --- Tab 1: 财务看板 (统计分析) ---
with tab1:
    if df.empty:
        st.info("还没有数据，快去【记一笔】吧！")
    else:
        # 1. 核心指标卡片
        total_income = df[df["类型"] == "收入"]["金额"].sum()
        total_expense = df[df["类型"] == "支出"]["金额"].sum()
        balance = total_income - total_expense

        col1, col2, col3 = st.columns(3)
        col1.metric("💰 总资产(结余)", f"¥{balance:.2f}")
        col2.metric("🟢 总收入", f"¥{total_income:.2f}")
        col3.metric("🔴 总支出", f"¥{total_expense:.2f}", delta_color="inverse")

        st.divider()

        # 2. 支出分析图表
        col_chart1, col_chart2 = st.columns(2)

        # 饼图：钱花哪了？
        expense_df = df[df["类型"] == "支出"]
        if not expense_df.empty:
            fig_pie = px.pie(expense_df, values='金额', names='分类', title='支出构成分析', hole=0.4)
            col_chart1.plotly_chart(fig_pie, use_container_width=True)

        # 柱状图：近期趋势
        daily_sum = df.groupby("日期")["金额"].sum().reset_index()
        fig_bar = px.bar(daily_sum, x='日期', y='金额', title='每日流水趋势')
        col_chart2.plotly_chart(fig_bar, use_container_width=True)

# --- Tab 2: 记账输入 (支持收入/支出) ---
with tab2:
    st.subheader("新增交易")

    with st.form("add_form"):
        c1, c2 = st.columns(2)
        with c1:
            date_input = st.date_input("日期", datetime.date.today())
            # 增加类型选择
            type_input = st.radio("类型", ["支出", "收入"], horizontal=True)
        with c2:
            amount_input = st.number_input("金额", min_value=0.01, step=1.0)

        # 根据类型动态调整分类建议
        if type_input == "支出":
            category_list = ["餐饮", "交通", "购物", "娱乐", "数码", "学习", "其他"]
        else:
            category_list = ["生活费", "兼职", "奖学金", "理财收益", "红包"]

        category_input = st.selectbox("分类", category_list)
        note_input = st.text_input("备注 (例如: 买了耳机)")

        submitted = st.form_submit_button("💾 提交保存", type="primary")

        if submitted:
            new_row = pd.DataFrame({
                "日期": [date_input],
                "类型": [type_input],
                "分类": [category_input],
                "金额": [amount_input],
                "备注": [note_input]
            })

            # 合并数据
            updated_df = pd.concat([df, new_row], ignore_index=True)
            updated_csv = updated_df.to_csv(index=False)

            try:
                if file_exists:
                    repo.update_file(file_name, "Add record", updated_csv, existing_sha)
                else:
                    repo.create_file(file_name, "Init ledger", updated_csv)
                st.success("✅ 记账成功！")
                st.rerun()
            except Exception as e:
                st.error(f"同步失败: {e}")

# --- Tab 3: 数据明细 (表格管理) ---
with tab3:
    st.subheader("流水清单")

    # 简单的筛选器
    filter_type = st.multiselect("筛选类型", ["支出", "收入"], default=["支出", "收入"])

    if not df.empty:
        # 按日期倒序排列（最新的在最上面）
        df_sorted = df.sort_values(by="日期", ascending=False)

        # 应用筛选
        if filter_type:
            df_sorted = df_sorted[df_sorted["类型"].isin(filter_type)]

        st.dataframe(
            df_sorted,
            use_container_width=True,
            column_config={
                "金额": st.column_config.NumberColumn(format="¥ %.2f"),
                "日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
            }
        )
    else:
        st.text("暂无数据")
        
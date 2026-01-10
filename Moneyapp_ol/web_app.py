import streamlit as st
import pandas as pd
import datetime
import requests
import plotly.express as px
import os
from github import Github
from io import StringIO

# ==========================================
# ⚙️ 页面配置
# ==========================================
st.set_page_config(page_title="MoneyApp v12.2", page_icon="💰", layout="wide")


# ==========================================
# 🛠️ 核心数据逻辑 (GitHub + CSV)
# ==========================================
def get_github_file():
    """从 GitHub 读取文件对象"""
    if "github" in st.secrets:
        try:
            token = st.secrets["github"]["token"]
            g = Github(token)
            repo = g.get_user(st.secrets["github"]["owner"]).get_repo(st.secrets["github"]["repo"])
            file_path = st.secrets["github"]["file_path"]
            file = repo.get_contents(file_path, ref=st.secrets["github"]["branch"])
            return file, repo
        except:
            return None, None
    return None, None


def load_data():
    """加载数据：GitHub -> 本地 CSV -> 空表"""
    if "github" in st.secrets:
        file, _ = get_github_file()
        if file:
            content = file.decoded_content.decode("utf-8")
            return pd.read_csv(StringIO(content))

    if os.path.exists("data.csv"):
        return pd.read_csv("data.csv")
    else:
        return pd.DataFrame(columns=['日期', '项目', '账户', '币种', '金额', '类型'])


def save_data(df):
    """保存数据到本地和 GitHub"""
    csv_content = df.to_csv(index=False)

    # 1. 保存到 GitHub
    if "github" in st.secrets:
        try:
            file, repo = get_github_file()
            file_path = st.secrets["github"]["file_path"]
            branch = st.secrets["github"]["branch"]
            if file:
                repo.update_file(file_path, "Update data via Streamlit", csv_content, file.sha, branch=branch)
            else:
                repo.create_file(file_path, "Init data.csv", csv_content, branch=branch)
            st.toast("☁️ 数据已同步至 GitHub", icon="✅")
        except Exception as e:
            st.error(f"云端同步失败: {e}")

    # 2. 保存到本地
    df.to_csv("data.csv", index=False)


# ==========================================
# 🧮 辅助计算函数
# ==========================================
@st.cache_data(ttl=3600)
def get_online_rates():
    try:
        url = "https://api.exchangerate-api.com/v4/latest/CNY"
        res = requests.get(url, timeout=3).json().get('rates', {})
        # 转为 1外币=?CNY
        return {k: 1 / v for k, v in res.items() if v > 0}
    except:
        return {'HKD': 0.89, 'USD': 7.25, 'MOP': 0.87}


def get_stats(df, rates):
    if df.empty: return 0, 0, 0, 0, 0, 0

    # 预处理数据
    df['日期'] = pd.to_datetime(df['日期']).dt.date
    df['汇率'] = df['币种'].map(lambda x: 1.0 if x == 'CNY' else rates.get(x, 1.0))
    df['折合'] = df['金额'] * df['汇率']

    # 修正逻辑：只统计"支出"和"收入"，剔除转账和余额调整
    now = datetime.date.today()
    start_week = now - datetime.timedelta(days=now.weekday())

    def calc(mask):
        sub = df[mask]
        exp = sub[sub['类型'] == '支出']['折合'].sum()
        inc = sub[sub['类型'] == '收入']['折合'].sum()
        return exp, inc

    d_e, d_i = calc(df['日期'] == now)
    w_e, w_i = calc(df['日期'] >= start_week)
    m_e, m_i = calc(
        (pd.to_datetime(df['日期']).dt.month == now.month) & (pd.to_datetime(df['日期']).dt.year == now.year))

    return d_e, d_i, w_e, w_i, m_e, m_i


def get_account_balances(df, rates):
    if df.empty: return pd.DataFrame()

    # 计算每个账户的实际余额
    # 逻辑：收入/转入/余额调整(+), 支出/转出(-)
    def get_signed_amount(row):
        amt = row['金额']
        if row['类型'] in ['收入', '转入', '余额调整']: return amt
        if row['类型'] in ['支出', '转出']: return -amt
        return 0

    df['实际变动'] = df.apply(get_signed_amount, axis=1)

    # 按账户和币种分组
    balances = df.groupby(['账户', '币种'])['实际变动'].sum().reset_index()
    balances.rename(columns={'实际变动': '当前余额'}, inplace=True)

    # 算折合人民币
    balances['汇率'] = balances['币种'].map(lambda x: 1.0 if x == 'CNY' else rates.get(x, 1.0))
    balances['折合CNY'] = balances['当前余额'] * balances['汇率']

    return balances


# ==========================================
# 🎨 主界面布局
# ==========================================
st.title("💰 MoneyApp v12.2")

# 加载数据
df = load_data()
rates = get_online_rates()
rates['CNY'] = 1.0

# --- 侧边栏：记账 ---
with st.sidebar:
    st.header("📝 记一笔")
    with st.form("add_form", clear_on_submit=True):
        d = st.date_input("日期", datetime.date.today())
        i = st.text_input("项目")
        c1, c2 = st.columns(2)
        amt = c1.number_input("金额", min_value=0.0, step=1.0)
        curr = c2.selectbox("币种", ["CNY", "HKD", "USD", "MOP"])
        c3, c4 = st.columns(2)
        acc = c3.selectbox("账户", ["微信", "支付宝", "银行卡", "现金", "余额宝", "基金账户"])
        typ = c4.selectbox("类型", ["支出", "收入", "转出", "转入"])

        if st.form_submit_button("💾 提交", use_container_width=True):
            if amt > 0:
                new_row = pd.DataFrame([{'日期': d, '项目': i, '账户': acc, '币种': curr, '金额': amt, '类型': typ}])
                df = pd.concat([df, new_row], ignore_index=True)
                save_data(df)
                st.rerun()

# --- 主区域 Tabs ---
tab1, tab2, tab3 = st.tabs(["📊 仪表盘", "💳 资产管理 (校准)", "🛠️ 流水管理 (修改/删除)"])

with tab1:
    # 1. 统计看板
    d_e, d_i, w_e, w_i, m_e, m_i = get_stats(df, rates)
    c1, c2, c3 = st.columns(3)
    c1.metric("📅 今日支出", f"¥ {d_e:,.0f}", f"收: {d_i:,.0f}", delta_color="inverse")
    c2.metric("📅 本周支出", f"¥ {w_e:,.0f}", f"收: {w_i:,.0f}", delta_color="inverse")
    c3.metric("📅 本月支出", f"¥ {m_e:,.2f}", f"收: {m_i:,.2f}", delta_color="inverse")

    st.info(f"☁️ 实时汇率: 1 USD ≈ {rates.get('USD', 0):.2f} CNY | 1 HKD ≈ {rates.get('HKD', 0):.2f} CNY")

    # 2. 支出图表
    if not df.empty:
        df_chart = df[df['类型'] == '支出'].copy()
        if not df_chart.empty:
            fig = px.pie(df_chart, names='账户', values='金额', title='总支出账户分布', hole=0.4)
            st.plotly_chart(fig, use_container_width=True)

with tab2:
    # 资产校准功能
    st.subheader("💳 各账户余额")

    bal_df = get_account_balances(df, rates)
    if not bal_df.empty:
        # 展示总资产
        total_asset = bal_df['折合CNY'].sum()
        st.metric("💰 总资产估值", f"¥ {total_asset:,.2f}")

        # 展示详情表
        st.dataframe(bal_df[['账户', '币种', '当前余额', '折合CNY']], use_container_width=True)

        st.divider()
        st.subheader("🔧 余额校准 (平账)")
        st.caption("发现余额对不上？在这里输入实际金额，系统自动生成一条‘余额调整’记录。")

        c_acc = st.selectbox("选择账户", bal_df['账户'].unique())
        # 获取该账户当前币种和余额
        curr_row = bal_df[bal_df['账户'] == c_acc].iloc[0]
        c_curr = curr_row['币种']
        c_sys_bal = curr_row['当前余额']

        st.write(f"**{c_acc}** ({c_curr}) 系统记录余额: **{c_sys_bal:,.2f}**")

        real_bal = st.number_input("请输入实际余额", value=float(c_sys_bal))

        if st.button("⚖️ 自动平账"):
            diff = real_bal - c_sys_bal
            if abs(diff) > 0.01:
                # 生成平账记录
                adj_row = pd.DataFrame([{
                    '日期': datetime.date.today(),
                    '项目': '余额校准',
                    '账户': c_acc,
                    '币种': c_curr,
                    '金额': abs(diff),
                    '类型': '收入' if diff > 0 else '支出'  # 也可以用 '余额调整'，但为了统计方便这里归类到收支或单独处理
                }])
                # 为了不影响"支出"统计，建议类型强制设为特殊类型，或者逻辑上处理
                # 这里我们强制设为 '余额调整'，并在 get_stats 里排除了这个类型
                adj_row['类型'] = '余额调整'
                adj_row['金额'] = diff  # 记录实际差额（正负皆可），但在CSV里最好存绝对值+类型，或者允许金额为负
                # 修正策略：存绝对值，类型决定正负。但在Dataframe计算时比较麻烦。
                # 最简单的策略：类型叫'余额调整'，金额存差值（可正可负）。
                # 我们上面的 get_signed_amount 已经支持 '余额调整' 直接加金额。

                df = pd.concat([df, adj_row], ignore_index=True)
                save_data(df)
                st.success(f"已生成平账记录：{diff:+.2f}")
                st.rerun()
            else:
                st.warning("余额一致，无需调整")
    else:
        st.info("暂无数据")

with tab3:
    st.subheader("🛠️ 全能流水编辑器")
    st.caption("💡 双击单元格直接修改，修改完点击下方的【保存修改】。勾选左侧删除行。")

    if not df.empty:
        # 使用 Streamlit 强大的 Data Editor
        edited_df = st.data_editor(
            df,
            num_rows="dynamic",  # 允许添加/删除行
            use_container_width=True,
            column_config={
                "日期": st.column_config.DateColumn("日期", format="YYYY-MM-DD"),
                "金额": st.column_config.NumberColumn("金额", format="%.2f"),
                "类型": st.column_config.SelectboxColumn("类型", options=["支出", "收入", "转出", "转入", "余额调整"]),
                "币种": st.column_config.SelectboxColumn("币种", options=["CNY", "HKD", "USD", "MOP"]),
            },
            hide_index=True
        )

        if st.button("💾 保存修改到账本", type="primary"):
            save_data(edited_df)
            st.success("✅ 账本已更新！")
            st.rerun()
    else:
        st.info("空空如也，快去记一笔吧！")
        